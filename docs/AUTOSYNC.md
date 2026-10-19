# AUTOSYNC — unattended data publish + safe auto-deploy

`tools/autosync.sh` is the scalper's port of `gold-trading-bot`'s script of the
same name. It replaces the old "run `deploy.sh` every 15 minutes" cron with:

1. **publish** the durable paper state to `origin/main`;
2. **deploy** when `origin/main` advanced (a merged PR), behind a smoke gate
   with automatic rollback;
3. **verify** integrity and liveness;
4. write one **digest** to `logs/autosync.log`.

This repo's `deploy.sh` is not removed — it is the manual, deploy-only path, and
its per-service restart rules are better than gold's. `autosync.sh` keeps them.

---

## 1. What the cron line assumes

| Requirement | Why | Check |
|---|---|---|
| `/root/scalper` is a git clone of this repo | the script `cd`s there and runs git | `cd /root/scalper && git remote -v` |
| the clone is on `main` | `AUTOSYNC_BRANCH=main`: it merges `origin/main` to deploy | `git rev-parse --abbrev-ref HEAD` |
| `tools/autosync.sh` is executable | cron needs `+x` | `ls -l tools/autosync.sh` |
| git can **push** to `origin/main` unattended | data commits are pushed every run | `git push --dry-run origin main` |
| cron user is **root** | `systemctl stop/start` the units | `crontab -l` (root) |
| the interpreter has `pandas`/`numpy`/`rpyc` | the smoke gate imports the engine | `mt5env/bin/python tools/smoke_test.py` |
| no uncommitted **code** edits on the box | the script refuses to deploy over them | `git status --short` |
| exactly one trigger (timer **or** cron) | two schedulers double-deploy | `./tools/autosync.sh --status` |

The interpreter is auto-detected: `mt5env/bin/python` if it exists, else
`python3`. Override with `AUTOSYNC_PYTHON`. A bare `python3` without pandas
would fail the smoke gate for the wrong reason and roll back every deploy, so
the `mt5env/` default matters.

### The trigger: a systemd timer, or cron — exactly one

`services/scalper-autosync.{timer,service}` are the installed trigger. The timer
fires every 15 minutes and starts the oneshot service; install it with
`systemctl enable --now scalper-autosync.timer`. Never `enable` the **service**
as well — that is a second, boot-time trigger — and never add a cron line beside
the timer.

Cron is the fallback when systemd is not in use:

```cron
*/15 * * * * cd /root/scalper && ./tools/autosync.sh >> /root/scalper/logs/autosync.cron.log 2>&1
```

Remove the old `*/15 … deploy.sh` line. Both scripts take the same
`logs/deploy.lock`, so they cannot corrupt each other, but whichever loses the
race logs a skip every tick — noise, not a bug. Two *different* schedulers are
still wrong: `./tools/autosync.sh --status` prints `TWO TRIGGERS` when a timer
and a cron line are both present.

`.env` is **not** read by this script (there is no Telegram digest yet); it is
never committed.

---

## 2. The branch rule

**Data flows up `main`; code only comes down `main`.** Every run:

1. `git add`s the six durable files, commits them as `data collection N`
   (numbering continues from the last such commit), and pushes;
2. `git fetch origin main`; if `origin/main` advanced and is not an ancestor,
   it stops the engines whose runtime code changed, merges
   (data-file conflicts = **server wins**, everything else = **remote wins**),
   runs the smoke gate, rolls back on failure, restarts the units that were
   active, and checks the status file is fresh;
3. runs `tools/check_data.py`, a `live_status.json` freshness backstop, and a
   `STATUS.md` age advisory;
4. writes one digest.

A commit on any other branch (`arena/*`, an open PR) never reaches the bot.
**Merging to `main` is the deploy trigger; the next cron slot is the deploy
time.**

### What is published, and what is not

| Published (`data collection N`) | Left on the box |
|---|---|
| `logs/ledger.jsonl` | `logs/trades.jsonl` (the raw event log) |
| `logs/daily_stats.json` | `logs/live_status.json` |
| `logs/paper_account.json` | `logs/connection_status.json` |
| `btc/logs/{ledger.jsonl,daily_stats.json,paper_account.json}` | `logs/system.jsonl`, logs, locks, `KILL_SWITCH`, `quarantine/` |

The published files move only when a trade does (~5–30 commits/day). The
unpublished ones change every 15 seconds and would turn this into 96 commits a
day for no analytical value. `.gitignore` enforces the split; `logs/*` (not
`logs/`) so the negations work.

### `ledger.jsonl` is not `trades.jsonl`

`run.py` writes a `SIGNAL` row on **every loop iteration** (~4/min per book,
24/7) plus `SKIP` rows, so `trades.jsonl` reached 187,406 rows (~20–30 MB) by
2026-10-19 and grows ~11,500 rows / ~1.7 MB a day. Publishing that is what made
`data collection 1` enormous.

`tools/ledger_export.py` distils the lifecycle events into `ledger.jsonl`
(a few hundred bytes a day, clean diffs) and autosync publishes that. The raw
log stays on the box as telemetry. `AUTOSYNC_PUBLISH_EVENT_LOG=1` restores the
old behaviour.

The first run already committed the raw log once. See
[`autosync_first_run_2026-10-19.md`](autosync_first_run_2026-10-19.md) §"One-time
cleanup" for the supervised `git rm --cached` procedure that stops it being
tracked. Until that is done, an upstream commit that deletes the file will be
**refused** by autosync (correctly) rather than merged.

---

## 3. The deploy time is the era boundary

Every experiment is judged on "trades after the change went live", so the
cutover must be when the **engine actually started running the new code** — not
the plan, and not the PR merge.

Gold's worked example (2026-10-06): the plan said 21:00, PR #28 merged 00:31,
the code went live at **03:00:04** via autosync, and the first trade on the new
geometry was 03:33. Four trades in that gap ran the old rule; counting them as
the new era made a working change look like a failure.

For this repo, date a cutover from:

```bash
git log --grep 'autosync: merge upstream' --format='%H %cI' -1
```

then confirm it from `logs/trades.jsonl` (the first `SIM_ENTRY` with a `time`
after that stamp). A `dashboard.py`-only change moves no trading behaviour and
is not a cutover.

---

## 4. The digest

One block per run in `logs/autosync.log` (and on stdout, if cron redirects it):

```
──────── autosync digest 2026-10-20 14:15 UTC ────────
  data:      committed 2 new trade row(s) -> 'data collection 7' (push: ok)
  deploy:    deployed 4f2c1ab (code files: 3, smoke: ok); restarted: scalper-bot
  integrity: 0 fail, 1 warn
  freshness: gold: ok (0 min since last write) | btc: ok (2 min since last write)
  docs:      13 day(s) since STATUS.md was verified
  books:     gold $249.7 | 4W/17L/0T | position: flat
🚨 …
```

| Line | Meaning | Action |
|---|---|---|
| `data: no changes` | no trade moved since the last run | none |
| `data: committed N new trade event(s)` | a trade opened/closed and was published | none |
| `deploy: none` | `origin/main` did not move | none |
| `deploy: deployed <sha>` | merged, smoke passed | **note the time** (§3) |
| `deploy: SKIPPED (AUTO_DEPLOY=0)` | data-only mode | expected if you set it |
| `deploy: SKIPPED - local code edits detected` | someone hand-edited code on the box | `git status`, commit or `git checkout -- <file>` |
| `deploy: ROLLED BACK (smoke=FAIL)` + 🚨 | the smoke gate failed; code was reset to the pre-merge SHA, live data restored | read `logs/smoke.log`, fix, re-merge |
| `deploy: ROLLED BACK` with `merge produced no MERGE_HEAD` in the log | `git merge` aborted before it started (a dirty tracked file the merge wanted to touch). Before 2026-10-20 this was **silently reported as a deploy** and the upstream change was lost | resolve the dirty path by hand, then re-run |
| `push: FAILED` + ⚠️ | data is safe in a local commit and retried next run | fix git credentials |
| `integrity: … fail` + 🚨 | `check_data.py` found a broken ledger | `python3 tools/check_data.py`, then `tools/repair_phantom_ledger.py` |
| `freshness: gold: STALE (N min…)` + 🛑 | the unit is up but has not written `live_status.json` for 30+ min — the 2026-09-29 "alive but starving" failure | `journalctl -u scalper-bot -n 50` |
| `docs: N day(s) since STATUS.md was verified` | advisory only; docs drift | update `STATUS.md` at the next session |

### `--status`

`./tools/autosync.sh --status` is the read-only answer to "is the 15-minute
schedule actually firing?". It prints the trigger (timer/cron), the age of the
last digest — `OK (last run N min ago)` or `STALE (last run N min ago)` — the
last digest lines, the repo and unit state, then `result: OK` or
`result: ATTENTION NEEDED`. Exit 0 = OK, 1 = attention.

It never takes the lock, never writes, never fetches and never restarts a unit,
so it is safe to run while a deploy is in progress. A completed run older than
45 minutes is `STALE` (`AUTOSYNC_STALE_MINUTES` overrides), and a rollback or a
failed push in the last digest is attention too.

`NOTIFY=quiet` suppresses a digest only when nothing at all changed (no data,
no deploy, push ok, no 🚨/⚠️/🛑). During market hours a closed trade usually
makes that false, so `always` is the honest default here.

---

## 5. Environment variables

| Var | Default | Effect |
|---|---|---|
| `AUTOSYNC_REPO_DIR` | script's parent | repo location |
| `AUTOSYNC_REMOTE` / `AUTOSYNC_BRANCH` | `origin` / `main` | what to sync against |
| `AUTOSYNC_PUBLISH_DATA` | `1` | `0` = never commit/push data (deploy-only, like `deploy.sh`) |
| `AUTOSYNC_PUBLISH_EVENT_LOG` | `0` | `1` = also publish the raw `trades.jsonl` (grows ~1.7 MB/day; see above) |
| `AUTO_DEPLOY` | `1` | `0` = publish data only, never merge or restart |
| `SMOKE_GATE` | `1` | `0` = deploy without the smoke test (**not advised**) |
| `AUTOSYNC_PYTHON` | `mt5env/bin/python`, else `python3` | interpreter for the checks |
| `AUTOSYNC_SETTLE_SECONDS` | `20` | wait after a restart before judging liveness |
| `NOTIFY` | `always` | `quiet` = skip the digest when nothing changed |
| `AUTOSYNC_LOCK_FILE` | `logs/autosync.lock` | the `flock` guard; overlapping runs exit 0 |
| `AUTOSYNC_STALE_MINUTES` | `45` | `--status` reports `STALE` after this many minutes without a completed run |

---

## 6. What a deploy does to a running trade

Safe. `paper_account.json` carries the open position across a restart (written
atomically), and `run.py` restores it on start. The engine is stopped only when
a runtime path changed for **that** unit, and only while it was active.

The smoke gate runs **before** the restart, so a broken commit is rolled back
before the engine ever loads it. That makes `tools/smoke_test.py` a deploy gate,
not just a dev tool — and it means every scenario in the suites it runs must
stay **hermetic** (temp dirs, no wall clock, no live CSVs). A test that goes red
because the paper book had a bad day would roll back a good deploy.

The gate runs on **any** `*.py` change. Docs-only, research-only and tools-only
changes merge and deploy without it.

---

## 7. Testing the script itself

```bash
bash tests/test_autosync.sh          # 56 checks, ~5 s, no network
python3 tools/smoke_test.py          # includes the above
```

The test builds a real bare origin, a "seed" clone that plays the PR author and
a "server" clone that plays the box, with a fake `systemctl` and a fake
interpreter for the smoke gate. It covers: quiet run, data commit + push (the
ledger, never the event log), docs-only merge, engine-only change,
dashboard-relevant change, smoke failure rollback (including "data written
during the failed merge survives"), an upstream that deletes the tracked event
log (must roll back, not fake a deploy), the hand-edit refusal, the stopped-unit
rule and the lock.

If the sandbox running the test blocks `git push` (a merged/closed PR does), the
harness replaces push with the equivalent fetch into the bare origin. With
`FAKE_GIT_PUSH_TARGET` unset — a normal box — the real push path is used.

---

## 8. Differences from gold's autosync

| Gold | Here | Why |
|---|---|---|
| `DATA_FILES` = CSV ledger + `status.json` + `xm_data/` | JSONL ledger + state + daily stats | different book format |
| engine auto-detected by scanning units for `engine.py` | fixed unit names, same as `deploy.sh` | this repo has four known units, two of them the same engine |
| restarts the engine whenever core changed | restarts only units that were **active** | `systemctl restart` on a stopped unit would start it |
| one `CORE_CHANGED` flag | per-unit runtime-path allowlists | a BTC-only or dashboard-only commit must not touch the gold book |
| Telegram digest | log digest | no bot token on this box; the digest format is one function away from `curl` |
| `handoff_check.py` machine-checked doc | `STATUS.md` age advisory | no snapshot block to checksum yet |
| `xm_quote_report.py` liveness | `live_status.json` freshness | no separate quote logger here |
| 3-hourly cron | 15-minute cron | deploy latency matters more than commit count; only durable state is published |

## Deploy hardening (2026-10-19)

`--status` is read-only (exit 0 healthy / 1 attention). It counts lock skips
since the last `done`/digest and flags even one immediately; a recent digest
cannot hide consecutive skipped ticks. A quiet completion counts as a run;
a log containing only skips does not. Probe locks without `fuser` using
`flock -n logs/autosync.lock -c true` and the equivalent for `logs/deploy.lock`.
Do not delete a lock file to clear a holder.

Autosync fetch/push use GNU `timeout`: 120 seconds by default, TERM then KILL
after 10 seconds; override with positive `AUTOSYNC_GIT_TIMEOUT_SECONDS`.
Fetch failure prevents merging; push failure retains local commits for retry.
This deadline covers the git process group, including SSH children.

Changed `.sh` files now trigger the smoke gate just like `.py` files, with
`bash -n` on existing changed shell files first. Docs-only changes remain
ungated. Tools-only changes still do not stop/restart books. `SMOKE_GATE=0`
remains an explicit opt-out, not recommended. Autosync's body is one parsed
function: replacing its on-disk file during merge/rollback cannot change the
instructions of the current invocation. The **first upgrade from the old
script** must use an external snapshot of the new script with
`AUTOSYNC_REPO_DIR=/root/scalper`; see the PR rollout commands. Do not allow
an old running invocation to merge its own replacement.
