# HANDOFF — Gold Scalper (live engine + paper mode)

Read this first in a new session. **Keep it honest:** any session that changes
code, parameters, or the server must update §1 (state), §3 (changelog) and
§5 (TODOs) before it ends, and push its commits.

---

## 1. Where things stand (as of 2026-09-30 09:36 UTC)

- **Repo/branch:** `shashidaren/scalper`; PR #4 merged to `main` (merge commit
  `4a21a33`, 2026-09-30 09:31 UTC) — RSI 35/65 paper-test is now on `main`.
  Current session branch is `arena/01a0f1b0-scalper`.
- **Server** (`scalping`), deployed 2026-09-30 09:36 UTC:
  - `scalper-bot.service` is active in **FORWARD_TEST (paper)** mode; no real
    orders are sent. Server now runs `main` at `4a21a33` (PR #4 deploy).
  - **Confirmed on server:** `RSI_BUY_LEVEL=35`, `RSI_SELL_LEVEL=65`,
    `MAX_SPREAD_POINTS=80`. Server clock is UTC.
  - Pre-deploy trades-log tail showed repeated `SIGNAL` events with
    `signal: null`, not high-spread skips (baseline before RSI 35/65).
  - `scalper-dashboard.service` on port 8088 (reads files only).
  - MT5 container managed by `docker-compose.yml`, image
    `lprett-mt5linux-patched` (see §4), ports 18812/5901/8080,
    restart `unless-stopped`.
  - **Deploy:** `deploy.sh` pulls its configured branch and restarts the bot
    only when HEAD changes. The 09:36 UTC deploy to `4a21a33` succeeded; still
    verify the cron's target branch before relying on hands-off deploys.
  - **Status script:** local `paper_status_daily.sh` edits were stashed for
    the deploy; backup at `/root/paper_status_daily.sh.backup`. Keep
    `.env.paper_status` private — never commit it.
- **Strategy:** v7 closed-bar signals + one-shot per bar, session 07:00–17:00
  UTC, paper-testing RSI 35/65 instead of 30/70 to modestly increase signals.
  **Confirmed active on the server** since the 09:36 UTC deploy of `4a21a33`.
- **Paper book:** inspect on server with `python paper.py` after deploy.

## 2. Architecture

```
run.py (engine loop)
  └─ mt5_bridge.MT5Bridge ──RPyC :18812──► mt5server.exe (Wine) ──► MT5 terminal
  └─ strategy.ScalpStrategy (M5: EMA200 trend, RSI pullback, ATR filter, session filter, closed-bar)
  └─ paper.PaperAccount (FORWARD_TEST fills, ledger in logs/paper_account.json)
  └─ logger.* writes logs/{system,trades}.jsonl, live_status.json,
     connection_status.json, daily_stats.json
dashboard.py ──reads those files only──► :8088
MT5 container: lprett/mt5linux image (Xvfb→x11vnc→noVNC :8080, Wine MT5,
               RPyC server :18812), credentials via .env (env_file)
systemd: scalper-bot has ExecStartPre=wait_for_mt5.py (readiness gate)
deploy.sh: git pull --ff-only + systemctl restart only if HEAD moved
```

Key config (`config.py`): `TRADING_MODE` ("FORWARD_TEST" default / "LIVE"),
`SIM_START_BALANCE=200`, `BE_TRIGGER_R=0.75`, `RPC_TIMEOUT_SECONDS=30`,
backoff caps, stale-tick thresholds, **SESSION_FILTER_***, **RSI_*_LEVEL**,
**SIGNAL_ON_CLOSED_BAR**.

## 3. Changelog (what was done and why)

| Date | Change | Why |
|---|---|---|
| 09-30 | **PR #4 merged + deployed (`4a21a33`, 09:36 UTC); confirmed RSI 35/65, `MAX_SPREAD_POINTS=80` on server** | RSI paper-test now on `main` and active in FORWARD_TEST; baseline for trade-count/quality comparison |
| 09-30 | **Stashed `paper_status_daily.sh` edits; backup at `/root/paper_status_daily.sh.backup`; `.env.paper_status` kept private** | Keep deploy clean (`git pull --ff-only`) without losing local status-script work or leaking secrets |
| 09-30 | **Paper-test RSI 35/65** (from 30/70) | Modest, controlled relaxation after recent UTC-session logs showed repeated null signals; compare trade count and quality before further changes |
| 09-18 | **Conflict resolve:** new branch `resolve/v6-v7-deploy` on top of `main` (squash from PR #1 had diverged `HANDOFF.md` / `config.py`) | PR #2 was dirty; clean history so main can take v6+v7 + deploy without conflict markers |
| 09-18 | **`deploy.sh`** + HANDOFF cron notes | Hands-off server updates after daily-review pushes |
| 09-18 | **v7 strategy**: evaluate EMA/RSI/ATR on last *completed* M5 bar (`SIGNAL_ON_CLOSED_BAR`); one-shot per bar timestamp | Forming-bar RSI flicker + same-bar re-entry after quick exits |
| 09-17 | **v6 strategy**: London/NY session filter (07–17 UTC), RSI 30/70, backtester PF / max-DD / avg-R + BE + session | Cut Asian-session noise; better offline evaluation |
| 09-15 | Engine hardening, paper mode, rpyc obtain, docker-compose/.env, HANDOFF | Production outage recovery + FORWARD_TEST |

### Daily review notes

- **2026-09-18:** Shipped v7 and deploy.sh. The clean promotion was subsequently
  merged to `main` (base commit `69d7478`). The old work-branch name in earlier
  notes and the deploy.sh default may be stale; verify the server's deploy
  target before relying on the cron.
- **2026-09-30:** PR #4 ("Paper-test more frequent RSI thresholds") merged to
  `main` at `4a21a33` (09:31 UTC) and deployed to `scalping` at 09:36 UTC.
  Verified RSI 35/65 and `MAX_SPREAD_POINTS=80` in the server checkout. Local
  `paper_status_daily.sh` edits were stashed with a backup at
  `/root/paper_status_daily.sh.backup`; `.env.paper_status` stays off-git.

## 4. Server-side patches NOT in git (baked into the container image)

`lprett/mt5linux` (upstream: `lucas-campagna/mt5linux`) has two restart bugs.
They were patched **inside the container** with `docker cp` + `sed` and baked
in via `docker commit mt5 lprett-mt5linux-patched`:

1. `automation.sh` `init_wine`: `mkfifo .../drive_c/server` crashed when the
   fifo already existed after a restart (`set -e`). Patched line:
   `rm -f "$WIN_ROOT/server"; mkfifo -m 666 "$WIN_ROOT/server"`
   (upstream's "hotfix" is broken: `[-e ...` typo → check never runs).
2. `config.sh` `apply_mt5_config`: `test $FIRST_RUN || return` returned 1 on
   every non-first run, killing `main.sh` under `set -e`. Patched to
   `test "$FIRST_RUN" || return 0`.

If a container is ever recreated from stock `lprett/mt5linux:latest`,
re-apply both (same `docker cp`/`sed` pattern) or it will crash-loop after
its first restart. **TODO:** file these upstream.

Note: the patched image may still carry `set -ex` tracing in
`/app/src/main.sh` (line 2). Harmless but noisy in `docker logs` — revert to
`set -e` with the same docker-cp pattern if desired.

## 5. Open TODOs

- [ ] **Rotate the MT5 password** (and VNC password) — both were pasted in
  plain text. Change at XM, re-login via noVNC (`:8080`), update `.env`.
- [ ] Revert `set -ex` → `set -e` in the container's `main.sh` (see §4 note).
- [ ] File upstream issues for the two `lucas-campagna/mt5linux` bugs.
- [ ] Verify the server deploy cron targets the intended branch. The current
  `deploy.sh` default names the old `arena/01a0a475-scalper` branch; use
  `DEPLOY_BRANCH=main` only if `main` is the intended production target.
  (09:36 UTC deploy to `main@4a21a33` succeeded; still confirm the cron env
  matches.)
- [ ] Restore or re-apply stashed `paper_status_daily.sh` edits from
  `/root/paper_status_daily.sh.backup` if still wanted; verify deploy/status
  cron timezone and that the status script exists on the server. Keep
  `.env.paper_status` private — never commit it.
- [ ] Paper-test RSI 35/65 (deployed 09:36 UTC as `4a21a33`); compare with the
  30/70 baseline using trade count, net expectancy after spread, drawdown,
  and session coverage.
- [ ] Add signal skip-reason diagnostics: current `SIGNAL: null` entries do not
  distinguish session, ATR, EMA, or RSI conditions.
- [ ] Fix backtest input-length mismatch (backtest supplies 201 bars while
  strategy currently requires 202), then validate backtests before tuning.
- [ ] Judge the paper book after 100+ trades across sessions; only then flip
  `TRADING_MODE = "LIVE"` in `config.py` (+ restart service).
- [ ] Consider: GOLD symbol naming (`config.SYMBOL="GOLD"` works today on
  XMGlobal; revisit if broker changes it).
- [ ] After more paper data: experiment with H1 trend confirmation or tighter
  session window (e.g. 08–16 UTC only).
- [ ] Optional next filter: skip new entries after 16:00 UTC on Friday (thin gold).

## 6. Runbook (common commands, on the server)

```bash
# bot health
journalctl -u scalper-bot -n 20 --no-pager
cat /root/scalper/logs/connection_status.json /root/scalper/logs/live_status.json

# paper account
cd /root/scalper && mt5env/bin/python paper.py
mt5env/bin/python paper.py --reset
grep SIM_ logs/trades.jsonl | tail

# MT5 container
docker ps | grep mt5
docker logs mt5 --tail 60
mt5env/bin/python wait_for_mt5.py --timeout 120
docker compose up -d

# one-shot deploy (choose the intended production branch explicitly)
cd /root/scalper && DEPLOY_BRANCH=main ./deploy.sh

# hands-off deploy cron (every 15 min; only restarts when commits land)
# crontab -e  → set DEPLOY_BRANCH to the intended production branch:
# */15 * * * * DEPLOY_BRANCH=main /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1

# manual deploy (if main is the intended production branch)
cd /root/scalper && git fetch origin && git checkout main && git pull --ff-only origin main && systemctl restart scalper-bot
```

## 7. Failure signatures (what each error means)

| Symptom | Meaning |
|---|---|
| `Connection refused ...:18812` | MT5 container down/booting (or crash-looping — check §4) |
| `[Errno 104] Connection reset by peer` | docker-proxy flapping while container restarts; benign during boot |
| `pickling is disabled` | rpyc client missing classic flags — fixed in `78fe7e8`; if it returns, something recreated the bridge without them |
| `Market data temporarily unavailable` | tick/symbol issue (symbol missing, terminal not logged in) |
| container `Restarting (1)` silently | upstream `set -e` bugs (§4) |

## 8. Session protocol

1. Day-to-day strategy work on the session Arena branch (currently
   `arena/01a0f1b0-scalper`); promote to `main` via PR, rebasing onto current
   `main` when history diverges (squash merges).
2. Test engine changes against the fake RPyC server pattern (venv with
   `rpyc pandas numpy`, a fake `MetaTrader5` module exposing
   `initialize/symbol_select/symbol_info_tick/copy_rates_from_pos` returning a
   real structured numpy array, `ThreadedServer(SlaveService, port=18812)`).
3. Update §1, §3, §5 here; add long-form analysis to `docs/` if needed.
