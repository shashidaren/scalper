# Strategy iteration — 2026-09-30 (offline, blocking for LIVE)

**Question.** HANDOFF §5 blocks any LIVE flip on the fact that the first honest
backtest lost money: PF 0.92, −$57.78 over ~70 days (29 TP / 96 BE / 76 SL).
This note re-measures that baseline, tests the candidate variables one at a
time, and records what was changed — and what the evidence does *not* support.

**Data.** `data/GOLD_M5.csv`, 20,000 M5 bars, 2026-06-02 18:05 → 2026-09-11
16:25 UTC (~70 trading days, one regime: gold 3,957 → 4,695, +19%).

**Tooling.** `research/strategy_sweep.py` replays `backtest.py`'s exact logic
with vectorised indicators (~1 s/run instead of ~28 s). It is verified against
the reference on every configuration change: with the old defaults it
reproduces **201 trades / −$57.78 / PF 0.92 / maxDD $93.02 / 29 TP · 96 BE ·
76 SL** exactly, and with the new defaults it reproduces the new
`backtest.py` output exactly. Nothing below is based on a divergent
re-implementation.

---

## 1. Two measurement bugs found first

### 1a. The "EMA200" was not an EMA200 — and live ≠ backtest

`strategy.check_signal` computes the EMA with `ewm(span=200, adjust=False)` on
whatever window it is handed. With `adjust=False` the first bar of the window
acts as the seed and keeps weight `(1 − 2/201)^(n−1)`:

| window handed to the strategy | seed weight | effective filter |
|---|---|---|
| 202 bars (backtester) | 13.5 % | ≈ a much faster, sample-dependent average |
| 250 bars (live `get_rates(count=250)`) | 8.4 % | a *different* average again |

So the trend filter was not the indicator it claimed to be, and the live path
was evaluating a different indicator than the backtest that was "validating"
it. Fix: one shared constant, `config.INDICATOR_WINDOW_BARS = 1000`
(seed weight ≈ 5e-5, i.e. converged), consumed by the strategy guard, the
bridge fetch and the backtester.

**This makes the honest baseline worse, not better:**

| variation | trades | net $ | PF | maxDD $ |
|---|---|---|---|---|
| window 202 (as reported) | 201 | −57.78 | 0.92 | 93.02 |
| window 300 | 200 | −154.52 | 0.79 | 171.85 |
| window 500 | 202 | −248.80 | 0.67 | 255.00 |
| window 1000 | 198 | −240.87 | 0.67 | 255.00 |
| window 2000 | 189 | −239.30 | 0.65 | 252.66 |
| window 5000 | 153 | −208.37 | 0.63 | 209.21 |

The old 202-bar figure was flattered by the un-converged seed. I also checked
whether the filter is *legitimately* useful as a shorter average — i.e. a
converged EMA of a shorter length:

| converged EMA | 30 | 50 | 75 | 100 | 150 | 200 | 300 |
|---|---|---|---|---|---|---|---|
| net $ | −182 | −146 | −146 | −140 | −149 | −239 | −227 |

Every length loses. The trend filter has no edge at any horizon; the old number
was an artifact.

### 1b. The spread assumption was ~40 % too optimistic

The backtester used a flat `spread_cost = 0.30` (price units) while the data
carries a real spread column: **mean 47 points ($0.47), median 51 points
($0.51)**, on 2-digit gold pricing. `MAX_SPREAD_POINTS = 80` also gates live
entries at $0.80, which confirms the order of magnitude. The backtester now
uses the per-bar spread from the data (falling back to
`config.SPREAD_COST_PRICE = 0.45`) and prints which source it used.

---

## 2. One variable at a time (window 1000, per-bar spread, BE 0.75)

### Breakeven trigger — the one variable that matters

| BE trigger | trades | net $ | PF | WR % | maxDD $ | TP / BE / SL |
|---|---|---|---|---|---|---|
| 0.50 R | 205 | −216.06 | 0.64 | 8.3 | 239.69 | 17 / 122 / 66 |
| **0.75 R (old)** | 198 | −240.87 | 0.67 | 11.1 | 255.00 | 22 / 94 / 82 |
| 1.00 R | 192 | −138.07 | 0.84 | 15.6 | 177.94 | 30 / 69 / 93 |
| 1.25 R | 187 | −48.78 | 0.95 | 20.3 | 115.59 | 38 / 47 / 102 |
| **1.50 R (chosen)** | 174 | +77.50 | 1.08 | 23.6 | 93.96 | 41 / 29 / 104 |
| off | 163 | +73.97 | 1.07 | 28.8 | 107.44 | 47 / 0 / 116 |

Monotone across the whole ladder, and the same shape at window 202
(0.75 R → −$57.78 … 1.5 R → +$341, off → +$365). Mechanically it is exactly
what you would expect from a 5R-target design: with BE at 0.75R, a trade needs
to travel 0.75R *and never once pull back 0.75R again* to reach target, so 94
of ~200 trades got scratched at entry — each paying a full spread — while
almost no winner survived. Loosening BE converts scratches into either full
winners or honest stop-outs, and the stop-outs are already priced in.

`1.5R` is chosen over `off` because it is the conservative end of the plateau
(it still protects a trade that runs far in favour) and it was the better of
the two on the half-split test.

### Rejected / not adopted

| Candidate | Result at window 1000 | Verdict |
|---|---|---|
| Session 08–16 UTC | −152.77 (vs −57.78 for 07–17) | worse; narrower is worse, "session off" is worse too → keep 07–17 |
| H1 trend confirmation (EMA50/100) | −220.23 / −216.51 | clearly worse — the hypothesised fix does not work |
| RSI 40/60 | +108.43 | tempting but **non-monotone** (30/70 −98, 35/65 −241, 45/55 −50) → looks like noise, not a mechanism |
| SL 1.0–3.0 × ATR | −365 → −4.81 | monotone but never positive on its own; wider stops just trade fewer, bigger losses. Not adopted alone. |
| TP 2.0–6.0 × ATR | −34 → +24.59 | non-monotone/noisy (2.5R −9.82, 3.5R −119) → no signal |
| Long-only | BUY +105 / SELL −52 | SELLs lose consistently, but the sample is a +19 % uptrend; dropping shorts would be curve-fitting to one regime. Flagged, not adopted. |

---

## 3. Result of the changed configuration

New defaults: `BE_TRIGGER_R = 1.5`, `INDICATOR_WINDOW_BARS = 1000`,
per-bar spread in the backtester.

| | old config, as reported | old config, honest | **new config** |
|---|---|---|---|
| window / spread | 202 / 0.30 | 1000 / per-bar | 1000 / per-bar |
| trades | 201 | 198 | 174 |
| net | −$57.78 | **−$270.27** | **+$52.80** |
| PF | 0.92 | 0.64 | 1.06 |
| max DD | $93.02 | $286.80 | $99.62 |
| exits | 29 / 96 / 76 | 22 / 94 / 82 | 41 / 29 / 104 |

Bootstrap over the per-trade PnL (5,000 resamples):

| config | observed net | 95 % CI | P(net > 0) |
|---|---|---|---|
| old, as reported | −$57.78 | [−$332, +$237] | 0.335 |
| old, honest | −$270.27 | [−$529, +$8] | 0.027 |
| **new, honest** | +$52.80 | [−$314, +$452] | 0.599 |

**Reading.** The old configuration is *reliably losing* under honest
measurement (P(net>0) ≈ 3 %). The new one is indistinguishable from zero
(P ≈ 60 %) with a 95 % CI roughly ±$380 wide. Stability of the new config:
BUY +$104.75 / SELL −$51.95; first half +$1.07 / second half +$51.73;
months −3.72 / −24.31 / +23.04 / +57.80.

**So: this change removes a reliably-losing behaviour. It does not establish a
validated edge.** The §5 launch criteria (expectancy > 0 after spread, PF > 1.2,
≥6 months, 100+ paper trades) are still not met, and `TRADING_MODE` stays
`FORWARD_TEST`.

---

## 4. Caveats

- **One sample, one regime.** ~70 days of a strong gold uptrend. Every number
  here is in-sample; there is no out-of-sample period available in the repo.
- **Long bias.** BUY is positive and SELL negative in nearly every variant;
  with gold +19 % that is as likely to be regime as skill.
- **Exit resolution is M5-OHLC based** and assumes SL-before-TP when a bar
  touches both (pessimistic), but the intra-bar path is unknown — the same
  caveat that applies to `gold-trading-bot`.
- **No slippage/swap** modelled; the paper book fills at zero slippage.

## 5. Next steps

1. Let the paper book run on the new settings and compare trade-by-trade with
   the backtester (this is the real out-of-sample check).
2. Re-test the BE ladder on more data (append bars / another regime) before
   treating 1.5R as settled.
3. Size the instrument properly: 2×ATR ≈ $10 risk per trade against a $200
   paper balance is 5 %/trade, while the daily-loss gate is $30 (≈3 trades).
   Decide the risk model before any LIVE consideration.
4. Keep the rejected candidates (H1 confirmation, 08–16 session) closed unless
   new data reopens them.
