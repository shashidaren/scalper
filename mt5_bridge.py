"""Robust bridge to MetaTrader5 running behind an RPyC classic server.

Failure modes handled here:
  * RPyC server not listening (connection refused)      -> actionable error
  * Host firewalled / down (connect timeout)            -> actionable error
  * MT5 terminal not ready (initialize() fails)         -> actionable error
  * Symbol missing from Market Watch                    -> fail fast
  * Dead/hung server mid-session                        -> bounded RPC timeout
  * Any of the above during setup                       -> connection cleaned up
"""
import socket
import time

import rpyc
from rpyc.core.service import MasterService
from rpyc.utils.factory import connect as rpyc_connect

import config


class MT5ConnectionError(ConnectionError):
    """Raised when the RPyC bridge or the MT5 terminal cannot be reached."""


def probe_bridge(host=None, port=None, timeout=5.0):
    """Cheap TCP probe of the RPyC endpoint.

    Returns (ok, human_readable_error). Classifies the failure so the logs
    explain *what* to fix instead of just saying "Connection refused".
    """
    host = host or config.HOST
    port = port if port is not None else config.PORT
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, None
    except ConnectionRefusedError:
        return False, (
            f"Connection refused by {host}:{port} - nothing is listening. "
            f"Is the MT5 Docker container (RPyC server) running?"
        )
    except (socket.timeout, TimeoutError):
        return False, (
            f"Connection to {host}:{port} timed out after {timeout}s "
            f"(host down or firewalled?)"
        )
    except OSError as e:
        return False, f"Connection to {host}:{port} failed: {e}"


class MT5Bridge:
    """Connects to MetaTrader5 through the RPyC classic server."""

    def __init__(self):
        self.conn = None
        self.mt5 = None
        self._closed = False

        # 1) Classified TCP pre-check so errors are actionable.
        ok, err = probe_bridge(timeout=getattr(config, "CONNECT_TIMEOUT_SECONDS", 10))
        if not ok:
            raise MT5ConnectionError(err)

        # 2) RPyC connect with a bounded per-request timeout so a dead or hung
        #    server can never wedge the engine forever. MasterService is the
        #    client-side peer for the classic (SlaveService) server and gives
        #    us the conn.modules namespace.
        try:
            self.conn = rpyc_connect(
                config.HOST,
                config.PORT,
                service=MasterService,
                config={
                    "sync_request_timeout": getattr(config, "RPC_TIMEOUT_SECONDS", 30),
                },
                keepalive=True,
            )
        except Exception as e:
            raise MT5ConnectionError(
                f"RPyC handshake with {config.HOST}:{config.PORT} failed: {e}"
            ) from e

        # 3) Bring up MT5 inside the remote process, cleaning up on any failure.
        try:
            self.mt5 = self.conn.modules.MetaTrader5

            if not self.mt5.initialize():
                try:
                    last_err = self.mt5.last_error()
                except Exception:
                    last_err = "unknown"
                raise MT5ConnectionError(f"MT5 initialize() failed: {last_err}")

            if not self.mt5.symbol_select(config.SYMBOL, True):
                raise MT5ConnectionError(
                    f"symbol_select('{config.SYMBOL}') failed - "
                    f"symbol missing or Market Watch unavailable"
                )

            time.sleep(1)  # let the terminal settle after symbol activation
        except Exception:
            self.close()
            raise

    def get_account_info(self):
        return self.mt5.account_info()

    def get_live_tick(self):
        for _ in range(5):
            tick = self.mt5.symbol_info_tick(config.SYMBOL)
            if tick and tick.bid > 0 and tick.ask > 0:
                return tick
            time.sleep(0.5)
        return None

    def get_symbol_info(self):
        return self.mt5.symbol_info(config.SYMBOL)

    def get_rates(self, count=250):
        tf_map = {
            "M1": self.mt5.TIMEFRAME_M1,
            "M5": self.mt5.TIMEFRAME_M5,
            "M15": self.mt5.TIMEFRAME_M15,
            "H1": self.mt5.TIMEFRAME_H1
        }
        tf = tf_map.get(config.TIMEFRAME, self.mt5.TIMEFRAME_M5)
        return self.mt5.copy_rates_from_pos(config.SYMBOL, tf, 0, count)

    def has_open_position(self):
        positions = self.mt5.positions_get(symbol=config.SYMBOL)
        if positions:
            for pos in positions:
                if pos.magic == config.MAGIC_NUMBER:
                    return True
        return False

    def open_trade(self, signal, sl_dist, tp_dist):
        """Executes market trade using dynamic ATR-based SL/TP distances."""
        tick = self.get_live_tick()
        sym_info = self.get_symbol_info()

        if not tick or not sym_info:
            print("[ERROR] Market data unavailable for trade execution.")
            return None

        digits = sym_info.digits

        if signal == "BUY":
            price = tick.ask
            order_type = self.mt5.ORDER_TYPE_BUY
            sl = round(price - sl_dist, digits)
            tp = round(price + tp_dist, digits)
        elif signal == "SELL":
            price = tick.bid
            order_type = self.mt5.ORDER_TYPE_SELL
            sl = round(price + sl_dist, digits)
            tp = round(price - tp_dist, digits)
        else:
            return None

        request = {
            "action": self.mt5.TRADE_ACTION_DEAL,
            "symbol": config.SYMBOL,
            "volume": float(config.LOT_SIZE),
            "type": order_type,
            "price": float(price),
            "sl": float(sl),
            "tp": float(tp),
            "deviation": 20,
            "magic": config.MAGIC_NUMBER,
            "comment": "Gold Scalper v5",
            "type_time": self.mt5.ORDER_TIME_GTC,
            "type_filling": self.mt5.ORDER_FILLING_IOC,
        }

        result = self.mt5.order_send(request)
        return result

    def close(self):
        """Idempotent teardown that survives an already-dead connection."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.mt5 is not None:
                self.mt5.shutdown()
        except Exception:
            pass
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass
