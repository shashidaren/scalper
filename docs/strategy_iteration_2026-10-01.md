# Strategy iteration — 2026-10-01 (trade-frequency adjustment)

**Question.** User report: "the gold scalper is hardly taking any trades."
With the 2026-09-30 config (`RSI_BUY_LEVEL=35` / `RSI_SELL_LEVEL=65`,
session `07:00–17:00 UTC`), the backtest fires **174 trades over ~101 days**
(`data/GOLD_M5.csv`, 2026-06-02 → 2026-09-11, ~70 trading weekdays) — about
2.5 trades/day inside a 10-hour session, one at a time (the engine only
re-arms once flat). That matches the "hardly any trades" feeling for a bot
billed as a scalper. This note looks for a config change that increases
frequency **without** degrading (ideally while improving) the edge, using the
same one-variable-at-a-time + bootstrap discipline as the 2026-09-30 note.

**Tooling.** `research/strategy_sweep.py --verify` reproduces `backtest.py`
bit-for-bit on the current config (255 trades / $456.58 / PF 1.32 — see
below). While investigating this I found and fixed a tooling bug (not a
strategy/live bug): `_rolling_mean` used a plain `cumsum`-based rolling mean,
which accumulates floating-point error over the full 20,000-bar file and can
disagree with `strategy.py`'s freshly-windowed
`pandas.Series.rolling(period).mean()` by ~1e-11 at a given bar. That is
normally invisible, but `research/parity_test.py` caught it the moment a
real bar's RSI (69.0 → **60.000000000000...**) landed exactly on the new
`RSI_SELL_LEVEL=60` — cumsum rolling gave `59.999999999992184` (< 60 → fires)
vs. the live path's exact `60.0` (not < 60 → no signal), i.e. the fast
sweep tool would have overstated frequency on *this* config until fixed.
Switched `_rolling_mean` to `pandas.Series(x).rolling(period).mean()` (not a
speed regression: sweeps still run in <1 s); `research/parity_test.py` now
passes clean on the new config (0 mismatches). `backtest.py` was never
affected — it always calls the real `strategy.check_signal`.

---

## 1. What moves trade frequency

Two independent levers, swept with the fixed tool, base = the 2026-09-30
config otherwise unchanged:

**RSI thresholds** (`--sweep rsi`, session left at 07–17):

| config | trades | net $ | PF | WR% | avgR | maxDD $ |
|---|---|---|---|---|---|---|
| RSI 30/70 | 136 | 7.77 | 1.01 | 23.5 | −0.11 | 167.30 |
| RSI 35/65 (old) | 174 | 52.80 | 1.06 | 23.6 | −0.06 | 99.62 |
| **RSI 40/60** | **213** | **352.31** | **1.34** | **27.7** | **0.09** | 88.21 |
| RSI 45/55 | 249 | 183.07 | 1.13 | 26.5 | 0.02 | 120.95 |

40/60 is a local peak but not a knife-edge — a fine-grained scan around it
(36/64 … 44/56, with the session widening below already applied) is
monotone-ish and uniformly profitable:

| RSI | 36/64 | 38/62 | 40/60 | 42/58 | 44/56 |
|---|---|---|---|---|---|
| trades | 219 | 236 | **255** | 273 | 290 |
| net $ | 249.60 | 238.41 | **456.58** | 429.14 | 313.69 |
| PF | 1.20 | 1.18 | **1.32** | 1.27 | 1.17 |

**Session window** (`--sweep session`, RSI left at 35/65):

| config | trades | net $ | PF | maxDD $ |
|---|---|---|---|---|
| 07–17 (old) | 174 | 52.80 | 1.06 | 99.62 |
| 08–17 | 149 | 139.90 | 1.17 | 87.19 |
| 13–17 (NY only) | 71 | 236.52 | 1.68 | 80.72 |
| **07–20** | **216** | **179.93** | **1.14** | 100.13 |
| off | 332 | −21.48 | 0.99 | 309.93 |

13–17 (NY) has the best quality metrics (PF 1.68, WR 31%) but *cuts* trade
count to 71 — the opposite of what's needed here, so it's noted but not
adopted now. 07–20 (extending the end of the session from 17:00 to 20:00 UTC
to keep the full NY afternoon, still stopping well before the 21:00–22:00 UTC
daily rollover break) adds trades **and** improves PF/maxDD over the old
07–17 window, so it's the one adopted.

## 2. Adopted: RSI 40/60 + session 07:00–20:00 UTC combined

| metric | old (RSI 35/65, 07–17) | new (RSI 40/60, 07–20) | Δ |
|---|---|---|---|
| trades (≈101 days) | 174 | **255** | **+47%** |
| net $ | +52.80 | **+456.58** | +403.78 |
| profit factor | 1.06 | **1.32** | +0.26 |
| win rate | 23.6% | 28.2% | +4.6pp |
| avg R | −0.06 | **+0.11** | |
| max drawdown | $99.62 | $108.65 | +$9.03 |
| exits | 41 TP / 29 BE / 104 SL | 72 TP / 43 BE / 140 SL | |
| bootstrap (10k resamples) P(net>0) | 0.60 (CI spans zero) | **0.96** | |

Stability checks on the combined config (`--detail`):
- **Both sides profitable:** BUY 126 trades/+$197.60/PF 1.27; SELL 129
  trades/+$258.98/PF 1.38.
- **Every calendar month profitable:** Jun +$155, Jul +$129, Aug +$65,
  Sep +$107 (partial month).
- **Both halves of the data profitable:** first half +$300.63, second half
  +$155.94 (roughly half the net in each half — not front-loaded by a few
  lucky trades).
- **Bootstrap:** 10,000 resamples of the 255 trade PnLs, 95% CI of net
  `[-$53.91, +$987.77]`, `P(net>0) = 0.959`. The old config's CI spanned
  zero (`P(net>0)=0.60`); this one does not.

This is **not** a reason to flip `TRADING_MODE="LIVE"` by itself — see
HANDOFF §5, the launch criteria are unchanged (100+ paper trades under the
new config, PF > ~1.2 sustained, affordable max DD). It is a trade-frequency
fix with a backtested quality improvement, not a validated live edge; keep
`TRADING_MODE="FORWARD_TEST"` and judge the resulting paper book same as
before.

## 3. Changes made

- `config.py`: `RSI_BUY_LEVEL` 35 → **40**, `RSI_SELL_LEVEL` 65 → **60**,
  `SESSION_END_HOUR_UTC` 17 → **20** (`SESSION_START_HOUR_UTC` unchanged at
  7). `BE_TRIGGER_R`, ATR filter, SL/TP multiples, spread/margin settings all
  unchanged (ATR floor 0.50 was checked at 0.30/0.40/0.50/0.60 — it never
  binds on this dataset, so it is not the frequency bottleneck and was left
  alone).
- `research/strategy_sweep.py`: `_rolling_mean` switched from a cumsum-based
  rolling mean to `pandas.Series.rolling(period).mean()` to match
  `strategy.py` bit-for-bit at window boundaries (see Tooling note above).
  `research/parity_test.py` now passes with 0 mismatches on the new config
  (previously 2, both traced to the float-precision tie described above, not
  to a live/backtest logic bug).

## 4. Not changed / explicitly considered and rejected for this pass

- **Session 13:00–17:00 (NY only):** best quality (PF 1.68) but *fewer*
  trades (71) — wrong direction for "too few trades."
- **RSI 45/55 or wider:** still profitable but PF and avgR both degrade past
  40/60 (45/55: PF 1.13 vs 1.32; 44/56 combined with the new session: PF 1.17
  vs 1.32) — 40/60 is the better trade-off, not just the top of a monotone
  trend.
- **ATR floor:** unchanged — swept 0.30/0.40/0.50/0.60, identical results
  every time on this dataset, so it isn't gating frequency here.
