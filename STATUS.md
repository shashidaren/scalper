# STATUS — read this first

Current truth only. History lives in `docs/archive/` and the dated notes in `docs/`.
A session may edit this file and add one changelog row. Do not paste a new status essay on top.

Last verified on `scalping`: 2026-10-19 17:2x UTC (user-reported box verification; 17:30 tick still needs confirmation).

## Gold

- Production book. Engine is the repo root (`run.py` + `config.py`). Dashboard `:8088`. Unit `scalper-bot`.
- `TRADING_MODE` stays `FORWARD_TEST` until an explicit live decision. Kill switch is `logs/KILL_SWITCH` (blocks new entries only).
- Paper track record (2026-10-19 16:37 UTC, `logs/paper_account.json`): balance **`$237.98`** (book started $300 on 2026-10-04), **47 closed, 10 wins / 37 losses**. Previous snapshot 2026-10-12: `$249.70`, 21 closed, 4W/17L. Still far short of the stated launch criteria (~100+ paper trades under the current config, sustained PF > ~1.2, affordable max DD — see `docs/strategy_iteration_2026-10-01.md`). A Gold-only live flip is not yet justified; the shared-account rule also still applies.
- Deploy freeze is explained and closed. A dirty tracked `docker-compose.yml` froze every 15-minute deploy from 2026-10-04 12:30 to 2026-10-07 02:28 UTC (~63 h). The process ran `a122e7a`-era code, so PRs #22/#23/#24 were on disk but not in memory, and `logs/live_status.json` had no `spread_gate` field. Server HEAD after the fix was `b033986` with a clean tree (user-verified 2026-10-07). `deploy.sh` now logs `DIRTY TREE` and `PULL FAILED` and exits 1 without restarting.
- The 15-minute autosync pulls `main` and restarts a unit only if a runtime path changed. `docs/`, `research/`, `tests/`, `*.md`, `tools/`, and `deploy.sh` do not restart the book.
- **Autosync is live** (`tools/autosync.sh` on `scalper-autosync.timer`, every 15 min; first manual run 16:36 UTC, first timer run 2026-10-19 17:00:14 UTC, service exit 0). It publishes `logs/ledger.jsonl` + the state files as `data collection N`. The crontab has **no** `deploy.sh`/`autosync.sh` line — the timer is the only scheduler. The raw `logs/trades.jsonl` (SIGNAL/SKIP telemetry, ~11.5k rows/day) is local-only; untracking is DONE (840ceca, merged with PR #32 / 4184046 into 59620a0). Both raw logs remain on disk and growing, with backups in `/root/scalper-eventlog/*-2026-10-19.jsonl`. Only the six publish files are tracked under `logs/` and `btc/logs/`.
- The first run reported `integrity: 2 fail`. That was a **false positive** in `tools/check_data.py` (it chained the balance across the 2026-10-04 `paper.py --reset`). Fixed 2026-10-20; the check now chains only the current book. The books were healthy. The 17:00 UTC run reports `0 fail, 0 warn`.

## BTC

- Paper book 2026-10-19 16:37 UTC: balance `$295.90`, 85 closed (19W/66L). Phase 1 and 1c remain FAIL; nothing here changes that.

- Instance dir `btc/`. Same engine, `btc/config.py` swapped in via `btc/_instance.py`. Dashboard `:8089`. Units `scalper-btc-bot` and `scalper-btc-dashboard`.
- User-verified 2026-10-07 21:39 UTC: all three units `active`, tree clean, `spread_gate` in the running process is `6250` (13/13 quotes passed, spread 4000, state `ok`). The 1,500 placeholder is no longer what the process is enforcing.
- `TRADING_MODE="FORWARD_TEST"`. `MAX_SPREAD_POINTS=6250` is the recorded 1.25× TRAIN p90 rule. Paper observation only. Phase 1 is still a fail, so a paper fill is not a go-live.
- Phase 1 (M5 pullback) is a **FAIL / no-go** on real XM bars (2026-10-03): cold OOS about −$46, PF 0.75. Write-up: `docs/btc_phase1_result_2026-10-03.md`.
- Phase 1c (Donchian on untouched H1) is a **FAIL / no-go**, not blocked. Collected 2026-10-07 02:55 UTC. Train-selected winner cold OOS `n=96`, −$40.03, PF 0.96. Baseline +$129.23 / PF 1.18 also fails (PF < 1.2, CI includes 0). Write-up: `docs/btc_phase1c_result_2026-10-07.md`. Do not set `BTC_STRATEGY=donchian`. Do not retune `data/BTCUSD_H1.csv`.

## Do not

- Do not raise `MAX_SPREAD_POINTS` again, or change `TRADING_MODE`, `BTC_STRATEGY`, or the service units, without a new cold-OOS pass. 6,250 is the observation gate, not a strategy approval.
- Treat proxy or exchange CSVs as BTC evidence. The gate reads XM bars only.
- Flip either book to `LIVE` on the shared XM account. A separate account or a hard combined risk gate is required first.
- Re-pull or reuse the inspected 2026-07-25..2026-10-03 BTC M5 window for a new gate.
- Re-rank on `data/BTCUSD_H1.csv` (sha256 `f7305461…ab21`, 2024-06-25..2026-10-07). That file is now inspected.

## Server

- Timer active + enabled; autosync service disabled, no `[Install]` or boot symlink. 17:00:14 run exited 0/SUCCESS, digest `0 fail, 0 warn`, deploy none. 17:15 skipped after an interrupted manual run; user reports both locks free and no merge/rebase at 17:2x. Confirm 17:30 completion before rollout; investigate a repeated skip first. Dashboard already restarted after the config change; all five tools executable.

- Crontab (verified 2026-10-19 17:08 UTC): `CRON_TZ=UTC`, `PATH`, `MAILTO`, and one paper-status line at `7 1 * * *`. The old `*/15 … deploy.sh` line is gone; `scalper-autosync.timer` is the only deploy trigger. Copy: `docs/ops/README.md`.
- Live paper-status script is `/root/ops/paper_status_daily.sh` (105 lines, copied from `docs/ops/`). Token file is `/root/ops/.env.paper_status` and is not in git.
- Latest published gold paper snapshot (`status/paper`, 2026-10-12 01:07 UTC): balance `$249.70`, 21 closed, 4 wins / 17 losses. Earlier 2026-10-07 snapshot was `$277.99`, 13 closed, 3W/10L. That branch is a snapshot, not `main`.
- 2026-10-07 21:53 UTC deploy of `d44528b` logged `restart skipped` for `scalper-bot`.

## Open

- Rotate the MT5 and VNC passwords (they were pasted in plain text; change at the broker, update `.env`).
- Re-apply the two mt5linux image patches if the container is ever recreated from stock `lprett/mt5linux`. Details: `docs/archive/HANDOFF_2026-10-07.md` §4.
- File the two upstream mt5linux bugs (fifo `mkfifo` crash, `config.sh` `return` under `set -e`).
- A new BTC hypothesis needs its own pre-registered rule and a fresh pull. Phase 1 and Phase 1c are both closed.
- Gold paper book needs substantially more track record (target ~100+ trades, PF > ~1.2 sustained) before any live decision. Shared-account constraint still applies even for Gold-only.

## Changelog

| Date | What |
|---|---|
| 2026-10-07 | Docs consolidated. Full handoffs moved to `docs/archive/`. No runtime path changed. |
| 2026-10-07 | BTC `MAX_SPREAD_POINTS` 1500 → 6250 (1.25× measured TRAIN p90). Paper observation only. Phase 1 still FAIL. |
| 2026-10-08 | `deploy.sh` restarts an already-active BTC unit when its runtime path changes. A stopped unit is still not started. The 6250 gate still needs one manual `systemctl restart scalper-btc-bot` if that unit was not restarted after PR #27. |
| 2026-10-08 | Paper-status script backed up at `docs/ops/paper_status_daily.sh`. Live copy is `/root/ops/`. Token file stays off git. |
| 2026-10-08 | Server verified: crontab installed, BTC gate 6250 passing 4000-pt quotes, paper status published (`$277.99`, 13 closed, 3W/10L). |
| 2026-10-10 | Phase 1c Donchian H1 gate recorded FAIL (`docs/btc_phase1c_result_2026-10-07.md`). Docs only. |
| 2026-10-12 | Recorded Gold paper snapshot (`$249.70`, 21 closed, 4W/17L) and that it does not yet meet launch criteria for live (even Gold-only). Shared-account rule unchanged. Docs only. |
| 2026-10-19 | Autosync went live on the box: first `data collection` commits, smoke gate green, deploy path unchanged. `integrity: 2 fail` was a `check_data.py` false positive across the 2026-10-04 reset (fixed 10-20). Raw event log replaced by `ledger.jsonl` in the publish set. Docs: `docs/autosync_first_run_2026-10-19.md`. |
| 2026-10-19 | Timer verified end-to-end: 17:00:14 run, service exit 0, `data collection 4` pushed, digest `0 fail`/`0 warn`, both books fresh, `deploy: none`. `--status` was never implemented (the argument started a full run) — added a read-only one; `--help` no longer leaks the script body. Removed the stray `autosync-fix-2026-10-20.patch` and ignored `*.patch`. `scalper-autosync.service` is boot-enabled; disable it (timer only). Dashboard was already restarted after the 10-19 `config.py` change (17:00:27 > 16:32:06). |
| 2026-10-20 | Ported the operational half of `gold-trading-bot`: `tools/autosync.sh` (data publish + smoke gate + rollback + digest), `tools/smoke_test.py`, `tools/check_data.py`, `tools/repair_phantom_ledger.py`, paper geometry guards + atomic state save, LIVE-only %-risk sizing (`RISK_PCT=0`), optional `MAX_HOLD_MINUTES=0` time stop. No strategy parameter changed; paper behaviour identical by default. Assessment: `docs/port_assessment_2026-10-20.md`. Cron not switched yet. |
| 2026-10-19 | Recorded completed raw-log untrack and PR #32 merge (59620a0), timer-only scheduling and 17:00 clean verification; 17:30 verification pending. Hardened read-only status against skipped ticks, bounded autosync network operations, gated shell deploys, and pre-parsed autosync against self-replacement. |
