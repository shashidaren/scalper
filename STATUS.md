# STATUS — read this first

Current truth only. History lives in `docs/archive/` and the dated notes in `docs/`.
A session may edit this file and add one changelog row. Do not paste a new status essay on top.

Last consolidated: 2026-10-07. No trading parameter, config value, or service unit was changed in that consolidation.

## Gold

- Production book. Engine is the repo root (`run.py` + `config.py`). Dashboard `:8088`. Unit `scalper-bot`.
- `TRADING_MODE` stays `FORWARD_TEST` until an explicit live decision. Kill switch is `logs/KILL_SWITCH` (blocks new entries only).
- Deploy freeze is explained and closed. A dirty tracked `docker-compose.yml` froze every 15-minute deploy from 2026-10-04 12:30 to 2026-10-07 02:28 UTC (~63 h). The process ran `a122e7a`-era code, so PRs #22/#23/#24 were on disk but not in memory, and `logs/live_status.json` had no `spread_gate` field. Server HEAD after the fix was `b033986` with a clean tree (user-verified 2026-10-07). `deploy.sh` now logs `DIRTY TREE` and `PULL FAILED` and exits 1 without restarting.
- This repo's cron pulls `main` and restarts a unit only if a runtime path changed. `docs/`, `research/`, `tests/`, `*.md`, and `deploy.sh` do not restart the book.

## BTC

- Instance dir `btc/`. Same engine, `btc/config.py` swapped in via `btc/_instance.py`. Dashboard `:8089`. Units `scalper-btc-bot` and `scalper-btc-dashboard`.
- User-verified 2026-10-07: both units are **enabled and active**, `:8089` listening. Older notes that say disabled/inactive are stale.
- `TRADING_MODE="FORWARD_TEST"`. `MAX_SPREAD_POINTS=1500` is still the placeholder. XM BTCUSD mean spread is about 4,242 points, so the gate vetoes 100% of quotes and the bot takes 0 trades. That is the correct output. Do not raise the gate to make it trade.
- Phase 1 (M5 pullback) is a **FAIL / no-go** on real XM bars (2026-10-03): cold OOS about −$46, PF 0.75. Write-up: `docs/btc_phase1_result_2026-10-03.md`.
- Phase 1c (Donchian on untouched H1) is **BLOCKED, not failed**. The collect has not been run. One command, on `scalping` only: `bash docs/collect-2026-10-07/collect_phase1c.sh`. Paste `/root/ops/collect-2026-10-07/collection.md` back. Fail rule: net ≤ 0, PF < 1.2, n < 60, or g ≤ c. A pass still needs an explicit user decision before any config change.

## Do not

- Change `MAX_SPREAD_POINTS`, `TRADING_MODE`, `BTC_STRATEGY`, or the service units from a docs session.
- Treat proxy or exchange CSVs as BTC evidence. The gate reads XM bars only.
- Flip either book to `LIVE` on the shared XM account. A separate account or a hard combined risk gate is required first.
- Re-pull or reuse the inspected 2026-07-25..2026-10-03 BTC M5 window for a new gate.

## Open

- Run the Phase 1c collect on `scalping` and paste `collection.md` back.
- Rotate the MT5 and VNC passwords (they were pasted in plain text; change at the broker, update `.env`).
- Move `paper_status_daily.sh` and its env file out of the deployed tree to `/root/ops/`. Drop the duplicate weekday cron. See `docs/cron_review_2026-10-07.md`.
- Re-apply the two mt5linux image patches if the container is ever recreated from stock `lprett/mt5linux`. Details: `docs/archive/HANDOFF_2026-10-07.md` §4.
- File the two upstream mt5linux bugs (fifo `mkfifo` crash, `config.sh` `return` under `set -e`).

## Changelog

| Date | What |
|---|---|
| 2026-10-07 | Docs consolidated. Full handoffs moved to `docs/archive/`. No runtime path changed. |
