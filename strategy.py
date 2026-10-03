from datetime import datetime, timezone
import pandas as pd
import config

class ScalpStrategy:
    def __init__(self):
        # Last closed-bar timestamp we already emitted a BUY/SELL for.
        # Prevents the 15s live loop from re-entering on the same RSI cross.
        self._last_fired_bar_ts = None
        # Why the most recent check_signal() returned no trade (None when it
        # returned a BUY/SELL). Diagnostic only - never affects the signal.
        self.last_skip_reason = None
        # Cached closed-bar indicator values keyed by the closed bar's
        # timestamp + window boundary prices so repeated 15s calls inside the
        # same 5m bar do not rebuild a 1000-row DataFrame 20 times.
        self._cached_eval_key = None
        self._cached_eval_vals = None
        self.indicator_computations = 0
        self.indicator_cache_hits = 0

    @staticmethod
    def _extract_bar_field(bar, key):
        try:
            val = bar[key]
            if hasattr(val, "item"):
                val = val.item()
            return val
        except Exception:
            return None

    def _in_session(self, when=None):
        """Return True if current (or given) UTC hour is inside the allowed session."""
        if not getattr(config, "SESSION_FILTER_ENABLED", False):
            return True
        when = when or datetime.now(timezone.utc)
        hour = when.hour
        start = getattr(config, "SESSION_START_HOUR_UTC", 7)
        end = getattr(config, "SESSION_END_HOUR_UTC", 17)
        return start <= hour < end

    def check_signal(self, rates, when=None):
        # Window length must match the backtester's and the bridge's fetch
        # count, otherwise the EMA200 warm-up differs between live and backtest
        # (see config.INDICATOR_WINDOW_BARS).
        min_bars = getattr(config, "INDICATOR_WINDOW_BARS", 202)
        self.last_skip_reason = None
        if rates is None or len(rates) < min_bars:
            n = 0 if rates is None else len(rates)
            self.last_skip_reason = f"insufficient_bars:{n}<{min_bars}"
            return None, 0, 0

        # The bridge fetches window + INDICATOR_FETCH_MARGIN bars so a missing
        # bar cannot trip the guard above. Indicators must still see exactly
        # the last `min_bars` bars, otherwise the EMA200 seed weight (and thus
        # the signal) would differ from the backtester.
        rates = rates[-min_bars:]

        # Session filter (live uses now; backtest can pass bar time)
        if not self._in_session(when):
            now = when or datetime.now(timezone.utc)
            self.last_skip_reason = f"session:hour={now.hour}"
            return None, 0, 0

        # Prefer last *completed* bar so live (forming M5 candle) matches backtest
        # and does not flicker as the current bar's RSI wiggles through the level.
        use_closed = getattr(config, "SIGNAL_ON_CLOSED_BAR", True)
        idx = -2 if use_closed and len(rates) >= 3 else -1
        prev_idx = idx - 1

        bar_ts = self._extract_bar_field(rates[idx], "time")
        eval_key = None
        if use_closed and bar_ts is not None:
            eval_key = (
                bar_ts,
                len(rates),
                self._extract_bar_field(rates[0], "close"),
                self._extract_bar_field(rates[idx], "close"),
            )

        if eval_key is not None and eval_key == self._cached_eval_key and self._cached_eval_vals is not None:
            current_close, current_ema, current_atr, rsi_curr, rsi_prev = self._cached_eval_vals
            self.indicator_cache_hits += 1
        else:
            df = pd.DataFrame(rates)

            # Indicator periods come from config so a second symbol instance
            # (btc/config.py) can run different ones; defaults are the original
            # literals (200/14/14), so gold is unchanged.
            ema_period = int(getattr(config, "EMA_PERIOD", 200))
            rsi_period = int(getattr(config, "RSI_PERIOD", 14))
            atr_period = int(getattr(config, "ATR_PERIOD", 14))

            # 1. Trend Filter: EMA (200 by default)
            df['ema200'] = df['close'].ewm(span=ema_period, adjust=False).mean()

            # 2. RSI
            delta = df['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
            rs = gain / loss
            df['rsi'] = 100 - (100 / (1 + rs))

            # 3. ATR Volatility
            high_low = df['high'] - df['low']
            high_cp = (df['high'] - df['close'].shift()).abs()
            low_cp = (df['low'] - df['close'].shift()).abs()
            tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
            df['atr'] = tr.rolling(atr_period).mean()

            current_close = df['close'].iloc[idx]
            current_ema = df['ema200'].iloc[idx]
            current_atr = df['atr'].iloc[idx]
            rsi_curr = df['rsi'].iloc[idx]
            rsi_prev = df['rsi'].iloc[prev_idx]
            self.indicator_computations += 1

            if bar_ts is None and 'time' in df.columns:
                try:
                    bar_ts = df['time'].iloc[idx]
                    if hasattr(bar_ts, "item"):
                        bar_ts = bar_ts.item()
                except Exception:
                    bar_ts = None
            if eval_key is not None:
                self._cached_eval_key = eval_key
                self._cached_eval_vals = (
                    current_close, current_ema, current_atr, rsi_curr, rsi_prev
                )

        # Minimum volatility filter (price units; gold 0.50, BTC sets its own)
        atr_min = float(getattr(config, "ATR_MIN", 0.50))
        if current_atr < atr_min:
            self.last_skip_reason = f"atr_low:{current_atr:.2f}<{atr_min:g}"
            return None, 0, 0

        # Dynamic SL & TP based on market volatility (gold: 2.0 -> 5.0 ATR,
        # i.e. ~1:2.5 RR; both multiples are config keys so a BTC instance can
        # carry its own geometry without touching the engine)
        sl_dist = current_atr * float(getattr(config, "SL_ATR_MULT", 2.0))
        tp_dist = current_atr * float(getattr(config, "TP_ATR_MULT", 5.0))

        buy_level = getattr(config, "RSI_BUY_LEVEL", 35)
        sell_level = getattr(config, "RSI_SELL_LEVEL", 65)

        signal = None
        # BUY: Uptrend + RSI bounce from oversold
        if current_close > current_ema and rsi_prev <= buy_level and rsi_curr > buy_level:
            signal = "BUY"
        # SELL: Downtrend + RSI reversal from overbought
        elif current_close < current_ema and rsi_prev >= sell_level and rsi_curr < sell_level:
            signal = "SELL"

        if signal is None:
            self.last_skip_reason = (
                f"no_setup:rsi={rsi_curr:.1f}(prev {rsi_prev:.1f}),"
                f"close{'>' if current_close > current_ema else '<='}ema200"
            )
            return None, 0, 0

        # One-shot per closed bar: same RSI cross must not re-fire every 15s
        # (or after a quick scratch) while that bar is still the latest complete one.
        if bar_ts is not None and bar_ts == self._last_fired_bar_ts:
            self.last_skip_reason = "duplicate_bar"
            return None, 0, 0
        if bar_ts is not None:
            self._last_fired_bar_ts = bar_ts

        return signal, sl_dist, tp_dist
