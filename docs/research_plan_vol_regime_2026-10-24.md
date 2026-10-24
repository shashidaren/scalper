# Gold Research Plan — Volatility Regime Filter
**Date locked:** 2026-10-24  
**Status:** PRE-REGISTERED (no results yet)  
**Hypothesis ID:** VOL-REGIME-A

## 1. Motivation (why this, not another RSI/EMA tweak)

The current RSI-pullback + EMA200 geometry has a thin edge (~0.03R on the most recent window, previously ~0.11R).  
Loss anatomy (both old and new windows) repeatedly showed that low-ATR environments are the weakest or only losing regime.  
A hard volatility filter is a clean, structural change that removes a losing regime rather than re-ranking the same signals.  
It is orthogonal to the existing entry logic, so we can keep the current shape and only add a gate.

## 2. Exact hypothesis

**Statement:**  
Restricting entries to bars where the current ATR(14) is at or above the X-th percentile of ATR over the previous N bars will improve mean R, profit factor, and walk-forward stability, while keeping acceptable trade frequency.

**Null hypothesis we are trying to reject:**  
The filter does not produce a statistically meaningful improvement on completely unseen data.

## 3. Pre-registered parameter search space

Only these knobs will be searched. Everything else stays exactly as in current `config.py`.

| Parameter              | Values to test                          | Notes |
|------------------------|-----------------------------------------|-------|
| `ATR_LOOKBACK`         | 50, 100, 200                            | Bars used for percentile |
| `ATR_PERCENTILE`       | 40, 50, 60, 70                          | Minimum percentile to allow entry |
| `ATR_MIN_ABSOLUTE`     | None (disabled) or 2.5 / 3.0            | Optional hard floor on top of percentile |

- Total combinations: 3 × 4 × 3 = 36 (manageable).  
- No other parameters (TP, SL, RSI, session, BE, etc.) will be touched in this plan.

## 4. Data splits (locked before any run)

- **Full available file** after fresh pull (target: as far back as the broker will give us, ideally ≥ 18 months).  
- **TRAIN:** earliest 60% of the file (or up to 2026-06-30 if the file is shorter).  
- **Cold OOS:** the most recent 40% (must include the entire Jul–Oct 2026 window that the current strategy already saw).  
- **Walk-forward:** 4 contiguous non-overlapping folds on the full file.  
- File hash + exact date range of every split will be recorded in this document *before* the first sweep is run.

## 5. Success criteria (all must pass)

A candidate is only considered for paper deployment if **all** of the following are true on the cold OOS + walk-forward:

1. Mean R ≥ 0.12  
2. Profit Factor ≥ 1.25  
3. Bootstrap 95% CI of mean R excludes zero (or P(net > 0) ≥ 0.90)  
4. At least 3 out of 4 walk-forward folds are profitable  
5. Average trades per day still ≥ 1.8 (so we do not re-introduce the “hardly trading” problem)  
6. Max DD on OOS is not worse than 1.3× the current geometry’s OOS DD

If no combination meets the bar, the hypothesis is **closed as failed** and we move to Hypothesis B (breakout) without cherry-picking.

## 6. Execution order

1. Fresh data pull + hash documentation.  
2. Implement the percentile filter as a clean optional gate in `strategy.py` (default = off, so current behaviour is unchanged).  
3. Extend `research/strategy_sweep.py` (or new script) to search only the 36 combinations above.  
4. Run TRAIN → select best → freeze → evaluate on cold OOS + 4-fold walk-forward.  
5. Write results into this same document under a new “Results” section.  
6. Decision: adopt / reject / move to next hypothesis.

## 7. What will NOT be done

- No looking at OOS numbers until the candidate is locked.  
- No adding hour/day filters, consecutive-loss rules, or TP/SL changes in this plan.  
- No changing the paper book or `TRADING_MODE` until a candidate fully clears the gate above.  
- No re-using the already-inspected Jul–Oct window for selection.

## 8. Next actions after this document is committed

- [ ] Fresh `GOLD_M5.csv` pull + record hashes/dates here  
- [ ] Code the ATR percentile gate (feature-flagged)  
- [ ] Implement the restricted search in the sweep tool  
- [ ] Run the pre-registered experiment  
- [ ] Update this file with results and a clear adopt/reject decision

## 9. Code changes (draft)

See accompanying notes in the PR / session for the exact patch to `strategy.py` and `config.py`.
