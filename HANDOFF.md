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

## 1. Where things stand (as of 2026-09-23 PM)

- **Repo/branch:** `shashidaren/scalper`. Daily-review work lands on
  `arena/01a0a475-scalper` (server `deploy.sh` defaults here). `main` is behind
  (has v6–v7 + deploy.sh via PR #3; does **not** have v8–v12).
- **Server** (`scalping`):
  - `scalper-bot.service` → **FORWARD_TEST (paper)** only. $200 sim start on
    real GOLD ticks. **No real orders.**
  - `scalper-dashboard.service` on port 8088 (reads log files only).
  - MT5 container via `docker-compose.yml` (`lprett-mt5linux-patched`, see §4).
  - **Deploy:** hands-off via `deploy.sh` + cron (see §0).
- **Strategy version:** **v12** after paper wipe under v11. Filters: RSI recovery
  band 40/60 + signal-candle confirm + session **08–16 UTC** + consecutive-loss
  pause **@2** + prior v10/v9/v8/v7/v6 stack. Paper-only. `TRADING_MODE` unchanged.
- **Paper book (user dump 2026-09-23):** balance **$142.03** (start $200),
  **0 wins / 13 losses**, no open position. Avg ~−$4.46/trade ≈ full ATR SL hits.
  Edge under v6–v11 filters is **negative**. Optional: `python paper.py --reset`
  after v12 deploys for a clean sample (or keep ledger as evidence).
- **Daily automation:** `scalper-daily-review-9am-kl` @ 09:00 Asia/Kuala_Lumpur.

## 2. Architecture

```
run.py (engine loop)
  └─ mt5_bridge.MT5Bridge ──RPyC :18812──► mt5server.exe (Wine) ──► MT5 terminal
  └─ strategy.ScalpStrategy (M5: EMA200, RSI band, ATR, session 08-16, candle confirm, …)
  └─ paper.PaperAccount (FORWARD_TEST fills → logs/paper_account.json)
  └─ logger.* → logs/{system,trades}.jsonl, live_status.json, connection_status.json, daily_stats.json
dashboard.py ──reads those files only──► :8088
MT5 container: lprett/mt5linux (patched image), .env secrets
systemd: scalper-bot ExecStartPre=wait_for_mt5.py
deploy.sh (cron */15): git pull --ff-only + restart only if HEAD moved
```

Key config (`config.py`): `TRADING_MODE` ("FORWARD_TEST" default / "LIVE"),
`SIM_START_BALANCE=200`, `BE_TRIGGER_R=0.75`, `RPC_TIMEOUT_SECONDS=30`,
**SESSION_FILTER_*** (08–16), **FRIDAY_CUTOFF_***, **WEEKEND_FLAT_ENABLED**,
**RSI_*_LEVEL**, **RSI_BUY_MAX / RSI_SELL_MIN**, **REQUIRE_SIGNAL_CANDLE**,
**SIGNAL_ON_CLOSED_BAR**, **MIN_ATR**, **MIN_SL_SPREAD_MULT**,
**MAX_CONSECUTIVE_LOSSES=2**.

## 3. Changelog (what was done and why)

| Date | Change | Why |
|---|---|---|
| 09-23 PM | **v12**: RSI recovery band (BUY≤40 / SELL≥60), signal-candle body confirm, session 08–16 UTC, `MAX_CONSECUTIVE_LOSSES` 4→2 | Paper **0/13**, $200→$142; late RSI chases + edge-hour noise; stop bleeding clusters faster |
| 09-23 AM | Daily review only — no strategy/engine change | v11 <24h old; no paper sample yet |
| 09-22 | **v11**: wire `MAX_CONSECUTIVE_LOSSES=4`. Track streak; pause *new* entries rest of day. `0` disables. | Stop revenge/overtrade after a losing cluster |
| 09-21 | **v10**: `MIN_ATR=0.80` + live `MIN_SL_SPREAD_MULT=3` | Dead-market ATR vs GOLD spread ate R |
| 09-20 | **HANDOFF §0**: hands-off model; deploy cron is the path | Zero day-to-day SSH for code updates |
| 09-20 | **v9**: `WEEKEND_FLAT_ENABLED` — no *new* entries Sat/Sun | Thin/gap weekend quotes |
| 09-19 | **v8**: Friday ≥16:00 UTC no *new* entries | Thin Friday gold / weekend-gap |
| 09-18 | **Conflict resolve + merge to main** (PR #3); **`deploy.sh`** | Promote v6+v7; hands-off pull+restart |
| 09-18 | **v7**: closed-bar signal + one-shot per bar | Forming-bar RSI flicker / re-entry |
| 09-17 | **v6**: London/NY 07–17 UTC, RSI 30/70, better backtest stats | Cut Asian noise |
| 09-15 | Engine hardening, paper mode, docker-compose/.env, HANDOFF | Production recovery + FORWARD_TEST |

### Daily review notes

- **2026-09-23 (Wed PM — paper dump):** User pasted paper ledger: **$142.03,
  closed=13, wins=0, losses=13**. Under v11 stack the strategy has no edge on
  this sample (avg loss ≈ full SL). Shipped **v12** quality filters (recovery
  band + candle confirm + 08–16 session) and faster day-pause (2 losses).
  Did **not** change RR 1:2.5, RSI cross levels 30/70, MIN_ATR, or LIVE.
  Next after a **fresh** v12 sample: H1 EMA confirm **or** mean-reversion
  experiment (drop EMA filter) — only with data. Optional `paper.py --reset`.
- **2026-09-23 (Wed AM):** No paper sample yet; no code change. Listed late RSI
  recoveries and 07/16 edge hours as next candidates — those are now in v12.
- **2026-09-22 (Tue AM):** Wired consecutive-loss pause (v11).
- **2026-09-21 (Mon AM):** Shipped v10 (min ATR + SL-vs-spread).
- **2026-09-20:** Hands-off §0 + v9 weekend flat.
- **2026-09-19:** v8 Friday cutoff.
- **2026-09-18:** v7 + deploy.sh.

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
- [ ] Later: merge work branch (v8…v12) → `main`, or keep `DEPLOY_BRANCH` on work branch.
- [ ] Judge paper book after **100+ trades under a single version**; only then consider LIVE.
- [ ] Optional: GOLD symbol if broker renames it.
- [x] Tighter session 08–16 UTC (v12).
- [ ] After v12 sample: H1 trend filter **or** test pure RSI mean-reversion (no EMA).
- [x] Friday early-close (v8).
- [x] Weekend flat (v9).
- [x] Spread-aware min ATR + SL-vs-spread (v10).
- [x] Consecutive-loss day pause (v11; tightened to 2 in v12).
- [x] RSI recovery band + signal-candle confirm (v12).
- [ ] Optional later: max-hold / flatten before Friday close.
- [ ] Optional: `python paper.py --reset` then note new WR/PF in §1.

## 6. Runbook (only if something breaks or you want a peek)

```bash
# --- normal path: do nothing. deploy cron handles updates. ---

# health peek
journalctl -u scalper-bot -n 20 --no-pager
cat /root/scalper/logs/connection_status.json /root/scalper/logs/live_status.json
tail -5 /root/scalper/logs/deploy.log

# paper account (optional)
cd /root/scalper && mt5env/bin/python paper.py
# clean sample for v12 (optional — destroys evidence of v11 wipe):
# mt5env/bin/python paper.py --reset
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
| `Consecutive-loss pause` | v12: 2 losing closes in a row today; no new entries until next day |

## 8. Session protocol (for agents / daily review)

1. Work on `arena/01a0a475-scalper`. Prefer small reversible, config-gated changes.
2. **Never** set `TRADING_MODE = "LIVE"` without explicit user request + paper evidence.
3. **Never** touch `.env` / secrets.
4. Push commits; server cron deploys. Do not ask the user to `git pull` unless cron is missing.
5. Update §1, §3, §5 here every session that changes code or state.
