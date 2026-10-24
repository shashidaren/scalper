# Gold effectiveness plan — 2026-10-24

**Status. CLOSED for parameter changes.** Fresh-data candidate pass completed
2026-10-24 on the box. **No strategy parameter adopted.** `TRADING_MODE` stays
`FORWARD_TEST`. Current geometry remains in force for the paper book.

**Source.** Review of architecture/handoff + `docs/loss_analysis_2026-10-02.md` +
`docs/live_readiness_review_2026-10-23.md`, then a live re-pull and
`strategy_sweep.py --candidates` / `backtest.py` / `loss_analysis.py` on the
new file.

---

## 1. Why we looked

- Edge was thin (~0.11R on the spent research file). Launch gate underpowered.
- `ATR_MIN = 0.50` was dead code on the old file; bottom ATR quartile had been
  the only losing bucket.
- Research file ending 2026-09-11 was spent (inspected three times).
- LIVE protection and risk controls already shipped 2026-10-23.

## 2. Pre-registered candidates (results)

| # | Change | Fresh-data result (TRAIN Jul20–Sep7 / OOS Sep7–Oct23) | Decision |
|---|---|---|---|
| 1 | `ATR_MIN` → 2.5 / 3.0 / 3.5 | 3.0 TRAIN +$236 OOS −$162; 3.5 similar; 2.5 overfit | **Not adopted** — OOS still negative |
| 2 | `TP_ATR_MULT` → 6.0 | TRAIN +$245 OOS **−$181** (overfit) | **Rejected** |
| 3 | TP 6.0 + ATR floor 3.0 | Not re-tested as combo after #2 failed | **Rejected** |
| 4 | Session 08–20 | TRAIN +$254 OOS −$149 | **Not adopted** |

Other levers that looked better than adopted on both halves still lost money on
OOS (BE off, SL 2.5×, time-exit 72 bars). “Survives” in the sweep output means
*better than the adopted baseline*, not *profitable on OOS*.

Walk-forward on the new file: adopted **1/4** folds positive; best survivors
only **2/4**. Not adoption-grade.

## 3. Fresh full-window backtest (current config)

`data/GOLD_M5.csv` after `fetch_data.py` (start_pos=0, 20k bars):

| Metric | Value |
|---|---|
| Window | 2026-07-15 06:10 → 2026-10-23 19:20 |
| Trades | 257 |
| Net | **+$29.15** |
| PF | **1.02** |
| WR | 26.5% |
| Avg R | **0.03** |
| Max DD | $254.99 |
| Exits | 68 TP / 41 BE / 148 SL |

Compare to the spent-file reference (Jun–Sep research window): 255 / +$456 /
PF 1.32 / avg R 0.11. **The edge has degraded sharply on the recent window.**

### Loss anatomy highlights

- Sep −$27, Oct −$60 (both negative months).
- Friday −$193 (PF 0.51) — worst weekday by far.
- Hours 17–18 UTC heavily negative (−$90 / −$159).
- Net excluding top-5 winners: **−$192** (tail-driven, fragile).
- ATR quartile pattern from the old file **did not reproduce** (low-ATR is no
  longer the clear loser).
- Broker pull only returned the latest 20k M5 bars — **no pre-June history**
  available from this container for a true older OOS check.

## 4. Decision

1. **Do not change** `ATR_MIN`, `TP_ATR_MULT`, RSI levels, session window, or
   BE trigger in `config.py`.
2. Keep the paper book on the current geometry. The weak forward record is
   consistent with this backtest, not just an underpowered sample.
3. LIVE remains **no-go** (unchanged from the 2026-10-23 readiness review).
4. Next research, if any, needs a **new hypothesis** with its own pre-registration
   — not another re-tune of the same RSI-pullback / EMA200 shape on overlapping
   data.

## 5. Parallel operational items (still valid, still optional)

- Paper ↔ LIVE exit parity (already the intent of `live_position.py`).
- Demo execution drill before any real-money flip.
- Tighten `MAX_SPREAD_POINTS` only after measuring veto rate.
- Log rotation / dashboard auth before a funded account.
- `SYMBOL_TRADE_STOPS_LEVEL` preflight.

## 6. Explicit non-goals (unchanged)

- No LIVE on the shared XM account or a ~$300 balance.
- No hour/day filters fitted on this sample (Friday/17–18 look bad but n is
  thin and we already rejected that class of filter).
- No wiring `MAX_CONSECUTIVE_LOSSES` without a new measurement (old file said
  harmful; new file is mixed and not decisive).

## 7. Gate going forward

Still require, before any LIVE consideration:

1. A strategy (current or new) with cold OOS on data not used for selection,
   bootstrap mean-R CI above zero, and strong walk-forward.
2. Forward evidence with real power (~300+ paper trades on the exact LIVE exit
   engine, or mean R whose CI excludes zero).
3. Demo execution drill (20 trades).
4. Adequate account size for the equity floor to be meaningful.

---

**Closed 2026-10-24.** Parameter candidates from this plan are rejected or not
adopted. No runtime path changed.
