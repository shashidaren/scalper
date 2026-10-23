# HANDOFF — Gold Scalper

Current truth is [`STATUS.md`](STATUS.md). Architecture is [`ARCHITECTURE.md`](ARCHITECTURE.md). Commands are [`RUNBOOK.md`](RUNBOOK.md).

The previous append-only handoff (1,335 lines, stacked banners through 2026-10-07) is archived at [`docs/archive/HANDOFF_2026-10-07.md`](docs/archive/HANDOFF_2026-10-07.md). Read that for the image patches, the full TODO history, and the session-by-session changelog. Do not copy a superseded banner back into `STATUS.md`.

Session rule: edit `STATUS.md` in place. Add one changelog row. Do not start a new status essay here.

## Where things live (2026-10-23)

Read these three before touching the book. The first is a verdict, the other two
are implementations.

| | |
|---|---|
| [`docs/live_readiness_review_2026-10-23.md`](docs/live_readiness_review_2026-10-23.md) | The live-readiness verdict: **no-go**, and why 100 paper trades cannot answer the question. Also the gate I'd replace the launch criteria with. |
| [`docs/live_protection_2026-10-23.md`](docs/live_protection_2026-10-23.md) | `live_position.py` — post-fill stop verification and the BE ratchet, LIVE only. |
| [`docs/risk_controls_2026-10-23.md`](docs/risk_controls_2026-10-23.md) | `risk_guard.py` — Friday weekend flat (on), hold cap (off), latched equity floor. |

Two rules that were implicit and are now code:

- **LIVE never runs an exit the paper book did not.** That mismatch is what
  `live_position.py` exists to fix; if you add an exit rule to `paper.py`, add
  the LIVE half too, in the same commit.
- **A rule that changes with the wall clock makes the deploy gate flaky.** Any
  suite not about the clock must set `WEEKEND_FLAT_ENABLED = False`; clock cases
  inject `now`. `tools/smoke_test.py` runs on every autosync tick.

`TRADING_MODE` is still `FORWARD_TEST`. Nothing in the 2026-10-23 work changes a
strategy parameter: the backtest is still 255 trades / +$456.58 / PF 1.32, and
`research/parity_test.py` still passes.

Before any live decision: the demo execution drill in the review (§6.3) has not
been run — `live_position.py` has only ever been tested against a fake terminal.
