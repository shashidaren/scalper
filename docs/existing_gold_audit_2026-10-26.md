# Existing Gold data audit — 2026-10-26

Descriptive / hypothesis-generating only. No parameters changed, no new OOS gate run.

## Published book

State timestamp: 2026-10-26 14:20:04. Current book: last 69 exits; 27 older exits excluded across reset. Inferred starting balance $300.00; balance chain verified.

| Group | Closed | Net | PF |
|---|---:|---:|---:|
| All | 69 | $-5.90 | 0.98 |
| side=BUY | 34 | $-96.36 | 0.48 |
| side=SELL | 35 | $90.46 | 1.59 |
| reason=BE | 7 | $0.00 | n/a |
| reason=SL | 44 | $-337.75 | 0.00 |
| reason=TP | 17 | $332.99 | n/a |
| reason=WEEKEND | 1 | $-1.14 | 0.00 |
| First 34 | 34 | $-18.30 | 0.89 |
| Remaining 35 | 35 | $12.40 | 1.07 |
| Since Oct 23 snapshot | 5 | $-3.30 | 0.80 |

Positive / negative / zero P&L: 17 / 45 / 7. State wins/losses: 17/52; the state loss counter includes zero-P&L exits, so it is not a count of cash losses.

Mean winner $19.59; mean cash loss $7.53. Closed-equity max drawdown $103.95 (34.6% of starting balance; not intratrade drawdown).

Largest three winners total $102.82; net without them $-108.72. This is concentration sensitivity, not a reason to discard winners.

Exit-day clustered bootstrap (10,000 draws, seed 20261026, 16 exit days): 95% percentile interval for resampled total net [$-204.83, $204.25]. Days without exits excluded; assumes independent exit-day clusters, does not establish an edge or model regime change.

## Candle coverage and integrity

| File | Rows | First | Last | Duplicate times | OHLC violations | Gaps > interval | SHA256 |
|---|---:|---|---|---:|---:|---:|---|
| GOLD_M1.csv | 20000 | 2026-08-24 02:13:00 | 2026-09-11 16:22:00 | 0 | 0 | 14 | `342e9fdd89e243c7b8c4f9445b9498b299966f72bb8d30af8040e81af05b7625` |
| GOLD_M5.csv | 20000 | 2026-07-15 06:10:00 | 2026-10-23 19:20:00 | 0 | 0 | 72 | `b5bb79e2813c1766dbbe511c2447d56cfec959f29727b2c52e3a4b999ac69d2b` |

Gaps include scheduled market closures; these counts alone do not prove missing broker data. Candle timestamps are treated as supplied; this audit does not independently verify broker timezone. File hashes identify inputs, not broker provenance.

## Interpretation and next steps

- The open position is excluded from realized P&L; no mark-to-market equity or current terminal access is available here. Published heartbeat is a historical observation, not a fresh liveness check.
- M1 and M5 are separate rolling exports, not automatically synchronized tick replay. Do not use M1 as intrabar validation unless entry/exit windows actually overlap.
- Paper BE is booked at zero, whereas backtest BE subtracts spread; summary PF is not directly comparable across these execution models. Entry timing, bid/ask treatment, weekend exit, and intrabar sequencing also need matched replay. Zero paper BE does not by itself prove spread is omitted: spread may be embedded in quote-side fills.
- BREAKOUT-B protocol needs clarification before any sweep: its Cartesian grid is 3×3×3×3×2 = 162 combinations, not ≤54. Its fresh rolling pull can overlap inspected history; freshness of download is not coldness of OOS. Fix the exact subset/exit rules and reserve genuinely unseen timestamps before results are inspected. Do not silently expand or reinterpret the locked plan.
- Do not fit side/hour filters from these small, post-hoc groups. Keep FORWARD_TEST and existing geometry; prioritize matched execution diagnostics and a corrected pre-registered prospective test.
