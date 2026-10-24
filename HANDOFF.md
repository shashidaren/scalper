# HANDOFF — Gold Scalper

Current truth is [`STATUS.md`](STATUS.md). Architecture is [`ARCHITECTURE.md`](ARCHITECTURE.md). Commands are [`RUNBOOK.md`](RUNBOOK.md).

The previous append-only handoff (1,335 lines, stacked banners through 2026-10-07) is archived at [`docs/archive/HANDOFF_2026-10-07.md`](docs/archive/HANDOFF_2026-10-07.md). Read that for the image patches, the full TODO history, and the session-by-session changelog. Do not copy a superseded banner back into `STATUS.md`.

Session rule: edit `STATUS.md` in place. Add one changelog row. Do not start a new status essay here.

## Where things live (2026-10-24)

Read these before touching the book.

| | |
|---|---|
| [`docs/effectiveness_plan_2026-10-24.md`](docs/effectiveness_plan_2026-10-24.md) | **Current plan.** Pre-registered ATR-floor + TP-6.0 candidates. Data refresh required before any config change. |
| [`docs/live_readiness_review_2026-10-23.md`](docs/live_readiness_review_2026-10-23.md) | Live-readiness verdict: **no-go**. Why 100 paper trades cannot answer the question. Replacement gate. |
| [`docs/live_protection_2026-10-23.md`](docs/live_protection_2026-10-23.md) | `live_position.py` — post-fill stop verification and the BE ratchet, LIVE only. |
| [`docs/risk_controls_2026-10-23.md`](docs/risk_controls_2026-10-23.md) | `risk_guard.py` — Friday weekend flat (on), hold cap (off), latched equity floor. |

Two rules that were implicit and are now code:

- **LIVE never runs an exit the paper book did not.** That mismatch is what
  `live_position.py` exists to fix; if you add an exit rule to `paper.py`, add
  the LIVE half too, in the same commit.
- **A rule that changes with the wall clock makes the deploy gate flaky.** Any
  suite not about the clock must set `WEEKEND_FLAT_ENABLED = False`; clock cases
  inject `now`. `tools/smoke_test.py` runs on every autosync tick.

`TRADING_MODE` is still `FORWARD_TEST`. Strategy parameters are unchanged:
backtest still 255 trades / +$456.58 / PF 1.32, and `research/parity_test.py`
still passes.

**Next action (do this first):** refresh `GOLD_M5.csv` (pre-June + post-2026-09-11)
and re-run the pre-registered candidates in
`docs/effectiveness_plan_2026-10-24.md`. Do **not** edit `ATR_MIN` or
`TP_ATR_MULT` until that cold-OOS pass completes.

Before any live decision: the demo execution drill in the readiness review
(§6.3) has not been run — `live_position.py` has only ever been tested against
a fake terminal.
