"""
BTC Strategy Phase-1c placeholder — DO NOT ENABLE LIVE.

Current ScalpStrategy (EMA200 + RSI pullback + ATR 2.0/5.0 + BE 1.5) is
proven FAIL on BTC M5 at XM spread (Phase-1b: -165 PF 0.74, spread/risk 26%
vs gold 5%, required WR 36% vs 23.8% actual). See docs/btc_phase1_result_2026-10-03.md
and btc/HANDOFF.md §9.

This module is the landing zone for the *next* pre-registered hypothesis family.
It is NOT wired into btc/config.py yet; btc/run.py still uses strategy.ScalpStrategy.

To try a new family:
  1. Implement a class with the same interface as ScalpStrategy:
        class BtcStrategy:
            def __init__(self): self.last_skip_reason = None
            def check_signal(self, rates, when=None): -> (signal, sl_dist, tp_dist)
     It must respect config.ATR_MIN, SL_ATR_MULT, TP_ATR_MULT, SESSION_FILTER,
     ENTRY_BLACKOUTS etc, or explicitly document why it diverges.
  2. Add a config flag, e.g. BTC_STRATEGY = "scalp" | "donchian_breakout" | "m15_trend"
     and make btc/run.py instantiate the right class:
        from strategy import ScalpStrategy
        from btc.strategy_btc import DonchianBreakoutStrategy
        strat = {"scalp": ScalpStrategy, "donchian": DonchianBreakoutStrategy}[cfg.BTC_STRATEGY]()
  3. Add a matching replay path in research/strategy_sweep.py (params_from_config
     + signal_at) so --verify still proves equivalence.
  4. Pre-register the hypothesis in docs/btc_phase1c_hypotheses_2026-10-04.md
     BEFORE looking at untouched data.

Hypotheses pre-registered for Phase-1c (see that doc):
  A. M15 / H1 trend — same shape, larger stop dwarfs spread (26%→~7%)
  B. Ultra-Low spread account tier (225pt vs 500pt)
  C. Donchian breakout + time-stop (no BE ratchet, no RSI) — larger gross edge

Do NOT:
  - Re-sweep the inspected 2026-07-25..10-03 M5 file
  - Loosen MAX_SPREAD_POINTS to let a losing shape trade
  - Copy gold TP/BE numbers onto BTC

Until a Phase-1c gate passes (train-select → cold OOS net>0, PF≥1.2,
sufficient trades, sane spread economics) on UNTOUCHED data, this file stays
inactive and btc/config.py TRADING_MODE stays FORWARD_TEST.
"""
# Intentionally empty — the next hypothesis is described in
# docs/btc_phase1c_hypotheses_2026-10-04.md.  Implement here when you have a
# broker-verified, pre-registered shape to test.

class BtcStrategyPlaceholder:
    """Placeholder — raises if ever instantiated, so wiring it by accident fails loudly."""
    def __init__(self, *a, **kw):
        raise RuntimeError(
            "BtcStrategyPlaceholder is not a real strategy. "
            "Implement a pre-registered hypothesis from "
            "docs/btc_phase1c_hypotheses_2026-10-04.md before wiring it."
        )
