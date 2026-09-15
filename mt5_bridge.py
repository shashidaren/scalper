import time
import rpyc
import config

class MT5Bridge:
    def __init__(self):
        self.conn = rpyc.classic.connect(config.HOST, config.PORT)
        self.mt5 = self.conn.modules.MetaTrader5
        
        if not self.mt5.initialize():
            raise Exception(f"MT5 Init failed: {self.mt5.last_error()}")
            
        self.mt5.symbol_select(config.SYMBOL, True)
        time.sleep(1)

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
        self.mt5.shutdown()
        self.conn.close()
