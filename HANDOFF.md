# HANDOFF — Gold Scalper (live engine + paper mode)

Read this first in a new session. **Keep it honest:** any session that changes
code, parameters, or the server must update §1 (state), §3 (changelog) and
§5 (TODOs) before it ends, and push its commits.

---

## 1. Where things stand (as of 2026-09-20)

- **Repo/branch:** `shashidaren/scalper`. Daily-review work still lands on
  `arena/01a0a475-scalper` (server `deploy.sh` defaults here). `main` is behind
  the work branch (has v6–v7 + deploy.sh via PR #3; does **not** have v8 Friday
  cutoff or v9 weekend flat).
- **Server** (`scalping`):
  - `scalper-bot.service` active, running **FORWARD_TEST (paper)** mode with a
    $200 simulated balance on real GOLD ticks. No real orders are sent.
  - `scalper-dashboard.service` on port 8088 (reads files only).
  - MT5 container managed by `docker-compose.yml`, image
    `lprett-mt5linux-patched` (see §4), ports 18812/5901/8080,
    restart `unless-stopped`.
  - **Deploy:** `deploy.sh` pulls the tracked branch and restarts the bot only
    when HEAD changes.
- **Strategy version:** v9 (weekend Sat/Sun flat on top of v8 Friday 16:00 UTC
  cutoff + v7 closed-bar + v6 London/NY + RSI 30/70). Still paper-only.
  `TRADING_MODE` unchanged.
- **Paper book:** not visible from this daily-review session (no server logs).
  After deploy: `python paper.py` and note win/loss in §1.
- **Daily automation:** `scalper-daily-review-9am-kl` runs every day 09:00
  Asia/Kuala_Lumpur.

## 2. Architecture

```
run.py (engine loop)
  └─ mt5_bridge.MT5Bridge ──RPyC :18812──► mt5server.exe (Wine) ──► MT5 terminal
  └─ strategy.ScalpStrategy (M5: EMA200 trend, RSI pullback, ATR filter, session filter, Friday cutoff, weekend flat, closed-bar)
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
backoff caps, stale-tick thresholds, **SESSION_FILTER_***, **FRIDAY_CUTOFF_***,
**WEEKEND_FLAT_ENABLED**, **RSI_*_LEVEL**, **SIGNAL_ON_CLOSED_BAR**.

## 3. Changelog (what was done and why)

| Date | Change | Why |
|---|---|---|
| 09-20 | **v9 strategy**: `WEEKEND_FLAT_ENABLED` — no *new* entries Sat/Sun | Session hours are UTC-hour only; Sat/Sun 07–17 could still fire on thin/gap quotes; companion to v8 |
| 09-19 | **v8 strategy**: `FRIDAY_CUTOFF_ENABLED` + `FRIDAY_CUTOFF_HOUR_UTC=16` — no *new* entries Fri ≥16:00 UTC | Thin Friday gold / weekend-gap risk; already queued in TODOs; reversible flags |
| 09-18 | **Conflict resolve + merge to main:** `resolve/v6-v7-deploy` (PR #3) | Promote v6+v7 + deploy.sh without conflict markers |
| 09-18 | **`deploy.sh`** + HANDOFF cron notes | Hands-off server updates after daily-review pushes |
| 09-18 | **v7 strategy**: evaluate EMA/RSI/ATR on last *completed* M5 bar (`SIGNAL_ON_CLOSED_BAR`); one-shot per bar timestamp | Forming-bar RSI flicker + same-bar re-entry after quick exits |
| 09-17 | **v6 strategy**: London/NY session filter (07–17 UTC), RSI 30/70, backtester PF / max-DD / avg-R + BE + session | Cut Asian-session noise; better offline evaluation |
| 09-15 | Engine hardening, paper mode, rpyc obtain, docker-compose/.env, HANDOFF | Production outage recovery + FORWARD_TEST |

### Daily review notes

- **2026-09-20 (Sun):** Work branch still ahead of `main` (v8 not merged). Reviewed v8 stack: M5 EMA200 + RSI 30/70 + ATR 2/5 + session 07–17 UTC + closed-bar one-shot + Fri≥16:00 cutoff. Paper ledger still not in this session — left RR, RSI, spread 80, ATR min $0.50, and `TRADING_MODE` alone. Shipped weekend Sat/Sun flat (config-gated) so hour-only session filter cannot open on weekend quotes. Next after a paper sample: H1 EMA confirmation, spread-aware min ATR, tighter 08–16 window. Merge v8+v9 to main when ready.
- **2026-09-19:** `main` is ahead of the previous work-branch HANDOFF (PR #3 merged v6–v7). Reviewed M5 EMA200 + RSI 30/70 + ATR 2/5 + session 07–17 UTC + closed-bar one-shot. Paper ledger not in this session. Left RR, RSI, spread 80, and `TRADING_MODE` alone — no paper stats to justify those. Shipped Friday 16:00 UTC cutoff (config-gated) as the next listed, low-risk overtrading cut. Next after a paper sample: H1 EMA confirmation, spread-aware min ATR, tighter 08–16 window.
- **2026-09-18:** Shipped v7, deploy.sh. Server tracks work branch until you opt into `DEPLOY_BRANCH=main`.

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
- [x] Merge clean PR (`resolve/v6-v7-deploy` → `main`); close conflicted PR #2.
- [ ] After more work-branch commits (v8+v9): merge work branch → `main` or keep
  `DEPLOY_BRANCH` on `arena/01a0a475-scalper`.
- [ ] Install deploy cron once (see §6) if not already wired.
- [ ] Judge the paper book after 100+ trades across sessions; only then flip
  `TRADING_MODE = "LIVE"` in `config.py` (+ restart service).
- [ ] Consider: GOLD symbol naming (`config.SYMBOL="GOLD"` works today on
  XMGlobal; revisit if broker changes it).
- [ ] After more paper data: experiment with H1 trend confirmation or tighter
  session window (e.g. 08–16 UTC only).
- [x] Friday early-close filter (skip new entries after 16:00 UTC Friday) — shipped 2026-09-19 as v8.
- [x] Weekend flat (skip new entries Sat/Sun) — shipped 2026-09-20 as v9.
- [ ] After pull+restart: dump `python paper.py` and note win rate / PF in §1.

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

# one-shot deploy (work branch — what daily review pushes to)
cd /root/scalper && chmod +x deploy.sh && ./deploy.sh

# hands-off deploy cron (every 15 min; only restarts when commits land)
# crontab -e  →
# */15 * * * * /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1
#
# After merging to main, either keep work branch as deploy target or:
#   DEPLOY_BRANCH=main /root/scalper/deploy.sh

# manual deploy (legacy)
cd /root/scalper && git fetch && git checkout arena/01a0a475-scalper && git pull && systemctl restart scalper-bot
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

1. Day-to-day strategy work on `arena/01a0a475-scalper`; promote to `main` via a
   branch based on current `main` when history diverges (squash merges).
2. Test engine changes against the fake RPyC server pattern (venv with
   `rpyc pandas numpy`, a fake `MetaTrader5` module exposing
   `initialize/symbol_select/symbol_info_tick/copy_rates_from_pos` returning a
   real structured numpy array, `ThreadedServer(SlaveService, port=18812)`).
3. Update §1, §3, §5 here; add long-form analysis to `docs/` if needed.
