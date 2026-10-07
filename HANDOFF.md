# HANDOFF — Gold Scalper (live engine + paper mode)

Read this first in a new session. **Keep it honest:** any session that changes
code, parameters, or the server must update §1 (state), §3 (changelog) and
§5 (TODOs) before it ends, and push its commits.

---

## 1. Where things stand (as of 2026-10-07)

> **Update (2026-10-07, branch `arena/87d768e3-scalper`): cron review — three
> findings accepted, `deploy.sh` hardened; no trading parameter touched.**
> - **Review written up: `docs/cron_review_2026-10-07.md`.** Verdicts on the
>   three recorded cron lines: keep `*/15 … DEPLOY_BRANCH=main` (`main` is the
>   production target); keep the daily `15 1 * * *` paper-status line but move
>   it off the quarter-hour (`7 1`) so it cannot read the book mid-restart;
>   **drop `0 1 * * 1-5`** — on weekdays it ran the identical script 15 minutes
>   after the daily line (the §5 "double-run on weekdays" TODO). The recommended
>   paste-ready crontab adds `SHELL`/`PATH`/`MAILTO`/`CRON_TZ=UTC`, a
>   `mkdir -p /root/scalper/logs &&` prefix (the shell opens the redirect
>   *before* `deploy.sh` can create `logs/`), and a `test -x` guard on the
>   server-only status script.
> - **`deploy.sh` changed — the two real defects.** (1) It restarted
>   `scalper-bot` on **any** commit, including the BTC-only/docs-only commits
>   that dominate (`#22`, `#23`, …). A restart re-arms state that exists only in
>   memory: `strategy._last_fired_bar_ts` (the one-shot-per-bar guard,
>   `strategy.py:60-62,226-232`), the `SpreadGateMonitor` counters (`run.py:142`)
>   and the stale-tick counters — so a mid-session restart can allow a **second
>   entry on a closed bar** once that bar's first entry has exited, i.e. it can
>   contaminate the §5 "100+ paper trades" LIVE clock. It now restarts a service
>   only when a runtime input for it changed (`git diff --name-only BEFORE
>   AFTER` against an inert allowlist; empty diff, failed diff and unknown paths
>   all **fail safe into a restart**; `DEPLOY_FORCE_RESTART=1` bypasses).
>   `btc/config.py` is deliberately *not* inert: the shared portfolio gate reads
>   its `MAX_DAILY_LOSS`/`MAX_TRADES_PER_DAY` via `portfolio.py::_btc_config()`
>   (`portfolio.py:40-52,108-110`), currently short-circuited by gold's own
>   `PORTFOLIO_MAX_*` keys (`config.py:144-150`) but a real coupling. (2)
>   `flock -n` on `logs/deploy.lock` (`DEPLOY_LOCK_FILE`) so a run cannot
>   overlap the next 15-minute tick — `ExecStartPre` (`wait_for_mt5.py
>   --timeout 180`) can block longer than the slot. Restart lines keep the
>   historical `restarted <svc> at <sha> (was <sha>) branch=<branch>` wording;
>   skips log `restart skipped for <svc> (no runtime path changed)`.
> - **Dashboard gap found.** `deploy.sh` never restarted `scalper-dashboard`,
>   and `dashboard.py` module changes do **not** hot-reload (Jinja templates
>   do — `auto_reload=True` is the Jinja2 3.1.6 default and Starlette does not
>   disable it; verified in-process). PR #22's red "NO ENTRY IS POSSIBLE WITH
>   THIS CONFIGURATION" banner is a `dashboard.py` *context* change, so on a
>   dashboard not restarted since 2026-10-06 the banner silently never appears.
>   The deploy now logs a note naming dashboard-relevant files; opt in with
>   `DEPLOY_SERVICES="scalper-bot scalper-dashboard"`. Check
>   `systemctl show scalper-dashboard -p ActiveEnterTimestamp`.
> - **Also flagged, deliberately not changed:** `/root/scalper/scripts/`
>   `paper_status_daily.sh` (server-only, not in git) lives inside the directory
>   the cron pulls into — if a future commit ever adds that path, every
>   `git pull --ff-only` aborts with "untracked working tree files would be
>   overwritten" and updates stop silently; "fixing" it with `.gitignore` would
>   instead let git clobber the script. Move server-only ops scripts outside the
>   deployed tree (`/root/ops/`). No `MAILTO`/alert exists, so a failed pull
>   stops all deployments with only a log line. `services/*.service` edits are
>   pulled but never copied to `/etc/systemd/system` nor `daemon-reload`ed. No
>   logrotate for `logs/`. Cron runs with `/usr/bin:/bin` while the units run
>   with the `mt5env` PATH — declare it in the crontab.
> - **Verification (local; this container has no `ssh scalping`):**
>   `tests/test_deploy_services.sh` **18/18 PASS** (was 3/3 — BTC-only ⇒ no
>   restart, `btc/config.py` ⇒ restart, empty/failed diff ⇒ restart,
>   `DEPLOY_FORCE_RESTART=1`, dashboard opt-in on/off, lock-held ⇒ skip) plus a
>   real-git 7-scenario integration run on a scratch clone. Gold regressions
>   after the edit: `backtest.py` **255 / +$456.58 / PF 1.32 / maxDD $108.65 /
>   WR 28.2% / 72-43-140 / avgR 0.11** (identical), `research/parity_test.py`
>   **PASS** (460 signals, 0 mismatches), `tests/test_spread_gate.py` **21/21**,
>   `research/paper_exit_test.py` PASS. No gold-runtime file was edited and
>   `config.py`, `btc/config.py`, `strategy.py`, `run.py`, both `TRADING_MODE`s,
>   `MAX_SPREAD_POINTS` and every trading parameter are untouched; the gold-only
>   deploy default stands, so BTC remains an explicit Phase-2 opt-in.
> - **Server action (not done from here):** §6 checklist in
>   `docs/cron_review_2026-10-07.md` — back up `crontab -l`, install the
>   recommended block, restart `scalper-dashboard` once if its
>   `ActiveEnterTimestamp` predates 2026-10-06, then read the next
>   `logs/deploy.log` tick.

> **Update (2026-10-06, branch `arena/037cb1f4-scalper`, pushed as
> [PR #22](https://github.com/shashidaren/scalper/pull/22)): the BTC "no trades,
> high spread" report is the placeholder gate, now made *visible*; no trading
> parameter changed. Gold unchanged and re-verified.**
> - **Root cause, code-verified.** `run.py` skips the cycle while
>   `spread_points > config.MAX_SPREAD_POINTS` (`SKIP {"reason":"high_spread"}`,
>   then sleep), so `strategy.check_signal()` is never reached on BTC. The real
>   XM BTCUSD feed quotes **mean 4,242 pts**; `btc/config.py` still carries the
>   **1,500-pt placeholder** → **100.00%** of quotes vetoed. The derived value
>   (1.25 × TRAIN p90, `btc/derive_params.py`) is **≈6,250 pts**, which vetoed
>   0.00% of TRAIN quotes — but the 10-03 Phase 1b run already showed the shape
>   loses *after* such a gate (**−$165.84, PF 0.74**), so the gate was not the
>   thing hiding an edge. **`MAX_SPREAD_POINTS` was not raised**: per the
>   standing rule, raising it requires a passing hypothesis, not a config edit.
> - **New shared code (all backwards-compatible; gold path verified unchanged):**
>   `spread_gate.py` (`SpreadGateMonitor`: quote/veto counts, min/median/max,
>   verdicts `ok|starved|infeasible`, one rate-limited `SPREAD GATE INFEASIBLE`
>   warning + recovery INFO); `run.py` feeds it and publishes a `spread_gate`
>   snapshot in `live_status.json`; `logger.py` takes the new optional key
>   (`None` default); `dashboard.py` + `templates/index.html` render a red
>   **"NO ENTRY IS POSSIBLE WITH THIS CONFIGURATION"** banner (amber STARVED
>   variant) plus `gate N, M% vetoed` on the price card. **The gate decision
>   itself is the identical comparison it was before.**
> - **New BTC tools:** `btc/preflight.py` (pre-start "can this gate ever pass?"
>   verdict; exit 0 OK / 1 STARVED / 2 INFEASIBLE / 3 unmeasured; `--offline
>   --csv` or read-only live ticks that never `mt5.shutdown()`);
>   `btc/edge_screen.py` (gross-edge-vs-cost decomposition; reproduces
>   `backtest.py` exactly and shows gold g +0.157R > c 0.051R vs BTC
>   g +0.02R < c 0.23–0.26R); `btc/breakout_screen.py` (hypothesis-C screen,
>   proxy-only). Plus `docs/btc_spread_edge_analysis_2026-10-06.md` and
>   `btc/HANDOFF.md` §7a/§9.
> - **Tests, after the shared-code edits:** `backtest.py` **255 / +$456.58 /
>   PF 1.32 / WR 28.2% / max DD $108.65 / 72-43-140** (identical),
>   `research/parity_test.py` **PASS** (460 signals, 0 mismatches),
>   `research/paper_exit_test.py` PASS, `btc/train_select_test.py` PASS,
>   `btc/e2e_smoke.py` **ALL PASS** (both config dirs, incl. the new gate
>   snapshot check), `btc/tool.py --check` **14/14**, `tests/test_spread_gate.py`
>   **21/21**, `tests/test_deploy_services.sh` **3/3**. No BTC file or server
>   observation exists in the sandbox (only `github.com`/`api.github.com`/
>   `pypi.org` reachable, `ssh scalping` still unresolved).
> - **BTC plan amendment (proxy-screened, non-evidence):** hypothesis A
>   (M15/H1 same shape) deprioritised; B (cheaper tier) is not binding; C
>   (**H1 Donchian breakout**) is the pre-registered priority for the next
>   untouched pull. Details in `btc/HANDOFF.md` §5 and
>   `docs/btc_spread_edge_analysis_2026-10-06.md`.

> **Update (2026-10-03, branch `arena/01a102c4-scalper`, HEAD `f5e76c8`):
> BTCUSD Phase 1b is closed — FAIL / No-Go. Gold is unchanged and re-verified.**
> - **The BTC question now has a measured answer: no.** Phase 1b was run on the
>   real 20,000-bar `data/BTCUSD_M5.csv` on `scalping` at
>   `2026-10-03T17:07:55+00:00` (`/root/scalper` clean at `f5e76c8` on `main`).
>   `research/strategy_sweep.py --verify` reproduced `backtest.py` exactly
>   (**433 trades / −$165.84 / PF 0.74 / WR 23.8% / 107 TP · 59 BE · 267 SL**),
>   then the `btc/train_select.py` decision gate **FAILED**: the frozen
>   TRAIN-selected candidate (`ATR p75=113.14, SL=2.0, BE=off`) is negative on
>   cold OOS (**n=70, −$46.11, PF 0.75, P(net>0)=0.138**) and the pre-registered
>   baseline is worse (**n=217, −$95.50, PF 0.72**), against a gate requiring
>   positive cold-OOS net and PF ≳ 1.2. Write-up:
>   **`docs/btc_phase1_result_2026-10-03.md`**; details in `btc/HANDOFF.md` §9.
> - **The failure is structural, so it is not fixable by tuning.** XM BTCUSD
>   spread is **52.0% of median ATR** and **26.0% of a 2×ATR stop** (gold pays
>   ~5.3% of a stop), so the required win rate is **~36.0%** vs **23.8%**
>   actual. Net before spread is **+$17.16 (+$0.04/trade)** against **$183.00**
>   of spread paid — the raw signal is coin-flip-neutral and the cost is ~10×
>   the gross edge. Every one-variable sweep (SL/TP/BE/RSI/spread) over all
>   20,000 bars is net-negative; all 4 months, all 4 ATR quartiles, 6 of 7
>   weekdays and both directions lose.
> - **Consequence: no BTC service, and Phase 2 stays blocked.** On `scalping`,
>   `scalper-btc-bot` and `scalper-btc-dashboard` are **disabled + inactive**
>   (`:8089` not listening; the unit that the `a4d6ecf` → `d8add56` transition
>   deploy had started was stopped at `16:50:21 UTC` after 0 trades), the deploy
>   cron is `*/15 * * * * DEPLOY_BRANCH=main /root/scalper/deploy.sh` with **no**
>   `DEPLOY_SERVICES`/`DEPLOY_SERVICE` override, and the last deploy line reads
>   `restarted scalper-bot at f5e76c8… (was d8add56…) branch=main` — the
>   gold-only default from PR #17 is doing its job. Do **not** tune on OOS, do
>   **not** loosen `MAX_SPREAD_POINTS` so a losing strategy can trade, and do
>   **not** copy gold parameters onto BTC.
> - **Gold is untouched and re-verified.** This session changed **documentation
>   only** — `config.py`, `btc/config.py`, `strategy.py`, `run.py` and every
>   trading/engine parameter are unmodified, and `TRADING_MODE` remains
>   `"FORWARD_TEST"` on both instances. Locally re-run: `backtest.py`
>   **255 trades / +$456.58 / PF 1.32 / max DD $108.65 / WR 28.2% / 72 TP ·
>   43 BE · 140 SL / avgR 0.11** (identical to the standing baseline),
>   `research/parity_test.py` **PASS** (460 replay signals, 0 mismatches, 20×
>   bridge-cache reduction, blackout check clean), `btc/tool.py --check`
>   **11/11 PASS**, `btc/train_select_test.py` **PASS**, and
>   `tests/test_deploy_services.sh` **PASS 3/3**. Gold's paper book was not
>   disturbed (`SIM: $128.62 | SimEquity: $131.03` with an open position across
>   the `17:07:44 UTC` restart) — **the §5 "100+ paper trades" clock is
>   unaffected and remains the binding constraint on any gold LIVE decision.**
> - **Provenance:** this Arena container cannot resolve `scalping` and holds
>   only `GOLD_M1.csv` / `GOLD_M5.csv` (`data/*.csv` is git-ignored), so the BTC
>   figures above are the server run's recorded output rather than a local
>   reproduction; the five verification checks in the previous bullet *were*
>   re-run locally.

> **Update (2026-10-03, branch `arena/01a102b0-scalper`, after PR #17 `d8add56`):
> BTC dashboard price-card label fix + `server_check.py` cron output.**
> - **Server access & Phase 1b:** From this Arena container (`e2b.local`),
>   `ssh scalping` still fails DNS resolution and `/home/user/scalper/data/` has
>   only `GOLD_M1.csv` and `GOLD_M5.csv` (`data/BTCUSD_M5.csv` is git-ignored on
>   `/root/scalper`). No live server state or real-file BTC Phase 1b result is
>   claimed from the local checkout.
> - **User-reported server snapshot (2026-10-03 16:47 UTC, carry-over):**
>   `/root/scalper` was clean at `d8add5678d74a1b6381c6e702432a0e1f0a0ce62`;
>   `data/BTCUSD_M5.csv` had 20,000 bars through `2026-10-03 13:40 UTC` (BTC M1
>   absent); `scalper-btc-bot` was `disabled` but **active** (SIM mode, 0 trades,
>   repeated `high_spread` skips at ~4,000 pts vs `MAX_SPREAD_POINTS=1500`);
>   `scalper-btc-dashboard` was `enabled` and `active` on `:8089`; gold was
>   active with an open paper position.
> - **Why `scalper-btc-bot` started on the PR #17 deploy & why `crontab -l` was
>   missing from the markdown report:** (1) In `deploy.sh`, `SERVICES` is bound
>   at line 17 *before* `git pull --ff-only` at line 33. When the cron ran on the
>   pre-PR-#17 checkout (`a4d6ecf`), the running shell still held the old default
>   (`scalper-bot scalper-btc-bot`) during the pull to `d8add56` and restarted
>   both units one final time (`systemctl restart` starts a disabled unit). Later
>   cron runs on `d8add56` default to `scalper-bot` only (unless `crontab`
>   overrides `DEPLOY_SERVICES`/`DEPLOY_SERVICE`), which does not stop an
>   already-running `scalper-btc-bot`. (2) `btc/server_check.py` collected
>   `r["cron"]` in `collect()` (`--json`) but omitted it in `to_markdown()`;
>   fixed so default markdown output includes `crontab -l`.
> - **BTC dashboard price vs label (`templates/index.html`):** Verified that
>   `btc/dashboard.py` + `btc/run.py` already display real **`BTCUSD`** `bid`,
>   `ask`, and `spread` from `btc/logs/live_status.json` (`MT5Bridge` queries
>   `config.SYMBOL = "BTCUSD"`). Only the price card header in
>   `templates/index.html` line 132 was hard-coded as `<h2>GOLD Price</h2>`;
>   changed to `<h2>{{ config.symbol if config is defined and config.symbol else "GOLD" }} Price</h2>`
>   (`GOLD Price` on gold, `BTCUSD Price` on BTC) and added an assertion to
>   `btc/tool.py --check` (11/11 PASS). Gold backtest (**255 / +$456.58 /
>   PF 1.32 / max DD $108.65 / 72-43-140**), parity, paper-exit, BTC e2e smoke,
>   selector helper, and deploy-service tests all PASS.

> **Update (2026-10-03, branch `arena/01a101b6-scalper`): reviewed the BTC
> bootstrap and closed two follow-ups.** The bootstrap's old private-branch /
> bundle instructions are stale: PR #16 already merged the pre-data work to
> `main` as `a4d6ecf` at 11:22:44 UTC. Phase 1b is still open, but this Arena
> checkout has only the gold CSVs, not `data/BTCUSD_M5.csv` or the referenced
> server command script, and `ssh scalping` fails DNS resolution here; no BTC
> result or server state was re-claimed, and no BTC service was touched. Added
> `btc/train_select.py`: the existing generic `--oos`/`--candidates` reports
> hard-code gold settings, so the new BTC selector ranks only on TRAIN, freezes
> one config, then reads its cold OOS result; its replay applies a TRAIN-derived
> spread veto. Also made `deploy.sh` default to `scalper-bot` only because
> `systemctl restart` can start a disabled-but-installed BTC unit; BTC now
> requires explicit `DEPLOY_SERVICES` opt-in after Phase 1 and paper approval.
> Verification: gold backtest remains **255 / +$456.58 / PF 1.32 / max DD
> $108.65 / 72-43-140**; parity and paper-exit tests PASS; BTC isolation/e2e
> smoke tests PASS; `btc/train_select_test.py` and the deploy-service mock test
> PASS. The selector's end-to-end smoke used `GOLD_M5.csv` under the BTC config
> strictly as a plumbing test—not BTC evidence.

> **Update (2026-10-03, branch `arena/01a1016f-scalper`): BTC pre-data
> follow-through — gold is again PROVEN unchanged, nothing deployed.** Closed
> every BTC item that does not need the server (details in `btc/HANDOFF.md` §9):
> the sweep's spread levels and `parity_test`'s fake tick are now derived from
> the loaded instrument's own data instead of gold literals; shared code gained
> an **optional entry-blackout filter** for 24/7 instruments
> (`ENTRY_BLACKOUTS_ENABLED` / `ENTRY_BLACKOUT_WINDOWS`, UTC windows with
> optional weekdays, implemented once in `strategy.py` and mirrored in the
> replay engine so live/backtest parity still holds) — **empty and inert for
> gold**; and three new artefacts landed: `btc/server_check.py` (the §0 server
> checklist as one read-only, MT5-free command), `btc/derive_params.py`
> (bar file → measured ATR/spread distributions → candidate values for the
> flagged placeholders) and `docs/btc_market_reference_2026-10-03.md` (cited
> web priors for XM BTCUSD: 1 BTC/lot, 0.01 min lot, leverage 1:250 vs 1:500
> *conflicting*, Standard spread ~500 points ≈ $5/lot, 24/7 with a Saturday
> 10:05–10:35 GMT+2 maintenance halt, crypto triple swap Friday→Saturday — each
> mapped to the command that confirms it). **Gold evidence after the changes:
> `backtest.py` 255 / +$456.58 / PF 1.32 / max DD $108.65 / 72 TP · 43 BE ·
> 140 SL, `research/parity_test.py` PASS (460 signals, 0 mismatches, plus a new
> blackout parity check: 874 bars compared, 40 real signals suppressed, 0
> mismatches), `research/paper_exit_test.py` PASS (M5 OHLC 48 / +$89.43 /
> PF 1.35), `btc/tool.py --check` 10/10, `btc/e2e_smoke.py` ALL PASS on both
> instances.** The deriver was sanity-checked on `data/GOLD_M5.csv`: it
> reproduces gold's documented spread mean $0.47, 28.6% structural break-even
> win rate and a $31.3 daily-loss suggestion against the adopted $30.
> **User decision 2026-10-03: BTC trades the same XM account and MT5 terminal
> as gold** — accepted while both books are `FORWARD_TEST`, still blocked by
> the separate-account / combined-gate requirement before any LIVE flip.
> Phase 0 (server recon, real BTC bars) is unchanged and remains the next step.

> **Update (2026-10-03, branch `arena/01a10125-scalper`): BTC scalper plumbing
> built — gold's behaviour is PROVEN unchanged, and nothing was deployed or run
> on the server.** The user asked whether a **BTCUSD scalper** can reuse this
> stack, in a separate subfolder with its own dashboard port, and asked for a
> separate handoff: **`btc/HANDOFF.md`** is that handoff (verdict, architecture,
> phase plan with decision gates, risks, Phase 0 commands), with
> **`btc/recon.py`** as the read-only Phase 0 probe (contract spec,
> spread-vs-ATR economics, 24/7 coverage; no orders and deliberately **no**
> `mt5.shutdown()`, because the gold bot shares the terminal session).
> Verdict: the **infrastructure** (MT5 container + bridge, engine loop, ledger,
> paper book, backtest/sweep/parity/loss tooling, deploy + systemd pattern) is
> ~70% reusable verbatim; gold's **parameter values** are 0% reusable and must
> be re-derived on BTC data.
>
> **What changed in shared gold code:** ten gold values that were hard-coded in
> the engine are now config keys — `CONTRACT_SIZE=100.0`, `PRICE_DIGITS=2`,
> `ATR_MIN=0.50`, `SL_ATR_MULT=2.0`, `TP_ATR_MULT=5.0`, `EMA_PERIOD=200`,
> `RSI_PERIOD=14`, `ATR_PERIOD=14` (new, in `config.py`), plus `config.LOG_DIR`
> and `config.DASHBOARD_TITLE` read via `getattr` with the old paths/names as
> fallbacks (`logger.py`, `dashboard.py`). **Every value equals the literal it
> replaced**; `strategy.py`'s skip reason now formats the floor as
> `atr_low:x.xx<0.5` instead of `<0.50` (string only — nothing parses it).
> Verified after all hooks were in place: **`backtest.py` = 255 trades /
> +$456.58 / PF 1.32 / max DD $108.65 / WR 28.2% / 72 TP · 43 BE · 140 SL**
> (identical), **`research/parity_test.py` = PASS, 460 signals, 0 mismatches**
> and **`research/paper_exit_test.py` = PASS** (M1/M5 table unchanged), plus an
> instance-regression where a gold-valued config with a diverted `LOG_DIR`
> reproduces the same 255/+$456.58 through the hooked engine. Also added
> **`btc/e2e_smoke.py`**, a committed end-to-end test (fake MT5 over a real RPyC
> socket, ephemeral port, temp dirs, refuses a non-FORWARD_TEST config) that
> drives signal → paper entry → SL exit: it passes on the BTC instance with
> `-$3.45` (344.7 px × 0.01 × **1 BTC**) and on the **gold** config dir with
> `-$344.72` (× **100 oz**) — the contract-size hook is proven per instrument.
> New BTC-side code (`btc/config.py`, `_instance.py`, `run.py`, `dashboard.py`,
> `tool.py`, `e2e_smoke.py`, two systemd units, `deploy.sh` multi-service
> restart) is inert for gold. `TRADING_MODE` stays `"FORWARD_TEST"`;
> `btc/HANDOFF.md` §4 tracks the ten hooks and §6 records the evidence.
> **PR #14 merged into `main` at 2026-10-03 10:11:28 UTC** as `bfb1dff`
> ([PR #14](https://github.com/shashidaren/scalper/pull/14)). This made the code
> eligible for the existing `*/15` `main` deploy cron, but this repository has
> **no post-merge server observation**. Before the merge, BTC units were not
> installed and no BTC data had been collected; do not infer that this remains
> true—or that a deploy succeeded—without running the evidence checklist in
> `btc/HANDOFF.md` §0. No BTC service may be installed, enabled, or started
> until its Phase 0/1 gates are met and the user explicitly chooses paper
> deployment.
>
> **Update (2026-10-02, this session, branch `arena/01a0fd8e-scalper`):** loss
> analysis of the adopted config — **decision: REMAIN, no parameter change** —
> full writeup in `docs/loss_analysis_2026-10-02.md`. New tooling:
> `research/loss_analysis.py` (per-trade loss anatomy) and
> `research/strategy_sweep.py --candidates` (train-select → cold-OOS re-test of
> the exit/risk knobs); both replay through the engine that `--verify` proves
> identical to `backtest.py` (255 / +$456.58 / PF 1.32 / 72 TP, 43 BE, 140 SL)
> and that `research/parity_test.py` proves identical to the live
> `check_signal` (460 signals, 0 mismatches). **No change to `config.py`,
> `strategy.py`, `run.py` or `backtest.py`; `TRADING_MODE` stays
> `"FORWARD_TEST"`.**
> 1. **The losses are structural, not a leak.** 98.7% of gross loss is full
>    stop-outs (140 SL = −$1,388.93); the 43 BE scratches cost **$18.99 total**
>    (spread only), so exit management has almost nothing left to give. Spread
>    is **$112.24 = 6% of gross profit**, so costs are not the leak either. With
>    a 1R stop / 2.5R target the structural break-even WR is **28.6%** and the
>    book wins **28.2%** — it is profitable only because 43 losers scratch for
>    spread. Median trade −$6.05; top-5 winners = 57% of net (top-10 = 104%).
> 2. **Every "obvious fix" fails train-only validation.** The two biggest
>    in-sample improvements available — **BE off (+$563.46)** and **SL 2.5×ATR
>    (+$520.66)** — are both *worse* than the adopted config on TRAIN alone
>    (+$250.11 / +$245.56 vs +$286.06); their full-file ranking was an OOS-half
>    artefact. A time-based exit (12–72 bars) is worse at every length, and
>    `ATR floor 4.0` / `BE 2.0R` are TRAIN+ but OOS− (overfit). Hour/weekday
>    buckets (16–32 trades) are too thin to filter on.
> 3. **Survivors are pre-registered, not adopted.** `TP 6.0×ATR` is the only
>    lever that clears TRAIN, cold OOS, both regimes and 4/4 walk-forward folds
>    (full sample 251 trades, +$538.06, PF 1.38, max DD $104.49, P(net>0)=0.968),
>    and `TP 6.0 + ATR floor 3.0` is the only config whose 95% bootstrap CI
>    excludes zero (228 trades, +$580.90, PF 1.44, max DD $98.98,
>    CI [+$25.48, +$1,145.70], P(net>0)=0.980). Rejected for now: the gain is
>    inside the noise (±$570 CI), `GOLD_M5.csv` has already been inspected in
>    PR #7/#11/#12, both cost the trade frequency PR #11 was raised to fix, and
>    changing config again would reset the §5 "100+ paper trades" clock a third
>    time in three days.
> 4. **Two §5 TODOs closed by measurement:** wiring `MAX_CONSECUTIVE_LOSSES=4`
>    would **cost $31.49** (N=3 costs $184.34) — losing streaks are not followed
>    by more losses — and "skip Friday after 16:00 UTC" is **backwards**: Friday
>    ≥16:00 is **+$51.90 / 16 trades** while Friday's damage is 07:00 (−$36.74)
>    and 13:00 (−$34.58). Also: `config.atr_min = 0.50` **never binds** (file ATR
>    min 1.22, 0.0000 of bars below 0.50), and `backtest.py` does not model the
>    live daily gates — replayed through them the same 255 trades net $438.48
>    (**−$18.10**), so expect the paper book to read slightly below the ungated
>    backtest.
>
> **Update (2026-10-01, branch `arena/01a0f77d-scalper`, merged as PR #12 at
> 2026-10-01 13:16:53 UTC):**
> followed up on PR #11 (`7635fad`, merged to `main` 2026-10-01 12:00:13 UTC
> and verified on the server: 255 trades / PF 1.32 / +$456.58 / max DD $108.65)
> to address three review items — full writeup in
> `docs/oos_and_execution_fidelity_2026-10-01.md`:
> 1. **Out-of-sample (OOS) & walk-forward validation (`research/strategy_sweep.py --oos`, `fetch_data.py`):**
>    - The MT5 RPyC bridge (`localhost:18812`) runs on `scalping` and is not
>      reachable from the Arena sandbox, so `fetch_data.py` was upgraded with
>      `--bars`, `--start-pos`, and `--out` to pull pre-June-2026 (`--start-pos 20000`)
>      or 60k-bar (~300-day) OOS files directly on the server (commands in §5/§6).
>    - Corrected an earlier note in `docs/strategy_iteration_2026-09-30.md`:
>      `data/GOLD_M5.csv` is **not** a single +19% bull regime — start-to-end
>      gold moves `4,506.57 → 4,387.55` (**−2.64%**) across four distinct
>      monthly regimes: **June −11.00% sell-off** (`4,503 → 4,007`, low `3,942`),
>      **July +0.80% range**, **August +9.01% breakout rally** (high `4,697`),
>      and **Sept 1–11 −1.38% pullback**.
>    - Under a strict 50/50 chronological split (**TRAIN** `2026-06-08..2026-07-27`
>      bear+range vs **Cold OOS** `2026-07-27..2026-09-11` rally+pullback),
>      tuning on TRAIN alone (both one-variable-at-a-time and across a 60-config
>      `BE × RSI × Session` grid) selects the exact adopted config
>      (`BE=1.5R, RSI=40/60, session=07–20 UTC`, #1 of 60 on TRAIN: **131 trades,
>      +$286.06, PF 1.37, P(net>0)=0.919**). Evaluated **cold on OOS**, it
>      delivers **124 trades, +$170.52, PF 1.27, WR 27.4%, avgR +0.10, max DD
>      $108.65, P(net>0)=0.838** (and on the `Aug–Sep` bull regime OOS slice:
>      **101 trades, +$172.72, PF 1.33, P(net>0)=0.858**, with both BUY and SELL
>      profitable in both halves).
>    - **Honest caveats:** OOS expectancy shrinks 37% from TRAIN (`+$2.18/tr` →
>      `+$1.38/tr`); 4-fold walk-forward shows a 3.5-week flat/drawdown quarter
>      in `Q3 (2026-07-27..2026-08-19)` (`70 trades, +$5.81, PF 1.02, max DD
>      $108.65, P(net>0)=0.510`); the 124-trade OOS half's 95% bootstrap CI
>      `[−$159.1, +$524.9]` still spans zero; and because `GOLD_M5.csv` was
>      previously inspected in PR #7/#11, this split is retrospective until
>      re-run on a fresh server pull (`--start-pos 20000`).
> 2. **Paper-mode exit fidelity (`config.POSITION_CHECK_INTERVAL_SECONDS = 1`, `run.poll_paper_position`, `research/paper_exit_test.py`):**
>    - While `paper.has_position()` is `True`, `run.py` now polls
>      `bridge.get_live_tick(retries=1)` every **1s** instead of sleeping a
>      blind 15s, resolving intra-window SL/BE/TP wicks immediately while
>      keeping 0 extra bridge calls when flat and leaving `stale_tick_cycles`
>      anchored to the 15s outer loop. M1 vs M5 overlap replay
>      (`2026-08-24..2026-09-11`) shows coarse close-only sampling inflates PF
>      to `1.55–2.33` whereas M1 wick resolution (`PF 1.31, +$81.69, 13 TP /
>      10 BE / 25 SL`) converges closely to `backtest.py` (`PF 1.35, +$89.43,
>      13 TP / 11 BE / 24 SL`).
> 3. **Reduced redundant MT5 bridge fetches (`MT5Bridge.get_rates(tick=tick)`, `ScalpStrategy` indicator cache):**
>    - `MT5Bridge.get_rates()` caches the 1,050-bar window by closed-bar
>      timestamp (0 RPyC calls mid-bar when `tick.time` is inside the forming
>      M5 bucket; 2-bar probe fallback when `tick` is omitted), and
>      `ScalpStrategy.check_signal()` caches the closed-bar indicator tuple.
>      Verified by `research/parity_test.py`: **20× reduction in full 1,050-bar
>      fetches** (60 instead of 1,200 across 60 M5 bars × 20 cycles), reacts on
>      cycle 0 of every new bar, **0 signal mismatches**.
>    - `TRADING_MODE` stays `"FORWARD_TEST"`.
>
> **Update (2026-10-01, PR #11 merged `7635fad` at 12:00:13 UTC, verified on
> server):** user feedback that the bot was "hardly taking any
> trades." Re-swept `research/strategy_sweep.py` and adopted **RSI 40/60**
> (was 35/65) **+ session 07:00–20:00 UTC** (was 07:00–17:00, end only;
> start unchanged) in `config.py`. Backtest: **255 trades over the same
> ~101-day window (was 174, +47%), net +$456.58 (was +$52.80), PF 1.32
> (was 1.06), max DD $108.65 (was $99.62), exits 72 TP / 43 BE / 140 SL**,
> profitable in every calendar month and both halves of the data, bootstrap
> (10k resamples) **P(net>0)=0.96 (was 0.60 — the old config's CI spanned
> zero)**. Also fixed a floating-point precision bug in
> `research/strategy_sweep.py`'s fast replay (`_rolling_mean` cumsum →
> `pandas.Series.rolling`) that `research/parity_test.py` caught the moment a
> real bar's RSI landed exactly on the new 60 threshold; `backtest.py`/live
> were never affected, and the parity test now passes with 0 mismatches on
> the new config. Full writeup: `docs/strategy_iteration_2026-10-01.md`.
> **This is a backtested frequency/quality improvement, not a validated live
> edge** — `TRADING_MODE` stays `"FORWARD_TEST"`, and the §5 launch criteria
> (100+ paper trades, PF sustained > ~1.2, affordable max DD) now need to be
> re-counted **from whenever this config reaches the paper book**.
>
> **Update (PR #8 deployed, verified 2026-09-30 11:06 UTC; PR #9 merged 11:32 UTC):**
> the PR #7 follow-up is **merged (`fc6f4fc`, PR #8 merged 11:04:30 UTC) and
> deployed + verified on the server** (recorded on `main` in PR #9, `108e773`) —
> nothing is pending merge/deploy any more. Server
> HEAD is `fc6f4fc` (or `108e773` after the docs-only PR #9 cron pull) with
> `INDICATOR_FETCH_MARGIN=50`,
> `INDICATOR_WINDOW_BARS=1000`; `backtest.py` reproduces **174 trades, PF 1.06,
> +$52.80, max DD $99.62, exits 41 TP / 29 BE / 104 SL**; new `SIGNAL` lines in
> `logs/trades.jsonl` carry `reason` (e.g.
> `no_setup:rsi=42.6(prev 43.1),close>ema200`) with **no `insufficient_bars`
> seen**; the bot restarted clean at 11:06:21 UTC in **FORWARD_TEST (paper)**,
> no traceback. Server `git status` is clean and `deploy.sh` is `-rwxr-xr-x`
> (the mode-only diff that blocked the first deploy is fixed);
> `.env.paper_status` is now git-ignored. **The paper book's config changed at
> 10:43:53 UTC** (the PR #7 deploy) and `logs/paper_account.json` carries across
> restarts, so count the "100+ paper trades" criterion **from 10:43:53 UTC**, not
> from the file's start (balance $151.26 at 11:06 still includes the old config;
> see §5 for the counting command). Live spread is running **53–55 pts (~$0.54)**
> vs the backtest's $0.47 mean — worth remembering when judging the paper book.
> **Note on evening `Tick data unchanged for 20 cycles` warnings (~21:00–22:00 UTC):**
> benign — spot gold (`GOLD` on XM / CME Globex) has its daily 1-hour rollover
> break from **21:00 to 22:00 UTC** (05:00–06:00 Asia/KL) and is closed
> **Fri 21:00 → Sun 22:00 UTC**; see §7.
> `TRADING_MODE` stays `"FORWARD_TEST"` — the bootstrap CI spans zero
> (P(net>0)≈60%), so **there is no validated edge**.

- **Repo/branch:** `shashidaren/scalper`; **PR #6 merged to `main` at
  2026-09-30 10:19:58 UTC** (merge commit `40ec328`, branch
  `arena/01a0f1c8-scalper` → `main`), **PR #7 at 10:37:49 UTC** (`e12e845`,
  strategy iteration: indicator warm-up + spread measurement fixes,
  `BE_TRIGGER_R` 1.5), **PR #8 at 11:04:30 UTC** (`fc6f4fc`, the follow-up:
  fetch margin + skip-reason diagnostics), **PR #9 at 11:32:35 UTC**
  (`108e773`, HANDOFF verification record), **PR #10 at 22:03:53 UTC**
  (stale-tick-warning HANDOFF note), and **PR #11 on 2026-10-01 12:00:13 UTC**
  (`7635fad`, RSI 40/60 + session 07-20 UTC). Gate 1 (live-path hardening) and
  Gate 2 (backtest fix) are on `main`. That session's work (OOS validation,
  1s paper-exit polling, closed-bar rate caching) shipped as **PR #12**
  (`arena/01a0f77d-scalper`, merged 2026-10-01 13:16:53 UTC, merge commit
  `4eaf437` — confirmed via `gh pr list`). Current session branch is
  **`arena/01a0fd8e-scalper`** (branched from `4eaf437`): the 2026-10-02 loss
  analysis — research tooling + docs only, **no config/strategy change** — which
  will be **PR #13** once opened.
- **Deploy cron confirmed and working (2026-09-30):**
  `*/15 * * * * DEPLOY_BRANCH=main /root/scalper/deploy.sh` — so `main` is the
  production target. **Verified end-to-end on `scalping`:** the server is at
  `fc6f4fc` (PR #8 merge, 11:04:30 UTC), i.e. PR #6 (`40ec328`) → PR #7
  (`e12e845`) → PR #8 all auto-deployed via cron without intervention, and the
  bot restarted at 11:06:21 UTC. `git status` on the server is clean.
  Backtest smoke test on the server prints **174 trades / PF 1.06 / +$52.80**
  (was 0 before Gate 2, 201/0.92 on the old defaults). `live_ledger.py` is
  present. (`logs/live_ledger.json` staying absent in FORWARD_TEST is by design
  — LiveLedger is LIVE-only — but was not re-checked in this pass; it is covered
  by the first-LIVE-run item in §5.)
  **Changed 2026-10-07:** the cron line gains a `mkdir -p /root/scalper/logs &&`
  prefix, and `deploy.sh` itself now (a) holds `logs/deploy.lock` via `flock -n`
  so runs cannot overlap an `ExecStartPre` wait, and (b) restarts a unit only
  when a changed path is a runtime input for it — BTC-only/docs-only commits no
  longer restart the gold book (see §1 10-07 and §3).
- **Status script:** runs from cron on the server at **01:15 UTC daily** and
  **01:00 UTC Mon–Fri** (double-run on weekdays by design/legacy), at
  `/root/scalper/scripts/paper_status_daily.sh` — **server-only, not in git**.
  Keep `.env.paper_status` private; never commit it.
  **2026-10-07 review:** the weekday double-run is a duplicate (same script,
  15 min apart) → **recommended: one daily run at `7 1 * * *`** (off the
  deploy cron's :00/:15 ticks) and delete the Mon–Fri line; move the script
  *out* of the deployed tree (e.g. `/root/ops/`) because `/root/scalper` is what
  the 15-minute cron pulls into — a future commit adding `scripts/` would abort
  every `git pull --ff-only` (see `docs/cron_review_2026-10-07.md` F1/F2).
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
- **Server** (`scalping`), **confirmed** at HEAD `fc6f4fc` as of
  2026-09-30 11:06 UTC (PRs #6/#7/#8 all auto-deployed via cron; working tree
  clean; `deploy.sh` mode `-rwxr-xr-x` correct). Bot restarted 11:06:21 UTC.
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
- **Strategy:** v7 closed-bar signals + one-shot per bar, session 07:00–20:00
  UTC (end widened from 17:00 by **PR #11, merged 2026-10-01 12:01:18 UTC**),
  RSI 40/60 (widened from 35/65 by the same PR), ATR 2.0 SL / 5.0 TP.
  **Correction (2026-10-02):** earlier revisions of this bullet said the
  RSI/session widening was "not yet deployed — server is still 35/65 / 07-17".
  That is stale: `gh` confirms PR #11 merged at 12:01:18 UTC and the 15-min
  deploy cron targets `main`, and the §5 PR #11 TODO is checked off as verified
  on the server (255 trades / PF 1.32 / +$456.58 — the exact numbers
  `backtest.py` reproduces from this tree, which carries RSI 40/60 and
  `SESSION_END_HOUR_UTC = 20`). **Count the §5 "100+ paper trades" criterion
  from the PR #11 deploy (~2026-10-01 12:15 UTC), not from a future deploy.**
  **Changed 2026-09-30 and live on the server:** `BE_TRIGGER_R` 0.75
  → **1.5**, the indicator window is pinned to `INDICATOR_WINDOW_BARS = 1000`
  so the EMA200 is converged and the live path matches the backtester (it was
  250 live vs 202 backtest, i.e. two different indicators), plus
  `INDICATOR_FETCH_MARGIN = 50` for headroom (the server probe was returning
  exactly 1000 bars against a `>= 1000` guard). Verified active at `fc6f4fc`
  on 2026-09-30 11:06 UTC.
  **Re-tested 2026-10-02 and kept:** `BE_TRIGGER_R = 1.5` and the 2.0×ATR stop
  both survive train-only selection; the in-sample sweep's better-looking
  alternatives (BE off, SL 2.5×ATR) do not — see
  `docs/loss_analysis_2026-10-02.md` §5. `atr_min = 0.50` **never binds** (file
  ATR min 1.22) and is documented as dead rather than silently mis-tuned.
- **Paper book:** inspect on server with `python paper.py`; balance $151.26 at
  11:06 UTC. **The book's config changed at 10:43:53 UTC** and the JSON carries
  across restarts — but the config changed *again* with the PR #11 deploy
  (~2026-10-01 12:15 UTC), so count the "100+ paper trades" criterion from
  **there** (command in §5), not from the file's start or from 10:43:53.

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
`SIM_START_BALANCE=300` (was 200 until 2026-10-04), `BE_TRIGGER_R=1.5`, `INDICATOR_WINDOW_BARS=1000`,
`INDICATOR_FETCH_MARGIN=50`, `CHECK_INTERVAL_SECONDS=15`,
`POSITION_CHECK_INTERVAL_SECONDS=1`, `RPC_TIMEOUT_SECONDS=30`, backoff caps,
stale-tick thresholds (`STALE_TICK_WARN_CYCLES=20`,
`STALE_TICK_RECONNECT_CYCLES=120`), **SESSION_FILTER_***, **RSI_*_LEVEL**,
**SIGNAL_ON_CLOSED_BAR**.

## 3. Changelog (what was done and why)

| Date | Change | Why |
|---|---|---|
| 10-07 | **Cron review + deploy hardening (`arena/87d768e3-scalper`, `docs/cron_review_2026-10-07.md`; PR pending)**: reviewed the three recorded `crontab -l` lines on `scalping` and closed the decisions. **`deploy.sh` now restarts only when a runtime path changed** — `git diff --name-only BEFORE AFTER` is checked against an inert allowlist (`docs/`, `research/`, `tests/`, `*.md`, `deploy.sh`; for `scalper-bot` also `btc/*` except `btc/config.py`, plus non-runtime tooling `backtest.py`/`fetch_data.py`/`gold.py`/`balance.py`/`dashboard.py`/`templates/*`; for dashboard units only `dashboard.py`/`config.py`/`logger.py`/`portfolio.py`/`templates/*` are runtime inputs), **failing safe into a restart** on empty/failed diff or unknown path (`DEPLOY_FORCE_RESTART=1` bypasses) — because a restart re-arms in-memory-only state (`strategy._last_fired_bar_ts` one-shot-per-bar guard, spread-gate counters, stale-tick counters) and the BTC-only/docs-only commits that dominate the log were restarting the gold paper book mid-session. It also takes **`flock -n` on `logs/deploy.lock`** (`DEPLOY_LOCK_FILE`) since `ExecStartPre` (`wait_for_mt5.py --timeout 180`) can outlast the 15-minute slot, and logs a note when dashboard-relevant files changed but `scalper-dashboard` is not in `DEPLOY_SERVICES`. Restart lines keep the historical `restarted <svc> at <sha> (was <sha>) branch=<branch>` wording. **Cron recommendation:** keep `*/15 … DEPLOY_BRANCH=main` (add `mkdir -p logs &&`); keep the daily status report but at `7 1 * * *`; **delete `0 1 * * 1-5`** (weekday duplicate, 15 min after the daily one); add `SHELL`/`PATH` (mt5env)/`MAILTO`/`CRON_TZ=UTC`. **Findings not code-changed:** `scalper-dashboard` is never restarted by the cron and `dashboard.py` does not hot-reload (templates do — Jinja2 `auto_reload=True` verified in-process), so PR #22's red gate banner needs one manual dashboard restart; `/root/scalper/scripts/paper_status_daily.sh` sits inside the pull target (a future commit adding `scripts/` aborts every `git pull --ff-only`; a `.gitignore` "fix" would let git clobber it) → move ops scripts to `/root/ops/`; no `MAILTO`/alert for failed pulls; `services/*.service` edits never reach `/etc/systemd/system` (no copy, no `daemon-reload`); no logrotate. **Verification:** `tests/test_deploy_services.sh` **18/18 PASS** (was 3/3) + real-git 7-scenario integration; gold `backtest.py` **255 / +$456.58 / PF 1.32 / maxDD $108.65 / 72-43-140** (identical), `parity_test` **PASS** 460/0, `test_spread_gate` **21/21**, `paper_exit_test` PASS. **No trading/engine/config parameter changed**; `TRADING_MODE` stays `FORWARD_TEST`, `MAX_SPREAD_POINTS` stays 1500, deploy still defaults to the gold unit only, server crontab untouched (no `ssh scalping` from this container). | User asked for a review of the cron ("do we need any changes?"). The deploy cron is the only thing that ships code to the paper book that gates any LIVE decision, and it was restarting that book on every commit — including BTC-only ones — which both re-arms the one-shot-per-bar guard mid-session and adds `ExecStartPre` waits that can overlap the next tick. The status cron was double-running the same script 15 minutes apart (`§5` TODO). Recording the verdicts, the exact crontab, and the things deliberately left alone (BTC opt-in, `main`, schedule) keeps the next session from re-deriving them and from "fixing" the paper-status path in a way that breaks every future deploy. |
| 10-06 | **BTC spread-gate telemetry + diagnostics; "high_spread / 0 trades" root-caused ([PR #22](https://github.com/shashidaren/scalper/pull/22), `arena/037cb1f4-scalper`, `btc/HANDOFF.md` §7a/§9, `docs/btc_spread_edge_analysis_2026-10-06.md`)**: new shared **`spread_gate.py`** (`SpreadGateMonitor` — counts quotes/vetoes, min/median/max spread, verdicts `ok\|starved\|infeasible`, rate-limited **one** `SPREAD GATE INFEASIBLE` warning + recovery INFO) fed by `run.py` and published as `spread_gate` in `live_status.json` (`logger.py` optional key, default `None`); dashboard banner **"⛔ NO ENTRY IS POSSIBLE WITH THIS CONFIGURATION"** / amber STARVED + `gate N, M% vetoed` on the price card (`dashboard.py`, `templates/index.html`). New tools: **`btc/preflight.py`** (exit 0 OK / 1 STARVED / 2 INFEASIBLE / 3 unmeasured; `--offline --csv` or read-only live ticks, never `mt5.shutdown()`), **`btc/edge_screen.py`** (gross-edge vs cost ratio; reproduces gold's 255 / +$456.58 / PF 1.32), **`btc/breakout_screen.py`** (hypothesis-C proxy screen). New tests `tests/test_spread_gate.py` 21/21, `btc/preflight_test.py`, `btc/edge_screen_test.py`; `btc/e2e_smoke.py` now asserts the gate snapshot, `btc/tool.py --check` **14/14** (BTC instance). **No trading/engine parameter changed** (notably `MAX_SPREAD_POINTS` stays 1500 and `TRADING_MODE` stays `FORWARD_TEST`; no BTC service). Gold unchanged: `backtest.py` **255 / +$456.58 / PF 1.32 / maxDD $108.65 / 72-43-140**, `parity_test` PASS 460/0, `paper_exit_test` PASS, `train_select_test` PASS, `e2e_smoke` ALL PASS both dirs, `test_deploy_services.sh` 3/3. | User reported the BTC bot showing `high_spread` with no trades. Measured cause: `MAX_SPREAD_POINTS=1500` placeholder vs a real 4,242-pt mean spread ⇒ **100% veto** before `strategy.check_signal` ever runs (derived gate ≈6,250 pts vetoes 0.00%). §5 forbids loosening the gate to let a losing shape trade, so the fix is to make the impossibility *visible and measured* (engine log, `live_status.json`, banner, preflight exit code) instead of silently skipping forever, and to give the next attempt the g > c decision rule. |
| 10-06 | **BTC Phase-1c amendment recorded (proxy non-evidence) (`arena/037cb1f4-scalper`, `docs/btc_spread_edge_analysis_2026-10-06.md`)**: screening the pullback shape on public Binance klines (costed at the measured XM quote, 5.486 bp of price) shows the *gross* edge decays to ~0 after 2021 (per-era gross PF 1.17/1.26/0.98/0.96/1.02) and that even **zero cost** leaves the 8-year book at PF 1.01 — so cheaper tiers are not the binding constraint. A long-lookback **H1 Donchian breakout** (don100/exit50/sl2.0) shows net PF **1.16 / +$406.20 / 532 trades**, positive 2021–2024, negative in 2025 on n=36. A is deprioritised, B downgraded to "after a gross edge exists", **C is the pre-registered priority** for the next untouched XM pull (still gated by `btc/train_select.py` cold-OOS: net > 0, PF ≳ 1.2, n ≥ 60). Proxy numbers are **not evidence** for XM BTCUSD. | Keeps the untouched CSVs clean: screening families before spending a pull stops the same (already negative) family being re-litigated and stops a proxy result being mistaken for a Phase-1 pass. |
| 10-04 | **Hybrid shared/isolated LIVE redesign implemented (`arena/01a106bd-scalper`, design `docs/redesign_2026-10-04.md`, hypotheses `docs/btc_phase1c_hypotheses_2026-10-04.md`)**: `ACCOUNT_MODE=shared|isolated` in one `.env` (shared=today: one `mt5-gold` :18812 one pool; isolated: `mt5-gold` :18812 + `mt5-btc` :18813 two pools, `profiles: [isolated]`), `.env.example` v2, `docker-compose.yml` hybrid with `mt5` alias compat. `config.py`/`btc/config.py` now env-aware (`PORTFOLIO_MAX_*`, `SHARED_BRIDGE`, `BTC_TIMEFRAME` override, `MT5_BTC_PORT`). **Bridge fix:** `MT5Bridge` adds `threading.RLock`, `SHARED_BRIDGE` skip of `mt5.shutdown()` on shared, `wait_for_mt5.py` `--shared/--no-shared` and env-aware probe. **`portfolio.py` new:** combined `logs/portfolio.json` + `logs/portfolio_KILL_SWITCH` gate (`38 / 25` default, derived 30+8 / capped 25), both bots check it every loop after per-instance gates (`run.py` `portfolio_blocked()`). `services/*.service` add `EnvironmentFile=-/root/scalper/.env`. **Dashboards:** keep `:8088` gold + `:8089` btc (user choice) + portfolio banner & `GET /api/portfolio` (also merged into `/api/status`), `templates/index.html` portfolio CSS. `btc/strategy_btc.py` placeholder + per-hypothesis runbook. Verified: `backtest.py` **255 / +$456.58 PF 1.32**, `parity` **PASS 460/0**, `btc/tool --check` **11/11**, `btc/e2e_smoke` **ALL PASS** (`-$3.45` ×1 vs `-$344.72` ×100), `portfolio.py` shared/isolated & kill tests PASS, dashboards `/api/portfolio` live. | User chose `Go` on hybrid (`shared|isolated` in one `.env`), `revisit_strategy` for BTC (no reuse of inspected 20k), keep split dashboards + portfolio overlay. Makes shared-credential LIVE safe: combined loss/trades gate was the hard blocker (`btc/HANDOFF.md` §8-5) and `mt5.shutdown()` on shared bridge was the latent kill-both bug. BTC stays `FORWARD_TEST`+disabled until a Phase-1c gate (M15/H1 or Ultra Low or Donchian+sweep, on *untouched* data via `BTC_TIMEFRAME`) passes cold OOS `net>0 & PF≥1.2`. |
| 10-04 | **Paper balance reset $200 → $300 (`arena/01a106bd-scalper`)**: `SIM_START_BALANCE` bumped from 200.0 to **300.0** in both `config.py` (gold) and `btc/config.py` (BTC), with fallbacks in `paper.py` (`300.0`). No strategy/logic change — `backtest.py` still **255 / +$456.58 / PF 1.32 / maxDD $108.65 / 72-43-140**, `parity_test` **PASS 460/0**, `btc/tool.py --check` **11/11 PASS** (template now expects $300). `btc/e2e_smoke.py` fake account updated to 300.0. Server action needed: `mt5env/bin/python paper.py --reset` and `mt5env/bin/python btc/tool.py paper.py --reset` after deploy (paper state files `logs/paper_account.json` / `btc/logs/paper_account.json` carry across restarts). | User asked to reset dummy account to $300. Keeps both books comparable; backtest initial $1000 unchanged. Paper-book `SIM: \$ → SimEquity` on dashboards will start at $300 after reset; until reset they show the old persisted balance. |
| 10-03 | **BTCUSD Phase 1b closed: FAIL / No-Go, negative result recorded (`arena/01a102c4-scalper`)**: ran the `btc/HANDOFF.md` §5 sequence on the real `data/BTCUSD_M5.csv` (20,000 bars, `2026-07-25 21:55` .. `2026-10-03 13:40` UTC, 5,600 weekend bars, 24/24 hours) on `scalping` at `2026-10-03T17:07:55+00:00` (`/root/scalper` clean at `f5e76c8`) and wrote **`docs/btc_phase1_result_2026-10-03.md`**, the negative result §5 requires when the cold-OOS gate fails. `--verify` reproduced `backtest.py` exactly (**433 trades / −$165.84 / PF 0.74 / WR 23.8% / 103W-330L / avgR −0.46 / maxDD $169.46 / 107 TP · 59 BE · 267 SL / −$0.38 per trade**), then `btc/train_select.py` derived its ATR floors (`0.00/19.94/40.22/65.06/113.14`) and a `1.25× TRAIN p90 = 6,250`-point replay veto from TRAIN bars only (0.00% of TRAIN quotes vetoed, vs **100.00%** for the `MAX_SPREAD_POINTS=1500` placeholder), ranked the 60-config grid on TRAIN net, froze `ATR p75=113.14 SL=2.0 BE=off` (`44 tr, +$33.43, PF 1.29, maxDD $26.71`) and read cold OOS: **winner n=70, −$46.11, PF 0.75, maxDD $56.29, CI [−$126.90, +$37.82], P(net>0)=0.138**; **baseline n=217, −$95.50, PF 0.72, CI [−$190.49, +$0.45], P(net>0)=0.025** → **FAIL** (net < 0 and PF < 1.2). `btc/derive_params.py` gives the mechanism: median $77,304.55, `PRICE_DIGITS=2`, $0.0100 per 1.00 move, ATR(14) p05/p25/p50/p75/p90 = 18.88/48.32/81.62/121.31/179.03, spread mean 4,242 pts = 42.41 px = **$0.4242** round trip at 0.01 lots → SL 163.24 px = $1.63, TP 408.11 px = $4.08, **spread/median-ATR 52.0%**, **spread/risk 26.0%**, break-even WR 28.6% → **~36.0%** with spread (+7.4 pp) vs **23.8%** actual. `research/loss_analysis.py`: gross profit $465.72 / gross loss $631.55; 267 SL exits = **96.0%** of gross loss (−$606.26) vs 59 BE = 3.9% (−$24.90); **net before spread +$17.16 (+$0.04/trade) vs $183.00 spread paid** (28% of gross profit, avg $0.42/trade, 1R = avg $1.82) = −$165.84; BUY −$91.18 / SELL −$74.65; 4/4 months, 4/4 ATR quartiles and 6/7 weekdays negative; 76 losing streaks, mean 4.34, max 20. Every one-variable sweep is net-negative (SL 1.0× −$338.79 / 1.5× −$224.83 / 2.0× −$165.84 / 2.5× −$68.94 / 3.0× −$6.96; TP 2.0× −$266.97 … 6.0× −$157.43; BE 0.5R −$320.29 … off −$119.42; RSI 30/70 −$129.03, 35/65 −$182.03, 40/60 −$165.84, 45/55 −$177.76; spread 5.00 fallback −$4.49 PF 0.99, 42.41 mean −$166.49, 40.00 median −$156.04, 50.00 p90 −$199.34, per-bar CSV −$165.84). Server state recorded read-only: `scalper-bot` + `scalper-dashboard` **enabled/active** (`SIM: $128.62 \| SimEquity: $131.03`, open paper position undisturbed, `:8088` up), `scalper-btc-bot` + `scalper-btc-dashboard` **disabled/inactive** (`:8089` not listening; BTC bot stopped `16:50:21 UTC` after 0 trades with repeated `high_spread` skips at ~4,000 pts vs the 1,500-pt placeholder), bridge `18812` listening, `crontab -l` = deploy `*/15 * * * * DEPLOY_BRANCH=main` + two `paper_status_daily.sh` lines with **no** `DEPLOY_SERVICES`/`DEPLOY_SERVICE` override, deploy log `2026-10-03T17:07:44+00:00 restarted scalper-bot at f5e76c8… (was d8add56…) branch=main` (gold-only restart confirmed). **Documentation only — `config.py`, `btc/config.py`, `strategy.py`, `run.py` and all trading/engine parameters untouched; `TRADING_MODE` still `FORWARD_TEST` on both instances; no BTC unit installed, enabled or started.** Gold + BTC tests re-run locally: `backtest.py` **255 / +$456.58 / PF 1.32 / max DD $108.65 / WR 28.2% / 72-43-140 / avgR 0.11** (identical), `research/parity_test.py` **PASS** (460 signals, 0 mismatches, 20× cache reduction, blackout check clean), `btc/tool.py --check` **11/11 PASS**, `btc/train_select_test.py` **PASS**, `tests/test_deploy_services.sh` **PASS 3/3**. | User asked to record the completed Phase 1b negative result and the verified `scalping` server state without touching any config, strategy or engine parameter. `btc/HANDOFF.md` §5 makes a one-page negative result the deliverable and forbids a service when the cold-OOS gate fails; writing down the verdict and its structural cause (a ~52% spread-to-ATR ratio ⇒ ~36% required win rate vs 23.8% actual, with the spread costing ~10× the gross edge) is what stops a later session from re-searching the same inspected dataset, loosening the spread gate, or copying gold parameters onto an instrument where they cannot pay for the spread. Gold's paper clock is untouched and remains the binding constraint on any LIVE decision. |
| 10-03 | **BTC dashboard price-card label + `server_check.py` cron output (`arena/01a102b0-scalper`)**: confirmed `ssh scalping` and `/root/scalper/data/BTCUSD_M5.csv` remain unreachable from the Arena container (`e2b.local`), so no real-file Phase 1b result or live server state is claimed from the local checkout. Audited the BTC dashboard (`btc/dashboard.py` → `dashboard.py` → `templates/index.html`) and engine (`btc/run.py` → `run.py` → `mt5_bridge.py` → `logger.py`): `live.bid`, `live.ask`, and `live.spread` on `:8089` are genuine `BTCUSD` quotes read from `btc/logs/live_status.json`, while `templates/index.html` line 132 still had `<h2>GOLD Price</h2>` hard-coded. Replaced it with `<h2>{{ config.symbol if config is defined and config.symbol else "GOLD" }} Price</h2>` (`GOLD Price` on gold, `BTCUSD Price` on BTC) and added a template check in `btc/tool.py --check` (11/11 PASS). Also fixed `btc/server_check.py` `to_markdown()` to emit the already-collected `crontab -l` (`r["cron"]`) block, and documented why the transition deploy from `a4d6ecf` → `d8add56` started the disabled `scalper-btc-bot` unit (the pre-PR-#17 `deploy.sh` bound `SERVICES` before `git pull`). All gold regressions (`backtest.py` 255 / +$456.58 / PF 1.32, `parity_test.py`, `paper_exit_test.py`) and BTC tests (`e2e_smoke.py`, `train_select_test.py`, `test_deploy_services.sh`) PASS. | User asked to check whether the BTC dashboard displays the right instrument/price (suspecting the price is BTC while the label says Gold) and to check why the BTC bot was active after PR #17 merged. |
| 10-03 | **BTC Phase 1b prep + deploy safety (`arena/01a101b6-scalper`, PR #17)**: added `btc/train_select.py` because the existing `research/strategy_sweep.py --oos` and `--candidates` reports hard-code gold settings; the BTC selector ranks a fixed ATR-floor/SL/BE grid on TRAIN only, derives its spread veto from TRAIN p90, then reads one frozen winner and baseline on cold OOS. Added optional `Params.max_spread_points` to the replay engine (default off, preserving gold). `deploy.sh` now defaults to `scalper-bot` only—`systemctl restart` starts disabled-but-installed units—while Phase 2 can opt BTC in explicitly. Arena had no BTC CSV or reachable `scalping` host, so no real Phase 1b result or new server state is claimed. Gold regression, BTC isolation/e2e, selector helper, and mocked deploy tests passed; the selector's Gold CSV smoke was plumbing-only. | Make the real-file BTC test reproducible and stop the main deploy cron from starting an unauthorized BTC unit. |
| 10-03 | **BTC pre-data follow-through (`arena/01a1016f-scalper`)**: closed the two ⚠️ leftovers in `btc/HANDOFF.md` §4 (spread sweep levels and the parity fake tick are now derived from the loaded CSV/instrument rather than gold literals), added an optional, parity-tested **entry blackout** filter to shared code for 24/7 instruments (inert for gold), and added `btc/server_check.py` (read-only §0 evidence collector), `btc/derive_params.py` (CSV → candidate values for every flagged placeholder) and `docs/btc_market_reference_2026-10-03.md` (cited XM BTCUSD priors: contract, spread, leverage conflict, 24/7 + Saturday maintenance, Friday triple swap). **Gold unchanged and re-verified: backtest 255 / +$456.58 / PF 1.32 / max DD $108.65 / 72-43-140, parity PASS (460 signals, 0 mismatches + new blackout check), paper-exit PASS, `btc/tool.py --check` 10/10, `btc/e2e_smoke.py` ALL PASS both instances.** Nothing deployed; no server observation; `TRADING_MODE` still `FORWARD_TEST` on both instances. | User asked to follow through the pending BTC work and add a web reference sheet for bitcoin like the gold material. Phase 0/1 need the MT5 bridge, so this finishes everything that does not. |
| 10-03 | **BTC plumbing finished: `btc/e2e_smoke.py` + full pipeline dry-run (`arena/01a10125-scalper`)**: committed end-to-end smoke test (fake MT5 behind a real RPyC `SlaveService` on an ephemeral port, temp instance/log dir, refuses a non-FORWARD_TEST config) — 7/7 PASS on the BTC instance (`-$3.45` stop = 344.7 px × 0.01 × 1 BTC) and on the gold config dir (`-$344.72` = × 100 oz), so the contract-size hook is proven on both instruments. Ran the whole BTC research pipeline (sweep `--verify` ≡ `backtest.py`, `--oos` train/cold + 4-fold walk-forward, `loss_analysis`) under the BTC config on synthetic BTC-shaped bars — the tooling runs; the synthetic P&L is noise and is labelled as such. Small shared-code cleanups: `loss_analysis` prints `session=off` when the filter is disabled, the walk-forward header says "Price Δ%" instead of "Gold Δ%", and the order comment is now `getattr(config, "ORDER_COMMENT", ...)`. **Gold re-verified after all of it: backtest 255 / +$456.58 / PF 1.32 / max DD $108.65 / 72-43-140, parity PASS (460 signals, 0 mismatches), paper-exit PASS (M5 OHLC 48 / +$89.43 / PF 1.35), `btc/tool.py --check` 10/10.** PR [#14](https://github.com/shashidaren/scalper/pull/14) subsequently merged into `main` as `bfb1dff` at 2026-10-03 10:11:28 UTC. The merge does not prove server deployment; see `btc/HANDOFF.md` §0 for the required post-merge observation before any BTC-runtime claim. | Finish the BTC plumbing verification before Phase 0/1 need it. |
| 10-03 | **BTC scalper: separate handoff + Phase 1 plumbing (`arena/01a10125-scalper`)**: added `btc/HANDOFF.md` (reusability audit, instance-dir architecture, phased plan with gates, risks, server commands) and `btc/recon.py` (read-only Phase 0 probe: contract spec, spread-vs-ATR economics, weekday/hour coverage, writes `data/BTCUSD_M5.csv`; no orders and no `mt5.shutdown()` so the running gold bot is undisturbed; `--self-test` verified). Then the plumbing: ten hard-coded gold values became config keys with default-equal values (`CONTRACT_SIZE`, `PRICE_DIGITS`/POINT, `ATR_MIN`, `SL_ATR_MULT`, `TP_ATR_MULT`, `EMA_PERIOD`, `RSI_PERIOD`, `ATR_PERIOD`, plus `getattr`-style `LOG_DIR` and `DASHBOARD_TITLE`), and the BTC instance landed (`btc/config.py`, `_instance.py`, `run.py`, `dashboard.py` on :8089, `tool.py`, two systemd units, multi-service `deploy.sh`). **Proof it did not move gold: `backtest.py` still 255 / +$456.58 / PF 1.32 / max DD $108.65 / 72-43-140, `parity_test.py` PASS (460 signals, 0 mismatches), `btc/tool.py --check` 9/9, and a gold-valued instance config with a diverted `LOG_DIR` reproduces the same 255/+$456.58 through the hooked engine.** Nothing deployed; `btc/config.py` is all flagged placeholders and stays `FORWARD_TEST`. | User asked whether a bitcoin scalper is cheaper to set up on the back of this work, wanted it in a subfolder with its own port, and asked for a separate handoff. |
| 10-02 | **Loss analysis → decision: REMAIN, no parameter change (`arena/01a0fd8e-scalper`)**: added `research/loss_analysis.py` (per-trade loss anatomy: exit-type P&L decomposition, spread-vs-edge split, streak/day clustering, live-gate replay, conditional expectancy by hour/weekday/side/month/ATR quartile, MFE-excursion and tail/concentration stats) and `research/strategy_sweep.py --candidates` (train-select → cold-OOS → regime → walk-forward re-test of BE/SL/TP/time-exit/ATR-floor/session under the *adopted* config). Written up in `docs/loss_analysis_2026-10-02.md`. **`config.py`/`strategy.py`/`run.py`/`backtest.py` untouched; still `FORWARD_TEST`.** | User asked whether to change the strategy or remain after 183 of 255 trades lost. The losses are structural: 98.7% of gross loss is full stop-outs (−$1,388.93) while the 43 BE scratches cost $18.99 in total, and spread is only $112.24 = 6% of gross profit — so neither exit management nor costs are the leak; with a 1R stop / 2.5R target the structural break-even WR is 28.6% vs 28.2% actual, i.e. a thin tail-driven edge (top-5 winners = 57% of net). Re-testing the knobs the honest way killed every "obvious fix": the two best in-sample options (BE off +$563.46, SL 2.5×ATR +$520.66) are both *worse* on TRAIN alone, time exits lose at every length, and ATR floor 4.0 / BE 2.0R are TRAIN+ but OOS−. Only `TP 6.0×ATR` clears TRAIN + cold OOS + both regimes + 4/4 walk-forward folds (251 trades, +$538.06, PF 1.38), with `TP 6.0 + ATR floor 3.0` the only config whose 95% CI excludes zero (+$580.90, PF 1.44, max DD $98.98, P(net>0)=0.980) — pre-registered for the untouched OOS pull rather than adopted, because the gain is inside a ±$570 CI, the dataset was already inspected in PR #7/#11/#12, both cost trade frequency, and a third config change in three days would reset the §5 100-trade paper clock. Also closed two §5 TODOs by measurement: `MAX_CONSECUTIVE_LOSSES=4` would cost $31.49 (N=3: $184.34), and "skip Friday after 16:00 UTC" is backwards (Friday ≥16:00 is +$51.90/16 trades; the damage is 07:00 and 13:00). |
| 10-01 | **OOS validation, 1s paper-exit polling & closed-bar rate caching (`arena/01a0f77d-scalper`, PR #12)**: added `--oos` to `research/strategy_sweep.py` and `--bars`/`--start-pos`/`--out` to `fetch_data.py`; added `POSITION_CHECK_INTERVAL_SECONDS=1` (`config.py`), `poll_paper_position` (`run.py`), and `research/paper_exit_test.py`; cached closed-bar rates in `MT5Bridge.get_rates()` and closed-bar indicators in `ScalpStrategy.check_signal()`, verified in `research/parity_test.py`; documented in `docs/oos_and_execution_fidelity_2026-10-01.md` | Follow-up review after PR #11 flagged three gaps: (1) all tuned thresholds were evaluated on the full `GOLD_M5.csv` sample — chronological 50/50 and regime (`Jun–Jul` Bear/Range vs `Aug–Sep` Bull/Pullback) splits show train-only selection still picks `BE 1.5R, RSI 40/60, 07–20 UTC` (#1 of 60 on H1) and holds up cold on OOS (`+$170.52`, PF 1.27, `P(net>0)=0.838`; regime OOS PF 1.33, `P(net>0)=0.858`), though expectancy shrinks 37%, Q3 is flat (`+$5.81`, PF 1.02), and the 124-trade OOS CI still spans zero; (2) 15s snapshot polling in paper mode could miss fast wicks through SL/BE/TP — 1s polling while `paper.has_position()` closes that gap with 0 extra load when flat; (3) `get_rates()` was pulling 1,050 bars every 15s — caching by closed-bar timestamp cuts full RPyC fetches 20× with 0 signal/timing drift. Still `FORWARD_TEST`. |
| 10-01 | **Trade-frequency tuning (PR #11, `7635fad`, merged & verified on server)**: `RSI_BUY_LEVEL` 35→40, `RSI_SELL_LEVEL` 65→60, `SESSION_END_HOUR_UTC` 17→20 in `config.py`; fixed a float-precision bug in `research/strategy_sweep.py`'s `_rolling_mean` (cumsum → `pandas.rolling`, see `docs/strategy_iteration_2026-10-01.md`) | User reported the bot was "hardly taking any trades" (174 trades over ~101 backtest days, one-at-a-time, 10h session). Swept RSI thresholds and the session window one variable at a time; the combination gives 255 trades (+47%), net +$456.58 (was +$52.80), PF 1.32 (was 1.06), bootstrap P(net>0)=0.96 (was 0.60 — old config's CI spanned zero), profitable every month and both halves of the data. More trades *and* a better backtested edge, not a trade-off between them. Still `FORWARD_TEST` only — no validated live edge yet. |
| 09-30 | **Stale-tick warning check & HANDOFF update**: documented `Tick data unchanged for 20 cycles` (`STALE_TICK_WARN_CYCLES=20`, 5 min) and `Tick data frozen for 120 cycles - forcing reconnect` (`STALE_TICK_RECONNECT_CYCLES=120`, 30 min) in §1/§7; synced §2 (`BE_TRIGGER_R=1.5`, `INDICATOR_WINDOW_BARS=1000`, `INDICATOR_FETCH_MARGIN=50`) and §5 (`deploy.sh` default branch already `main`) | The warning observed around 21:00–22:00 UTC is the normal daily 1-hour XAUUSD/CME maintenance break (21:00–22:00 UTC / 05:00–06:00 Asia/KL, plus weekends Fri 21:00 → Sun 22:00 UTC). No ticks arrive during the break; the bot warns at 5 min, does a clean self-healing reconnect at 30 min, and resumes automatically at 22:00 UTC. Session filter (07:00–17:00 UTC) and closed-bar one-shot guard already block entries during that window. |
| 09-30 | **PR #7 follow-up — MERGED and DEPLOYED (`fc6f4fc`, PR #8 merged 11:04:30 UTC; verified on the server 11:06 UTC)**: `config.INDICATOR_FETCH_MARGIN = 50` (bridge fetches 1050 bars); `check_signal` slices to the last `INDICATOR_WINDOW_BARS`; `strategy.last_skip_reason` (`insufficient_bars:N<1000`, `session:hour=H`, `atr_low:x<0.50`, `no_setup:rsi=…`, `duplicate_bar`) logged as `reason` on `SIGNAL` events; parity test checks window+50 (real and poisoned margin bars) gives the same signal; `.gitignore` covers `.env.*` (except `.env.example`); `deploy.sh` recorded as 100755 | The server probe returned exactly 1000 bars vs a `>= 1000` guard: zero headroom, one missing bar would silence every signal as a bare `signal: null`. Slicing keeps live identical to the backtest (174 trades / PF 1.06 / +$52.80 / 41 TP / 29 BE / 104 SL unchanged). `.env.paper_status` was not ignored (server-local secret). The deploy.sh mode-only diff on the server blocked the first post-merge deploy. **Post-deploy verification (11:06 UTC):** server HEAD `fc6f4fc` with `INDICATOR_FETCH_MARGIN=50` / `INDICATOR_WINDOW_BARS=1000`; backtest reproduces 174 / PF 1.06 / +$52.80 / max DD $99.62; new `SIGNAL` lines carry `reason` (e.g. `no_setup:rsi=42.6(prev 43.1),close>ema200`) and **no `insufficient_bars`** — the margin fixed the headroom problem; bot restarted 11:06:21 UTC in FORWARD_TEST with no traceback; server `git status` clean and `deploy.sh` `-rwxr-xr-x`. |
| 09-30 | **PR #6 merged to `main`** (merge commit `40ec328`, 10:19:58 UTC); deploy cron confirmed as `*/15 * * * * DEPLOY_BRANCH=main /root/scalper/deploy.sh` | Gate 1+2 live-path hardening + backtest fix are now the production branch; hands-off deploy should carry `main` to the server within 15 min. **Confirmed on the server 11:06 UTC** (HEAD `fc6f4fc` includes it) — the §6 "Post-PR#6 verification" block is now covered by the PR #8 deploy check. |
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

- **2026-10-02 (`arena/01a0fd8e-scalper`):** User asked to analyse the losses
  and decide whether to change the strategy or remain. Built
  `research/loss_analysis.py` + `research/strategy_sweep.py --candidates` on top
  of the already-verified replay (`--verify` reproduces `backtest.py` exactly:
  255 / +$456.58 / PF 1.32 / 72-43-140; `parity_test.py` PASS, 460 signals /
  0 mismatches) and worked through the 183 losing trades
  (`docs/loss_analysis_2026-10-02.md`). **Decision: remain, change nothing.**
  The losses are the arithmetic of a 1R-stop / 2.5R-target book — 98.7% of gross
  loss is full stop-outs, the 43 BE scratches cost $18.99 in total, spread is 6%
  of gross profit, and the 28.2% WR sits just under the 28.6% structural
  break-even, so the edge is a thin tail (top-5 winners = 57% of net) rather than
  something broken. The valuable negative result: the in-sample sweeps are
  *misleading* on this file — "remove the BE ratchet" (+$563.46) and "widen the
  stop to 2.5×ATR" (+$520.66), the two biggest available in-sample gains, are
  both worse than the adopted config on TRAIN alone, so tuning on the full file
  would have adopted an OOS-half artefact. Surviving candidates (`TP 6.0×ATR`;
  `TP 6.0 + ATR floor 3.0`; `session 08-20`) are pre-registered for the untouched
  pre-June pull instead of being adopted now: the gain is inside a ±$570 CI, this
  CSV has been inspected in three PRs already, both cost the trade frequency
  PR #11 bought, and PR #11 only merged 2026-10-01 12:01:18 UTC so the paper book
  has ~1 day of data under it — a third config change in three days would reset
  the §5 100-trade clock for nothing. Two long-standing TODOs closed by
  measurement: wiring `MAX_CONSECUTIVE_LOSSES=4` would cost $31.49 (streaks do
  not predict more losses; N=3 costs $184.34), and the proposed "skip Friday
  after 16:00 UTC" filter is backwards (Friday ≥16:00 is +$51.90 over 16 trades;
  Friday's losses are 07:00 −$36.74 and 13:00 −$34.58). Also recorded:
  `atr_min = 0.50` never binds (file ATR min 1.22, 0.0000 of bars below it), and
  `backtest.py` ignores the live daily gates — replayed through them the same 255
  trades net $438.48 (−$18.10), which is the expected paper-vs-backtest offset.
- **2026-10-01 (follow-up, `arena/01a0f77d-scalper`):** Worked through the
  three post-PR #11 review items (`docs/oos_and_execution_fidelity_2026-10-01.md`):
  (1) **OOS validation:** added `research/strategy_sweep.py --oos` and
  `fetch_data.py --bars/--start-pos/--out`. Showed `data/GOLD_M5.csv` spans
  four regimes (June −11.0% sell-off, July +0.8% range, Aug +9.0% rally, Sept
  −1.4% pullback; overall −2.64%, correcting the earlier "+19% single bull
  regime" note). Under both a 50/50 chronological split and a `Jun–Jul` vs
  `Aug–Sep` regime split, train-only selection still picks `BE 1.5R, RSI 40/60,
  session 07–20` (#1 of 60 grid configs on H1: +$286.06, PF 1.37) and stays
  profitable cold on OOS (+$170.52, PF 1.27, P(net>0)=0.838 on H2; +$172.72,
  PF 1.33, P(net>0)=0.858 on `Aug–Sep`, with both BUY and SELL positive in
  both halves). However, OOS expectancy shrinks 37% ($2.18 → $1.38/tr), Q3
  (`2026-07-27..2026-08-19`) is flat (+$5.81 over 70 trades, PF 1.02, max DD
  $108.65), the 124-trade OOS CI `[−$159, +$525]` spans zero, and a truly
  untouched pre-June-2026 pull (`fetch_data.py --start-pos 20000`) must run on
  `scalping` where the MT5 bridge lives.
  (2) **Paper-mode exit fidelity:** added `POSITION_CHECK_INTERVAL_SECONDS=1`
  and `run.poll_paper_position` so open paper positions poll ticks every 1s
  (0 extra bridge load when flat), verified by `research/paper_exit_test.py`.
  (3) **Bridge rate caching:** `MT5Bridge.get_rates(tick=tick)` and
  `ScalpStrategy.check_signal()` now cache by closed-bar timestamp, cutting
  full 1,050-bar RPyC fetches 20× with 0 signal/timing mismatches in
  `research/parity_test.py`. `TRADING_MODE` stays `"FORWARD_TEST"`.
- **2026-10-01:** User reported the bot was "hardly taking any trades."
  Investigated with `research/strategy_sweep.py` (one-variable-at-a-time
  sweeps + bootstrap, same discipline as the 2026-09-30 iteration): the old
  config (RSI 35/65, session 07–17 UTC) only fires 174 trades over ~101
  backtest days, one at a time. Found a combination that increases frequency
  *and* improves the backtested edge rather than trading one off against the
  other: **RSI 40/60 + session 07–20 UTC** → 255 trades (+47%), net +$456.58
  (was +$52.80), PF 1.32 (was 1.06), bootstrap P(net>0)=0.96 (was 0.60).
  Checked robustness: a fine RSI scan (36/64…44/56) is a smooth hump, not a
  fluky single point; profitable in every calendar month and both halves of
  the data; ATR floor (0.30–0.60) never binds on this dataset so it wasn't
  the bottleneck. Also fixed a float-precision bug in the sweep tool's
  `_rolling_mean` that `research/parity_test.py` caught at exactly this new
  threshold (cumsum rolling mean vs. `strategy.py`'s windowed pandas rolling
  mean disagreed by ~1e-11 at one bar whose RSI tied 60.000...) — switched to
  `pandas.Series.rolling`, parity test now passes clean. Changed
  `config.py` only; **not yet merged or deployed** — see the §1 banner and
  `docs/strategy_iteration_2026-10-01.md`. `TRADING_MODE` stays
  `"FORWARD_TEST"`: this is a better backtest, not a validated live edge.
- **2026-09-30 (22:00 UTC / 2026-10-01 06:00 Asia/KL):** Checked the log
  warning `Tick data unchanged for 20 cycles - possible stale feed (market
  closed or terminal frozen)`. This is **benign and expected**: `run.py` checks
  `tick.time_msc` every 15s (`CHECK_INTERVAL_SECONDS=15`) and warns at 20
  cycles (5 min, `STALE_TICK_WARN_CYCLES=20`), then forces a clean bridge
  reconnect at 120 cycles (30 min, `STALE_TICK_RECONNECT_CYCLES=120`). Spot
  gold (`GOLD` on XM / CME Globex) closes daily from **21:00 to 22:00 UTC**
  (05:00–06:00 Asia/KL) for the NY rollover break and on weekends (**Fri 21:00
  → Sun 22:00 UTC**). During that break no new ticks arrive, the session filter
  (`07:00–17:00 UTC`) + closed-bar guard block any entries anyway, and
  `stale_tick_cycles` resets to 0 automatically on the first tick after 22:00
  UTC. Added both stale-tick signatures to §7 and cleaned up two stale notes in
  §2 (`BE_TRIGGER_R=1.5`) and §5 (`deploy.sh` default branch already `main`).
- **2026-09-30 (11:15):** PR #8 (`fc6f4fc`, the PR #7 follow-up) merged to
  `main` at 11:04:30 UTC and **auto-deployed to `scalping` via the 15-min cron**;
  verified on the server at 11:06 UTC (HEAD `fc6f4fc`, backtest 174 trades /
  PF 1.06 / +$52.80, `reason` present on new `SIGNAL` lines, no
  `insufficient_bars`, clean restart, clean `git status`, `deploy.sh` mode
  correct). This also closes the outstanding PR #6 deploy question: the cron
  chain PR #6 → #7 → #8 is proven to work hands-off. Live spread is running
  53–55 pts (~$0.54) vs the backtest's $0.47 mean — a live cost the backtest
  does not yet model. §5 "Post-follow-up verification" and the skip-reason
  diagnostics item are checked off. **No strategy work this session** and none
  should follow from it: the bootstrap CI still spans zero, so
  `TRADING_MODE` stays `"FORWARD_TEST"`.
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
  `main` is the production target, and `deploy.sh`'s fallback default
  (`BRANCH="${DEPLOY_BRANCH:-main}"`) was also updated to `main` in PR #7
  (`22ddba9`).
- [ ] Restore or re-apply stashed `paper_status_daily.sh` edits from
  `/root/paper_status_daily.sh.backup` if still wanted. Status cron is
  confirmed (01:15 UTC daily + 01:00 UTC Mon–Fri, server-only
  `/root/scalper/scripts/paper_status_daily.sh`); **decided 2026-10-07 — the
  weekday line is a duplicate** (same script 15 min apart): keep one daily run
  (`7 1 * * *`, off the deploy ticks) and delete `0 1 * * 1-5`, or if a
  weekday-only report is really wanted make the daily line `15 1 * * 0,6`.
  Move the script (and `.env.paper_status`) **out of the deployed tree** to
  `/root/ops/` — `/root/scalper` is the pull target, so a future commit adding
  `scripts/` would make every `git pull --ff-only` abort (and a `.gitignore`
  workaround would let git clobber it). See `docs/cron_review_2026-10-07.md` §4.
- [ ] **Install the reviewed crontab on `scalping`** (2026-10-07 review):
  back up `crontab -l`, add `SHELL`/`PATH`(mt5env)/`MAILTO`/`CRON_TZ=UTC`,
  prefix the deploy line with `mkdir -p /root/scalper/logs &&`, dedupe the
  status lines, and decide on `DEPLOY_SERVICES="scalper-bot scalper-dashboard"`
  (the dashboard is otherwise never restarted, so `dashboard.py` fixes — e.g.
  PR #22's gate banner — do not go live; templates hot-reload, modules do not).
  Checklist: `docs/cron_review_2026-10-07.md` §6.
- [ ] **Confirm the dashboard picked up PR #22:** `systemctl show
  scalper-dashboard -p ActiveEnterTimestamp` — if it predates 2026-10-06,
  `systemctl restart scalper-dashboard`, then check the `:8088` price card for
  the spread-gate banner/`gate N, M% vetoed`.
- [ ] Decide whether `services/*.service` should be copied to
  `/etc/systemd/system` + `daemon-reload` by the deploy (today a unit edit is
  pulled but never applied; no auto-install was added deliberately).
- [ ] Paper-test RSI 35/65 (deployed 09:36 UTC as `4a21a33`); compare with the
  30/70 baseline using trade count, net expectancy after spread, drawdown,
  and session coverage.
- [x] Add signal skip-reason diagnostics — `strategy.last_skip_reason`, logged
  as `reason` on `SIGNAL` events. **Done and verified on the server
  2026-09-30 11:06 UTC** (PR #8, `fc6f4fc`): new `SIGNAL` lines in
  `logs/trades.jsonl` carry e.g. `no_setup:rsi=42.6(prev 43.1),close>ema200`,
  and **no `insufficient_bars`** has been seen — the
  `INDICATOR_FETCH_MARGIN = 50` headroom is doing its job.
- [x] Fix backtest input-length mismatch — **done 09-30 on
  `arena/01a0f1c8-scalper`** (`WINDOW_BARS=202`, entry at signal-bar close,
  manage from next bar). First results: PF 0.92 / −$58 over ~70 days — later
  shown to be flattered by measurement bugs; see the 2026-09-30 strategy
  iteration row in §3 and `docs/strategy_iteration_2026-09-30.md`.
- [x] **Merge the Gate 1+2 PR** — PR #6 merged to `main` 2026-09-30 10:19:58 UTC
  (`40ec328`).
- [x] **Confirm the deploy actually landed on the server** — **done
  2026-09-30 11:06 UTC** (was run on `scalping`). Server HEAD is `fc6f4fc`
  (PR #8), so PR #6 (`40ec328`) and PR #7 (`e12e845`) are on the server too —
  the `*/15 * * * * DEPLOY_BRANCH=main deploy.sh` cron carried all three
  hands-off. `live_ledger.py` present, `journalctl -u scalper-bot` banner shows
  the new HEAD with a clean restart (11:06:21 UTC, no traceback), and
  `mt5env/bin/python backtest.py` prints **174 trades / PF 1.06 / +$52.80** (not
  0, not 201 — 201/0.92 was the pre-strategy-iteration default). Only
  `logs/live_ledger.json` was left unchecked (LIVE-only by design; it is part
  of the first-LIVE-run verification below).
- [~] **Strategy work (blocking for LIVE):** first iteration done 2026-09-30
  (`docs/strategy_iteration_2026-09-30.md`). Tested one variable at a time:
  **BE trigger → 1.5R (adopted)**, ATR multiples (only monotone via wider SL,
  never positive alone — not adopted), **session 08–16 UTC (rejected: worse)**,
  **H1 trend confirmation (rejected: clearly worse)**, RSI 40/60 (rejected
  at the time: non-monotone *under the old 07-17 session* — superseded
  2026-10-01, see below), TP multiples (rejected: noise). Also fixed the
  indicator warm-up and the spread assumption. **2026-10-01 OOS check
  (`docs/oos_and_execution_fidelity_2026-10-01.md`):** retrospective 50/50 and
  regime (`Jun–Jul` Bear/Range vs `Aug–Sep` Bull/Pullback) splits confirm
  train-only tuning selects `BE 1.5R, RSI 40/60, session 07–20` (#1 of 60 on
  H1) and stays positive cold on H2 (+$170.52, PF 1.27, P(net>0)=0.838) and on
  `Aug–Sep` (+$172.72, PF 1.33, P(net>0)=0.858), but expectancy shrinks 37%,
  Q3 (`2026-07-27..2026-08-19`) is flat (+$5.81, PF 1.02), and a single
  ~120-trade OOS slice's 95% CI still spans zero. **Still open:** run a
  strictly untouched pre-June-2026 / 60k-bar OOS pull on the `scalping` server
  (where the MT5 bridge is reachable — see TODO below), model slippage + swap,
  and compare backtest vs paper book trade-by-trade. Remaining untested
  candidates: Friday cutoff, tighter ATR/volatility filters, exit-time limit.
  **2026-10-02 update (`docs/loss_analysis_2026-10-02.md`):** all three of those
  candidates are now measured. The Friday cutoff is *backwards* (Friday ≥ 16:00 UTC
  is +$51.90/16 trades), every exit-time limit 12–72 bars is worse on TRAIN, and
  the ATR/volatility filter does have signal — but note `atr_min = 0.50` **never
  binds** (file ATR min 1.22, 0.0000 of bars below 0.50), so "tightening" it means
  moving it ~6× up to where the data actually starts (2.5–3.5), which costs
  trade frequency. See the pre-registered-candidates TODO below.
- [x] **Merge + deploy PR #11 RSI/session change** (`7635fad`, merged
  2026-10-01 12:00:13 UTC; `config.py`: RSI 40/60, session 07-20 UTC) —
  verified on the server: 255 trades / PF 1.32 / +$456.58 / max DD $108.65.
- [ ] **Run untouched historical OOS pull on `scalping` (requires MT5 bridge)**
  and verify PR #12 deploy (1s paper-exit polling + 20× bridge rate caching):
  ```bash
  cd /root/scalper
  mt5env/bin/python research/parity_test.py
  mt5env/bin/python research/paper_exit_test.py
  mt5env/bin/python fetch_data.py --bars 20000 --start-pos 20000 --out data/GOLD_M5_pre_jun.csv
  mt5env/bin/python research/strategy_sweep.py --csv data/GOLD_M5_pre_jun.csv --detail --bootstrap 10000
  mt5env/bin/python fetch_data.py --bars 60000 --out data/GOLD_M5_60k.csv
  mt5env/bin/python research/strategy_sweep.py --csv data/GOLD_M5_60k.csv --oos
  ```
  Re-run periodically (e.g. monthly) as fresh live history accumulates so the
  post-`2026-09-11` window also serves as a growing prospective OOS sample.
- [ ] Judge the paper book after 100+ trades across sessions **and** a
  profitable backtest over ≥6 months; only then flip
  `TRADING_MODE = "LIVE"` in `config.py` (+ restart service). Pre-agreed
  launch criteria: expectancy > 0 after spread, PF > ~1.2, max DD affordable.
  **Count the 100+ trades from the PR #11 deploy (~2026-10-01 12:15 UTC)** —
  `gh` confirms PR #11 merged at 2026-10-01 12:01:18 UTC and the 15-min cron
  deploys `main`, so the 40/60 + 07-20 config is what the paper book has been
  running since then (the older note here saying "not yet deployed" was stale).
  `logs/paper_account.json` carries across restarts, so filter by timestamp:
  `grep -E 'SIM_(ENTRY|EXIT)' logs/trades.jsonl | awk -F'"' '$4 >= "2026-10-01 12:15:00"' | wc -l`
  (divide by 2 for round trips). Balance was $151.26 at 2026-09-30 11:06 UTC
  (last check before the 2026-10-02 session; that figure still includes the old
  35/65 config). **As of 2026-10-02 this sample is only ~1 day old — that, not
  the backtest, is the binding constraint on any LIVE decision.**
- [ ] **Pre-registered strategy candidates (do NOT adopt without fresh data).**
  The 2026-10-02 loss analysis (`docs/loss_analysis_2026-10-02.md` §5,
  `research/strategy_sweep.py --candidates`) found exactly one lever that
  survives train-select → cold OOS → both regimes → 4/4 walk-forward folds, and
  one combination whose 95% bootstrap CI excludes zero:
  1. `TP` multiple 5.0 → **6.0** (251 trades, +$538.06, PF 1.38, max DD $104.49,
     P(net>0)=0.968; repairs the weak quarters — Q3 +$45.6 vs +$5.8).
  2. **TP 6.0 + `atr_min` 3.0** (228 trades, +$580.90, PF 1.44, max DD $98.98,
     CI [+$25.48, +$1,145.70], P(net>0)=0.980) — note it cuts trades 255 → 228.
  3. `SESSION_START_HOUR_UTC` 7 → **8** (08-20: TRAIN +$317.06, OOS +$223.36).
  Re-run all three on the untouched pre-June-2026 pull **and** on post-2026-09-11
  history; adopt only if still better there. Explicitly **rejected** (in-sample
  gains that fail train-only selection): BE off, BE 2.0R, SL 2.5/3.0xATR, every
  time-exit length, ATR floor 4.0, and session 09-20 (fails walk-forward Q3).
- [ ] Live-mode verification on first LIVE run: confirm `LIVE_EXIT` events
  land in `logs/trades.jsonl` when broker-side SL/TP fill, daily stats update,
  and the loss gate actually halts entries; test the KILL_SWITCH file.
- [x] Wire `MAX_CONSECUTIVE_LOSSES` (defined in config.py, currently unused) —
  **measured and rejected 2026-10-02** (`research/loss_analysis.py`,
  `docs/loss_analysis_2026-10-02.md` §3): pausing for the rest of the day after
  N straight losses costs net **−$31.49 at N=4** (the config value), −$184.34 at
  N=3, −$29.08 at N=5, −$21.98 at N=6. Losing streaks (58 runs, mean 3.16, max 10)
  are *not* followed by more losses in this sample, so the pause only skips
  trades that were net profitable. Leave the constant as documentation (or delete
  it); do **not** wire it. Re-measure if a future dataset shows streak persistence.
- [x] Optional next filter: skip new entries after 16:00 UTC on Friday —
  **closed 2026-10-02, the data says the opposite**
  (`docs/loss_analysis_2026-10-02.md` §6): Friday ≥16:00 UTC is **+$51.90 over
  16 trades** (Fri 16:00 +$63.31, Fri 17:00 +$25.15), i.e. the profitable part of
  the day. Friday's net −$66.17 comes from the morning/early afternoon
  (Fri 07:00 −$36.74, Fri 13:00 −$34.58). Adopting the filter as written would
  cut Friday's winners and keep its losers. Hour/weekday buckets are 16–32 trades
  each — too thin to select on in any case.
- [ ] Backtester realism: model slippage (paper fills are zero-slippage ticks),
  add swap for overnight holds, and compare backtest vs paper book trade-by-trade.
  **Two measured gaps to fold in (2026-10-02, `docs/loss_analysis_2026-10-02.md`
  §3):** `backtest.py` does not model the live `MAX_DAILY_LOSS` /
  `MAX_TRADES_PER_DAY` gates — replaying the same 255 trades through them nets
  **$438.48 instead of $456.58 (−$18.10)** and blocks 5 trades, so a paper-vs-
  backtest comparison should expect roughly that offset before blaming the fills;
  and spread is only **$112.24 = 6% of gross profit**, so slippage/swap modelling
  has room to matter but costs are not the current leak.
- [ ] Consider: GOLD symbol naming (`config.SYMBOL="GOLD"` works today on
  XMGlobal; revisit if broker changes it).
- [ ] After more paper data: experiment with H1 trend confirmation or tighter
  session window (e.g. 08–16 UTC only).
- [ ] Optional next filter: skip new entries after 16:00 UTC on Friday (thin gold).
- [x] **BTCUSD scalper — Phase 1b answered: FAIL / No-Go (closed 2026-10-03,
  `arena/01a102c4-scalper`; separate handoff: `btc/HANDOFF.md`,
  write-up: `docs/btc_phase1_result_2026-10-03.md`).** Plumbing, pre-data
  follow-through, and the Phase 1b selector/deploy guard are merged (PR #14
  `bfb1dff`, #15, #16 `a4d6ecf`, #17 `d8add56`, #18 `f5e76c8`), and the
  decision gate has now been run on real XM data.
  - **Verdict.** On `scalping` at `2026-10-03T17:07:55+00:00` (`/root/scalper`
    clean at `f5e76c8`, `data/BTCUSD_M5.csv` = 20,000 bars,
    `2026-07-25 21:55` .. `2026-10-03 13:40` UTC, M1 absent): `--verify`
    reproduced `backtest.py` exactly (**433 trades / −$165.84 / PF 0.74 /
    WR 23.8% / 107 TP · 59 BE · 267 SL**), then `btc/train_select.py` **FAILED**
    the gate — frozen TRAIN winner (`ATR p75=113.14 SL=2.0 BE=off`) reads
    **n=70, −$46.11, PF 0.75, P(net>0)=0.138** on cold OOS, baseline
    **n=217, −$95.50, PF 0.72**, against a requirement of positive cold-OOS net
    and PF ≳ 1.2. Every one-variable sweep (SL/TP/BE/RSI/spread) over all
    20,000 bars is net-negative; all 4 months, all 4 ATR quartiles, 6 of 7
    weekdays and both directions lose.
  - **Cause (structural, not tunable).** Spread is **52.0% of median ATR** and
    **26.0% of a 2×ATR stop** ($0.4242 round trip at 0.01 lots vs a $1.63 stop),
    so the required win rate is **~36.0%** vs **23.8%** actual. Net before
    spread is **+$17.16 (+$0.04/trade)** against **$183.00** spread paid
    (28% of gross profit) — the signal is coin-flip-neutral and the cost is
    ~10× the gross edge. Charging the 5.00 config-fallback spread instead of
    the real one moves the result only from −$165.84 to −$4.49 (PF 0.99).
  - **Server state verified read-only.** `scalper-bot` + `scalper-dashboard`
    `enabled`/`active` (`SIM: $128.62 | SimEquity: $131.03`, open paper position
    undisturbed, `:8088` up); `scalper-btc-bot` + `scalper-btc-dashboard`
    **`disabled` + `inactive`** (`:8089` not listening) — the unit the
    `a4d6ecf` → `d8add56` transition deploy had started was stopped at
    `16:50:21 UTC` after **0 trades** with repeated `high_spread` skips at
    ~4,000 pts vs the 1,500-pt placeholder; bridge `18812` listening; deploy
    cron `*/15 * * * * DEPLOY_BRANCH=main` with **no**
    `DEPLOY_SERVICES`/`DEPLOY_SERVICE` override; last deploy line
    `restarted scalper-bot at f5e76c8… (was d8add56…) branch=main`
    (gold-only restart confirmed, so the PR #17 guard works).
  - **Standing rules from here.** **No BTC service** and Phase 2 stays blocked.
    Do **not** tune on the OOS half, do **not** re-run the grid after seeing
    OOS, do **not** loosen `MAX_SPREAD_POINTS` to let a losing strategy trade,
    and do **not** copy gold parameters onto BTC. `research/strategy_sweep.py
    --oos` / `--candidates` remain gold-specific and must not be read as BTC
    selection results. `config.py`, `btc/config.py`, `strategy.py` and `run.py`
    were **not** modified; `TRADING_MODE` is still `"FORWARD_TEST"` on both
    instances, and gold re-verified unchanged (**255 / +$456.58 / PF 1.32 /
    max DD $108.65 / 72-43-140**; parity, `btc/tool.py --check` 11/11,
    `btc/train_select_test.py`, `tests/test_deploy_services.sh` 3/3 all PASS).
- [x] **BTC "no trades / high spread" explained and instrumented (2026-10-06,
  `arena/037cb1f4-scalper`; `btc/HANDOFF.md` §7a/§9,
  `docs/btc_spread_edge_analysis_2026-10-06.md`).** The engine skips every
  cycle while `spread_points > config.MAX_SPREAD_POINTS`
  (`SKIP {"reason":"high_spread"}`) and `btc/config.py` still carries the
  1,500-pt placeholder against a real 4,242-pt mean spread → **100% veto**,
  `strategy.check_signal()` never runs. The gate was **not** raised (§5 rule:
  a passing hypothesis first, and Phase 1b already showed the shape loses
  after such a gate). Shared-code additions are telemetry only: `spread_gate.py`
  + a `spread_gate` field in `live_status.json` + a dashboard banner
  ("NO ENTRY IS POSSIBLE…") + `btc/preflight.py` (exit 0/1/2/3) +
  `btc/edge_screen.py` + `btc/breakout_screen.py`, with gold re-verified
  unchanged (255 / +$456.58 / PF 1.32; parity PASS 460/0; `btc/tool.py --check`
  14/14; `e2e_smoke` ALL PASS; `test_spread_gate.py` 21/21). Phase 1c
  amendment (proxy-screened, non-evidence): A deprioritised, B not binding,
  **C (H1 Donchian breakout) pre-registered as the next untouched-data trial**.
  Any future `run.py`/`logger.py` reader: the gate comparison is unchanged and
  `spread_gate` is optional (`None`), so old writers/dashboards still work.
- [ ] **If BTC is ever revisited, it needs a new pre-registered hypothesis —
  not another pass over this file.** The 20,000-bar
  `2026-07-25 .. 2026-10-03` window has now been inspected, so reusing it for a
  fresh search would be tuning on inspected data. Untested and *not* ruled out:
  a wider timeframe (M15/H1, where a stop dwarfs the ~$0.42 spread), a
  lower-spread account tier, or a strategy family that is not
  spread-dominated. Any attempt must re-run the same train-select → cold-OOS
  gate on its own untouched pull, and must first re-derive
  `MAX_DAILY_LOSS`/`MAX_TRADES_PER_DAY` (measured avg 1R = $1.82 with a max
  20-trade losing streak, so the $8 daily gate and 15-trade cap are both
  mis-scaled) and run the §7 shared-bridge concurrency probe before any BTC
  unit is installed or started. Swap P&L and slippage are still unmodelled and
  `data/BTCUSD_M1.csv` is still absent, so intra-bar exit ordering is
  unmeasured — both would make any future result worse, not better.

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
mt5env/bin/python research/parity_test.py                      # live vs backtest signals + 20x bridge cache check (2s)
mt5env/bin/python research/paper_exit_test.py                  # fake-bridge 1s paper-exit wick tests + M1/M5 comparison
mt5env/bin/python research/strategy_sweep.py --verify          # equivalence check (do this first)
mt5env/bin/python research/strategy_sweep.py --oos             # chronological 50/50 + regime OOS split + 4-fold walk-forward
mt5env/bin/python research/strategy_sweep.py --sweep be
mt5env/bin/python research/strategy_sweep.py --detail --set be_trigger_r=1.5
mt5env/bin/python research/strategy_sweep.py --bootstrap 5000 --set be_trigger_r=1.5

# loss analysis (2026-10-02): where the money actually goes, per trade
mt5env/bin/python research/loss_analysis.py                    # exit/cost/streak/hour/ATR anatomy + gate replay
mt5env/bin/python research/loss_analysis.py --json trades.json # + per-trade dump for ad-hoc slicing
# candidate re-test under the ADOPTED config: select on TRAIN, read OOS cold,
# then regime split + 4-fold walk-forward (use this, not --sweep, to decide)
mt5env/bin/python research/strategy_sweep.py --candidates
mt5env/bin/python research/strategy_sweep.py --detail --bootstrap 10000 --set tp_atr_mult=6.0

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

# --- Post-follow-up verification (PR #7 follow-up: fetch margin + skip reasons) ---
# ✅ RUN AND PASSED on `scalping` 2026-09-30 11:06 UTC, HEAD fc6f4fc (PR #8).
#    Re-run only if the server HEAD moves away from fc6f4fc.
cd /root/scalper
git log -1 --format='%h %s'                                          # expect the follow-up merge
grep -E '^INDICATOR_FETCH_MARGIN|^INDICATOR_WINDOW_BARS' config.py   # 50 / 1000
mt5env/bin/python backtest.py                                        # expect 174 / PF 1.06 / +$52.80
grep SIGNAL logs/trades.jsonl | tail -3                              # new entries carry "reason"
journalctl -u scalper-bot -n 20 --no-pager

# hands-off deploy cron (every 15 min; restarts only when a runtime path changed)
# crontab -e  → set DEPLOY_BRANCH to the intended production branch:
# */15 * * * * mkdir -p /root/scalper/logs && DEPLOY_BRANCH=main /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1
# Full reviewed crontab (PATH/MAILTO/CRON_TZ + the deduped status line):
#   docs/cron_review_2026-10-07.md §4

# deploy decisions, newest last (restart = runtime file changed):
tail -5 /root/scalper/logs/deploy.log
#   restarted scalper-bot at <sha> (was <sha>) branch=main          <- runtime change
#   <ts>; restart skipped for scalper-bot (no runtime path changed) <- inert commit (docs/btc/tests/…)
#   <ts> already up to date (<sha>) branch=main                     <- nothing landed
#   <ts> deploy already running (lock …) - skipped                  <- overlapping run, expected 0
# force a restart by hand if a filter verdict is ever disputed:
cd /root/scalper && DEPLOY_FORCE_RESTART=1 ./deploy.sh

# manual deploy (if main is the intended production branch)
cd /root/scalper && git fetch origin && git checkout main && git pull --ff-only origin main && systemctl restart scalper-bot
```

## 6b. Cron review (2026-10-07) — what to install and check

Full write-up: **`docs/cron_review_2026-10-07.md`**. Summary of the three
recorded lines: keep the `*/15` deploy (add the `mkdir -p logs &&` prefix);
keep one daily status report at `7 1 * * *`; **delete `0 1 * * 1-5`** (weekday
duplicate). Recommended crontab, in full:

```
SHELL=/bin/bash
PATH=/root/scalper/mt5env/bin:/usr/local/bin:/usr/bin:/bin
MAILTO=root
CRON_TZ=UTC

# Deploy: pull main every 15 min. deploy.sh restarts only when a runtime path
# changed and holds logs/deploy.lock so runs cannot overlap.
*/15 * * * * mkdir -p /root/scalper/logs && DEPLOY_BRANCH=main /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1

# Paper status: ONE report per day, 7 minutes after the 01:00 deploy tick.
7 1 * * * test -x /root/ops/paper_status_daily.sh && /root/ops/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1 || echo "$(date -Is) paper_status missing or exited non-zero" >> /root/scalper/logs/paper_status.cron.log
```

Optional: add `DEPLOY_SERVICES=scalper-bot scalper-dashboard` to the deploy
line so `dashboard.py` fixes (e.g. PR #22's banner) actually reach `:8088`.

## 7. Failure signatures (what each error means)

| Symptom | Meaning |
|---|---|
| `Connection refused ...:18812` | MT5 container down/booting (or crash-looping — check §4) |
| `[Errno 104] Connection reset by peer` | docker-proxy flapping while container restarts; benign during boot |
| `pickling is disabled` | rpyc client missing classic flags — fixed in `78fe7e8`; if it returns, something recreated the bridge without them |
| `Market data temporarily unavailable` | tick/symbol issue (symbol missing, terminal not logged in) |
| `Tick data unchanged for 20 cycles - possible stale feed (market closed or terminal frozen)` | **Benign outside trading hours:** 20 loops × 15s = 5 min with unchanged `tick.time_msc`. Expected every weekday during the daily gold maintenance/rollover break (**21:00–22:00 UTC** / 05:00–06:00 Asia/KL) and all weekend (**Fri 21:00 → Sun 22:00 UTC**). Self-clears on the first new tick at reopen; session filter (`07:00–17:00 UTC`) + closed-bar guard block entries outside hours anyway. Only investigate if it fires persistently during active London/NY hours (`07:00–17:00 UTC`) on a weekday. |
| `Tick data frozen for 120 cycles - forcing reconnect` (+ 3× `Loop error` → reconnect) | **Benign during market close / rollover:** 120 loops × 15s = 30 min with unchanged `tick.time_msc`. The watchdog forces a clean MT5 bridge reconnect (`reconnect_count` increments by 1; expect ~1 reconnect during the daily 21:00–22:00 UTC break and ~1 every 30 min over the weekend). Self-heals when quotes resume. |
| container `Restarting (1)` silently | upstream `set -e` bugs (§4) |
| `Insufficient free margin ... order not sent` | margin pre-flight blocked the LIVE order (see `mt5_bridge._margin_ok`) |
| `Transient fill failure retcode=... retrying` | requote/price-moved during LIVE entry; retried with a fresh tick |
| `KILL_SWITCH detected` | `logs/KILL_SWITCH` exists → new entries disabled; remove file to resume |
| `Live close detection: history_deals_get failed` | deal-history read hiccup in LIVE; next poll retries (no PnL lost) |

## 8. Session protocol

1. Day-to-day strategy work on the session Arena branch (currently
   `arena/01a0fd8e-scalper`; each Arena session gets its own, so verify with
   `git branch --show-current` rather than trusting this line); promote to
   `main` via PR, rebasing onto current `main` when history diverges (squash
   merges).
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
