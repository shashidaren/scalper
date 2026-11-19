# Gold research protocol — BREAKOUT-B

**v2, 2026-11-19. Rules locked; input freeze pending.** This amends the
2026-10-24 proposal before testing. The question is whether a trend-filtered
M5 close breakout has positive after-spread expectancy on unseen XM GOLD
bars. It is not a re-tune of the deployed RSI pullback. Phase 1 cannot finish
until the inventory and provenance below are reviewed and committed.

## Grid and execution rules

Test the Cartesian product in the order shown (leftmost changes slowest):

| Dimension | Ordered values |
|---|---|
| Prior channel length N | 10, 20, 30 |
| Trend EMA span | 50, 100, 200 |
| Initial stop distance in ATR(14) | 1.5, 2.0, 2.5 |
| Profit exit | fixed 3R, opposite channel |

That's **54 cells**. Drop the 2.5R target and unfiltered session: retaining
both exit families tests the payoff hypothesis without also selecting hours.

- At the last completed bar `s`, go long if its close is strictly above both
  the highest high of bars `[s-N,s)` and its EMA; short below both the lowest
  low and EMA. Equality is not a signal. Use `research/strategy_sweep.py` at
  `c96f3d3` for the windowed EMA, simple ATR, 202-bar warm-up and replay fill
  convention (signal close, first managed bar `s+1`). One position at a time;
  entries only at decision hours `[07:00,20:00)` UTC and ATR ≥ 0.50.
- `R` distance is fixed at entry. Keep Gold's 1.5R breakeven ratchet and the
  replay ordering: arm BE on the managed bar's favorable extreme, then check
  stop before profit exit. Fixed target is entry ± 3 initial stop distances.
  Channel style has **no target**: exit a surviving long at bar `t`'s close
  if strictly below the lowest low of `[t-N,t)`; mirror above the highest high
  for a short. No touch exit, second lookback, reversal on the exit bar, or
  session restriction on exits. No trailing, time exit or other overlays.
- Use the pinned Gold replay economics for both candidate and comparator:
  0.01 lot, 100 oz/lot, deduct exit-bar spread × 0.01 in price once. Like
  the pinned Gold `--verify` replay, do not simulate the live entry spread
  veto. These are research fill assumptions, not broker execution evidence.

## Prospective reservation and exclusions

Use **only** completed XM GOLD M5 bars, by exported UTC bar-open timestamp.
Reserve ten calendar weeks, split 60:40 **by time**, not by row count:

| Slice | Inclusive start UTC | Exclusive end UTC | Input SHA-256 |
|---|---|---|---|
| TRAIN | 2026-11-23 00:00 | 2027-01-04 00:00 | pending collection |
| Cold OOS | 2027-01-04 00:00 | 2027-02-01 00:00 | pending collection |

Exclude all rows outside those bounds, including every previously downloaded
window. In particular `data/GOLD_M5.csv` at `c96f3d3` (SHA-256
`b5bb79e2813c1766dbbe511c2447d56cfec959f29727b2c52e3a4b999ac69d2b`)
is spent, not a freeze. No proxy, gap filling, discretionary date drops, or
use of overlapping paper results to change these rules. Leave the reservation
sealed: no charts, screens or outcome summaries for strategy selection.

After the end, collect and fingerprint as in `RUNBOOK.md` (Gold BREAKOUT-B).
Record the inventory here (raw file hash, first/last timestamps, count and
hash per slice), retrieval time, broker/source and reviewer confirmation of
coverage, expected market closures and no prior research inspection. Slice
hashes cover the original header and selected CSV rows in original byte order.
A hash identifies bytes; it cannot certify provenance or blindness. If
coverage or blindness cannot be established, stop. Do not slide the split;
a replacement requires a new prospective reservation before inspection.

## Selection and decision (phase 2 only)

1. Start each replay segment flat, warm up within it, and omit a position
   still open at its end as in the pinned replay. On TRAIN only, rank cells
   with at least one closed trade by highest **unrounded arithmetic mean net
   R** (signed price move minus spread, divided by initial stop distance).
   Exact tie: first cell in the table's product order. If none qualifies,
   close as failed. Commit exactly one winning tuple and its input/code
   hashes before opening OOS. No runner-up or refitting.
2. Evaluate that winner once on OOS. Require mean net R ≥ 0.12, dollar PF ≥
   1.25, ≥ 1.5 closed trades per distinct OOS UTC date with bars (include
   zero-trade dates), and closed-equity dollar max DD ≤ 1.3× the deployed
   RSI geometry (`config.py` at `c96f3d3`) replayed on that same slice.
   Require the 2.5th percentile of 2,000 same-size IID resamples of closed
   OOS trade mean net R to exceed zero (NumPy default_rng seed 42, linear
   percentile). No alternative confidence metric after inspection.
3. For the four-fold stability check use four chronological, non-overlapping
   slices of the entire reserved file, cut at row indices `floor(k*n/4)`
   for k=1,2,3. Replay only the frozen tuple, independently per fold; require
   positive net dollars in ≥3 folds. This includes TRAIN; it is not another
   independent OOS result. No trades or undefined OOS metrics cannot pass.
4. Record all results here. A missed gate closes BREAKOUT-B; passing permits
   further paper evaluation only. `STATUS.md` and `plans/gold.json` govern
   the separate execution, account and forward-evidence gates. No adoption,
   mode change or sweep is authorized by this protocol amendment.
