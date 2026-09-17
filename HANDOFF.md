# HANDOFF — Gold Scalper (live engine + paper mode)

Read this first in a new session. **Keep it honest:** any session that changes
code, parameters, or the server must update §1 (state), §3 (changelog) and
§5 (TODOs) before it ends, and push its commits.

---

## 1. Where things stand (as of 2026-09-17)

- **Repo/branch:** `shashidaren/scalper`, work branch `arena/01a0a475-scalper`
  (branched from `main`). **Not merged to main yet** — open a PR once the
  paper book is trusted.
- **Server** (`scalping`):
  - `scalper-bot.service` active, running **FORWARD_TEST (paper)** mode with a
    $200 simulated balance on real GOLD ticks. No real orders are sent.
  - `scalper-dashboard.service` on port 8088 (reads files only).
  - MT5 container managed by `docker-compose.yml`, image
    `lprett-mt5linux-patched` (see §4), ports 18812/5901/8080,
    restart `unless-stopped`.
- **Strategy version:** v6 (session filter + softer RSI). Still paper-only.
- **Daily automation:** `scalper-daily-review-9am-kl` runs every day 09:00
  Asia/Kuala_Lumpur, reviews code/HANDOFF, may push small improvements.

## 2. Architecture

```
run.py (engine loop)
  └─ mt5_bridge.MT5Bridge ──RPyC :18812──► mt5server.exe (Wine) ──► MT5 terminal
  └─ strategy.ScalpStrategy (M5: EMA200 trend, RSI pullback, ATR filter, session filter)
  └─ paper.PaperAccount (FORWARD_TEST fills, ledger in logs/paper_account.json)
  └─ logger.* writes logs/{system,trades}.jsonl, live_status.json,
     connection_status.json, daily_stats.json
dashboard.py ──reads those files only──► :8088
MT5 container: lprett/mt5linux image (Xvfb→x11vnc→noVNC :8080, Wine MT5,
               RPyC server :18812), credentials via .env (env_file)
systemd: scalper-bot has ExecStartPre=wait_for_mt5.py (readiness gate)
```

Key config (`config.py`): `TRADING_MODE` ("FORWARD_TEST" default / "LIVE"),
`SIM_START_BALANCE=200`, `BE_TRIGGER_R=0.75`, `RPC_TIMEOUT_SECONDS=30`,
backoff caps, stale-tick thresholds, **SESSION_FILTER_*** and **RSI_*_LEVEL**.

## 3. Changelog (what was done and why)

| Date | Change | Why |
|---|---|---|
| 09-17 | **v6 strategy**: London/NY session filter (07–17 UTC), RSI extremes relaxed 28/72 → 30/70 (config-driven), backtester gains PF / max-DD / avg-R + BE ratchet + session awareness | Cut low-liquidity Asian-session noise; slightly more pullback signals; make offline evaluation more trustworthy before judging paper book |
| 09-15 | Engine: classified connection errors, exponential backoff (10→60s), bounded RPyC timeouts, stale-tick detection, `wait_for_mt5.py` + `ExecStartPre` gate, logs anchored to repo dir | Post-reboot crash loop spammed `Connection refused` every 10s with no diagnostics |
| 09-15 | Patched container `automation.sh` (`rm -f` + `mkfifo`) and `config.sh` (`return 0`); committed image as `lprett-mt5linux-patched`; moved container under `docker-compose.yml` + `.env` | Upstream `lprett/mt5linux` restart bugs (see §4); secrets out of git/CLI |
| 09-15 | `FORWARD_TEST` paper mode: `paper.py` (crash-safe $200 ledger, SL/TP tick resolution, pessimistic SL-first, BE ratchet 0.75R, sim closes feed daily stats) | Emulate trading on real ticks before funding a live account (pattern from `shashidaren/gold-trading-bot`) |
| 09-15 | rpyc `MasterService` + classic config flags; `get_rates()` uses `rpyc.classic.obtain()` | Real MT5 rates are numpy arrays → need pickle transfer ("pickling is disabled" fix) |

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
  (Image only uses `.env` creds for first-run auto-login; stored login lives
  in the Wine prefix.)
- [ ] Revert `set -ex` → `set -e` in the container's `main.sh` (see §4 note).
- [ ] File upstream issues for the two `lucas-campagna/mt5linux` bugs.
- [ ] Open PR `arena/01a0a475-scalper` → `main` once paper book is trusted.
- [ ] Judge the paper book after 100+ trades across sessions; only then flip
  `TRADING_MODE = "LIVE"` in `config.py` (+ restart service).
- [ ] Consider: GOLD symbol naming (`config.SYMBOL="GOLD"` works today on
  XMGlobal; revisit if broker changes it).
- [ ] After more paper data: experiment with H1 trend confirmation or tighter
  session window (e.g. 08–16 UTC only).

## 6. Runbook (common commands, on the server)

```bash
# bot health
journalctl -u scalper-bot -n 20 --no-pager
cat ~/scalper/logs/connection_status.json ~/scalper/logs/live_status.json

# paper account
cd ~/scalper && mt5env/bin/python paper.py            # inspect
mt5env/bin/python paper.py --reset                    # restart at $200
grep SIM_ logs/trades.jsonl | tail                    # sim ledger

# MT5 container
docker ps | grep mt5
docker logs mt5 --tail 60
mt5env/bin/python wait_for_mt5.py --timeout 120       # readiness probe
docker compose up -d                                  # (re)create from compose+.env

# deploy code (work branch)
cd ~/scalper && git fetch && git checkout arena/01a0a475-scalper && git pull && systemctl restart scalper-bot
# (service-file changes also need: cp services/*.service /etc/systemd/system/ && systemctl daemon-reload)
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

1. Work only on `arena/01a0a475-scalper`; commit + push every meaningful change.
2. Test engine changes against the fake RPyC server pattern (venv with
   `rpyc pandas numpy`, a fake `MetaTrader5` module exposing
   `initialize/symbol_select/symbol_info_tick/copy_rates_from_pos` returning a
   real structured numpy array, `ThreadedServer(SlaveService, port=18812)`).
3. Update §1, §3, §5 here; add long-form analysis to `docs/` if needed.
