# HANDOFF — Gold Scalper (live engine + paper mode)

Read this first in a new session. **Keep it honest:** any session that changes
code, parameters, or the server must update §1 (state), §3 (changelog) and
§5 (TODOs) before it ends, and push its commits.

---

## 1. Where things stand (as of 2026-10-02)

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
`SIM_START_BALANCE=200`, `BE_TRIGGER_R=1.5`, `INDICATOR_WINDOW_BARS=1000`,
`INDICATOR_FETCH_MARGIN=50`, `CHECK_INTERVAL_SECONDS=15`,
`POSITION_CHECK_INTERVAL_SECONDS=1`, `RPC_TIMEOUT_SECONDS=30`, backoff caps,
stale-tick thresholds (`STALE_TICK_WARN_CYCLES=20`,
`STALE_TICK_RECONNECT_CYCLES=120`), **SESSION_FILTER_***, **RSI_*_LEVEL**,
**SIGNAL_ON_CLOSED_BAR**.

## 3. Changelog (what was done and why)

| Date | Change | Why |
|---|---|---|
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
  `/root/scalper/scripts/paper_status_daily.sh`); double-run on weekdays may be
  intentional or a leftover — decide and clean up. Keep `.env.paper_status`
  private — never commit it.
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
