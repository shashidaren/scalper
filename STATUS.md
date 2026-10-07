# STATUS — read this first

Current truth only. History lives in `docs/archive/` and the dated notes in `docs/`.
A session may edit this file and add one changelog row. Do not paste a new status essay on top.

Last verified on `scalping`: 2026-10-07 21:57 UTC. Docs-only commits do not restart the book.

## Gold

- Production book. Engine is the repo root (`run.py` + `config.py`). Dashboard `:8088`. Unit `scalper-bot`.
- `TRADING_MODE` stays `FORWARD_TEST` until an explicit live decision. Kill switch is `logs/KILL_SWITCH` (blocks new entries only).
- Deploy freeze is explained and closed. A dirty tracked `docker-compose.yml` froze every 15-minute deploy from 2026-10-04 12:30 to 2026-10-07 02:28 UTC (~63 h). The process ran `a122e7a`-era code, so PRs #22/#23/#24 were on disk but not in memory, and `logs/live_status.json` had no `spread_gate` field. Server HEAD after the fix was `b033986` with a clean tree (user-verified 2026-10-07). `deploy.sh` now logs `DIRTY TREE` and `PULL FAILED` and exits 1 without restarting.
- This repo's cron pulls `main` and restarts a unit only if a runtime path changed. `docs/`, `research/`, `tests/`, `*.md`, and `deploy.sh` do not restart the book.

## BTC

- Instance dir `btc/`. Same engine, `btc/config.py` swapped in via `btc/_instance.py`. Dashboard `:8089`. Units `scalper-btc-bot` and `scalper-btc-dashboard`.
- User-verified 2026-10-07 21:39 UTC: all three units `active`, tree clean, `spread_gate` in the running process is `6250` (13/13 quotes passed, spread 4000, state `ok`). The 1,500 placeholder is no longer what the process is enforcing.
- `TRADING_MODE="FORWARD_TEST"`. `MAX_SPREAD_POINTS=6250` is the recorded 1.25× TRAIN p90 rule. Paper observation only. Phase 1 is still a fail, so a paper fill is not a go-live.
- Phase 1 (M5 pullback) is a **FAIL / no-go** on real XM bars (2026-10-03): cold OOS about −$46, PF 0.75. Write-up: `docs/btc_phase1_result_2026-10-03.md`.
- Phase 1c (Donchian on untouched H1) is **BLOCKED, not failed**. The collect has not been run. One command, on `scalping` only: `bash docs/collect-2026-10-07/collect_phase1c.sh`. Paste `/root/ops/collect-2026-10-07/collection.md` back. Fail rule: net ≤ 0, PF < 1.2, n < 60, or g ≤ c. A pass still needs an explicit user decision before any config change.

## Do not

- Do not raise `MAX_SPREAD_POINTS` again, or change `TRADING_MODE`, `BTC_STRATEGY`, or the service units, without a new cold-OOS pass. 6,250 is the observation gate, not a strategy approval.
- Treat proxy or exchange CSVs as BTC evidence. The gate reads XM bars only.
- Flip either book to `LIVE` on the shared XM account. A separate account or a hard combined risk gate is required first.
- Re-pull or reuse the inspected 2026-07-25..2026-10-03 BTC M5 window for a new gate.

## Server

- Crontab installed 2026-10-08: `CRON_TZ=UTC`, deploy every 15 minutes, one paper-status line at `7 1 * * *`. The weekday duplicate is gone. Copy: `docs/ops/README.md`.
- Live paper-status script is `/root/ops/paper_status_daily.sh` (105 lines, copied from `docs/ops/`). Token file is `/root/ops/.env.paper_status` and is not in git.
- 2026-10-07 21:57 UTC run wrote and published the gold ledger to `status/paper`: balance `$277.99`, 13 closed, 3 wins / 10 losses, SELL open from 17:30 UTC at 4113.46. That branch is a snapshot, not `main`.
- 2026-10-07 21:53 UTC deploy of `d44528b` logged `restart skipped` for `scalper-bot`.

## Open

- Run the Phase 1c collect on `scalping` and paste `collection.md` back.
- Rotate the MT5 and VNC passwords (they were pasted in plain text; change at the broker, update `.env`).
- Re-apply the two mt5linux image patches if the container is ever recreated from stock `lprett/mt5linux`. Details: `docs/archive/HANDOFF_2026-10-07.md` §4.
- File the two upstream mt5linux bugs (fifo `mkfifo` crash, `config.sh` `return` under `set -e`).

## Changelog

| Date | What |
|---|---|
| 2026-10-07 | Docs consolidated. Full handoffs moved to `docs/archive/`. No runtime path changed. |
| 2026-10-07 | BTC `MAX_SPREAD_POINTS` 1500 → 6250 (1.25× measured TRAIN p90). Paper observation only. Phase 1 still FAIL. |
| 2026-10-08 | `deploy.sh` restarts an already-active BTC unit when its runtime path changes. A stopped unit is still not started. The 6250 gate still needs one manual `systemctl restart scalper-btc-bot` if that unit was not restarted after PR #27. |
| 2026-10-08 | Paper-status script backed up at `docs/ops/paper_status_daily.sh`. Live copy is `/root/ops/`. Token file stays off git. |
| 2026-10-08 | Server verified: crontab installed, BTC gate 6250 passing 4000-pt quotes, paper status published (`$277.99`, 13 closed, 3W/10L). |
