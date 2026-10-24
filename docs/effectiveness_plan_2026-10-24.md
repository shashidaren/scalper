# Gold effectiveness plan — 2026-10-24

**Status.** Agreed. No runtime / strategy parameter changed in this commit.
`TRADING_MODE` stays `FORWARD_TEST`. Backtest and paper book remain the
255 / +$456.58 / PF 1.32 shape until a candidate survives cold OOS on **fresh**
data.

**Source.** Review of `ARCHITECTURE.md`, `HANDOFF.md`, `STATUS.md`,
`strategy.py`, `config.py`, `docs/loss_analysis_2026-10-02.md`, and
`docs/live_readiness_review_2026-10-23.md`.

---

## 1. Why change anything

- Edge is thin (~0.11R). The current launch gate ("100+ paper trades, PF > 1.2")
  has ~2:1 discrimination only; ~330 trades are needed for 80% power.
- `ATR_MIN = 0.50` is dead code (data ATR min ≈ 1.22). The bottom ATR quartile
  of entries is the only losing bucket (−$60.85, PF 0.76); top quartile is
  strongly profitable (PF 1.82).
- Research file `data/GOLD_M5.csv` ends 2026-09-11 and has been inspected three
  times. Any further split of it is not out-of-sample.
- LIVE protection and risk controls (weekend flat, stop verify, BE ratchet,
  equity floor) already shipped 2026-10-23. The remaining lever is **entry
  quality / payoff shape**, not more exit plumbing.

## 2. Pre-registered candidates (do not adopt until cold OOS on fresh data)

Run in this order on a **new** pull only:

| # | Change | Prior full-file / TRAIN+OOS evidence | Notes |
|---|---|---|---|
| 1 | `ATR_MIN` → 3.0 (also test 2.5 / 3.5) | Survived TRAIN + cold OOS in 2026-10-02 candidates | Removes the losing low-vol regime. Trade-count cost is the main trade-off. |
| 2 | `TP_ATR_MULT` → 6.0 | TRAIN +$342.62 / OOS +$195.44; 4/4 walk-forward; full +$538 / PF 1.38 | Monotone plateau; inside bootstrap noise on spent data. |
| 3 | Combo: TP 6.0 + ATR floor 3.0 | Strongest prior point estimate (+$580.90, PF 1.44, CI excluded zero) | Preferred if both #1 and #2 hold individually. |
| 4 | Session start 08 instead of 07 (optional) | Survived prior splits | Lower priority; frequency vs quality. |

**Reject without fresh data:** BE off, SL 2.5×, any hour/day filter, wiring
`MAX_CONSECUTIVE_LOSSES` (already measured harmful).

## 3. Data work (must precede any config.py edit)

1. Refresh `GOLD_M5.csv`:
   - Untouched pre-June-2026 window (`fetch_data.py --start-pos 20000` or
     equivalent).
   - Everything after 2026-09-11 through current.
2. Re-run the exact candidate protocol from `research/strategy_sweep.py
   --candidates` (and walk-forward / bootstrap) on the new file only.
3. Adopt a candidate **only** if it still wins on that fresh data under the
   same discipline (TRAIN → cold OOS → regimes → 4/4 folds).
4. After any adoption: restart the paper-book "stable config" clock and let it
   accumulate under the new parameters.

## 4. Parallel operational items (safe anytime)

These do not touch strategy geometry:

- Confirm paper and LIVE exit engines stay matched (already the intent of
  `live_position.py`).
- Demo execution drill before any real-money flip
  (`docs/live_readiness_review_2026-10-23.md` §6.3).
- Consider tightening `MAX_SPREAD_POINTS` toward 1.25× observed p90 (cost
  containment; measure veto rate first).
- Log rotation / dashboard auth before attaching a funded account.
- `SYMBOL_TRADE_STOPS_LEVEL` preflight in the bridge (cheap insurance).

## 5. Explicit non-goals

- No LIVE flip on the shared XM account or with a ~$300 balance.
- No re-tuning on the existing spent `GOLD_M5.csv`.
- No change to `TRADING_MODE`, magic, or service units without a new cold-OOS
  pass and an explicit decision.

## 6. Success criteria for the next gate

Replace the old "100 trades / PF > 1.2" rule with:

1. Cold OOS on data never used for selection (pre-June + post-2026-09-11),
   n ≥ 100, bootstrap mean-R CI above zero, 4/4 walk-forward quarters positive.
2. Forward evidence with real power (~300+ paper trades on the **exact** exit
   engine LIVE will run, or mean R whose bootstrap CI excludes zero).
3. Demo execution drill (20 trades) confirming stop attach, BE round-trip, and
   realized R vs modelled R.
4. Then, and only then, consider LIVE at 0.01 lots on a sufficiently funded
   account with the existing equity floor and kill switch.

---

**Next concrete action on the box:** refresh GOLD M5 data, then re-run the
candidate table above. Do not edit `ATR_MIN` / `TP_ATR_MULT` until that
completes.
