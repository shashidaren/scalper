# AGENTS.md — how to work in this repo

Read this before touching anything. It is the contract that makes a two-word
instruction ("follow execution plan gold") unambiguous.

## Trigger phrases

| The user says | Do this |
|---|---|
| **"follow execution plan gold"** | `python3 tools/execution_plan.py gold --status` and execute **only** the phase it prints. |
| **"follow execution plan bitcoin"** (or `btc`) | `python3 tools/execution_plan.py bitcoin --status`, same rule. |
| "where are we on gold/bitcoin?" | `python3 tools/execution_plan.py <book> --list` and summarise. Do not start work. |
| "update the plan" | Edit the phase entry in `plans/<book>.json`, then `python3 tools/execution_plan.py --validate`. |

The plans live in `plans/gold.json` and `plans/btc.json`. They are the
machine-readable form of the `/readiness` tab, `STATUS.md` and the dated docs in
`docs/`. The prose wins on conflict — if a plan and `STATUS.md` disagree,
`STATUS.md` holds the decisions and the plan is the checklist: fix the plan.

## What "follow the plan" means

1. Run the command above. It prints the **next** phase, its steps, its **exit
   gate**, its commands, and that book's hard rules.
2. Work **only** on that phase. If the work belongs to another phase, say so and
   stop — do not start the next phase early, and never skip a blocked one.
3. Stop when the exit gate is met or is proven unreachable. Then record the
   outcome in one `STATUS.md` changelog row and in the phase's `status` field
   (`done` / `blocked` / `active`), and move `"next"` only if the plan says so.
4. If a step cannot be executed from a checkout (no MT5 bridge, no box), say
   which command the user must run on `scalping` and hand back the exact line.
   `RUNBOOK.md` has them.

## Hard rules, both books

These are in the plans too, because they are the rules that get broken by
accident while "just fixing" something.

- **Never** change `TRADING_MODE` (both books are `FORWARD_TEST`), a service
  unit, or `MAX_SPREAD_POINTS` without an explicit user decision in the session.
- **Never** edit strategy parameters to make a result look better. Gold's
  `ATR_MIN` / `TP_ATR_MULT` / session / RSI and BTC's placeholders are governed
  by pre-registered protocols; a change needs a new pre-registration and cold
  OOS, not an edit.
- **Never** re-tune on inspected data. A fresh download of history that has
  already been looked at is not cold OOS.
- **Never** weaken the deploy gate: no editing `tests/`, no re-pinning
  `btc/golden.py`, no skipping `tools/smoke_test.py` to turn a red check green.
- **Never** delete or rewrite `data/*.csv`, `logs/*.jsonl`, `btc/logs/*` to
  "clean up". `tools/repair_phantom_ledger.py` (dry run first) exists for the
  one legitimate case.
- **Never** promote a book, or claim readiness, on the strength of this file, the
  plan, or the dashboard. Only a signed decision recorded in `STATUS.md` does
  that, and nothing here can auto-approve.

## Definition of done for any change

- `python3 tools/smoke_test.py` passes (21 suites, 0 failures) and
  `python3 tools/execution_plan.py --validate` passes.
- Follow the existing conventions: read-only views never write engine state;
  anything exported to git is published through `tools/autosync.sh`, not by hand.
- Documents cite each other by path, and any number quoted in prose is
  reproducible from a file in the repo (state the file and timestamp).

## Where the truth lives

| | |
|---|---|
| decisions, current state | `STATUS.md` (edit in place, one changelog row) |
| layout | `ARCHITECTURE.md` |
| commands for the box | `RUNBOOK.md` |
| the plan as prose | `/readiness` on the dashboards (`:8088` gold, `:8089` bitcoin) |
| the plan as data | `plans/gold.json`, `plans/btc.json` |
| research write-ups | `docs/*.md` |
