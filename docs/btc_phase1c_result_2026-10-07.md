# BTCUSD Phase 1c — negative result (FAIL / No-Go), 2026-10-07

**Question.** Does the pre-registered Donchian breakout (hypothesis C) have an edge on an untouched XM `BTCUSD` H1 pull after the broker's spread?

**Answer: NO. FAIL / No-Go.** The train-selected candidate is negative on cold OOS (`n=96`, **−$40.03**, **PF 0.96**). The gate requires positive cold-OOS net, PF ≥ 1.2, n ≥ 60, and gross edge above cost. Two of those four fail. Do not adopt `BTC_STRATEGY=donchian`. Do not retune this file.

Source: `/root/ops/collect-2026-10-07/collection.md`, produced read-only by `docs/collect-2026-10-07/collect_phase1c.sh` at `2026-10-07T02:55:44Z` on `scalping`. Repo HEAD at collection was `eba81743d0b088fbb608be1a05a7c47059f7cf4f`. Tree clean. No unit was started, stopped, or reconfigured, and no order was placed.

---

## 1. Verdict first

| Read | n | net | PF | max DD | iid 95% CI | P(net>0) | Gate |
|---|---|---|---|---|---|---|---|
| Pre-registered baseline (`don100/exit50`, SL 2.0, time-stop off) | 88 | +$129.23 | 1.18 | $292.17 | [−$450.11, +$801.65] | 0.633 | FAIL (PF < 1.2; CI includes 0) |
| **TRAIN-selected winner** (`don100/exit50`, SL 2.5, time-stop 100) | **96** | **−$40.03** | **0.96** | $317.45 | [−$551.02, +$539.53] | 0.425 | **FAIL** (net ≤ 0 and PF < 1.2) |

Winner exits on the OOS slice: SL 62, channel 12, time 22, breakeven 0, TP 0. Gross vs cost on that slice was `g=+0.172R` vs `c=0.041R`, so the cost precondition passed. It does not rescue a negative net or a sub-1.2 profit factor.

The baseline's +$129 is not a pass. It was not the selected candidate, PF 1.18 misses 1.2, and the interval runs from about −$450 to +$802.

All four train-eligible candidates were already negative before the OOS read:

| Rank | Config | TRAIN trades | TRAIN net | TRAIN PF | TRAIN max DD |
|---|---|---|---|---|---|
| 1 (frozen) | don100/exit50 SL=2.5 ts=100 | 96 | −$124.94 | 0.88 | $248.67 |
| 2 | don100/exit50 SL=2.5 ts=off | 83 | −$169.39 | 0.80 | $263.59 |
| 3 | don100/exit50 SL=2 ts=100 | 103 | −$234.68 | 0.77 | $365.99 |
| 4 | don100/exit50 SL=2 ts=off | 93 | −$358.78 | 0.61 | $464.03 |

TRAIN spread p90 was 9,506 points, so the replay gate was 11,890 (1.25× p90) and vetoed 0% of TRAIN quotes. The placeholder `MAX_SPREAD_POINTS=1500` would still veto 100% of those quotes. That is why the live paper book had 15,842 `high_spread` skips and 0 closed trades at collection time. Leaving that veto in place is correct. Loosening it does not create an edge.

---

## 2. What was read

| Item | Observed |
|---|---|
| File | `data/BTCUSD_H1.csv` (git-ignored), 1,329,908 bytes, 20,000 bars |
| Span | `2024-06-25 22:00:00` .. `2026-10-07 05:00:00` (833.3 days, 0 gaps, 24/7) |
| sha256 | `f73054611e9b27a589b55c63f4a9a4f734ac9c423c1f528d1b6c344bc023ab21` |
| Split | TRAIN `2024-08-06 13:00` .. `2025-09-06 08:00` (9,500 bars); OOS `2025-09-06 09:00` .. `2026-10-07 05:00` (9,501 bars); warmup 1,000 |
| Shape | entry don100, exit don50, EMA200 trend filter, no TP, no BE |
| Parity | `btc/strategy_btc_test.py` **22/22 PASS** |

The collector prints `timeframe=M5` in the edge-screen and train-select headers. The file is H1. Recon reports `timeframe_minutes=60`, and the ATR (median 493.11 price units) is the H1 distribution, not the M5 median of 81.62 from Phase 1. This is not a second read of the burnt `2026-07-25 .. 2026-10-03` M5 window.

H1 economics at 0.01 lots, from `btc/derive_params.py` on this file: median ATR 493.11, spread p50 6,000 points / p90 9,275, spread/median-ATR 12.9%, spread/risk 6.4% at a 2×ATR stop ($9.86 risk). Cost is no longer the M5 problem (that was 52% of ATR and 26% of risk). The signal still does not clear the gate.

Account login is omitted. The broker print in the collect bundle is the shared XM account, not the paper sim. At 02:55 UTC the BTC paper book was `$300`, 0 closed; gold paper was `$293.36` with spread 53–55 against a gate of 80, and every gold signal was `session:hour=2`.

---

## 3. What the full-file screen does not authorize

`btc/edge_screen.py --family donchian` on the same H1 file is diagnostic only. The configured baseline cannot pay the spread: 181 trades, gross `+0.060R`, cost `0.061R`, net −$229.55, PF 0.86.

The best row on that screen was `don200/exit100`: 99 trades, gross `+0.216R`, cost `0.058R`, net +$75.09, PF 1.07. It was not in the train-select grid, PF is under 1.2, and the file is now inspected. Adopting it would be tuning on seen data. The same ban covers `sl 2.5xATR` and the time-stop rows that printed `g > c` while still losing money.

Swap is unmodelled. The symbol spec in the collect bundle has a large negative swap on both sides. A multi-day H1 hold would be worse than these numbers, not better.

---

## 4. What this rules out, and what it does not

**Ruled out:** hypothesis C as registered and gated — Donchian 100/50 with the EMA200 filter, on this XM H1 pull, at 0.01 lots. Also ruled out: treating the +$129 baseline, or the +$75 `don200/exit100` diagnostic, as a pass.

**Not a license to change config.** `BTC_STRATEGY` stays `scalp`. `TRADING_MODE` stays `FORWARD_TEST`. Do not set the live gate to the measured 11,890 just so this shape can trade. Phase 1 M5 remains a fail (`docs/btc_phase1_result_2026-10-03.md`). A later observation gate of 6,250, if present on the server, is still not a strategy approval.

**Not ruled out, and not to be chased on this file:** a different pre-registered family, or hypothesis B (a lower-spread account tier, with commission modelled, on that tier's own bars). Either needs its own untouched pull. Hypothesis A, the same M5 pullback on a higher timeframe, was not this gate.

Gold is unchanged by this result. It stays on the 100-closed-trade paper clock.
