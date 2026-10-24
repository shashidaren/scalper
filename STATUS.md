# STATUS — read this first

Current truth only. History lives in `docs/archive/` and the dated notes in `docs/`.
A session may edit this file and add one changelog row. Do not paste a new status essay on top.

Last verified on `scalping`: 2026-10-19 17:31 UTC (user-supplied box output: 17:30 timer run completed cleanly).

## Gold

- Production book. Engine is the repo root (`run.py` + `config.py`). Dashboard `:8088`. Unit `scalper-bot`.
- `TRADING_MODE` stays `FORWARD_TEST` until an explicit live decision. Kill switch is `logs/KILL_SWITCH` (blocks new entries only).
- Paper track record (2026-10-19 16:37 UTC, `logs/paper_account.json`): balance **`$237.98`** (book started $300 on 2026-10-04), **47 closed, 10 wins / 37 losses**. Previous snapshot 2026-10-12: `$249.70`, 21 closed, 4W/17L. A Gold-only live flip is not justified; shared-account rule still applies.
- **Effectiveness plan CLOSED 2026-10-24** (`docs/effectiveness_plan_2026-10-24.md`). Fresh `GOLD_M5.csv` (2026-07-15 → 2026-10-23, 20k bars): current config **257 trades / +$29.15 / PF 1.02 / avg R 0.03 / max DD $255**. Sep and Oct both negative. TP 6.0 **rejected** (OOS −$181). ATR floor 3.0/3.5 not adopted (OOS still negative). Walk-forward adopted 1/4 folds. **No strategy parameter changed.** Edge has degraded vs the old spent-file reference (255 / +$456 / PF 1.32).
- **New research plan locked 2026-10-24**: `docs/research_plan_vol_regime_2026-10-24.md` (VOL-REGIME-A). ATR percentile regime filter is now coded (`ATR_REGIME_ENABLED=False` by default). Paper book behaviour is unchanged. Next step is a fresh data pull + the pre-registered 36-combination sweep.
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
- 2026-10-24: local `WEEKEND_FLAT_ENABLED = False` committed for BTC (24/7; gold's Friday rule does not transfer).

## Do not

- Do not raise `MAX_SPREAD_POINTS` again, or change `TRADING_MODE`, `BTC_STRATEGY`, or the service units, without a new cold-OOS pass. 6,250 is the observation gate, not a strategy approval.
- Do **not** adopt the 2026-10-24 candidates (`ATR_MIN`, `TP_ATR_MULT=6`, session 08–20) — they failed or did not clear OOS on the fresh pull.
- Do **not** enable `ATR_REGIME_ENABLED` until the pre-registered VOL-REGIME-A gate is cleared.
- Treat proxy or exchange CSVs as BTC evidence. The gate reads XM bars only.
- Flip either book to `LIVE` on the shared XM account. A separate account or a hard combined risk gate is required first.
- Re-pull or reuse the inspected 2026-07-25..2026-10-03 BTC M5 window for a new gate.
- Re-rank on `data/BTCUSD_H1.csv` (sha256 `f7305461…ab21`, 2024-06-25..2026-10-07). That file is now inspected.
- Re-tune the same RSI-pullback / EMA200 shape on overlapping Gold data without a new pre-registered hypothesis.

## Server

- Timer active + enabled; autosync service disabled, no `[Install]` or boot symlink. 17:00:14 run exited 0/SUCCESS, digest `0 fail, 0 warn`, deploy none. 17:15 skipped after an interrupted manual run; both lock probes were free at 17:29:15. The next timer tick completed at 17:30:23 with push OK, deploy none, `0 fail, 0 warn`, both books fresh (0 min), digest written, and service exit 0/SUCCESS; next tick scheduled 17:45. No repeated skip. Dashboard already restarted after the config change; all five tools executable.

- Crontab (verified 2026-10-19 17:08 UTC): `CRON_TZ=UTC`, `PATH`, `MAILTO`, and one paper-status line at `7 1 * * *`. The old `*/15 … deploy.sh` line is gone; `scalper-autosync.timer` is the only deploy trigger. Copy: `docs/ops/README.md`.
- Live paper-status script is `/root/ops/paper_status_daily.sh` (105 lines, copied from `docs/ops/`). Token file is `/root/ops/.env.paper_status` and is not in git.
- Latest published gold paper snapshot (`status/paper`, 2026-10-12 01:07 UTC): balance `$249.70`, 21 closed, 4 wins / 17 losses. Earlier 2026-10-07 snapshot was `$277.99`, 13 closed, 3W/10L. That branch is a snapshot, not `main`.
- 2026-10-07 21:53 UTC deploy of `d44528b` logged `restart skipped` for `scalper-bot`.

## Open

- **VOL-REGIME-A** is the active Gold research track (`docs/research_plan_vol_regime_2026-10-24.md`). Code is in place (default OFF). Next: fresh data pull + 36-combination sweep under the pre-registered protocol.
- Effectiveness parameter pass is **done** — no config change.
- Rotate the MT5 and VNC passwords (they were pasted in plain text; change at the broker, update `.env`).
- Re-apply the two mt5linux image patches if the container is ever recreated from stock `lprett/mt5linux`. Details: `docs/archive/HANDOFF_2026-10-07.md` §4.
- File the two upstream mt5linux bugs (fifo `mkfifo` crash, `config.sh` `return` under `set -e`).
- A new BTC hypothesis needs its own pre-registered rule and a fresh pull. Phase 1 and Phase 1c are both closed.
- Gold paper book continues under current geometry; LIVE remains no-go until a powered positive gate and the demo execution drill.
- Risk controls shipped 2026-10-23 (`docs/risk_controls_2026-10-23.md`): Friday 20:00 UTC weekend flat is now ON in both books (BTC explicitly off), the hold cap stays off, equity floor latched at 50%. No useful equity floor at $300 — minimum live balance ~$1,000 for a 20–25% floor.
- LIVE stop + BE (`live_position.py`) only tested against a fake terminal. Demo drill before real money: `docs/live_readiness_review_2026-10-23.md` §6.3.

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
| 2026-10-19 | Recorded completed raw-log untrack and PR #32 merge (59620a0), timer-only scheduling and 17:00 and 17:30 clean timer verification (17:30:23 completion, push OK, fresh books, digest, exit 0/SUCCESS). Hardened read-only status against skipped ticks, bounded autosync network operations, gated shell deploys, and pre-parsed autosync against self-replacement. |
| 2026-10-23 | Time-based exits + equity floor (`risk_guard.py`, measured by `research/risk_measure.py`). Weekend flat ON for paper and LIVE (Friday 20:00 UTC → Monday 00:00): cost +$5.46 over 255 trades (9 held, 6 losses avoided), against gap risk up to 12.2×ATR that the backtest cannot model. `MAX_HOLD_MINUTES` stays 0 (4h −$31 … 12h +$115, non-monotone = noise) but now applies to LIVE as well as paper. Equity floor latched at 50% of start: every 10–30% floor halted the paper book before it recovered (20% → $232.94 vs $294.35). New `WEEKEND` exit reason counts in the win/loss tally (TIME stays neutral) — `check_data` verified green on a synthetic ledger. 109 new checks (58 risk-guard + 10 live-guard clock cases + wiring); smoke 16/16. |
| 2026-10-23 | LIVE position protection implemented: `live_position.py` (post-fill stop verification/repair, BE ratchet via `TRADE_ACTION_SLTP`), plus `mt5_bridge.positions_get/modify_position_stops/close_position`. LIVE-only — `enabled` returns False outside `TRADING_MODE=LIVE` and the guard is constructed only in the LIVE branch (AST-tested), so the paper book is unchanged: backtest still 255/+$456.58/PF 1.32, parity PASS, smoke 15/15. Tests: `tests/test_live_position_guards.py` (79) + `tests/test_mt5_bridge_sltp.py` (26). Doc: `docs/live_protection_2026-10-23.md`. §4.3/§4.4 still open. |
| 2026-10-23 | Live-readiness review: **no-go** for LIVE, docs only, no runtime change (`docs/live_readiness_review_2026-10-23.md`). Reproduced backtest 255/+$456.58/PF 1.32, `--verify` parity, 6/6 suites, smoke 13/13. Paper book 2026-10-04..10-23: 60 closed, `$294.35`, 15W/45L, PF 0.978, max DD `$103.95` (34.6%). New: the "100+ trades, PF>1.2" launch gate has only ~2:1 discrimination — a real 0.11R edge fails it 54% of the time, a zero-edge book passes it 21% of the time (~330 trades needed for 80% power). Three blockers the paper book cannot close: BE ratchet and time stop are paper-only (`paper.py:280`, no `TRADE_ACTION_SLTP` anywhere), no post-fill check that the live position has a stop, and no weekend/hold cap with a 59h hold already on the record. Also: `ATR_MIN=0.50` has never gated a signal (data min 1.22) while the bottom ATR quartile is the only losing bucket. |
| 2026-10-24 | Effectiveness plan agreed (`docs/effectiveness_plan_2026-10-24.md`). Pre-registered ATR floor / TP 6.0 / combo for fresh-data test only. |
| 2026-10-24 | Fresh pull + candidates + full backtest/loss anatomy on box. Window 2026-07-15..10-23: **257 / +$29 / PF 1.02**. TP 6.0 rejected (OOS −$181). ATR floor not adopted. Plan **closed** — no strategy parameter change. HANDOFF/STATUS updated. |
| 2026-10-24 | **VOL-REGIME-A** pre-registered (`docs/research_plan_vol_regime_2026-10-24.md`). Code landed: `ATR_REGIME_ENABLED=False` + percentile gate in `strategy.py`. Paper book behaviour unchanged. |
