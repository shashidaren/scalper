# HANDOFF — Gold Scalper (live engine + paper mode)

Read this first in a new session. **Keep it honest:** any session that changes
code, parameters, or the server must update §1 (state), §3 (changelog) and
§5 (TODOs) before it ends, and push its commits.

---

## 1. Where things stand (as of 2026-09-30 11:00 UTC)

- **Repo/branch:** `shashidaren/scalper`; **PR #6 merged to `main` at
  2026-09-30 10:19:58 UTC** (merge commit `40ec328`, branch
  `arena/01a0f1c8-scalper` → `main`). Gate 1 (live-path hardening) and Gate 2
  (backtest fix) are therefore on `main`; `main` and the session branch are at
  the same commit right now.
- **Deploy cron confirmed (2026-09-30):**
  `*/15 * * * * DEPLOY_BRANCH=main /root/scalper/deploy.sh` — so `main` is the
  production target and the merge should have auto-deployed within 15 min of
  the merge. **Not yet verified from the server side** (see §6
  "Post-PR#6 verification"): the 2026-09-30 11:00 UTC session had no SSH
  access, so the checks below must be run on `scalping` and reported back.
  Expected: `git log` shows `40ec328`, `live_ledger.py` present,
  `journalctl -u scalper-bot` banner shows the new HEAD, and
  `mt5env/bin/python backtest.py` prints **201 trades** (was 0 before Gate 2).
- **Status script:** runs from cron on the server at **01:15 UTC daily** and
  **01:00 UTC Mon–Fri** (double-run on weekdays by design/legacy), at
  `/root/scalper/scripts/paper_status_daily.sh` — **server-only, not in git**.
  Keep `.env.paper_status` private; never commit it.
- **Backtest verdict (2026-09-30, `data/GOLD_M5.csv`, 20,000 M5 bars ≈ Jun–Sep
  2026):** the first honest run (201 trades, PF 0.92, −$57.78, exits 29 TP /
  96 BE / 76 SL) turned out to be *flattered by two measurement bugs* — see
  `docs/strategy_iteration_2026-09-30.md`. Under the corrected measurement the
  old config is **reliably losing: 198 trades, −$270, PF 0.64, P(net>0)≈3%**.
  Strategy iteration (offline, one variable at a time) found the breakeven
  ratchet at 0.75R was the dominant problem; new defaults
  (`BE_TRIGGER_R=1.5`, `INDICATOR_WINDOW_BARS=1000`, per-bar spread in the
  backtester) give **174 trades, +$52.80, PF 1.06, max DD $99.62, WR 23.6%,
  exits 41 TP / 29 BE / 104 SL**, but the bootstrap CI is [−$314, +$452] and
  P(net>0)≈60% — **no validated edge yet; do NOT flip TRADING_MODE="LIVE".**
- **Live-path hardening (this branch, fake-bridge tested):** LiveLedger makes
  the daily loss / max-trades gates work in LIVE mode; filling mode is now
  auto-selected from `symbol_info.filling_mode` (FOK→IOC→RETURN fallback);
  margin pre-flight check + transient-fill retries; KILL_SWITCH file gate.
- **Server** (`scalping`), last **confirmed** deploy 2026-09-30 09:36 UTC to
  `4a21a33`; PR #6 (`40ec328`) should have auto-deployed from cron within
  15 min of the 10:19:58 UTC merge — **verify, do not assume** (§6).
  - `scalper-bot.service` is active in **FORWARD_TEST (paper)** mode; no real
    orders are sent.
  - **Confirmed on server:** `RSI_BUY_LEVEL=35`, `RSI_SELL_LEVEL=65`,
    `MAX_SPREAD_POINTS=80`. Server clock is UTC.
  - Pre-deploy trades-log tail showed repeated `SIGNAL` events with
    `signal: null`, not high-spread skips (baseline before RSI 35/65).
  - `scalper-dashboard.service` on port 8088 (reads files only).
  - MT5 container managed by `docker-compose.yml`, image
    `lprett-mt5linux-patched` (see §4), ports 18812/5901/8080,
    restart `unless-stopped`.
  - **Deploy:** `deploy.sh` pulls its configured branch and restarts the bot
    only when HEAD changes. **Cron confirmed as**
    `*/15 * * * * DEPLOY_BRANCH=main /root/scalper/deploy.sh` → `main` is the
    production branch and hands-off deploys are expected to work.
- **Strategy:** v7 closed-bar signals + one-shot per bar, session 07:00–17:00
  UTC, RSI 35/65, ATR 2.0 SL / 5.0 TP. **Changed 2026-09-30 (pending deploy):**
  `BE_TRIGGER_R` 0.75 → **1.5**, and the indicator window is now pinned to
  `INDICATOR_WINDOW_BARS = 1000` so the EMA200 is converged and the live path
  matches the backtester (it was 250 live vs 202 backtest, i.e. two different
  indicators). Active on the server until deployed: `4a21a33` (BE 0.75,
  250-bar window).
- **Paper book:** inspect on server with `python paper.py` after deploy.

## 2. Architecture

```
run.py (engine loop)
  └─ mt5_bridge.MT5Bridge ──RPyC :18812──► mt5server.exe (Wine) ──► MT5 terminal
  └─ strategy.ScalpStrategy (M5: EMA200 trend, RSI pullback, ATR filter, session filter, closed-bar)
  └─ paper.PaperAccount (FORWARD_TEST fills, ledger in logs/paper_account.json)
  └─ live_ledger.LiveLedger (LIVE only: polls deal history, records realized
     PnL so daily risk gates fire; state in logs/live_ledger.json)
  └─ kill switch: logs/KILL_SWITCH file disables new entries (see §6)
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
| 09-30 | **PR #6 merged to `main`** (merge commit `40ec328`, 10:19:58 UTC); deploy cron confirmed as `*/15 * * * * DEPLOY_BRANCH=main /root/scalper/deploy.sh` | Gate 1+2 live-path hardening + backtest fix are now the production branch; hands-off deploy should carry `main` to the server within 15 min. Server-side verification still outstanding (§6). |
| 09-30 | **Gate 1: live-path hardening** (`live_ledger.py` + `run.py` + `mt5_bridge.py`) | Previously `update_daily_pnl` was only called by paper.py, so in LIVE the daily-loss/max-trades gates could never fire (exits happen broker-side). LiveLedger polls `history_deals_get` for OUT deals (magic-matched), records profit+swap+commission via the same gates, dedup/persisted in `logs/live_ledger.json`. Also: filling mode auto-selected from `symbol_info.filling_mode` (was hard-coded IOC → `INVALID_FILL` risk on XM), pre-flight margin check, requote/price-off retries (3 attempts, fresh tick each), `logs/KILL_SWITCH` file disables new entries. All verified against the fake-bridge pattern (FOK/IOC/RETURN selection, retry, margin block, ledger dedup + restart persistence) |
| 09-30 | **Gate 2: backtester fixed** (`backtest.py`) — was feeding 201 bars into the strategy's 202-bar guard → zero signals ever | Window then 202 bars (`WINDOW_BARS`, keep in sync with strategy guard — superseded by the next row, now `config.INDICATOR_WINDOW_BARS`); entry fill moved to the signal bar's close (mirrors live closed-bar timing) and trades are managed from the next bar. First honest run on 20k M5 bars: 201 trades, PF 0.92, WR 14.4%, −$58, max DD $93 (exits 29 TP / 96 BE / 76 SL). |
| 09-30 | **Strategy iteration + measurement fixes** (offline, see `docs/strategy_iteration_2026-09-30.md`): `BE_TRIGGER_R` 0.75 → **1.5**; new `config.INDICATOR_WINDOW_BARS = 1000` shared by `strategy.py`, `MT5Bridge.get_rates` and `backtest.py`; backtester now prices the **per-bar spread from the data** (mean $0.47) instead of a flat $0.30; `research/strategy_sweep.py` added (verified to reproduce `backtest.py` exactly) | Two measurement bugs made the old numbers meaningless: (a) with `ewm(adjust=False)` on a 202/250-bar window the "EMA200" kept 13.5%/8.4% weight on its seed, so live and backtest were running *different* indicators, and every converged EMA length (30–300) loses — the filter has no edge; (b) the real spread is ~$0.47–0.51, not $0.30. Re-measured honestly the old config loses −$270 (PF 0.64, P(net>0)≈3%). One-variable sweeps show the 0.75R BE ratchet was the dominant killer (monotone 0.5R→off; 94/198 trades scratched at entry while 5R targets never survived); BE 1.5R is the conservative end of the plateau. Session 08–16 and H1-trend confirmation both made results *worse* (rejected); RSI 40/60 and TP changes were non-monotone noise (rejected). New config: +$52.80, PF 1.06, but P(net>0)≈60% → still no validated edge. |
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
- **2026-09-30 (11:30):** Strategy iteration session. Found and fixed two
  measurement bugs (warm-up-contaminated EMA200 → live≠backtest; spread
  assumption 40% too optimistic), re-measured the old config as reliably losing
  (−$270, PF 0.64), and changed `BE_TRIGGER_R` to 1.5 after monotone sweeps.
  Full analysis: `docs/strategy_iteration_2026-09-30.md`. Live flip still not
  justified: the new config's CI spans zero.
- **2026-09-30 (11:00):** PR #6 merged to `main` at 10:19:58 UTC (`40ec328`).
  Deploy cron confirmed as `*/15 * * * * DEPLOY_BRANCH=main
  /root/scalper/deploy.sh`; status cron confirmed as 01:15 UTC daily + 01:00
  UTC Mon–Fri running `/root/scalper/scripts/paper_status_daily.sh`
  (server-only file, double-run on weekdays). §5 "merge + deploy" TODO checked
  off; the post-deploy verification block in §6 replaced the "is the branch
  right?" question.
- **2026-09-30 (later):** Live-readiness audit found the daily risk gates were
  dead in LIVE mode and the backtester produced zero trades. Gate 1 (live-path
  hardening: LiveLedger, filling-mode selection, margin pre-flight, retries,
  kill switch) and Gate 2 (backtest window/entry fix) implemented on
  `arena/01a0f1c8-scalper`, fake-bridge tested. First honest backtest: PF 0.92,
  −$58 over ~70 days — strategy needs offline work before any live flip.

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
- [x] Verify the server deploy cron targets the intended branch — **done
  2026-09-30**: `*/15 * * * * DEPLOY_BRANCH=main /root/scalper/deploy.sh`.
  `main` is the production target. (`deploy.sh`'s bare default still names the
  old `arena/01a0a475-scalper` branch, but the cron passes `DEPLOY_BRANCH=main`
  explicitly; consider changing the script default to `main` anyway.)
- [ ] Restore or re-apply stashed `paper_status_daily.sh` edits from
  `/root/paper_status_daily.sh.backup` if still wanted. Status cron is
  confirmed (01:15 UTC daily + 01:00 UTC Mon–Fri, server-only
  `/root/scalper/scripts/paper_status_daily.sh`); double-run on weekdays may be
  intentional or a leftover — decide and clean up. Keep `.env.paper_status`
  private — never commit it.
- [ ] Paper-test RSI 35/65 (deployed 09:36 UTC as `4a21a33`); compare with the
  30/70 baseline using trade count, net expectancy after spread, drawdown,
  and session coverage.
- [ ] Add signal skip-reason diagnostics: current `SIGNAL: null` entries do not
  distinguish session, ATR, EMA, or RSI conditions.
- [x] Fix backtest input-length mismatch — **done 09-30 on
  `arena/01a0f1c8-scalper`** (`WINDOW_BARS=202`, entry at signal-bar close,
  manage from next bar). First results: PF 0.92 / −$58 over ~70 days — later
  shown to be flattered by measurement bugs; see the 2026-09-30 strategy
  iteration row in §3 and `docs/strategy_iteration_2026-09-30.md`.
- [x] **Merge the Gate 1+2 PR** — PR #6 merged to `main` 2026-09-30 10:19:58 UTC
  (`40ec328`).
- [ ] **Confirm the deploy actually landed on the server** (may already have via
  the 15-min cron — must be run on `scalping`; the 2026-09-30 11:00 UTC session
  had no SSH access): run the §6 "Post-PR#6 verification" block —
  `git log -1` shows `40ec328`, `live_ledger.py` present,
  `journalctl -u scalper-bot` banner shows the new HEAD, and
  `mt5env/bin/python backtest.py` prints **201 trades** (not 0). Also confirm
  `logs/live_ledger.json` stays absent/empty in FORWARD_TEST.
- [~] **Strategy work (blocking for LIVE):** first iteration done 2026-09-30
  (`docs/strategy_iteration_2026-09-30.md`). Tested one variable at a time:
  **BE trigger → 1.5R (adopted)**, ATR multiples (only monotone via wider SL,
  never positive alone — not adopted), **session 08–16 UTC (rejected: worse)**,
  **H1 trend confirmation (rejected: clearly worse)**, RSI 40/60 (rejected:
  non-monotone), TP multiples (rejected: noise). Also fixed the indicator
  warm-up and the spread assumption. **Still open:** the new config is only
  *not reliably losing* (P(net>0)≈60%) — no validated edge. Next: re-test the
  BE ladder on more data/another regime, model slippage + swap, and compare
  backtest vs paper book trade-by-trade. Remaining untested candidates: Friday
  cutoff, tighter ATR/volatility filters, exit-time limit.
- [ ] Judge the paper book after 100+ trades across sessions **and** a
  profitable backtest over ≥6 months; only then flip
  `TRADING_MODE = "LIVE"` in `config.py` (+ restart service). Pre-agreed
  launch criteria: expectancy > 0 after spread, PF > ~1.2, max DD affordable.
- [ ] Live-mode verification on first LIVE run: confirm `LIVE_EXIT` events
  land in `logs/trades.jsonl` when broker-side SL/TP fill, daily stats update,
  and the loss gate actually halts entries; test the KILL_SWITCH file.
- [ ] Wire `MAX_CONSECUTIVE_LOSSES` (defined in config.py, currently unused).
- [ ] Backtester realism: model slippage (paper fills are zero-slippage ticks),
  add swap for overnight holds, and compare backtest vs paper book trade-by-trade.
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

# kill switch (disable NEW entries only; open positions keep broker SL/TP)
touch /root/scalper/logs/KILL_SWITCH      # stop new entries (logged once)
rm    /root/scalper/logs/KILL_SWITCH      # resume

# backtest (needs data/GOLD_M5.csv; run from repo root)
mt5env/bin/python backtest.py

# strategy iteration: fast sweeps, verified against backtest.py
#   --warmup defaults to config.INDICATOR_WINDOW_BARS; --sweep names:
#   warmup|ema|be|sl|tp|session|rsi|h1|spread|honest|combo
mt5env/bin/python research/parity_test.py                      # live vs backtest signals (2s)
mt5env/bin/python research/strategy_sweep.py --verify          # equivalence check (do this first)
mt5env/bin/python research/strategy_sweep.py --sweep be
mt5env/bin/python research/strategy_sweep.py --detail --set be_trigger_r=1.5
mt5env/bin/python research/strategy_sweep.py --bootstrap 5000 --set be_trigger_r=1.5

# one-shot deploy (choose the intended production branch explicitly)
cd /root/scalper && DEPLOY_BRANCH=main ./deploy.sh

# --- Post-PR#6 verification (run on the server; PR #6 = 40ec328, merged 10:19 UTC) ---
cd /root/scalper
git log -1 --format='%h %cI %s'          # expect 40ec328 + "Gate 1+2: live-path hardening ..."
ls -l live_ledger.py                     # must exist (Gate 1)
grep -c LiveLedger run.py                # >0
journalctl -u scalper-bot -n 30 --no-pager   # startup banner should reference the new HEAD
grep -i 'deploy\|restarted' logs/deploy.log | tail -5   # cron should show a 40ec328 restart
mt5env/bin/python backtest.py            # smoke test: expect Total Trades: 174, PF 1.06, +$52.80
                                         # (0 trades before Gate 2; 201/0.92 on the old defaults;
                                         #  output now prints spread source, window and TP/BE/SL exits)
ls -l logs/live_ledger.json              # should be absent/empty in FORWARD_TEST

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
| `Insufficient free margin ... order not sent` | margin pre-flight blocked the LIVE order (see `mt5_bridge._margin_ok`) |
| `Transient fill failure retcode=... retrying` | requote/price-moved during LIVE entry; retried with a fresh tick |
| `KILL_SWITCH detected` | `logs/KILL_SWITCH` exists → new entries disabled; remove file to resume |
| `Live close detection: history_deals_get failed` | deal-history read hiccup in LIVE; next poll retries (no PnL lost) |

## 8. Session protocol

1. Day-to-day strategy work on the session Arena branch (currently
   `arena/01a0f1c8-scalper`); promote to `main` via PR, rebasing onto current
   `main` when history diverges (squash merges).
2. Test engine changes against the fake RPyC server pattern (venv with
   `rpyc pandas numpy`, a fake `MetaTrader5` module exposing
   `initialize/symbol_select/symbol_info_tick/copy_rates_from_pos` returning a
   real structured numpy array, `ThreadedServer(SlaveService, port=18812)`).
   For order/close logic, a lightweight in-process fake is enough (no server):
   a fake `mt5` object with `symbol_info/symbol_info_tick/account_info/
   order_calc_margin/order_send/history_deals_get` + `DEAL_ENTRY_*`,
   `ORDER_FILLING_*`, `TRADE_RETCODE_*` constants — see the 2026-09-30 Gate 1
   verification. LiveLedger/open_trade take the bridge as an argument so they
   are directly testable this way.
3. Update §1, §3, §5 here; add long-form analysis to `docs/` if needed.
