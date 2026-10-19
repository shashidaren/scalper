# Autosync — first run on the box (2026-10-19)

What happened when `tools/autosync.sh` went live, what the two alarms meant, and
what changed as a result. Box clock is UTC; the cron runs every 15 minutes.

## Timeline

| UTC | Event |
|---|---|
| 16:35:09 | cron tried `./tools/autosync.sh` before the file existed → `/bin/sh: ./tools/autosync.sh: not found`. Harmless: the box was still on `e37e4a7`. |
| 16:35:16 | manual `./deploy.sh` fast-forwarded `e37e4a7..fdedfe4`, restarted `scalper-bot`, `scalper-btc-bot`, `scalper-btc-dashboard`. |
| 16:35:2x | `mt5env/bin/python tools/smoke_test.py` → **SMOKE TEST PASSED** (11 checks). |
| 16:36:24 | first real autosync run: `data collection 1`, push ok, `deploy: none`, `integrity: 2 fail`. |
| 16:37:09 | second run (manual): `data collection 2`, same 2 fails. |

## Alarm 1 — `integrity: 2 fail` is a false positive

Both books were reset to $300 on 2026-10-04 (`paper.py --reset`). A reset zeroes
the balance and the counters but deliberately does not rewrite `trades.jsonl`,
so the file holds a **permanent, legitimate** balance discontinuity — one per
book, i.e. exactly the two failures.

`tools/check_data.py` was chaining the balance from the first row that ever
existed. It now chains only the **current book**, sized by the state file's own
`closed` counter, and additionally proves that `wins`/`losses`/`time_exits`
describe the same set of trades. A break inside the current book, a state
balance that disagrees with the last exit, and a `closed` count larger than the
log are all still hard failures. See `tests/test_check_data.py`.

Nothing was wrong with either book.

## Alarm 2 — `committed 187406 new trade row(s)` was real

`logs/trades.jsonl` is not a trade ledger. `run.py` writes a `SIGNAL` row every
loop iteration (~4/min per book, 24/7) plus `SKIP` rows, so on the box it held
~187k rows — roughly 20-30 MB — and grows by ~11,500 rows / ~1.7 MB a day.

Publishing that every 15 minutes would have added ~650 MB a year to the repo
(GitHub's hard limit is 100 MB per file) and made every diff unreadable.

**Changed:** the published set is now the state files plus a compact
`logs/ledger.jsonl` built by `tools/ledger_export.py` — trade lifecycle events
only (`SIM_ENTRY`, `SIM_EXIT`, `ENTRY`, `ENTRY_FAILED`, `ENTRY_SKIPPED`, …).
Signal sampling stays on the box. `AUTOSYNC_PUBLISH_EVENT_LOG=1` restores the
old behaviour if it is ever wanted.

`data collection 1` already put the 187k-row file in history. That history
cannot be removed without rewriting `main`, which is not worth the risk; the
cost is bounded (it is one file, once).

### One-time cleanup (optional, supervised)

The tracked event log should stop being tracked. It is tracked today, so a
later commit that deletes it will collide with the dirty working copy — that is
why autosync now **refuses** such a merge instead of faking it (Alarm 3). Do it
by hand, once, on the box:

```bash
cd /root/scalper
mkdir -p /root/scalper-eventlog          # outside the repo
cp logs/trades.jsonl     /root/scalper-eventlog/gold-2026-10-19.jsonl
cp btc/logs/trades.jsonl /root/scalper-eventlog/btc-2026-10-19.jsonl
git rm --cached logs/trades.jsonl btc/logs/trades.jsonl
git commit -m "Stop publishing the raw event log; publish ledger.jsonl instead"
git push origin main
```

`git rm --cached` keeps the files on disk (no data loss); the next commit
removes them from the tree. The bot recreates `trades.jsonl` on its next write —
empty, which is fine: `ledger.jsonl` already carries every trade ever closed,
and `paper_account.json` carries the balance and counters.

## Alarm 3 — found while testing the cleanup: a merge that never happened

Reproducing the cleanup in `tests/test_autosync.sh` exposed a real bug: when
`git merge` aborted **before** writing `.git/MERGE_HEAD` (exactly the case above),
the conflict resolver found no unmerged paths, committed whatever happened to be
staged, and reported `deployed`. The upstream change was silently dropped.

`autosync.sh` now requires `.git/MERGE_HEAD` before committing a resolved merge;
anything else is a failed merge and rolls back. The rollback path also snapshots
and restores the tracked event log, because `git reset --hard` was reverting the
rows the engine had appended during the attempt.

## Still open

- `systemctl restart scalper-dashboard` once: the 10-19 pull changed `config.py`,
  which the dashboard imports, and it was not in `DEPLOY_SERVICES`.
- The cron entry should be `*/15 * * * *` with an absolute path or a `cd` first
  (`docs/AUTOSYNC.md` §1). If it is `* * * * *`, this box will generate 1,440
  runs and up to 1,440 commits a day.
- `STATUS.md` numbers were a week stale; they now record the 2026-10-19 snapshot
  from the box.
