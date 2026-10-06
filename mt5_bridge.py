"""Robust bridge to MetaTrader5 running behind an RPyC classic server.

Failure modes handled here:
  * RPyC server not listening (connection refused)      -> actionable error
  * Host firewalled / down (connect timeout)            -> actionable error
  * MT5 terminal not ready (initialize() fails)         -> actionable error
  * Symbol missing from Market Watch                    -> fail fast
  * Dead/hung server mid-session                        -> bounded RPC timeout
  * Any of the above during setup                       -> connection cleaned up
"""
import os
import socket
import threading
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

    _lock = threading.RLock()

    def __init__(self):
        self.conn = None
        self.mt5 = None
        self._closed = False
        self._cached_rates = None
        self._cached_count = None
        self._cached_closed_bar_ts = None
        self._cached_forming_bar_ts = None
        self.rates_full_fetches = 0
        self.rates_cache_hits = 0
        self._shared = bool(getattr(config, "SHARED_BRIDGE", False))
        env_mode = os.getenv("ACCOUNT_MODE", "").strip().lower()
        if env_mode == "isolated" and getattr(config, "SYMBOL", "") == "BTCUSD":
            env_port = os.getenv("MT5_BTC_PORT") or os.getenv("MT5_GOLD_PORT")
            if env_port:
                try:
                    config.PORT = int(env_port)
                except Exception:
                    pass

        # 1) Classified TCP pre-check so errors are actionable.
        ok, err = probe_bridge(timeout=getattr(config, "CONNECT_TIMEOUT_SECONDS", 10))
        if not ok:
            raise MT5ConnectionError(err)

        # 2) RPyC connect with a bounded per-request timeout so a dead or hung
        #    server can never wedge the engine forever. MasterService is the
        #    client-side peer for the classic (SlaveService) server and gives
        #    us the conn.modules namespace. The config mirrors what
        #    rpyc.classic.connect's ClassicService enables (numpy arrays and
        #    friends cross the wire pickled, e.g. copy_rates_from_pos).
        try:
            self.conn = rpyc_connect(
                config.HOST,
                config.PORT,
                service=MasterService,
                config={
                    "sync_request_timeout": getattr(config, "RPC_TIMEOUT_SECONDS", 30),
                    "allow_all_attrs": True,
                    "allow_pickle": True,
                    "allow_getattr": True,
                    "allow_setattr": True,
                    "allow_delattr": True,
                    "import_custom_exceptions": True,
                    "instantiate_custom_exceptions": True,
                    "instantiate_oldstyle_exceptions": True,
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
        with self._lock:
            return self.mt5.account_info()

    def get_live_tick(self, retries=5):
        with self._lock:
            for _ in range(max(int(retries), 1)):
                tick = self.mt5.symbol_info_tick(config.SYMBOL)
                if tick and tick.bid > 0 and tick.ask > 0:
                    return tick
                if retries > 1:
                    time.sleep(0.5)
            return None

    def get_symbol_info(self):
        with self._lock:
            return self.mt5.symbol_info(config.SYMBOL)

    @staticmethod
    def _bar_time(bar):
        try:
            t = bar["time"]
            if hasattr(t, "item"):
                t = t.item()
            try:
                return int(t)
            except Exception:
                return t
        except Exception:
            return None

    def invalidate_rates_cache(self):
        """Clear cached rate window (e.g. on reconnect or manual reset)."""
        self._cached_rates = None
        self._cached_count = None
        self._cached_closed_bar_ts = None
        self._cached_forming_bar_ts = None

    def get_rates(self, count=None, tick=None, force=False):
        with self._lock:
            return self._get_rates_locked(count, tick, force)

    def _get_rates_locked(self, count=None, tick=None, force=False):
        # Default to the shared indicator window (+ a small safety margin) so
        # the live signal sees the same warm-up as the backtester; the strategy
        # slices back to INDICATOR_WINDOW_BARS (see config.INDICATOR_FETCH_MARGIN).
        default_count = (getattr(config, "INDICATOR_WINDOW_BARS", 250)
                         + getattr(config, "INDICATOR_FETCH_MARGIN", 0))
        use_cache = (count is None and not force
                     and getattr(config, "SIGNAL_ON_CLOSED_BAR", True))
        if count is None:
            count = default_count

        tf_map = {
            "M1": self.mt5.TIMEFRAME_M1,
            "M5": self.mt5.TIMEFRAME_M5,
            "M15": self.mt5.TIMEFRAME_M15,
            "H1": self.mt5.TIMEFRAME_H1,
        }
        tf_sec_map = {"M1": 60, "M5": 300, "M15": 900, "H1": 3600}
        tf = tf_map.get(config.TIMEFRAME, self.mt5.TIMEFRAME_M5)
        tf_sec = tf_sec_map.get(config.TIMEFRAME, 300)

        cached_rates = getattr(self, "_cached_rates", None)
        cached_closed_ts = getattr(self, "_cached_closed_bar_ts", None)
        cached_forming_ts = getattr(self, "_cached_forming_bar_ts", None)

        if (use_cache
                and cached_rates is not None
                and getattr(self, "_cached_count", None) == count
                and len(cached_rates) >= count
                and cached_closed_ts is not None):
            # 1) Fast path: if caller supplied the live tick, derive whether
            #    the current forming bar is still open directly from tick.time.
            #    Inside [forming_ts, forming_ts + tf_sec) -> 0 RPyC calls.
            #    Once tick.time reaches forming_ts + tf_sec, a tick in the new
            #    bar has arrived so the previous bar is closed -> refetch full
            #    window directly without an extra probe RPC.
            tick_sec = None
            if tick is not None and isinstance(cached_forming_ts, int):
                raw_t = getattr(tick, "time", None)
                if not raw_t:
                    msc = getattr(tick, "time_msc", None)
                    if msc:
                        raw_t = int(msc) // 1000
                try:
                    tick_sec = int(raw_t) if raw_t is not None else None
                except Exception:
                    tick_sec = None

            if tick_sec is not None and isinstance(cached_forming_ts, int):
                if cached_forming_ts <= tick_sec < cached_forming_ts + tf_sec:
                    self.rates_cache_hits = getattr(self, "rates_cache_hits", 0) + 1
                    return cached_rates
            else:
                # 2) No tick time supplied: do a lightweight 2-bar probe to
                #    check whether the last completed bar timestamp
                #    (`probe[-2]['time']`) advanced before pulling 1,050 bars.
                try:
                    raw_probe = self.mt5.copy_rates_from_pos(config.SYMBOL, tf, 0, 2)
                    probe = rpyc.classic.obtain(raw_probe)
                except Exception:
                    probe = None
                if probe is not None and len(probe) >= 2:
                    closed_ts = self._bar_time(probe[-2])
                    forming_ts = self._bar_time(probe[-1])
                    if closed_ts is not None and closed_ts == cached_closed_ts:
                        try:
                            cached_rates[-1] = probe[-1]
                        except Exception:
                            pass
                        self._cached_forming_bar_ts = forming_ts
                        self.rates_cache_hits = getattr(self, "rates_cache_hits", 0) + 1
                        return cached_rates

        raw_rates = self.mt5.copy_rates_from_pos(config.SYMBOL, tf, 0, count)
        # Pull the numpy array across as a local object (same pattern as
        # fetch_data.py); a raw netref would force per-element remote calls.
        rates = rpyc.classic.obtain(raw_rates)
        self.rates_full_fetches = getattr(self, "rates_full_fetches", 0) + 1
        if use_cache and rates is not None and len(rates) >= 2:
            self._cached_rates = rates
            self._cached_count = count
            self._cached_closed_bar_ts = self._bar_time(rates[-2])
            self._cached_forming_bar_ts = self._bar_time(rates[-1])
        return rates

    def has_open_position(self):
        with self._lock:
            positions = self.mt5.positions_get(symbol=config.SYMBOL)
            if positions:
                for pos in positions:
                    if pos.magic == config.MAGIC_NUMBER:
                        return True
            return False

    def _filling_mode(self, sym_info):
        """Pick an order filling mode the symbol actually supports.

        symbol_info.filling_mode is a bitmask (1 = FOK allowed, 2 = IOC allowed).
        Sending a mode the broker doesn't support fails with
        TRADE_RETCODE_INVALID_FILL, which is why the old hard-coded IOC was a
        live-path risk. If neither bit is set, fall back to RETURN.
        """
        try:
            mask = int(sym_info.filling_mode)
        except Exception:
            mask = 0
        if mask & 1:
            return self.mt5.ORDER_FILLING_FOK
        if mask & 2:
            return self.mt5.ORDER_FILLING_IOC
        return self.mt5.ORDER_FILLING_RETURN

    def _margin_ok(self, order_type, volume, price):
        """Best-effort pre-flight margin check before sending an order.

        Returns True when the check cannot be performed (let the broker decide),
        False only when we can prove free margin is insufficient.
        """
        with self._lock:
            try:
                required = self.mt5.order_calc_margin(order_type, config.SYMBOL, float(volume), float(price))
            except Exception:
                return True
            if required is None:
                return True
            try:
                acc = self.mt5.account_info()
                free = float(acc.margin_free) if acc else None
            except Exception:
                return True
            if free is None:
                return True
            return float(required) <= free

    def open_trade(self, signal, sl_dist, tp_dist, max_attempts=3):
        """Thread-safe wrapper — serializes on the shared MT5 global."""
        with self._lock:
            return self._open_trade_locked(signal, sl_dist, tp_dist, max_attempts)

    def _open_trade_locked(self, signal, sl_dist, tp_dist, max_attempts=3):
        """Execute a market trade with dynamic ATR-based SL/TP distances.

        Retries transient failures (requotes, price moved/off) up to
        max_attempts times, refreshing the tick each attempt. Returns the
        final order_send result (check .retcode) or None if market data or
        the margin pre-flight failed.
        """
        if signal not in ("BUY", "SELL"):
            return None

        retriable = set()
        try:
            retriable = {
                int(self.mt5.TRADE_RETCODE_REQUOTE),
                int(self.mt5.TRADE_RETCODE_PRICE_CHANGED),
                int(self.mt5.TRADE_RETCODE_PRICE_OFF),
            }
        except Exception:
            pass
        try:
            retcode_done = int(self.mt5.TRADE_RETCODE_DONE)
        except Exception:
            retcode_done = 10009

        result = None
        for attempt in range(1, max_attempts + 1):
            tick = self.get_live_tick()
            sym_info = self.get_symbol_info()
            if not tick or not sym_info:
                print("[ERROR] Market data unavailable for trade execution.")
                return None

            digits = sym_info.digits
            # tp_dist <= 0 means no take-profit: send tp=0.0, MT5's native
            # "no TP" value (tp == price would be rejected as an invalid stop).
            has_tp = tp_dist is not None and float(tp_dist) > 0
            if signal == "BUY":
                price = tick.ask
                order_type = self.mt5.ORDER_TYPE_BUY
                sl = round(price - sl_dist, digits)
                tp = round(price + tp_dist, digits) if has_tp else 0.0
            else:
                price = tick.bid
                order_type = self.mt5.ORDER_TYPE_SELL
                sl = round(price + sl_dist, digits)
                tp = round(price - tp_dist, digits) if has_tp else 0.0

            if not self._margin_ok(order_type, config.LOT_SIZE, price):
                print(f"[ERROR] Insufficient free margin for {signal} {config.LOT_SIZE} {config.SYMBOL} - order not sent.")
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
                # Shows up in the MT5 terminal / broker statement, so a second
                # instance can label its own orders (btc/config.py sets it).
                "comment": getattr(config, "ORDER_COMMENT", "Gold Scalper v7"),
                "type_time": self.mt5.ORDER_TIME_GTC,
                "type_filling": self._filling_mode(sym_info),
            }

            result = self.mt5.order_send(request)
            if result is None:
                print(f"[ERROR] order_send returned no result (attempt {attempt}/{max_attempts}).")
                time.sleep(1)
                continue
            try:
                retcode = int(result.retcode)
            except Exception:
                return result
            if retcode == retcode_done:
                return result
            if retcode in retriable and attempt < max_attempts:
                print(f"[WARN] Transient fill failure retcode={retcode} ({getattr(result, 'comment', '')}) - retrying ({attempt}/{max_attempts}).")
                time.sleep(1)
                continue
            return result
        return result

    def close(self):
        """Idempotent teardown that survives an already-dead connection."""
        if self._closed:
            return
        self._closed = True
        # 2026-10-04 hybrid: in shared mode never shutdown the terminal — the other bot shares it.
        if not getattr(self, "_shared", False):
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
