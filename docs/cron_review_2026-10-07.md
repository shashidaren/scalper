# Cron review — 2026-10-07 (`scalping`)

**Scope.** The three crontab lines as recorded in `btc/HANDOFF.md` (2026-10-03
status block) and `HANDOFF.md` §2/§3. This is a **repo-side** review plus the
code hardening it justifies; **the server crontab itself was not touched** from
this container (no `ssh scalping`). Every claim about the server is a claim
about the *recorded* `crontab -l`, not a fresh observation.

```
*/15 * * * * DEPLOY_BRANCH=main /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1
15 1 * * * /root/scalper/scripts/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1
0 1 * * 1-5 /root/scalper/scripts/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1
```

## 1. Verdict per line

| Line | Verdict | Why |
|---|---|---|
| `*/15 … deploy.sh` | **Keep the schedule**, one safety prefix; `deploy.sh` itself hardened | The branch (`main`) and cadence are right. Two real defects fixed in `deploy.sh`: it restarted the gold book on *any* commit, and overlapping runs were possible. |
| `15 1 * * *` paper status | **Keep** (this is the superset line) | Daily cover, 01:15 UTC sits after the 21:00–22:00 UTC gold rollover and before the 07:00 session — a defensible reporting hour. Collided with the deploy cron's 01:15 tick; move to `7 1`. |
| `0 1 * * 1-5` paper status | **Remove** | On weekdays the same script runs at 01:00 **and** 01:15 — the same report twice, 15 minutes apart. Already an open TODO in `HANDOFF.md` §5 ("double-run on weekdays may be intentional or a leftover — decide and clean up"). If a weekday-only pre-open report is genuinely wanted, make the daily line `15 1 * * 0,6` instead; never both. |

**Do not change:** `DEPLOY_BRANCH=main` (it is the production target), the
gold-only default (`DEPLOY_SERVICES` unset — BTC's Phase 1 has not passed and no
BTC unit is authorized; `services/scalper-btc-bot.service` would be *started* by
`systemctl restart`, which is exactly the PR #17 lesson), and the `*/15` cadence.

## 2. Findings

### F1 — Weekday double-run (line 2 + line 3)
The script is invoked twice 15 minutes apart on Mon–Fri, and the two logs
interleave in one `paper_status.cron.log`. If the script is read-only reporting
the cost is noise; if it writes any snapshot/sends any message, it double-counts.
Decision needed; recommendation in §4.

### F2 — The status script lives *inside* the directory the cron pulls into
`/root/scalper/scripts/paper_status_daily.sh` is explicitly **server-only, not
in git** (`HANDOFF.md` §2) — but it sits inside `/root/scalper`, where
`deploy.sh` runs `git checkout main` + `git pull --ff-only` every 15 minutes.
Two failure modes, both silent from cron's side:

1. If any future commit ever adds `scripts/paper_status_daily.sh` (or a
   `scripts/` directory), `git pull` aborts with *"untracked working tree files
   would be overwritten by merge"* and **every subsequent deploy stops
   updating** — the bot keeps running old code, and the only record is one line
   in `logs/deploy.cron.log`. Nothing retries.
2. If someone "fixes" that by adding `scripts/` to `.gitignore`, git inverts the
   failure: ignored files are overwritten silently on checkout, so the
   server-only script (and `.env.paper_status`) would be **destroyed** by the
   next pull that adds a tracked file there.

**Fix:** keep server-only ops scripts outside the deployed tree (e.g.
`/root/ops/paper_status_daily.sh` + `/root/ops/.env.paper_status`) and point
cron there. Secrets stay safe either way — `.gitignore` covers `.env.*` at any
depth — but the collision risk does not.

### F3 — The cron redirect needs `logs/` to pre-exist
`>> /root/scalper/logs/deploy.cron.log` is opened by the shell **before**
`deploy.sh` runs, so if `logs/` were ever missing the cron command fails without
executing anything (the `mkdir -p` inside `deploy.sh` never gets a turn). The
directory exists today (the bot writes `logs/trades.jsonl`), so this is
belt-and-braces: prefix the cron command with `mkdir -p /root/scalper/logs &&`.
Related: every deploy message is written both to `logs/deploy.log` (by
`tee`) and to `logs/deploy.cron.log` (by the redirect) — harmless duplication;
`deploy.log` is the file the runbook greps and `btc/server_check.py` tails
(lines 146–151, 217), so it stays.

### F4 — Nothing reports a *failed* deploy
There is no `MAILTO`, no alert, and `deploy.sh` is `set -euo pipefail`: a dirty
tree, a diverged history or a network failure makes `git pull` abort, and from
then on every 15-minute run fails the same way with only a log line. The gold
bot keeps trading old code indefinitely. **Fixed 2026-10-07 in §3a** for the
log half of this finding: `deploy.sh` now warns about dirty tracked files
before the pull and writes a distinct `PULL FAILED: …` line (reason + the sha
still running) into `logs/deploy.log`, so the stop is visible where the runbook
looks. Still open: `MAILTO=root` (or better,
your real address) at the top of the crontab so cron mails stderr; optionally a
once-a-day liveness grep, e.g.
`0 6 * * * grep -q "$(date -u +%F)" /root/scalper/logs/deploy.log || echo "$(date -Is) deploy cron has not logged today" >> /root/scalper/logs/deploy.cron.log`.

### F5 — The restart policy (the change with the most effect on gold's evidence)
Until now **any** commit on `main` restarted `scalper-bot`, including the
BTC-only and docs-only commits that have been the majority (PR #22, PR #23, …).
Two costs:

* **Correctness.** A restart re-arms state that only lives in memory:
  `strategy._last_fired_bar_ts` (the one-shot-per-bar guard,
  `strategy.py:60-62,226-232`), the `SpreadGateMonitor` counters
  (`run.py:142`), and the stale-tick counters (`run.py`). Mid-session, a
  restart can therefore let the strategy take a *second* entry on a closed bar
  it already traded once that bar's first entry has exited. For a paper book
  whose **trade count is the §5 "100+ paper trades" LIVE gate**, that is
  evidence contamination, not cosmetics.
* **Churn.** Every deploy is also an `ExecStartPre` wait on the MT5 bridge
  (`wait_for_mt5.py --timeout 180`, `services/scalper-bot.service`), so a
  restart can block longer than the 15-minute slot if the container is down.

`deploy.sh` now restarts a service **only when a runtime input for it changed**
(allowlist; empty diff, git error and unrecognised paths all fail safe into a
restart). `btc/config.py` is deliberately *not* inert: the shared portfolio gate
reads `MAX_DAILY_LOSS`/`MAX_TRADES_PER_DAY` from it through
`portfolio.py::_btc_config()` (`portfolio.py:40-52,108-110`) — currently
short-circuited by gold's own `PORTFOLIO_MAX_*` keys (`config.py:144-150`), but
the coupling is real and cheap to respect. `DEPLOY_FORCE_RESTART=1` restores
restart-on-any-commit if ever needed.

A `flock` on `logs/deploy.lock` now makes overlapping runs impossible; the
second run logs `deploy already running … - skipped` and exits 0.

### F6 — The dashboard is never restarted by the cron (so `dashboard.py` fixes don't ship)
`deploy.sh`'s default is `scalper-bot` only and the crontab has no
`DEPLOY_SERVICES` — so `scalper-dashboard` (uvicorn, no `--reload`) has been
running whatever `dashboard.py` it imported at its last manual restart.

* `templates/*.html` changes **do** go live by themselves: Jinja2's
  `auto_reload` defaults to `True` (3.1.6) and Starlette's `Jinja2Templates`
  builds the environment without disabling it — verified in-process: render,
  edit file, render again picks up the edit.
* `dashboard.py` changes **do not**. Concretely: PR #22 added the red
  "NO ENTRY IS POSSIBLE WITH THIS CONFIGURATION" banner as `dashboard.py`
  context (`"spread_gate": live.get("spread_gate")`) plus template markup. The
  template side is live; the context side is not, and Jinja renders an undefined
  `spread_gate` as falsy. So on a dashboard that has not been restarted since
  PR #22, **the banner silently never appears**.

Check: `systemctl show scalper-dashboard -p ActiveEnterTimestamp` (compare with
the PR #22 merge, 2026-10-06) → `systemctl restart scalper-dashboard`.
Recommended: opt in with `DEPLOY_SERVICES="scalper-bot scalper-dashboard"`; with
the new filter the dashboard then restarts only when `dashboard.py`,
`config.py`, `logger.py`, `portfolio.py` or `templates/` change, and a
dashboard-only change no longer restarts the engine. If left manual, the deploy
now logs a note naming the relevant files.

### F7 — Unit-file changes are pulled but not applied
`services/*.service` in the repo is a template; nothing in `deploy.sh` copies it
to `/etc/systemd/system/` or runs `systemctl daemon-reload`. A unit edit
therefore has no effect until someone does that by hand. Confirm with
`systemctl cat scalper-bot | head -1` (if the path shown is
`/etc/systemd/system/…`, the repo copy is only a source of truth).

### F8 — Timezone and the trading session
Cron uses the system clock; the box is UTC today (`HANDOFF.md` §2). Pin it
(`CRON_TZ=UTC`, Vixie/Debian cron) so a future TZ change cannot silently move
the 01:00/01:15 reports relative to the 07:00–20:00 UTC session
(`config.py`/`strategy.py` session filter) — or the deploy cadence relative to
the day boundary. The `*/15` deploy ticks at :00/:15/:30/:45 fall inside the
session all day; with the path filter an in-session restart now happens only
when gold-runtime code actually changed (a merge inside the session still
restarts the book mid-session — see §5 "not done").

### F11 — Server-only compose tweaks belong in `docker-compose.override.yml`
Any host-specific edit to the tracked `docker-compose.yml` (ports, a shared
mount, a service tweak) will eventually be touched by an upstream commit and
from then on every `git pull --ff-only` aborts with *"Your local changes …
would be overwritten by merge"* — which is exactly the 2026-10-04 12:30 →
2026-10-07 02:28 UTC freeze (~63 h, ~250 ticks). Put server-only tweaks in
`docker-compose.override.yml` instead: Compose merges it automatically
(`docker compose` reads `docker-compose.yml` + `docker-compose.override.yml`),
it is not tracked, and the tracked file stays clean so pulls always apply.

### F9 — Log rotation (low priority)
No `logrotate` config exists for `logs/deploy.log`, `logs/deploy.cron.log`,
`logs/paper_status.cron.log`, `logs/trades.jsonl`, `logs/system.jsonl`. Volumes
are small (deploy ≈ 1 line / 15 min), so this is hygiene rather than urgency;
add a drop-in when convenient.

### F10 — Cron environment ≠ service environment
The crontab declares no `SHELL`/`PATH`, so cron uses `/usr/bin:/bin`, while the
services run with `PATH=/root/scalper/mt5env/bin:…` and the venv interpreter
(`services/*.service`). `deploy.sh` needs only `git`/`systemctl`/`flock`, which
works, but any script that shells out to `python`/`pip` will bypass the venv.
Set the PATH explicitly at the top of the crontab (see §4).

## 3. What changed in the repo (and the evidence)

`deploy.sh` (+ `tests/test_deploy_services.sh`):

* `flock -n` on `logs/deploy.lock` (overridable via `DEPLOY_LOCK_FILE`) —
  a second concurrent run logs and exits 0.
* Changed-path filter: restart unless *every* path in
  `git diff --name-only BEFORE AFTER` is inert for that service. Inert for the
  gold engine: `docs/`, `research/`, `tests/`, `*.md`, `deploy.sh`, `btc/**`
  except `btc/config.py`, and non-runtime tooling
  (`backtest.py`, `fetch_data.py`, `gold.py`, `balance.py`, `dashboard.py`,
  `templates/*`). Dashboard units: only `dashboard.py`, `config.py`,
  `logger.py`, `portfolio.py`, `templates/*` are runtime inputs. Fail-safe:
  empty or failed diff, unknown service, unknown path ⇒ restart.
  `DEPLOY_FORCE_RESTART=1` bypasses. Every decision is named in
  `logs/deploy.log` (restart lines keep the historical
  `restarted <svc> at <sha> (was <sha>) branch=<branch>` wording).
* A note line when a dashboard-relevant path changed but `scalper-dashboard` is
  not in `DEPLOY_SERVICES`.

Evidence (all local, this container; no server access):

* `tests/test_deploy_services.sh` — **18/18 PASS** (was 3; **47/47** after
  the §3a follow-up), including
  BTC-only ⇒ no restart, `btc/config.py` ⇒ restart, empty/failed diff ⇒ restart,
  `DEPLOY_FORCE_RESTART=1`, dashboard opt-in on/off, lock-held ⇒ skip, and a
  failed `systemctl restart` ⇒ logged as `RESTART FAILED for <svc>`
  (`systemctl` failing no longer aborts the loop or reads as "nothing
  installed").
* Real-git integration on a scratch clone (7 scenarios): BTC-only commit ⇒
  `restart skipped for scalper-bot (no runtime path changed)`; docs-only ⇒ same;
  `config.py` ⇒ `restarted scalper-bot at … branch=main`; no new commit ⇒
  `already up to date`; `dashboard.py` alone ⇒ no restart + dashboard note;
  concurrent run ⇒ `deploy already running … - skipped`.
* Gold regressions after the change: `backtest.py` **255 / +$456.58 / PF 1.32 /
  max DD $108.65 / WR 28.2% / 72 TP · 43 BE · 140 SL / avgR 0.11** (identical),
  `research/parity_test.py` **PASS** (460 signals, 0 mismatches),
  `tests/test_spread_gate.py` **21/21**, `research/paper_exit_test.py` PASS.
  No gold-runtime file was edited, so these are unchanged-baseline checks.

### 3a. Follow-up (2026-10-07, after PR #24): a failed pull is no longer silent

**What the server showed.** From 2026-10-04 12:30 to 2026-10-07 02:28 UTC a
dirty tracked `docker-compose.yml` made `git pull --ff-only` abort on **every**
15-minute tick (~63 h, ~250 runs) and the gold bot kept running 2026-10-04-era
(`a122e7a`) code: PRs #22/#23/#24 were on disk but not in memory
(`logs/live_status.json` had no `spread_gate` field). F4 above named the
mechanism; the fix below makes it visible in the file the runbook reads.

**`deploy.sh` (the change):**

* A pre-flight `git status --porcelain` (after the lock, guarded so a failing
  `git status` cannot abort the run) logs `DIRTY TREE: modified tracked
  file(s) …` plus the exact files when any **tracked** non-clean path exists.
  Untracked files (`logs/`, `data/*.csv`, server-only scripts) are ignored.
* `git fetch`, `git checkout` and `git pull --ff-only` are now each captured and
  wrapped: on failure `pull_failed()` writes one
  `PULL FAILED: <what failed> - code NOT updated (still <sha>); reason: <git's
  first error/fatal line>` line **plus** every captured git line tagged
  `PULL FAILED detail:` into `logs/deploy.log` (and stdout → the cron log), then
  exits 1. Nothing is restarted on a failed pull, and no update is left
  half-applied. Previously `set -e` exited before any log write, so the only
  trace was the cron redirect.
* Successful fetch/checkout/pull output is still echoed to stdout, so the cron
  log carries what it did before.

**Evidence (local, this container — the sandbox has no `ssh scalping`, so the
server itself was not touched):**

* `tests/test_deploy_services.sh` — **47/47 PASS** (was 18; the suite prints its
  own `ALL PASS: N/N` summary; 39/39 before the BTC-unit allowlists below).
  New cases: dirty tracked file ⇒ `DIRTY TREE`
  logged, pull still attempted, normal restart decision kept (exit 0);
  untracked-only dirt ⇒ no warning; pull failure ⇒ `PULL FAILED` + git's
  `would be overwritten` text + `code NOT updated (still …)` + **no** systemctl
  restart + exit 1; fetch failure ⇒ `PULL FAILED` + exit 1; failing
  `git status` ⇒ warning only, deploy still restarts (exit 0).
* BTC units in `DEPLOY_SERVICES` (the user's 2026-10-07 decision): `btc/**`
  runtime path ⇒ restarts **only** `scalper-btc-bot`; `btc/dashboard.py` ⇒ only
  `scalper-btc-dashboard`; `backtest.py`/`btc/dashboard.py` are inert for the
  BTC bot; `config.py` (gold) stays restart-worthy for it (fail safe); a
  docs-only commit ⇒ no restart for any of the four; `config.py` ⇒ all four.
* Real-git integration on scratch clones (`/tmp/deploy_int*`, disposable):
  (a) dirty `docker-compose.yml` + an incoming commit that also touches it —
  `PULL FAILED: git pull --ff-only origin main failed - code NOT updated (still
  dcdf924…); reason: error: Your local changes to the following files would be
  overwritten by merge:` and exit 1, repeated identically on the next tick;
  after `git stash push -m deploy-preflight` the very next run fast-forwards
  (`code updated to 468f052…`); (b) dirty file that the incoming diff does *not*
  touch ⇒ warning but the pull succeeds (documented nuance: the pre-check warns
  on dirt in general, git decides per file); (c) untracked-only dirt ⇒ 0
  `DIRTY TREE` lines, normal run; (d) `git remote set-url origin
  /nonexistent/repo.git` ⇒ `PULL FAILED: git fetch origin failed … reason:
  fatal: '/nonexistent/repo.git' does not appear to be a git repository`, exit 1.

**Not changed:** `config.py`, `btc/config.py`, `strategy.py`,
`btc/strategy_btc.py`, `run.py`, any trading parameter, both `TRADING_MODE`s,
`MAX_SPREAD_POINTS`, and the server crontab. The deploy still defaults to the
gold unit only, so BTC remains an explicit Phase-2 opt-in.

## 4. Recommended crontab (paste-ready)

```
SHELL=/bin/bash
PATH=/root/scalper/mt5env/bin:/usr/local/bin:/usr/bin:/bin
MAILTO=root
CRON_TZ=UTC

# Deploy: pull main every 15 min. deploy.sh restarts only when a runtime path
# changed (BTC-only / docs-only commits no longer restart the gold book) and
# holds logs/deploy.lock so runs cannot overlap.
*/15 * * * * mkdir -p /root/scalper/logs && DEPLOY_BRANCH=main /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1

# Paper status: ONE report per day, 7 minutes after the 01:00 deploy tick so it
# never reads the bot mid-restart (the old :15 collided with the deploy run).
7 1 * * * test -x /root/ops/paper_status_daily.sh && /root/ops/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1 || echo "$(date -Is) paper_status missing or exited non-zero" >> /root/scalper/logs/paper_status.cron.log
```

**Decision taken 2026-10-07 (user):** `DEPLOY_SERVICES` includes **all four
units** — both paper books stay running (observation on), so both are kept in
sync with the code. `deploy.sh` grew the two BTC units' allowlists in the same
change (a BTC runtime path restarts the BTC units; `btc/dashboard.py` restarts
only the BTC dashboard; gold-only tooling / `docs/` / `research/` / `tests/` /
`*.md` / `deploy.sh` restart nothing; `config.py` and `btc/config.py` restart
everything that reads a config, fail safe). Without those allowlists an
"unknown" service restarts on every non-empty diff — the opposite of PR #24's
intent. **Caveat:** `systemctl restart` also starts a stopped unit, so if the
BTC units are ever deliberately stopped, remove them from `DEPLOY_SERVICES` (or
mask them) at the same time. Paste-ready install + restart runbook:
`docs/server_apply_2026-10-07.md`.

Options, in priority order:

1. **Dashboard opt-in** (fixes F6): add
   `DEPLOY_SERVICES=scalper-bot scalper-dashboard` to the deploy line, *or* keep
   it manual and restart the dashboard once now (`systemctl restart
   scalper-dashboard`) to pick up the PR #22 banner. **(Superseded by the
   decision above: all four units opted in.)**
2. **Move the ops script** (fixes F2): `mkdir -p /root/ops && git -C
   /root/scalper status >/dev/null && mv /root/scalper/scripts/
   paper_status_daily.sh /root/ops/` (+ `.env.paper_status` if it sits there),
   then use the line above. If you prefer to leave it where it is, add a
   `scripts/` guard to the repo's `.gitignore`… **do not** — git would then
   clobber it silently (F2.2); moving it out is the safe fix.
3. **If a second, weekday-only report is really wanted**: `15 1 * * 0,6` for
   the daily line (weekends) and keep `0 1 * * 1-5`; otherwise delete the
   Mon–Fri line.

## 5. Deliberately not done

* **No in-session restart deferral.** Restarts are still allowed inside the
  07:00–20:00 UTC session when gold-runtime code changed; suppressing them
  (defer to the next pre-session tick via a marker file) changes deploy timing
  semantics and was left as an option for the user to choose.
* **No auto-install of `services/*.service`** or `daemon-reload` (F7) —
  installer behaviour is out of scope for a cron review and touches root-owned
  paths.
* **No changes to `paper_status_daily.sh`** itself (server-only, not in git) —
  only its schedule and location are recommended above.
* **No BTC opt-in**, no `MAX_SPREAD_POINTS` change, no trading parameter
  change: the BTC decision gate is unchanged (Phase 1 not passed; see
  `btc/HANDOFF.md`).

## 6. Server checklist (in order, ~5 minutes)

1. `crontab -l > /root/crontab.backup-$(date -u +%F)` — keep a rollback.
2. `crontab -e` → install the block in §4 (decisions from §4 options 1–3).
3. `systemctl show scalper-dashboard -p ActiveEnterTimestamp` → if older than the
   PR #22 merge (2026-10-06), `systemctl restart scalper-dashboard`; then load
   `:8088` and confirm the spread-gate banner state matches
   `btc/logs/live_status.json`.
4. Wait for the next :00/:15/:30/:45 tick, then `tail -20
   /root/scalper/logs/deploy.log` → expect `restart skipped … (no runtime path
   changed)` for inert commits and the historical `restarted …` wording when a
   runtime file changed; `grep -c "deploy already running" …` should stay 0.
5. `grep -c 'PULL FAILED' /root/scalper/logs/deploy.log` → **0** after the
   fix. Any hit names what failed and the sha the box is still running (the
   2026-10-04→10-07 freeze left no such line, because `set -e` exited first).
   `git -C /root/scalper status --porcelain` → empty; server-only compose
   tweaks go in `docker-compose.override.yml` (F11), not the tracked file.
6. `systemctl cat scalper-bot | head -1` → note whether the active unit is
   `/etc/systemd/system/scalper-bot.service` (repo copy is a template → apply
   unit edits by hand, F7).
