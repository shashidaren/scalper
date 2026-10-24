# Gold Research Plan — Breakout / Momentum
**Date locked:** 2026-10-24  
**Status:** PRE-REGISTERED (no results yet)  
**Hypothesis ID:** BREAKOUT-B

Previous track VOL-REGIME-A was closed the same day (no candidate cleared the gate on the spent Jul–Oct window).

## 1. Motivation

VOL-REGIME-A (volatility filter on the existing RSI-pullback shape) failed to clear the gate.  
The current mean-reversion geometry has a thin and degrading edge (~0.03R on the recent window).  
A clean breakout / momentum shape is a different payoff profile and is the highest-value next test.

## 2. Exact hypothesis

**Statement:**  
Entries on a clean M5 close break of the prior N-bar high/low (Donchian-style), filtered by a longer EMA trend, with ATR-based stop and either a fixed reward multiple or opposite-channel exit, will produce a higher mean R and more stable walk-forward performance than the current RSI-pullback geometry.

**Null hypothesis:** The breakout shape does not produce a statistically meaningful edge on completely unseen data.

## 3. Pre-registered search space

Only these knobs will be searched. Everything else stays fixed.

| Parameter            | Values to test                         | Notes |
|----------------------|----------------------------------------|-------|
| Entry channel (N)    | 10, 20, 30                             | Prior bars for high/low break |
| Trend EMA            | 50, 100, 200                           | Close must be on the correct side of EMA |
| SL ATR multiple      | 1.5, 2.0, 2.5                          | |
| TP style             | Fixed 2.5R / 3.0R **or** opposite-channel exit | Two exit families |
| Session filter       | Current 07–20 **or** none              | |

Maximum combinations kept deliberately small (≤ 54).  
No other parameters (RSI levels, BE trigger, hour filters, etc.) will be touched.

## 4. Data splits (locked before any run)

- Fresh pull required (use `tools/pull_gold_m5.sh` or equivalent).  
- **TRAIN** = earliest 60 % of the new file.  
- **Cold OOS** = most recent 40 % (must include post-2026-07 data that the old shape already saw).  
- **Walk-forward** = 4 contiguous non-overlapping folds on the full file.  
- File hash + exact date range of every split will be recorded in this document *before* the first sweep is run.

## 5. Success criteria (all must pass)

A candidate is only considered for paper deployment if **all** of the following are true on the cold OOS + walk-forward:

1. Mean R ≥ 0.12  
2. Profit Factor ≥ 1.25  
3. Bootstrap 95 % CI of mean R excludes zero (or P(net > 0) ≥ 0.90)  
4. At least 3 out of 4 walk-forward folds are profitable  
5. Average trades per day still ≥ 1.5  
6. Max DD on OOS is not worse than 1.3× the current geometry’s OOS DD

If no combination meets the bar, the hypothesis is **closed as failed** and we move on without cherry-picking.

## 6. Execution order

1. Fresh data pull + record hash/dates here.  
2. Implement the breakout shape as a clean optional family (default = current RSI-pullback remains the live path).  
3. Restricted search over the pre-registered combinations only.  
4. TRAIN → select best → freeze → evaluate on cold OOS + 4-fold walk-forward.  
5. Write results into this same document under a new “Results” section.  
6. Decision: adopt / reject / move to next hypothesis.

## 7. What will NOT be done

- No re-tuning of the old RSI-pullback / EMA200 parameters.  
- No hour/day filters fitted on this sample.  
- No enabling the new shape on the paper book until the full gate is cleared.  
- No expanding the search space without a new pre-registration.

## 8. Next actions after this document is committed

- [ ] Fresh `GOLD_M5.csv` pull via `tools/pull_gold_m5.sh` + record hash/dates here  
- [ ] Code the breakout family (feature-flagged, live path unchanged)  
- [ ] Restricted sweep over the locked combinations  
- [ ] Evaluate against the success criteria above  
- [ ] Update this file with results and a clear adopt/reject decision
