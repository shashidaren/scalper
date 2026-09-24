# HANDOFF — Gold Scalper (live engine + paper mode)

Read this first in a new session. **Keep it honest:** any session that changes
code, parameters, or the server must update §1 (state), §3 (changelog) and
§5 (TODOs) before it ends, and push its commits.

---

## 0. Hands-off operating model (default)

You should **not** need to SSH for day-to-day updates — including paper book.

| Who | Does what |
|---|---|
| **Daily review** (09:00 Asia/KL) | Reviews strategy on `arena/01a0a475-scalper`. **Paper book:** first try GitHub `status/paper` → `status/paper_latest.json`; else chat paste; else note "not available". |
| **Server** | `deploy.sh` cron every 15 min. **Paper:** `paper_status_daily.sh` writes local logs + optionally publishes sanitized snapshot to branch `status/paper` (no SSH needed for review). |
| **You** | One-time: deploy cron + paper-status cron + optional PAT (below). **Never** flip `TRADING_MODE` to LIVE without a deliberate paper review |

### Paper book path (preferred → fallback)

1. **Automated (preferred):** server cron runs `scripts/paper_status_daily.sh` with `PAPER_STATUS_TOKEN` set → updates `status/paper_latest.json` on branch **`status/paper`**. Daily review reads that file via GitHub API.
2. **Chat paste (fallback):** paste output of `cd /root/scalper && mt5env/bin/python paper.py`.
3. If neither: write "paper status not available this run" — **do not invent numbers**.

**One-time server setup** (run once if not already wired):

```bash
chmod +x /root/scalper/deploy.sh /root/scalper/scripts/paper_status_daily.sh

# crontab -e  → add:
*/15 * * * * /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1

# Paper snapshot after London/NY (17:05 UTC weekdays) — local + optional GitHub publish:
5 17 * * 1-5 /root/scalper/scripts/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1
# Optional: also just before KL morning review (01:00 UTC = 09:00 Asia/KL):
0 1 * * 1-5 /root/scalper/scripts/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1
```

**One-time: enable GitHub publish** (so you never need to paste for daily review):

1. GitHub → Settings → Developer settings → Fine-grained PAT:
   - Resource: only `shashidaren/scalper`
   - Permissions: **Contents: Read and write**
   - No other scopes
2. On server (root-only file, **never commit**):

```bash
cat > /root/scalper/.env.paper_status <<'EOF'
PAPER_STATUS_TOKEN=github_pat_YOUR_TOKEN_HERE
EOF
chmod 600 /root/scalper/.env.paper_status
```

3. Test once: `/root/scalper/scripts/paper_status_daily.sh` — should print `published ... status/paper`.
4. Confirm: https://github.com/shashidaren/scalper/blob/status/paper/status/paper_latest.json

After that: push to work branch → deploy cron applies code; paper cron feeds HANDOFF automatically.

---

## 1. Where things stand (as of 2026-09-24)

- **Repo/branch:** `shashidaren/scalper`. Daily-review work lands on
  `arena/01a0a475-scalper` (server `deploy.sh` defaults here). `main` is behind
  (has v6–v7 + deploy.sh via PR #3; does **not** have v8–v12).
- **Server** (`scalping`):
  - `scalper-bot.service` → **FORWARD_TEST (paper)** only. **No real orders.**
  - `scalper-dashboard.service` on port 8088 (reads log files only).
  - MT5 container via `docker-compose.yml` (`lprett-mt5linux-patched`, see §4).
  - **Deploy:** hands-off via `deploy.sh` + cron (see §0).
- **Strategy version:** **v12** + paper auto-publish plumbing (script + status branch).
  RSI recovery band 40/60 + signal-candle confirm + session **08–16 UTC** +
  consecutive-loss pause **@2** + prior stack. `TRADING_MODE` = FORWARD_TEST.
- **Paper book:** not available this run (no status publish yet; no chat paste).
  Last recorded (2026-09-23 after reset): balance **$200.00**, closed **0**,
  wins **0**, losses **0**, position null. Prior v11 sample was 0/13, $142.
- **Daily automation:** `scalper-daily-review-9am-kl` @ 09:00 Asia/Kuala_Lumpur.

## 2. Architecture

```
run.py (engine loop)
  └─ mt5_bridge.MT5Bridge ──RPyC :18812──► mt5server.exe (Wine) ──► MT5 terminal
  └─ strategy.ScalpStrategy (M5: EMA200, RSI band, ATR, session 08-16, candle confirm, …)
  └─ paper.PaperAccount (FORWARD_TEST fills → logs/paper_account.json)
  └─ logger.* → logs/{system,trades}.jsonl, live_status.json, connection_status.json, daily_stats.json
dashboard.py ──reads those files only──► :8088
scripts/paper_status_daily.sh → logs/paper_latest.json + paper_daily.jsonl
                 └─ (optional PAT) GitHub status/paper_latest.json on branch status/paper
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
| 09-24 | **Paper auto-publish:** enhanced `paper_status_daily.sh` + branch `status/paper` + HANDOFF protocol | Stop requiring manual `python paper.py` paste before each daily review |
| 09-24 | Daily review note only — no strategy/config change | v12 needs a paper sample before another tweak |
| 09-23 | Daily paper protocol: automation prompt + `scripts/paper_status_daily.sh` + HANDOFF | Need paper W/L in every review; Grok cannot SSH |
| 09-23 PM | **v12**: RSI recovery band, signal-candle confirm, session 08–16, pause@2 | Paper **0/13** under v11 |
| 09-23 AM | Daily review only — no strategy change | No paper sample yet |
| 09-22 | **v11**: wire `MAX_CONSECUTIVE_LOSSES` | Stop revenge clusters |
| 09-21 | **v10**: `MIN_ATR=0.80` + `MIN_SL_SPREAD_MULT=3` | Spread ate R |
| 09-20 | Hands-off §0 + **v9** weekend flat | |
| 09-19 | **v8** Friday cutoff | |
| 09-18 | PR #3 + deploy.sh + **v7** closed-bar | |
| 09-17 | **v6** session + RSI 30/70 | |
| 09-15 | Engine + paper mode + HANDOFF | |

### Daily review notes

- **2026-09-24 (Thu, later):** Shipped paper auto-publish path. User still needs
  one-time: paper cron + optional `PAPER_STATUS_TOKEN` in `/root/scalper/.env.paper_status`.
  Until first successful publish, reviews fall back to paste / "not available".
- **2026-09-24 (Thu):** Paper status **not available this run**. Work branch
  `arena/01a0a475-scalper` is ahead of `main` (v8–v12). Reviewed `strategy.py`,
  `config.py`, `run.py`. v12 filters look coherent; no high-confidence code
  change without a post-reset W/L sample. Next: collect paper after London/NY;
  only then consider H1 trend filter vs dropping EMA (mean-reversion). Do not
  flip LIVE.
- **2026-09-23 (Wed PM):** v12 live on server (`781d7dd`), bot restarted, paper
  **reset to $200 / 0 closed**. Session filter idle until 08:00 UTC. Daily review
  automation updated to always record paper dumps. Optional server cron for
  `paper_status_daily.sh`.
- **2026-09-23 (Wed earlier):** v11 paper wipe 0/13 $142 → shipped v12.
- **2026-09-22:** v11 consecutive-loss pause.
- **2026-09-21:** v10 min ATR + SL-vs-spread.

## 4. Server-side patches NOT in git (baked into the container image)

`lprett/mt5linux` has two restart bugs, patched inside the container and baked via
`docker commit mt5 lprett-mt5linux-patched`:

1. `automation.sh` `init_wine`: fifo already exists → `rm -f` then `mkfifo`.
2. `config.sh` `apply_mt5_config`: `test "$FIRST_RUN" || return 0` (was returning 1).

Recreating from stock `lprett/mt5linux:latest` requires re-applying both or the
container crash-loops after first restart. **TODO:** file upstream.

## 5. Open TODOs

- [ ] **One-time:** confirm deploy cron is installed (see §0). If yes, mark done.
- [ ] **One-time:** install `paper_status_daily.sh` weekday cron (17:05 UTC; optional 01:00 UTC).
- [ ] **One-time:** create fine-grained PAT + `/root/scalper/.env.paper_status` so paper publishes to `status/paper` (then no more pasting).
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
- [x] Daily paper status in review protocol (automation + HANDOFF).
- [x] Paper auto-publish plumbing (script + `status/paper` branch).

## 6. Runbook (only if something breaks or you want a peek)

```bash
# --- normal path: do nothing. deploy + paper-status crons handle it. ---

# health peek
journalctl -u scalper-bot -n 20 --no-pager
cat /root/scalper/logs/connection_status.json /root/scalper/logs/live_status.json
tail -5 /root/scalper/logs/deploy.log

# paper account (local)
cd /root/scalper && mt5env/bin/python paper.py
cat logs/paper_latest.json
tail logs/paper_daily.jsonl
# force publish now (needs .env.paper_status):
/root/scalper/scripts/paper_status_daily.sh

# MT5 container
docker ps | grep mt5
docker logs mt5 --tail 60
mt5env/bin/python wait_for_mt5.py --timeout 120
docker compose up -d

# force deploy now
/root/scalper/deploy.sh
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
| paper_status: `skip GitHub publish` | no `PAPER_STATUS_TOKEN` — local snapshot only |
| paper_status: `GitHub publish failed` | bad/expired PAT, wrong repo perms, or branch missing |

## 8. Session protocol (for agents / daily review)

1. Work on `arena/01a0a475-scalper`. Prefer small reversible, config-gated changes.
2. **Never** set `TRADING_MODE = "LIVE"` without explicit user request + paper evidence.
3. **Never** touch `.env` / secrets / `.env.paper_status`.
4. Push commits; server cron deploys. Do not ask the user to `git pull` unless cron is missing.
5. Update §1, §3, §5 here every session that changes code or state.
6. **Paper status (in order):**
   1. Fetch `status/paper_latest.json` from branch `status/paper` (GitHub API).
      If `ts` is present and not bootstrap, record balance / wins / losses / closed in §1 + §3.
   2. Else if user pasted `python paper.py` output in chat, use that.
   3. Else: "paper status not available this run" — do not invent stats.
