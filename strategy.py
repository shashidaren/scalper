from datetime import datetime, timezone
import pandas as pd
import config

class ScalpStrategy:
    def __init__(self):
        # Last closed-bar timestamp we already emitted a BUY/SELL for.
        # Prevents the 15s live loop from re-entering on the same RSI cross.
        self._last_fired_bar_ts = None

    def _in_session(self, when=None):
        """Return True if current (or given) UTC time is allowed for new entries."""
        when = when or datetime.now(timezone.utc)
        if when.tzinfo is None:
            # Backtest CSV times are treated as UTC-naive.
            pass

        # Sat=5, Sun=6 — do not open into weekend gap / thin quotes.
        if getattr(config, "WEEKEND_FLAT_ENABLED", False) and when.weekday() >= 5:
            return False

        if getattr(config, "FRIDAY_CUTOFF_ENABLED", False):
            cutoff = getattr(config, "FRIDAY_CUTOFF_HOUR_UTC", 16)
            if when.weekday() == 4 and when.hour >= cutoff:
                return False

        if not getattr(config, "SESSION_FILTER_ENABLED", False):
            return True
        hour = when.hour
        start = getattr(config, "SESSION_START_HOUR_UTC", 7)
        end = getattr(config, "SESSION_END_HOUR_UTC", 17)
        return start <= hour < end

    def check_signal(self, rates, when=None):
        if rates is None or len(rates) < 202:
            return None, 0, 0

        # Session filter (live uses now; backtest can pass bar time)
        if not self._in_session(when):
            return None, 0, 0

        df = pd.DataFrame(rates)

        # 1. Trend Filter: 200 EMA
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

        # 2. RSI (14)
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        # 3. ATR (14) Volatility
        high_low = df['high'] - df['low']
        high_cp = (df['high'] - df['close'].shift()).abs()
        low_cp = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
        df['atr'] = tr.rolling(14).mean()

        # Prefer last *completed* bar so live (forming M5 candle) matches backtest
        # and does not flicker as the current bar's RSI wiggles through the level.
        use_closed = getattr(config, "SIGNAL_ON_CLOSED_BAR", True)
        idx = -2 if use_closed and len(df) >= 3 else -1
        prev_idx = idx - 1

        current_close = df['close'].iloc[idx]
        current_open = df['open'].iloc[idx] if 'open' in df.columns else current_close
        current_ema = df['ema200'].iloc[idx]
        current_atr = df['atr'].iloc[idx]
        rsi_curr = df['rsi'].iloc[idx]
        rsi_prev = df['rsi'].iloc[prev_idx]

        bar_ts = None
        if 'time' in df.columns:
            try:
                bar_ts = df['time'].iloc[idx]
                if hasattr(bar_ts, "item"):
                    bar_ts = bar_ts.item()
            except Exception:
                bar_ts = None

        min_atr = float(getattr(config, "MIN_ATR", 0.50))
        if current_atr < min_atr:
            return None, 0, 0

        # Dynamic SL & TP based on market volatility (still ~1:2.5 RR)
        sl_dist = current_atr * 2.0
        tp_dist = current_atr * 5.0

        buy_level = getattr(config, "RSI_BUY_LEVEL", 30)
        sell_level = getattr(config, "RSI_SELL_LEVEL", 70)
        buy_max = float(getattr(config, "RSI_BUY_MAX", 0) or 0)
        sell_min = float(getattr(config, "RSI_SELL_MIN", 0) or 0)

        signal = None
        # BUY: Uptrend + RSI bounce from oversold (not a late chase)
        if current_close > current_ema and rsi_prev <= buy_level and rsi_curr > buy_level:
            if buy_max <= 0 or rsi_curr <= buy_max:
                signal = "BUY"
        # SELL: Downtrend + RSI reversal from overbought (not a late chase)
        elif current_close < current_ema and rsi_prev >= sell_level and rsi_curr < sell_level:
            if sell_min <= 0 or rsi_curr >= sell_min:
                signal = "SELL"

        if signal is None:
            return None, 0, 0

        # v12: signal-bar body must agree with direction (reject doji / opposite).
        if getattr(config, "REQUIRE_SIGNAL_CANDLE", False):
            if signal == "BUY" and not (current_close > current_open):
                return None, 0, 0
            if signal == "SELL" and not (current_close < current_open):
                return None, 0, 0

        # One-shot per closed bar: same RSI cross must not re-fire every 15s
        # (or after a quick scratch) while that bar is still the latest complete one.
        if bar_ts is not None and bar_ts == self._last_fired_bar_ts:
            return None, 0, 0
        if bar_ts is not None:
            self._last_fired_bar_ts = bar_ts

        return signal, sl_dist, tp_dist
