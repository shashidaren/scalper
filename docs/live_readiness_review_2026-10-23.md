# Live-readiness review — Gold scalper, 2026-10-23

**Question.** `HANDOFF.md` → `STATUS.md` says the book is `FORWARD_TEST` and the
launch criteria are ~100+ paper trades, sustained PF > 1.2, affordable max DD.
Is it ready for a live session, and what would actually make it produce better
results?

**Answer.** **No — do not flip `TRADING_MODE`.** The engine is operationally
sound (all 13 smoke checks pass, live/backtest signal parity passes, the ledger
guards hold), but the *evidence* is not there, and there are three live-only
gaps that the paper book structurally cannot close. Details and a corrected
gate below.

Everything here is read-only analysis. **No strategy parameter, config value or
runtime behaviour was changed.**

---

## 1. What I reproduced (so the numbers below are the repo's own)

| check | command | result |
|---|---|---|
| Reference backtest | `backtest.py` | 255 trades, **+$456.58**, PF **1.32**, WR 28.2%, max DD $108.65, 72 TP / 43 BE / 140 SL — identical to `docs/loss_analysis_2026-10-02.md` |
| Sweep engine parity | `strategy_sweep.py --verify` | identical to `backtest.py` |
| Live↔replay signal parity | `research/parity_test.py` | **PASS** — 0 mismatches over 598 bars + 1,200 loop-cache cycles |
| Unit suites | `tests/test_*.py` | 6/6 pass (128 checks) |
| Deploy gate | `tools/smoke_test.py` | **SMOKE TEST PASSED** (13 checks) |

Run in a clean venv with `pandas`/`rpyc`/`fastapi` installed; without `rpyc`
the smoke gate reports `SMOKE TEST FAILED: imports`, which is an artefact of the
review box, not the server.

## 2. The evidence, side by side

| | backtest (in-sample, 2026-06-02 → 09-11) | paper book (`logs/`, 2026-10-04 reset → 10-23) |
|---|---|---|
| trades | 255 | **60 closed** + 1 open |
| net | +$456.58 | **−$5.65** (300.00 → 294.35) |
| PF | 1.32 | **0.98** |
| win rate | 28.2% | **25.0%** (15W / 45L) |
| avg R | +0.11 | **−0.03** (σ 1.50) |
| max DD | $108.65 (10.9% of the nominal $1,000) | **$103.95 = 34.6% of the $300 book** |
| exits | 72 TP / 43 BE / 140 SL | 15 TP / 6 BE / 39 SL |

Two things to note before anyone reads the paper book as a verdict:

- **The paper book does not overlap the research data.** The checked-in M5 file
  ends 2026-09-11; the paper book starts 2026-09-15. The only post-June evidence
  in this repo is the one thing that has *not* been backtested, and the backtest
  window is now ~6 weeks stale.
- **−0.03R vs +0.11R is not a divergence.** With σ≈1.5R and n=60 the standard
  error on mean R is 0.19R. The paper book is consistent with the backtest edge;
  it simply cannot confirm or refute it.

## 3. Why 60 — or 100 — trades cannot answer the question

Monte Carlo on the strategy's **own** exit mix (28.2% at +2.45R, 16.9% at
−0.05R, 54.9% at −1.05R, which reproduces the printed avg R of 0.11), 20k
resamples per row:

| n | 95% range of observed PF | P(net ≤ 0) **given a real edge** | P(PF > 1.2) **given a real edge** |
|---|---|---|---|
| 60 (today) | 0.62 – 2.04 | **29%** | 47% |
| 100 (the stated gate) | 0.73 – 1.82 | **24%** | 46% |
| 255 | 0.88 – 1.55 | 13% | 45% |

And in a **zero-edge** book of the same geometry (same payoff shape, mean
shifted to 0), PF still exceeds 1.2 in **21%** of 100-trade samples.

So the current gate ("100+ paper trades, PF > 1.2") moves the odds from roughly
50/50 to about 2:1. It will fail a genuinely profitable strategy 54% of the time
and pass a genuinely worthless one 21% of the time. To reach 80% power against
a 0.11R edge you need **~330 trades**; for 95%, **~540** — i.e. 4–7 months at the
current 3 trades/day, to prove an edge of this size.

**That is the core finding: this strategy's edge is too thin to be verified by
forward testing on a practical timescale.** The cheap fix is not more paper
trades; it is (a) more independent data, (b) a bigger edge, and (c) a decision
rule that can actually say no.

## 4. Blocking findings for a LIVE session (ranked)

### 4.1 The paper book measures an exit engine that LIVE will not run — **blocker**

- The breakeven ratchet exists only in `paper.py:280-284` (`p["sl"] =
  p["entry"]` on `be_armed`). The live path never modifies a position: there is
  **no `TRADE_ACTION_SLTP` / `position_modify` anywhere in the repo**.
- In LIVE, every trade therefore runs to the original 2×ATR SL or the 5×ATR TP,
  with no BE and no time stop (`run.py` warns if `MAX_HOLD_MINUTES` is set in
  LIVE, because the stop is paper-only).
- The validated shape has 43 BE exits out of 255 (16.9%). The live shape is a
  different config: replayed, it is **232 trades, +$563.46, PF 1.37, WR 34.5%,
  max DD $122.26**. That is not worse in-sample — but it has *never been forward
  tested*, and the 60-trade paper record does not transfer to it.

Either implement BE in LIVE, or pre-register "LIVE = no BE" and run the paper
book with `BE_TRIGGER_R` off so the forward test measures what will trade. Until
one of those happens, the paper book is validating the wrong machine.

### 4.2 Nothing verifies that the live position actually has a stop — **blocker**

`mt5_bridge._open_trade_locked` returns on `TRADE_RETCODE_DONE` and `run.py`
logs the entry. Nothing re-reads the position to confirm `sl != 0` and that the
stops are where they were requested. A broker-side "invalid stops", an
`ORDER_TIME_GTC` surprise, or a partial stop attach leaves the book **naked with
no alarm** — the only failure mode here that is not self-limiting. Add a post-fill
`positions_get` check (2s later, then retry/close) before going live.

### 4.3 Weekend and gap exposure with no flat rule

The paper book has already held a trade **59.1 hours** (Fri 2026-10-09 13:10 →
Mon 00:14) and 8 trades longer than 4h; TP exits have a **median hold of 133
minutes**. `MAX_HOLD_MINUTES = 0` (`config.py:33`) and there is no
Friday-close rule.

This is not a P&L argument (the loss analysis already showed a Friday cut-off
costs P&L in-sample, and the paper book cannot see gap risk at all because it
fills the SL at the exact SL price). It is a tail-risk argument: in LIVE a
weekend gap fills *through* the stop, and one such fill can be several R. A
flat-by-Friday-20:00-UTC rule plus a max-hold cap converts an unbounded tail
into the modelled 1R.

### 4.4 No account-level drawdown stop, and the book already ran a 35% DD

The only loss gates are `MAX_DAILY_LOSS = 30` and `MAX_TRADES_PER_DAY = 15`
(`config.py:64-65`) plus the portfolio daily gate. There is no equity floor.

- Paper book peak-to-trough: **$103.95 on a $300 book = 34.6%**.
- Backtest max DD at 0.01 lots: **$108.65** (no-BE: $122.26).

A $300 live account is therefore one ordinary bad stretch away from losing a
third of its equity, and at 0.01 lots gold there is no smaller position to take.
Minimum viable live balance is ~**$600–1,000** (DD ≤ 10–20%), **or** enable
`RISK_PCT` sizing *with* a broker `volume_min` that can actually be met.

Two days in the paper book breached `MAX_DAILY_LOSS`: 2026-10-08 **−$37.00**,
2026-10-13 **−$32.90** — the gate blocks *new* entries only, so a day can
overshoot by one full stop. Expected, but budget for it.

### 4.5 Realized R ≠ modelled R (slippage on the entry)

`mt5_bridge.py:361-374` builds SL/TP from the **pre-fill** tick and sends
`deviation: 20`. If the fill differs, the true risk is `sl_dist ± slippage` and
every R in the forward record is off by that amount. Recompute the stops from
`result.price` (or from the position after the fill).

### 4.6 The research data is stale and spent

`data/GOLD_M5.csv` ends **2026-09-11**. The pre-registered "untouched pre-June
pull" (`fetch_data.py --start-pos 20000`) still has not been run, and the file
has now been inspected three times (PR #7, #11, #12). Any further "OOS" number
computed from it is a re-split, not out-of-sample. This is the cheapest real
improvement available: refresh the data before re-testing anything.

### 4.7 Smaller items (fix before or during the first live week)

- `MAX_CONSECUTIVE_LOSSES` (`config.py:66`) is dead code — documented as
  measured-harmful, but the comment still describes it as a live control.
- No log rotation: `logs/trades.jsonl` grows ~11.5k rows / ~1.7 MB per day
  (`logger.py` appends, nothing rotates).
- The dashboard serves `/`, `/api/status`, `/api/portfolio` with **no auth** on
  `0.0.0.0:8088` — read-only, but it publishes balance, equity and open
  positions. With a live account that is information disclosure.
- No `SYMBOL_TRADE_STOPS_LEVEL` preflight. Gold's ATR stop is ~8 price units so
  it will not bite today, but it is a one-line assert and a broker change away.
- `MAX_SPREAD_POINTS = 80` vs a data spread of median 51 / p90 52: the gate
  permits entries up to ~1.6× the typical spread, while the backtest charges
  0.47–0.51. Tightening to ~65 (1.25× p90, the BTC convention) is defensible as
  cost containment — but it also vetoes entries in fast moves, so it is a trade,
  not a free win.

## 5. Improvements that would actually raise the result

Ordered by expected value per unit of effort. **None of A–C should be adopted
without the pre-registered cold-OOS pass** — that discipline is the most
valuable thing in this repo.

**A. Fix the volatility floor — the biggest structural lever.**
`ATR_MIN = 0.50` (`config.py:123`) is dead code: the data's ATR min is **1.22**
(p5 2.43, median 4.46), so the filter has never blocked a single signal in its
life. Meanwhile the *bottom* ATR quartile of entries is the only losing bucket
(−$60.85, PF 0.76) and the top quartile makes +$402.44 at PF 1.82. A floor at
3.0 blocks only 13.7% of bars; 3.5 blocks 25.5%. `--candidates` rates ATR floor
3.0/3.5/4.0 as surviving TRAIN and cold OOS (+$315 / +$336 / +$300 TRAIN;
+$199 / +$176 / +$169 OOS). The cost is trade frequency, which is exactly what
PR #11 was raised to fix — so set the floor where PF improves without gutting
flow, and measure it. This is the one change that removes a losing regime rather
than re-ranking noise.

**B. Complete the pre-registered sequence on fresh data.**
`TP 6.0×ATR` is the only candidate that survived TRAIN + cold OOS + both regimes
+ **4/4** walk-forward folds (+$342.62 TRAIN / +$195.44 OOS / +$538.06 full,
PF 1.38, DD $104.49, P(net>0)=0.968). Then `TP 6.0 + ATR floor 3.0`
(+$580.90, PF 1.44, the only CI excluding zero), then `session 08-20`. Run all
three on the pre-June pull **and** the post-2026-09-11 pull before touching
`config.py`. Expect ~3–4 weeks of real edge improvement if it holds; expect it
to shrink, that is the point.

**C. Make the forward test measure the live engine** (§4.1). The cheapest
version is a config-only change to the paper book (`BE_TRIGGER_R = None`), which
costs nothing but restarts the "stable config" clock — worth it, because a
forward record for a config that cannot be traded is worth nothing.

**D. Add the risk controls that pay regardless of edge:** post-fill SL
verification (4.2), Friday 20:00 UTC flat + `MAX_HOLD_MINUTES` 360–480 (4.3),
an equity floor kill switch (e.g. −20% from start), and a min-account-size rule.
A 6h time exit is roughly P&L-neutral in the sweep (TRAIN +$208 vs +$286, OOS
+$238 vs +$171) — it is bought as tail insurance, not as alpha, and should be
described that way.

**E. Watch the short side, do not touch it.** Paper book: BUY 4 wins / 29
(−$93.06, mean R −0.41) vs SELL 11 / 31 (+$87.41, +0.34R). Two-sided Fisher
p = 0.075, and that is one of ~10 slices examined — i.e. noise. Backtest says
both sides work (BUY PF 1.27, SELL 1.38). Pre-register the rule now so it
cannot be fitted later: *re-examine at 40 BUY trades; act only if BUY mean R is
still < −0.25R and a one-sided test is < 0.05.*

## 6. The gate I would replace §"launch criteria" with

1. **Cold-OOS on data never used for selection** — the pre-June pull and the
   post-2026-09-11 pull, same config, n ≥ 100, bootstrap mean-R CI above zero,
   and **4/4** walk-forward quarters positive. A retrospective re-split of
   `GOLD_M5.csv` does not count any more.
2. **Forward evidence with power** — either ~300+ paper trades on the *exact*
   exit engine that LIVE will run, or a positive mean R whose bootstrap CI
   excludes zero. "PF > 1.2 at 100 trades" is retired: §3 shows it is a coin
   flip with extra steps.
3. **Execution drill on a demo login** — 20 trades at 0.01 lots verifying:
   fill price vs requested, `sl != 0` on the position, a BE modify round-trip,
   `stops_level` and filling-mode acceptance, and realized R vs modelled R
   within tolerance.
4. **Then LIVE at 0.01 lots**, hard equity floor, kill switch drilled, a 30-day
   review, and gold on its own account (the shared-account rule in `STATUS.md`
   still stands even for a Gold-only flip).

## 7. Bottom line

Operationally ready, evidentially not. The code, the guards, the parity and the
ops automation are in better shape than most live retail bots — the problem is
that the edge is ~0.11R per trade, which is real-if-it-is-real but takes 330+
trades to see, and the forward test is currently measuring an exit engine the
live path cannot reproduce. Fix §4.1 and §4.2, add the three risk controls in
§4.3–4.4, refresh the data, and re-open the question with the §6 gate.
