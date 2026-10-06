"""
BTC Phase-1c strategy: H1 long-lookback Donchian breakout (hypothesis C).

Provenance
----------
The shipped shape (EMA200 + RSI pullback + ATR SL/TP + BE) is FAIL on BTC at
XM's spread (Phase 1b: -$165.84, PF 0.74; gross edge +0.02R vs cost 0.23-0.26R
- see docs/btc_phase1_result_2026-10-03.md and docs/btc_spread_edge_analysis_
2026-10-06.md). Proxy screens (NON-evidence for XM) show this family is the
only one whose gross edge pays the measured 5.486 bp spread through 2024, so
the 2026-10-06 Phase-1c amendment pre-registered ONE geometry of it for an
untouched-data run:

    entry  : close breaks the highest high / lowest low of the prior
             DONCHIAN_ENTRY_BARS (100) bars, on the CLOSED bar
    filter : close vs EMA(DONCHIAN_TREND_EMA=200) trend filter
    stop   : SL_ATR_MULT (grid 2.0-2.5) x ATR(14), fixed
    exit   : opposite Donchian channel DONCHIAN_EXIT_BARS (50) crossed on bar
             close, or an ATR stop; NO take-profit, NO breakeven ratchet
    robustness variant: DONCHIAN_TIME_STOP_BARS time stop (off by default)

Status: NOT authorised to trade. `btc/config.py` ships `BTC_STRATEGY="scalp"`,
so the engine still instantiates the pullback ScalpStrategy and nothing below
runs until ALL of the following hold (btc/HANDOFF.md 10-06 status block):
  1. `btc/train_select.py --family donchian` PASSes on untouched XM H1 bars
     (frozen TRAIN winner: net>0, PF>=1.2, n>=60 cold OOS, AND g > c);
  2. `MAX_SPREAD_POINTS` is re-derived from the H1 TRAIN spread p90
     (btc/derive_params.py); the 1500-point placeholder stays until then;
  3. the user explicitly authorises the paper deployment.

Parity
------
`research/strategy_sweep.py` carries the matching replay family
(`Params.family="donchian"`, `signal_at_donchian`, channel/time exits).
`btc/strategy_btc_test.py` proves, on synthetic bars:
  * live check_signal == replay signal, bar-for-bar, zero mismatches
    (incl. entry-blackout suppression);
  * replay == btc/breakout_screen.py prototype (zero-cost trade ledger);
  * check_exit (CHANNEL/TIME) == the replay's exit choice on the same bars.
Do not change one side without the other and without re-running that test.
"""
from datetime import datetime, timezone

import pandas as pd

import config
from strategy import blackout_hit, config_blackouts


class DonchianBreakoutStrategy:
    """Bar-close Donchian breakout with the ScalpStrategy interface.

    check_signal(rates, when) -> (signal, sl_dist, tp_dist) with tp_dist=0.0
    meaning NO take-profit (MT5's tp=0 convention; paper.py stores tp=None).
    Exits are the fixed ATR stop (broker/paper-side, like gold), plus
    bar-close exits evaluated by check_exit() below.
    """

    # Engine hooks (run.py):
    #   BAR_CLOSE_EXITS - the engine must evaluate check_exit() on every newly
    #                     closed bar while a paper position is open.
    #   BE_OVERRIDE     - None forces the breakeven ratchet OFF for this
    #                     book regardless of config.BE_TRIGGER_R (the shape
    #                     pre-registers BE off); ScalpStrategy leaves it unset.
    BAR_CLOSE_EXITS = True
    BE_OVERRIDE = None

    def __init__(self):
        self._last_fired_bar_ts = None
        self.last_skip_reason = None
        self._cached_eval_key = None
        self._cached_eval_vals = None
        self.indicator_computations = 0
        self.indicator_cache_hits = 0

    # ------------------------------------------------------------ config
    @staticmethod
    def _geom():
        entry_n = int(getattr(config, "DONCHIAN_ENTRY_BARS", 20))
        return (
            entry_n,
            int(getattr(config, "DONCHIAN_EXIT_BARS", max(1, entry_n // 2))),
            int(getattr(config, "DONCHIAN_TREND_EMA", 0) or 0),
            int(getattr(config, "DONCHIAN_TIME_STOP_BARS", 0) or 0),
        )

    @staticmethod
    def _extract_bar_field(bar, key):
        try:
            val = bar[key]
            if hasattr(val, "item"):
                val = val.item()
            return val
        except Exception:
            return None

    @staticmethod
    def _bar_ts(rates, idx):
        try:
            t = rates[idx]["time"]
            if hasattr(t, "item"):
                t = t.item()
            return t
        except Exception:
            return None

    def _in_session(self, when=None):
        if not getattr(config, "SESSION_FILTER_ENABLED", False):
            return True
        when = when or datetime.now(timezone.utc)
        hour = when.hour
        start = getattr(config, "SESSION_START_HOUR_UTC", 7)
        end = getattr(config, "SESSION_END_HOUR_UTC", 17)
        return start <= hour < end

    # ------------------------------------------------------------ entry
    def check_signal(self, rates, when=None):
        """Same closed-bar / one-shot / blackout semantics as ScalpStrategy."""
        min_bars = getattr(config, "INDICATOR_WINDOW_BARS", 202)
        self.last_skip_reason = None
        if rates is None or len(rates) < min_bars:
            n = 0 if rates is None else len(rates)
            self.last_skip_reason = f"insufficient_bars:{n}<{min_bars}"
            return None, 0, 0

        rates = rates[-min_bars:]

        blackouts = config_blackouts()
        if blackouts:
            now = when or datetime.now(timezone.utc)
            hit = blackout_hit(blackouts, now)
            if hit:
                self.last_skip_reason = f"blackout:{hit}"
                return None, 0, 0

        if not self._in_session(when):
            now = when or datetime.now(timezone.utc)
            self.last_skip_reason = f"session:hour={now.hour}"
            return None, 0, 0

        use_closed = getattr(config, "SIGNAL_ON_CLOSED_BAR", True)
        idx = -2 if use_closed and len(rates) >= 3 else -1

        entry_n, exit_n, ema_span, time_stop = self._geom()
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
            vals = self._cached_eval_vals
            self.indicator_cache_hits += 1
        else:
            df = pd.DataFrame(rates)
            atr_period = int(getattr(config, "ATR_PERIOD", 14))

            high_low = df["high"] - df["low"]
            high_cp = (df["high"] - df["close"].shift()).abs()
            low_cp = (df["low"] - df["close"].shift()).abs()
            tr = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
            atr = tr.rolling(atr_period).mean()

            hh = df["high"].rolling(entry_n).max().shift(1)
            ll = df["low"].rolling(entry_n).min().shift(1)
            ema = df["close"].ewm(span=ema_span, adjust=False).mean() if ema_span > 0 else None

            vals = (df["close"].iloc[idx], hh.iloc[idx], ll.iloc[idx],
                    atr.iloc[idx], (ema.iloc[idx] if ema is not None else None))
            self.indicator_computations += 1
            if eval_key is not None:
                self._cached_eval_key = eval_key
                self._cached_eval_vals = vals

        current_close, ch_high, ch_low, current_atr, ema_val = vals

        # breakout_screen semantics: defined channel + positive ATR only.
        atr_min = float(getattr(config, "ATR_MIN", 0.0))
        if not (current_atr == current_atr and current_atr > 0):   # NaN/<=0 guard
            self.last_skip_reason = "atr_invalid"
            return None, 0, 0
        if current_atr < atr_min:
            self.last_skip_reason = f"atr_low:{current_atr:.2f}<{atr_min:g}"
            return None, 0, 0

        import math
        up = ch_high == ch_high and current_close > ch_high        # NaN-safe
        dn = ch_low == ch_low and current_close < ch_low
        if ema_span > 0 and ema_val is not None and ema_val == ema_val:
            up = up and current_close > ema_val
            dn = dn and current_close < ema_val

        signal = "BUY" if up else ("SELL" if dn else None)
        if signal is None:
            self.last_skip_reason = (
                f"no_breakout:close={current_close:.2f} "
                f"channel=[{ch_low if ch_low == ch_low else float('nan'):.2f},"
                f"{ch_high if ch_high == ch_high else float('nan'):.2f}]"
            )
            return None, 0, 0

        # One-shot per closed bar (same rule as ScalpStrategy).
        if bar_ts is not None and bar_ts == self._last_fired_bar_ts:
            self.last_skip_reason = "duplicate_bar"
            return None, 0, 0
        if bar_ts is not None:
            self._last_fired_bar_ts = bar_ts

        sl_dist = current_atr * float(getattr(config, "SL_ATR_MULT", 2.0))
        return signal, sl_dist, 0.0          # tp_dist 0.0 == no take-profit

    # ------------------------------------------------------------ exits
    def check_exit(self, rates, position, bars_in_trade):
        """Bar-close exits for an open paper position; None keeps it open.

        Called by run.py once per newly closed bar (BAR_CLOSE_EXITS). `rates`
        is the standard indicator window (last closed bar = index -2),
        `position` the paper position dict, `bars_in_trade` the number of
        bars closed since entry - this counts from the fill bar, so a
        time-stop of T closes at the close of bar signal+T, exactly matching
        the replay (`i - entry_bar >= T`) and btc/breakout_screen.py.

        The ATR stop is NOT re-checked here: paper.on_tick()/the broker
        already enforce it intra-bar, pessimistically first - the same order
        the replay uses.
        """
        _, exit_n, _, time_stop = self._geom()
        if rates is None or len(rates) < exit_n + 2:
            return None
        idx = -2 if len(rates) >= 3 else -1
        side = position.get("side")

        # 1) opposite channel crossed on the bar's close
        df = pd.DataFrame(rates[-getattr(config, "INDICATOR_WINDOW_BARS", 202):])
        if side == "BUY":
            ll = df["low"].rolling(exit_n).min().shift(1).iloc[idx]
            if ll == ll and df["close"].iloc[idx] < ll:
                return {"reason": "CHANNEL", "price": float(df["close"].iloc[idx])}
        elif side == "SELL":
            hh = df["high"].rolling(exit_n).max().shift(1).iloc[idx]
            if hh == hh and df["close"].iloc[idx] > hh:
                return {"reason": "CHANNEL", "price": float(df["close"].iloc[idx])}

        # 2) time stop
        if time_stop > 0 and bars_in_trade is not None and bars_in_trade >= time_stop:
            close_px = self._extract_bar_field(rates[idx], "close")
            if close_px is not None:
                return {"reason": "TIME", "price": float(close_px)}
        return None


class BtcStrategyPlaceholder:
    """Legacy placeholder - raises if ever instantiated, so wiring it by
    accident fails loudly. Kept only for backwards compatibility with older
    notes; the real Phase-1c landing zone is DonchianBreakoutStrategy above."""
    def __init__(self, *a, **kw):
        raise RuntimeError(
            "BtcStrategyPlaceholder is not a real strategy. "
            "Use DonchianBreakoutStrategy (pre-registered hypothesis C) or "
            "pre-register a new hypothesis in docs/btc_phase1c_hypotheses_2026-10-04.md."
        )
