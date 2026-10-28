# Execution plans: "follow execution plan gold" / "… bitcoin"

Status: **tooling + documentation. No strategy parameter, no `TRADING_MODE`, no
service unit and no engine path changed.** Both books stay `FORWARD_TEST` and
LIVE stays **no-go**.

## The problem this solves

The roadmap already existed three times over — as prose in `STATUS.md`, as dated
docs in `docs/`, and as the `/readiness` tab. A new session still had to
reconstruct "where are we and what may I touch" from all three, and a wrong
reconstruction is expensive in a repo where a careless edit changes a live
book's behaviour.

So the roadmap is now also **data**, in two files an executor can be pointed at:

```
plans/gold.json    5 phases
plans/btc.json     7 phases
```

and one command resolves it:

```bash
python3 tools/execution_plan.py gold                # brief for the NEXT phase
python3 tools/execution_plan.py bitcoin --status    # brief + published paper book
python3 tools/execution_plan.py bitcoin --list      # every phase and its status
python3 tools/execution_plan.py bitcoin --json      # resolved plan for tooling
python3 tools/execution_plan.py --validate          # both; exit 1 if a plan rotted
```

`gold`, `xau`, `btc`, `bitcoin` and `btcusd` all resolve; the alias exists so the
phrase the user actually says works without a lookup.

## What a phase carries

Every phase has the same shape, so an executor (or a reviewer) always gets the
same six answers:

| field | meaning |
|---|---|
| `status` | `active` / `parallel` / `blocked` / `waiting` / `done` |
| `steps` | the work, in order, written as instructions rather than themes |
| `exit_gate` | the evidence that ends the phase — the only thing that ends it |
| `blocked_by` | phase ids that must be `done` first |
| `commands` | real commands from this repo, not pseudocode |
| `sources` / `evidence` | the docs it derives from, and the artefact it produces |

Plus a per-book `never` list: no `TRADING_MODE` change, no strategy-parameter
edits, no re-pinning `btc/golden.py` to clear a red check, no re-tuning on
inspected bars, no LIVE on the shared XM account, and (BTC) no second
`WEEKEND_FLAT_ENABLED` assignment. Those are the rules that get broken by
accident while "just fixing" something, so they print with every brief.

The plans are the same content as the `/readiness` tabs, which now link to them.
`AGENTS.md` is the entry contract: trigger phrases, what "follow the plan"
means, the hard rules, and the definition of done.

## Fail closed, on purpose

`--validate` (also run inside `tools/smoke_test.py`) rejects:

- duplicate phase ids or `order` values;
- a `blocked_by` naming a phase that does not exist, or naming itself;
- a phase marked `done` whose blocker is not `done`;
- `next` pointing at a phase that is already `done`, or at one that is still
  blocked — the plan must name the *unblocking* work, so this cannot quietly
  become "work on the blocked thing";
- an unknown `status`, an unsupported schema, an empty `never` list, a missing
  required key;
- a `sources` path that no longer exists on disk (the cheapest way to notice a
  plan has rotted against the docs).

A malformed plan exits 1 with the reason, and the smoke gate fails, so a plan
cannot silently drift out of sync with the repo.

## Safety properties

- **Read-only.** The tool reads `paper_account.json` and exits; `tests/
  test_execution_plan.py` asserts byte-identical state and no new files after
  running every mode.
- **No config import.** Gold and BTC configs cannot coexist in one process
  (`btc/_instance.py`), so the tool is stdlib-only and reads the published JSON
  directly. `--root` makes it testable against a temp copy of the repo.
- **No restart.** `plans/*` is in the inert list of all four units in `deploy.sh`
  and `tools/autosync.sh`: editing the roadmap restarts neither book nor either
  dashboard. `tests/test_deploy_services.sh` pins that (`plans_only_commit_skips_all_four`).
- **No authority.** Nothing here can promote a book. The `verdict` field is
  `NO-GO` for both and the tool has no write path at all.

## What each plan says today

| | gold | bitcoin |
|---|---|---|
| verdict | NO-GO | NO-GO |
| next | `breakout-b-protocol` — freeze the pre-registration (grid 162 vs ≤54 cap, exact exit rule, unseen OOS hashes) | `btc-hypothesis` — pre-register a new shape on untouched bars |
| parallel work | 20-trade demo execution drill | broker recon (spec, swap, server offset) |
| blocked | BREAKOUT-B test → forward cohort → go/no-go | hypothesis test → parameters → drill → account → cohort |

## Verification

- `tests/test_execution_plan.py`: **23 checks** (committed plans valid; 10
  separate malformed-plan rejections; aliases; read-only; exit codes; JSON).
- `tools/smoke_test.py`: the suite is part of the deploy gate;
  `tests/test_deploy_services.sh` now runs **54/54** with the `plans/` case.
- `python3 tools/execution_plan.py --validate` → both plans OK.
