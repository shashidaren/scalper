# HANDOFF — Gold Scalper (live engine + paper mode)

Read this first in a new session. **Keep it honest:** any session that changes
code, parameters, or the server must update §1 (state), §3 (changelog) and
§5 (TODOs) before it ends, and push its commits.

---

## 0. Hands-off operating model (default)

You should **not** need to SSH for day-to-day updates.

| Who | Does what |
|---|---|
| **Daily review** (09:00 Asia/KL) | Reviews strategy, may push small reversible changes to `arena/01a0a475-scalper`, updates this file |
| **Server** | `deploy.sh` cron every 15 min: `git pull --ff-only` + restart `scalper-bot` **only if HEAD moved** |
| **You** | One-time: install the deploy cron (below). Optional: glance at dashboard `:8088` or `python paper.py` when curious. **Never** flip `TRADING_MODE` to LIVE without a deliberate paper review |

**One-time server setup** (run once if not already wired):

```bash
# ensure script is executable
chmod +x /root/scalper/deploy.sh

# crontab -e  → add:
*/15 * * * * /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1
```

After that: push to the work branch → within ~15 min the bot is on the new code.
No manual `git pull` / `systemctl restart` required.

---

## 1. Where things stand (as of 2026-09-23)

- **Repo/branch:** `shashidaren/scalper`. Daily-review work lands on
  `arena/01a0a475-scalper` (server `deploy.sh` defaults here). `main` is behind
  (has v6–v7 + deploy.sh via PR #3; does **not** have v8–v11).
- **Server** (`scalping`):
  - `scalper-bot.service` → **FORWARD_TEST (paper)** only. $200 sim balance on
    real GOLD ticks. **No real orders.**
  - `scalper-dashboard.service` on port 8088 (reads log files only).
  - MT5 container via `docker-compose.yml` (`lprett-mt5linux-patched`, see §4).
  - **Deploy:** hands-off via `deploy.sh` + cron (see §0).
- **Strategy version:** v11 (consecutive-loss day pause wired; still v10 filters:
  `MIN_ATR=0.80` + `MIN_SL_SPREAD_MULT=3` + v9 weekend + v8 Fri ≥16:00 UTC +
  v7 closed-bar + v6 London/NY + RSI 30/70). Paper-only. `TRADING_MODE` unchanged.
- **Paper book:** lives on the server (`logs/paper_account.json`). Not visible to
  daily-review sessions. Optional check: `python paper.py` on the server; paste
  win/loss into §1 when you have a sample. Not required for hands-off operation.
- **Daily automation:** `scalper-daily-review-9am-kl` @ 09:00 Asia/Kuala_Lumpur.

## 2. Architecture

```
run.py (engine loop)
  └─ mt5_bridge.MT5Bridge ──RPyC :18812──► mt5server.exe (Wine) ──► MT5 terminal
  └─ strategy.ScalpStrategy (M5: EMA200, RSI, ATR, session, Friday cutoff, weekend flat, closed-bar, min ATR)
  └─ paper.PaperAccount (FORWARD_TEST fills → logs/paper_account.json)
  └─ logger.* → logs/{system,trades}.jsonl, live_status.json, connection_status.json, daily_stats.json
dashboard.py ──reads those files only──► :8088
MT5 container: lprett/mt5linux (patched image), .env secrets
systemd: scalper-bot ExecStartPre=wait_for_mt5.py
deploy.sh (cron */15): git pull --ff-only + restart only if HEAD moved
```

Key config (`config.py`): `TRADING_MODE` ("FORWARD_TEST" default / "LIVE"),
`SIM_START_BALANCE=200`, `BE_TRIGGER_R=0.75`, `RPC_TIMEOUT_SECONDS=30`,
**SESSION_FILTER_***, **FRIDAY_CUTOFF_***, **WEEKEND_FLAT_ENABLED**,
**RSI_*_LEVEL**, **SIGNAL_ON_CLOSED_BAR**, **MIN_ATR**, **MIN_SL_SPREAD_MULT**,
**MAX_CONSECUTIVE_LOSSES**.

## 3. Changelog (what was done and why)

| Date | Change | Why |
|---|---|---|
| 09-23 | Daily review only — no strategy/engine change. | v11 is <24h old; no paper sample; stacking another filter would be guesswork |
| 09-22 | **v11**: wire `MAX_CONSECUTIVE_LOSSES=4` (already in config, unused). Track streak in daily_stats; pause *new* entries rest of day. Open trades still SL/TP/BE. `0` disables. | Stop revenge/overtrade after a losing cluster; listed risk control was a no-op |
| 09-21 | **v10**: `MIN_ATR=0.80` (was hardcoded 0.50) + live `MIN_SL_SPREAD_MULT=3` | Dead-market ATR vs 30–80pt GOLD spread ate R; listed next experiment on 09-20 |
| 09-20 | **HANDOFF §0**: hands-off model as default; deploy cron is the path | User wants zero day-to-day SSH for code updates |
| 09-20 | **v9 strategy**: `WEEKEND_FLAT_ENABLED` — no *new* entries Sat/Sun | Session hours are UTC-hour only; Sat/Sun 07–17 could still fire on thin/gap quotes |
| 09-19 | **v8 strategy**: Friday ≥16:00 UTC no *new* entries | Thin Friday gold / weekend-gap risk |
| 09-18 | **Conflict resolve + merge to main** (PR #3); **`deploy.sh`** | Promote v6+v7; hands-off pull+restart |
| 09-18 | **v7**: closed-bar signal + one-shot per bar | Forming-bar RSI flicker / re-entry |
| 09-17 | **v6**: London/NY 07–17 UTC, RSI 30/70, better backtest stats | Cut Asian noise |
| 09-15 | Engine hardening, paper mode, docker-compose/.env, HANDOFF | Production recovery + FORWARD_TEST |

### Daily review notes

- **2026-09-23 (Wed AM):** Reviewed work-branch HEAD `b13025b` (v11) vs `main`
  (`69d7478`, still v6–v7 only). Strategy remains M5 EMA200 + RSI 30/70 cross +
  ATR×2 / ×5 RR, session 07–17 UTC, Fri≥16:00, weekend flat, closed-bar one-shot,
  MIN_ATR 0.80, sl≥3×spread, MAX_CONSECUTIVE_LOSSES=4. `TRADING_MODE` still
  FORWARD_TEST. Paper ledger not visible here. Weaknesses still on the list but
  **not** changed today: late RSI recoveries (curr can print far from 30/70),
  no H1 trend confirm, 07 and 16 UTC edge hours, BE@0.75R can scratch winners,
  open Friday trades can still ride the weekend. Next after a paper sample:
  H1 EMA confirm or tighter 08–16 UTC — not both at once.
- **2026-09-22 (Tue AM):** `main` still behind work branch (v8–v11). No paper
  ledger visible here. Did not change RR 1:2.5, RSI 30/70, session 07–17, ATR,
  or LIVE. Wired the unused consecutive-loss circuit breaker (v11). Next after
  paper sample: H1 EMA confirm or tighter 08–16 window. Optional later: max hold
  / flatten into Friday close (open trades can still ride the weekend).
- **2026-09-21 (Mon AM):** First London week after v9. No paper ledger visible here.
  Shipped v10 (min ATR + SL-vs-spread). Left RR 1:2.5, RSI 30/70, session 07–17,
  and LIVE alone. Next after paper sample: H1 EMA confirm or tighter 08–16 window.
- **2026-09-20 (later):** User requested fully hands-off. Documented §0 (deploy
  cron as default). No strategy change. Paper ledger still on-server only.
- **2026-09-20 (Sun AM):** Shipped v9 weekend flat. Left RR/RSI/spread/ATR/LIVE alone
  (no paper sample). Next experiments after data: H1 EMA confirm, spread-aware min ATR, tighter 08–16 window.
- **2026-09-19:** Shipped v8 Friday cutoff.
- **2026-09-18:** Shipped v7 + deploy.sh.

## 4. Server-side patches NOT in git (baked into the container image)

`lprett/mt5linux` has two restart bugs, patched inside the container and baked via
`docker commit mt5 lprett-mt5linux-patched`:

1. `automation.sh` `init_wine`: fifo already exists → `rm -f` then `mkfifo`.
2. `config.sh` `apply_mt5_config`: `test "$FIRST_RUN" || return 0` (was returning 1).

Recreating from stock `lprett/mt5linux:latest` requires re-applying both or the
container crash-loops after first restart. **TODO:** file upstream.

## 5. Open TODOs

- [ ] **One-time:** confirm deploy cron is installed (see §0). If yes, mark done.
- [ ] **Rotate MT5 + VNC passwords** (were in plain text). Update `.env` after XM change.
- [ ] Revert container `main.sh` `set -ex` → `set -e` if log noise bothers you.
- [ ] File upstream issues for the two `mt5linux` bugs (§4).
- [x] Merge clean PR (`resolve/v6-v7-deploy` → `main`).
- [ ] Later: merge work branch (v8+v9+v10+v11) → `main`, or keep `DEPLOY_BRANCH` on work branch.
- [ ] Judge paper book after **100+ trades**; only then consider `TRADING_MODE = "LIVE"`.
- [ ] Optional: GOLD symbol if broker renames it.
- [ ] After paper data: H1 trend filter or tighter session (08–16 UTC).
- [x] Friday early-close (v8).
- [x] Weekend flat (v9).
- [x] Spread-aware min ATR + SL-vs-spread (v10).
- [x] Consecutive-loss day pause (v11; was config-only).
- [ ] Optional later: max-hold / flatten before Friday close (open trades can still ride weekend).
- [ ] Optional (not required for hands-off): dump `python paper.py` and note WR/PF in §1.

## 6. Runbook (only if something breaks or you want a peek)

```bash
# --- normal path: do nothing. deploy cron handles updates. ---

# health peek
journalctl -u scalper-bot -n 20 --no-pager
cat /root/scalper/logs/connection_status.json /root/scalper/logs/live_status.json
tail -5 /root/scalper/logs/deploy.log

# paper account (optional)
cd /root/scalper && mt5env/bin/python paper.py
grep SIM_ logs/trades.jsonl | tail

# MT5 container
docker ps | grep mt5
docker logs mt5 --tail 60
mt5env/bin/python wait_for_mt5.py --timeout 120
docker compose up -d

# force deploy now (skip waiting for cron)
/root/scalper/deploy.sh

# switch deploy target to main after you merge (optional)
# DEPLOY_BRANCH=main /root/scalper/deploy.sh
# (or set DEPLOY_BRANCH permanently in the cron line)
```

## 7. Failure signatures

| Symptom | Meaning |
|---|---|
| `Connection refused ...:18812` | MT5 container down/booting (or §4 crash-loop) |
| `[Errno 104] Connection reset by peer` | docker-proxy during container restart; usually benign |
| `pickling is disabled` | rpyc classic flags missing — fixed in `78fe7e8` |
| `Market data temporarily unavailable` | symbol/tick/login issue |
| container `Restarting (1)` silently | upstream `set -e` bugs (§4) |
| deploy.log shows "already up to date" | normal; no new commits |
| `SKIP reason=sl_vs_spread` | v10: ATR-based SL too small vs live bid/ask |
| `Consecutive-loss pause` | v11: 4 losing closes in a row today; no new entries until next day |

## 8. Session protocol (for agents / daily review)

1. Work on `arena/01a0a475-scalper`. Prefer small reversible, config-gated changes.
2. **Never** set `TRADING_MODE = "LIVE"` without explicit user request + paper evidence.
3. **Never** touch `.env` / secrets.
4. Push commits; server cron deploys. Do not ask the user to `git pull` unless cron is missing.
5. Update §1, §3, §5 here every session that changes code or state.
