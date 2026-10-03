# HANDOFF — Bitcoin (BTCUSD) Scalper

> ## ⛔ Status 2026-10-03 (latest): **Phase 1b FAILED — No-Go.** BTC has no edge at XM's spread; there is no service and Phase 2 is blocked.
>
> The Phase 1b decision gate — `btc/train_select.py` on the real 20,000-bar
> `data/BTCUSD_M5.csv`, observed on `scalping` at
> `2026-10-03T17:07:55+00:00` with `/root/scalper` clean at `f5e76c8` —
> returned **FAIL**. The frozen TRAIN-selected candidate
> (`ATR p75=113.14, SL=2.0, BE=off`) is **negative on cold OOS**:
> `n=70, net −$46.11, PF 0.75, maxDD $56.29, iid 95% CI [−$126.90, +$37.82],
> P(net>0)=0.138` — against a gate requiring positive cold-OOS net **and**
> PF ≳ 1.2. The pre-registered baseline is worse
> (`n=217, −$95.50, PF 0.72, P(net>0)=0.025`). Expectancy decays from
> **+$0.76/trade on TRAIN to −$0.66/trade on OOS**, i.e. the in-sample edge is
> selection noise.
>
> The cause is **structural, not a tuning problem**. Measured on the same file:
> **spread / median ATR = 52.0%**, **spread / risk = 26.0%** (gold pays ~5.3% of
> a stop), so the required win rate is **~36.0%** vs **23.8%** actual; net
> before spread is only **+$17.16 (+$0.04/trade)** against **$183.00** of
> spread paid (28% of gross profit); and 96.0% of gross loss is 267 full
> stop-outs while the 59 breakeven scratches cost $24.90 in total. Every
> one-variable sweep (SL / TP / BE / RSI / spread) over all 20,000 bars is
> net-negative, and all 4 months, all 4 ATR quartiles, 6 of 7 weekdays and both
> directions lose. The spread row is the cleanest proof: charging the 5.00
> config fallback instead of the real spread moves the result from −$165.84 to
> −$4.49 (PF 0.99) — nearly the whole loss is the spread, and even then there
> is no gross edge.
>
> **Full write-up: `docs/btc_phase1_result_2026-10-03.md`.** Per §5, a negative
> result is the deliverable and there is **no service**:
> `scalper-btc-bot` and `scalper-btc-dashboard` are `disabled`/`inactive` on
> `scalping` (`:8089` not listening; the unauthorized unit that started during
> the `a4d6ecf` → `d8add56` transition deploy was stopped at `16:50:21 UTC`
> after 0 trades), `deploy.sh` keeps its gold-only default, and `crontab -l`
> has **no** `DEPLOY_SERVICES`/`DEPLOY_SERVICE` override. **Do not tune on OOS,
> do not loosen `MAX_SPREAD_POINTS` to let a losing strategy trade, and do not
> copy gold parameters.** A future attempt needs a new pre-registered
> hypothesis (different timeframe or account tier) and its own untouched data
> pull — reusing this file would be tuning on inspected data.
>
> **This was a documentation-only change.** No config, strategy, engine or
> trading parameter was touched: `config.py`, `btc/config.py`, `strategy.py`
> and `run.py` are unmodified, and `TRADING_MODE` stays `"FORWARD_TEST"` on
> both instances. Gold re-verified locally on branch `arena/01a102c4-scalper`:
> `backtest.py` **255 / +$456.58 / PF 1.32 / max DD $108.65 / 72-43-140**,
> `research/parity_test.py` **PASS** (460 signals, 0 mismatches),
> `btc/tool.py --check` **11/11 PASS**, `btc/train_select_test.py` **PASS**,
> `tests/test_deploy_services.sh` **PASS 3/3**.
>
> **Provenance:** this Arena container cannot resolve `scalping` and holds only
> the gold CSVs (`data/*.csv` is git-ignored), so the BTC numbers above are the
> server run's recorded output, not a local reproduction. The five checks in
> the previous paragraph *were* re-run locally.

> **Status 2026-10-03: plumbing is merged; BTC trading is not authorised.**
> PR [#14](https://github.com/shashidaren/scalper/pull/14) merged into `main` as
> `bfb1dff` at **2026-10-03 10:11:28 UTC**. The code was verified locally before
> merge and gold's regression reproduced bit-for-bit (§6). `TRADING_MODE` remains
> `"FORWARD_TEST"` in `btc/config.py`; every BTC parameter is an explicit
> placeholder to be derived from BTC data in Phase 1.
>
> **Server status is deliberately unknown after the merge.** Before the merge,
> no BTC unit had been installed or started and no BTC history had been pulled.
> The existing `main` deploy cron makes the repository eligible to update, but
> is not evidence that it did. Confirm the server checklist in §0 before making
> any deployment claim or starting a BTC service.
>
> **Update 2026-10-03 (branch `arena/01a1016f-scalper`): pre-data follow-through.**
> Everything that does *not* require the server was closed out: the two ⚠️ items
> left in §4 (9: gold-literal spread sweep → measured from the loaded CSV; 10:
> parity's gold-ish fake tick → priced off the instrument's own bars), the
> 24/7 swap/maintenance gap (risk 3) now has an optional, parity-tested **entry
> blackout** filter in shared code (inert for gold), plus three new pieces of
> runbook tooling: **`btc/server_check.py`** (the §0 checklist as one read-only
> command), **`btc/derive_params.py`** (CSV → the placeholder config values) and
> **`docs/btc_market_reference_2026-10-03.md`** (cited web priors for every
> broker number, each mapped to the command that confirms it). Gold re-verified
> after all of it (§6). **Still nothing observed on the server and no BTC data:
> Phase 0 is unchanged and remains the next action.**
>
> **Account decision (user, 2026-10-03):** BTC uses the **same XM account and
> the same MT5 terminal/bridge as gold**. Accepted while both books are
> `FORWARD_TEST`; the separate-account / hard combined-gate requirement in §8
> risk 5 still blocks any LIVE flip.
>
> **Update 2026-10-03 (branch `arena/01a102b0-scalper`, after PR #17 `d8add56`):**
> - **Server access & Phase 1b status:** From this Arena container (`e2b.local`),
>   `ssh scalping` still fails DNS resolution and `/home/user/scalper/data/`
>   contains only `GOLD_M1.csv` and `GOLD_M5.csv` (`data/BTCUSD_M5.csv` is
>   git-ignored on `/root/scalper`). Per §0, no server runtime state or real-file
>   Phase 1b result is claimed from the local checkout.
> - **User-reported server snapshot (2026-10-03 16:47 UTC, carry-over):**
>   `/root/scalper` was clean at `d8add5678d74a1b6381c6e702432a0e1f0a0ce62`;
>   `data/BTCUSD_M5.csv` had 20,000 bars (`2026-07-25 21:55` .. `2026-10-03 13:40`
>   UTC), `data/BTCUSD_M1.csv` absent; `scalper-btc-bot` was `disabled` but
>   **active** (SIM mode, 0 trades, repeated `high_spread` skips at ~4,000 pts vs
>   the 1,500-pt placeholder); `scalper-btc-dashboard` was `enabled` and `active`
>   on `:8089`; gold was active with an open paper position.
> - **Why `scalper-btc-bot` started on the PR #17 deploy & why `crontab -l` was
>   missing from the markdown report:** (1) In `deploy.sh`, `SERVICES` is bound at
>   line 17 *before* `git pull --ff-only` at line 33, so when the cron ran on the
>   pre-PR-#17 checkout (`a4d6ecf`), the running shell still held the old default
>   (`scalper-bot scalper-btc-bot`) during the pull to `d8add56` and restarted
>   both units one final time (`systemctl restart` starts a disabled unit). Later
>   runs on `d8add56` default to `scalper-bot` only (unless `crontab` overrides
>   `DEPLOY_SERVICES`/`DEPLOY_SERVICE`), which does not stop an already-running
>   `scalper-btc-bot`. (2) `btc/server_check.py` collected `r["cron"]` in
>   `collect()` (`--json`) but omitted it in `to_markdown()`; fixed so default
>   markdown output includes `crontab -l`.
> - **BTC dashboard price vs label (`templates/index.html`):** Verified that
>   `btc/dashboard.py` + `btc/run.py` already display real **`BTCUSD`** `bid`,
>   `ask`, and `spread` from `btc/logs/live_status.json` (`MT5Bridge` queries
>   `config.SYMBOL = "BTCUSD"`). Only the price card header in
>   `templates/index.html` line 132 was hard-coded as `<h2>GOLD Price</h2>`;
>   changed to `<h2>{{ config.symbol if config is defined and config.symbol else "GOLD" }} Price</h2>`
>   (`GOLD Price` on gold, `BTCUSD Price` on BTC) and added an assertion to
>   `btc/tool.py --check` (now 11/11 PASS).
>
> **Update 2026-10-03 (Arena follow-up, PR #17 `d8add56`):** the bootstrap's referenced server
> command/bundle is not in this checkout, the local workspace has no BTC CSV,
> and `ssh scalping` cannot resolve from this environment. No real-file Phase
> 1b or server-status check was run. Added `btc/train_select.py` to replace the
> provisional `/tmp/btc_train_select.py`; it ranks only TRAIN metrics, freezes
> a winner before cold OOS, and explicitly models the live spread veto using a
> TRAIN-derived threshold. The existing `--oos` / `--candidates` reports are
> gold-specific and must not be used for BTC selection. Also changed the deploy
> default to gold-only because restarting a disabled-but-installed BTC unit can
> start it; Phase 2 requires an explicit `DEPLOY_SERVICES` opt-in. The smoke run
> on `GOLD_M5.csv` only checked selector plumbing and is not BTC evidence.
>
> Read `HANDOFF.md` (gold) first: this file assumes its conventions (§8 session
> protocol, "keep it honest", fake-bridge testing, train-select → cold-OOS).

---

## 0. Resume protocol — start here in a later session

1. **Establish the baseline; do not infer it from this file.** Work from the
   latest `main` on the session's assigned branch. PR #14 is the integration
   point (`bfb1dff`), but a later `main` may supersede it. On `scalping`, first
   collect—not modify—these facts:

   ```bash
   cd /root/scalper
   python3 btc/server_check.py          # all of the below in one read-only pass
   ```

   `btc/server_check.py` (added 2026-10-03) runs exactly this checklist and
   prints a paste-ready markdown evidence block (`--json` for machine use,
   `--journal 20` to include unit logs). It imports no MT5 module, opens no
   bridge connection and writes nothing, so it is safe while gold trades.
   Anything it cannot observe it reports as `unknown`, never as a default.
   Equivalent manual commands:

   ```bash
   git rev-parse HEAD
   git status --short
   systemctl is-enabled scalper-btc-bot scalper-btc-dashboard 2>&1 || true
   systemctl is-active scalper-btc-bot scalper-btc-dashboard 2>&1 || true
   ss -tlnp | grep -E '8088|8089' || true
   test -f data/BTCUSD_M5.csv && wc -l data/BTCUSD_M5.csv || true
   ```

   Record the output in the session notes before saying whether anything was
   deployed. Do **not** install, enable, restart, or start a BTC unit merely
   because its unit file is present in the repository.

2. **Do Phase 0 first if BTC data/specs are absent.** Run the read-only commands
   in §7, including the shared-bridge concurrency probe while observing the
   gold bot. `btc/recon.py` never sends orders and intentionally does not call
   `mt5.shutdown()` because gold may share the terminal session.

3. **Respect the gates.** Phase 1 must establish that the strategy has an edge
   on real XM BTCUSD data using train-select → cold-OOS; Phase 2 is paper-only;
   a separate XM account (or an equivalent hard combined-account risk gate) is
   required before any BTC LIVE decision. Never copy gold's parameter values.

4. **Close the loop before ending a session.** Update this status block, §9,
   and the BTC item in the root `HANDOFF.md` §5 with dated, observed evidence.
   For any shared-code change, rerun and record the gold regressions in §6. Do
   not write “deployed”, “running”, or “verified” without the command output
   that establishes it.

## 1. Verdict: what carried over

**The infrastructure is ~70% reusable verbatim; gold's parameter values are 0%
reusable.** That split is the reason this is cheap:

| Reused as-is | Notes |
|---|---|
| Patched MT5 container + RPyC bridge, `fetch_data.py` | One terminal serves both symbols (concurrency to be checked in Phase 0) |
| `mt5_bridge.py` | Nothing gold-specific; digits/filling/margin/stops all come from `symbol_info` |
| `run.py` engine loop | Risk gates, kill switch, stale-tick watchdog, backoff, 1s paper polling |
| `live_ledger.py`, `paper.py` | Magic-matched ledger; contract size now config-driven |
| `research/*` (`--verify`, `--oos`, `--candidates`, `loss_analysis`, parity, paper-exit) | Method + code; instrument economics now config-driven |
| `deploy.sh`, systemd pattern, dashboard app/template | Second instance on port 8089 |

Reusable as a **hypothesis only**: the strategy shape (EMA200 + RSI pullback +
ATR SL/TP). Untested on BTC, and Phase 1 may conclude it has no edge there.

**Decisions taken 2026-10-03** (user): same repo, `btc/` instance dir on `main`;
one shared XM account/bridge for now, but **"does BTC get its own account?" is a
hard prerequisite before any LIVE flip**; BTC research + trading use **XM CFD
bars from the bridge** (the instrument actually traded, with the broker's real
spread column).

## 2. Architecture — as built

```
/root/scalper/                     repo root (gold bot unchanged)
  config.py  run.py  strategy.py  paper.py  logger.py  mt5_bridge.py ...
  │  shared engine — every module does a plain `import config`
  data/GOLD_M5.csv   logs/                     gold instance
  btc/                                         BTC instance
    config.py        all BTC values (placeholders flagged)
    _instance.py     activate(dir) / add_engine_path(root) / import_engine(name, root)
    run.py           engine entry  -> services/scalper-btc-bot.service
    dashboard.py     :8089 board   -> services/scalper-btc-dashboard.service
    tool.py          run any repo script under the instance config; --check
    e2e_smoke.py     end-to-end fake-broker smoke test (no real MT5 needed)
    train_select.py  BTC-only TRAIN-select -> cold-OOS research screen
    recon.py         read-only Phase 0 probe (btc/HANDOFF §7)
    logs/            BTC runtime files (gitignored)
  services/scalper-btc-bot.service, scalper-btc-dashboard.service
```

**How the instance is selected (no engine fork):** `btc/_instance.activate()`
executes `btc/config.py` and registers it in `sys.modules["config"]` *before*
any engine import. Every later `import config` — whatever a script does to
`sys.path` — gets the BTC config, and `logger.LOG_DIR` follows it, so the two
bots can never share `trades.jsonl`, `daily_stats.json`, `paper_account.json`,
`daily_stats` or `KILL_SWITCH`. Gold runs untouched: it imports the root
`config.py` exactly as before.

**Two traps that were hit and are now encoded in the code:**

1. *Never* rely on `sys.path` order for config selection. `research/*.py` do
   `sys.path.insert(0, <repo root>)` at import time, which would put the gold
   config in front. `sys.modules` registration beats path order; `btc/tool.py`
   exists so research tools can be run under the BTC instance at all.
2. *Never* `import run` / `import dashboard` inside the same-named shim —
   `btc/` is first on `sys.path`, so the plain import re-enters the shim (the
   dashboard case fails loudly; the `run` case would silently import a
   half-initialised module and crash at `run.main()`). `_instance.import_engine`
   loads the engine by explicit path instead.

Both instances live on `main`, so any new commit can trigger the 15-minute
deploy cron. `deploy.sh` now defaults to `DEPLOY_SERVICES="scalper-bot"` only:
a disabled-but-installed BTC unit is still started by `systemctl restart`, so
installation alone must never opt BTC into deploys. After Phase 1 passes and
the user explicitly authorizes paper deployment, opt in with
`DEPLOY_SERVICES="scalper-bot scalper-btc-bot"`. Before either book goes LIVE,
revisit restart-only-what-changed and split service deployments.

## 3. BTCUSD on XM — still to confirm on the server (Phase 0)

Full cited version with sources, conflicts and the command that retires each
line: **`docs/btc_market_reference_2026-10-03.md`**. Summary — web sources
agree on the contract, conflict on leverage, and none of it is verified against
the account yet; `btc/recon.py` answers all of it in one run:

| Item | Expected | Note |
|---|---|---|
| Symbol name | `BTCUSD` | check `symbols_get("*BTC*")` — suffixes are common |
| Contract size | 1 BTC / lot | vs gold 100 oz — now `CONTRACT_SIZE` in `btc/config.py` |
| Min volume | 0.01 lots | same `LOT_SIZE` as gold, ~1/100th of the $ per $1 move |
| Leverage / margin | 1:250–1:500 (conflicting) | at 0.01 lots margin is a few dollars |
| Typical spread | ~500 pts ≈ $5/lot (Standard) | ≈ $0.05 round trip at 0.01 lots (gold: $0.47) |
| Trading hours | 24/7 | **gold's 21:00–22:00 rollover break does not exist** |
| Swap | daily financing at ~23:59 server time; **crypto triple swap Friday→Saturday** | nothing in the engine models swap P&L; entry blackout can avoid opening into it |
| Maintenance | XM suspends crypto **Sat 10:05–10:35 server time (GMT+2/+3)** | second blackout window candidate; confirm the terminal's UTC offset first |
| Digits / point | 2 / 0.01 (expected) | `spread * POINT` in the tools assumes it |

## 4. The ten gold assumptions found in shared code — status

| # | Where | Hook | State |
|---|---|---|---|
| 1 | `paper.py` `CONTRACT_SIZE=100` | `config.CONTRACT_SIZE` (default 100) | ✅ done |
| 2 | `backtest.py` `pnl * lot * 100` | `config.CONTRACT_SIZE` | ✅ done |
| 3 | `backtest.py` / sweep / loss_analysis `spread * 0.01` | `POINT = 10^-config.PRICE_DIGITS` | ✅ done |
| 4 | `strategy.py` ATR floor 0.50 + SL/TP 2.0/5.0 literals | `ATR_MIN`, `SL_ATR_MULT`, `TP_ATR_MULT` | ✅ done (gold values kept) |
| 4b | `strategy.py` EMA/RSI/ATR periods 200/14/14 | `EMA_PERIOD`, `RSI_PERIOD`, `ATR_PERIOD` | ✅ done (also wired into the sweep's `params_from_config`, so parity holds) |
| 5 | `logger.py` `LOG_DIR = <repo>/logs` | `config.LOG_DIR` (fallback = old path) | ✅ done |
| 6 | dashboard title/branding hard-coded | `config.DASHBOARD_TITLE` + `{{ title }}` + `{{ config.symbol }} Price` | ✅ done (gold name & `GOLD Price` preserved; BTC shows `BTCUSD Price`) |
| 7 | `MAGIC_NUMBER 999111`, "Gold Scalper v7" order comment | BTC = 999112; comment cosmetic | ✅ magic done; comment left |
| 8 | risk gates calibrated to gold P&L | `MAX_DAILY_LOSS=8` placeholder in `btc/config.py` | ⚠️ must be re-derived from BTC trade data |
| 9 | sweep's `CONTRACT_SIZE` + gold spread sweep list | `--sweep spread` / `--sweep honest` now price from the **loaded CSV's own spread column** (`csv_spread_stats`: config / mean / median / p90 / per-bar) | ✅ done 10-03 |
| 10 | `parity_test` fake tick at 4000.0 | tick is built from the bar it belongs to (`close` + the bar's own spread × POINT) | ✅ done 10-03 |
| 11 | no swap/maintenance awareness (24/7 only) | `ENTRY_BLACKOUTS_ENABLED` + `ENTRY_BLACKOUT_WINDOWS` in `strategy.py` *and* the replay engine, parity-tested | ✅ filter done 10-03 (windows still ⚠️ unconfirmed; swap **P&L** still unmodelled) |
| 12 | `research/strategy_sweep.py` did not model live `MAX_SPREAD_POINTS` veto | optional `Params.max_spread_points` replay mask; off by default for gold, explicitly TRAIN-derived by `btc/train_select.py` | ✅ added 10-03; test covers veto behavior |

Every hook defaults to today's gold value, so a config without the key behaves
exactly as before — proven in §6, not asserted.

## 5. Plan and gates

**Phase 0 — server recon (read-only, ~15 min).** Commands in §7. Answers §3 and
measures the shared-bridge concurrency question. *Gate: symbol exists, specs
sane, 20k+ bars available.* Then `data/BTCUSD_M5.csv` (+ M1) exist.

**Phase 1a — plumbing: DONE and verified 2026-10-03** (§6): instance dir, config
hooks, dashboard :8089, systemd units, deploy integration, and
`btc/e2e_smoke.py` — a committed end-to-end test (fake MT5 over a real RPyC
socket, its own ephemeral port + temp dirs, refuses a non-FORWARD_TEST config)
that drives a signal → paper entry → SL exit and checks the instrument's own
contract maths. It passes on both the BTC instance (`-$3.45` = 344.7 px × 0.01 ×
**1 BTC**) and the gold config dir (`-$344.72` = 344.7 px × 0.01 × **100 oz**),
i.e. the parameterisation is proven on both instruments, not just asserted.
Run it on the server any time: `mt5env/bin/python btc/e2e_smoke.py`.

**Phase 1b — does the shape have an edge on BTC at all?** On the real BTC CSV:

1. Run `btc/tool.py btc/derive_params.py` for measured ATR/spread and candidate
   economic values. These are facts/starting priors, not adopted strategy
   parameters.
2. Run `btc/tool.py research/strategy_sweep.py --verify` first and compare the
   sweep replay with `backtest.py`. Stop if they disagree.
3. Use the one-at-a-time `--sweep` runs for RSI/session/BE/SL/TP/spread
   diagnostics. They use the BTC config and CSV spread cost but do not apply the
   live spread veto; the veto-aware decision screen is `btc/train_select.py`.
4. For the decision gate, run **`btc/tool.py btc/train_select.py`**. It derives
   ATR-floor candidates and a 1.25× TRAIN-p90 spread veto using TRAIN bars
   only, ranks a fixed grid on TRAIN net only, then reads the frozen winner and
   pre-registered baseline on cold OOS. `BE off` is `None` (never `0`, which
   arms BE at entry). The script also shows how often the current
   `MAX_SPREAD_POINTS` placeholder would veto TRAIN quotes.
5. `research/strategy_sweep.py --oos` and `--candidates` are **gold-specific**
   reports: they hard-code gold's RSI/session/ATR assumptions and the
   2026-08 regime split. Do not interpret those as BTC train-selection results.
   `research/loss_analysis.py` can be used for descriptive BTC loss anatomy,
   with the same caveat about the current spread-veto placeholder.

The replay uses the CSV's per-bar spread and the live entry-spread veto (with a
threshold fixed from TRAIN p90); it still does not model slippage, swap P&L,
daily account gates, or weekend gaps. Derive `PRICE_DIGITS` and the spread
units from recon; do not run a service with the placeholder
`MAX_SPREAD_POINTS=1500`. The decision gate is positive cold-OOS net, PF ≳ 1.2,
sufficient trades, and sane spread economics. If BTC fails, a one-page negative
result is the deliverable and **no service**; do not tune on OOS.

**Phase 2 — service (only after Phase 1 passes and the user explicitly
authorizes paper deployment).** Install the two systemd units, explicitly set
`DEPLOY_SERVICES="scalper-bot scalper-btc-bot"` in the deploy cron, then open
:8089. Until then `deploy.sh` defaults to the gold unit only. Paper only.

**Phase 3 — paper in parallel with gold**, own 100-trade clock, own LIVE
decision, and a separate XM account before that decision (§1).

## 6. Gold-safety rules and the verification actually run

Rules while both bots share the tree: any shared-file change must keep
`backtest.py` at **255 trades / +$456.58 / PF 1.32 / max DD $108.65 / WR 28.2% /
72 TP · 43 BE · 140 SL** and `research/parity_test.py` at **PASS**; new config
keys must default to today's values; BTC-only orchestration lives in `btc/`.
The replay's optional `max_spread_points` gate defaults to `None`, so the gold
verification path remains behavior-identical unless a BTC caller opts in.

Local harness (the sandbox has no pandas by default; `/tmp` does not survive
between sessions):

```bash
python3 -m venv /tmp/v1 && /tmp/v1/bin/pip install pandas numpy rpyc jinja2 fastapi uvicorn
cd /home/user/scalper
/tmp/v1/bin/python backtest.py                    # 255 / +$456.58 / PF 1.32
/tmp/v1/bin/python research/parity_test.py        # PASS, 460 signals, 0 mismatches
/tmp/v1/bin/python btc/tool.py --check            # instance isolation, no MT5
```

Evidence from 2026-10-03 (all re-run after every hook was in place):

| Check | Result |
|---|---|
| `backtest.py` on gold | **255 / +$456.58 / PF 1.32 / max DD $108.65 / 72-43-140** — unchanged |
| `research/parity_test.py` | **PASS** — 460 replay signals, 0 mismatches, 20× cache reduction intact |
| `btc/tool.py --check` | 11/11 PASS: btc config wins, `btc/logs` isolated, contract size, magic, mode, template shows `BTCUSD Price` |
| Instance-regression: `/tmp/inst_test` config (gold values, only `LOG_DIR` diverted) driving the hooked engine | **255 / +$456.58 / PF 1.32** — plumbing is behaviour-neutral |
| `btc/tool.py research/strategy_sweep.py --csv data/GOLD_M5.csv --verify` under the **BTC** config | sweep engine ≡ `backtest.py` (both 377 trades / +$2.83 / PF 1.13) — numbers meaningless on gold data, equivalence is the point |
| `btc/run.py` + `btc/dashboard.py` executed via `runpy` | engine resolved from repo root, app title "Bitcoin Scalper Dashboard", port 8089, `LOG_DIR=btc/logs` |
| `research/paper_exit_test.py` (gold) | **PASS** — fake-bridge scenarios + M1/M5 table unchanged (`M5 OHLC 48 / +$89.43 / PF 1.35`) |
| `btc/e2e_smoke.py` on the **BTC** instance | **7/7 PASS** — signal → SIM_ENTRY → SL exit −$3.45 (344.7 px × 0.01 × 1 BTC), no ENTRY, gold `logs/` untouched |
| `btc/e2e_smoke.py --config-dir .` (**gold** config) | **7/7 PASS** — same path, −$344.72 (× 100 oz): the contract hook is correctly per-instrument |
| BTC-config pipeline dry-run on synthetic BTC-shaped bars (`/tmp`, disposable) | `--verify` sweep ≡ backtest (both 333 / −$140.42 / PF 0.80); `--oos` (train/cold, OAT, 4-fold walk-forward) and `loss_analysis` run clean; `loss_analysis` prints `session=off` and BTC-scale anatomy. **Synthetic numbers are noise — the point is the tooling runs under the BTC config.** |
| `templates/index.html` render (jinja2) | renders both titles and per-symbol price card header (`GOLD Price` vs `BTCUSD Price`) |
| `git check-ignore` | `btc/logs/*` and `data/*.csv` ignored |
| `btc/train_select_test.py` (Arena follow-up) | **PASS** — 60-grid generation, no BE=0, TRAIN-only ranking, spread-veto integration and split checks |
| `btc/tool.py btc/train_select.py --csv data/GOLD_M5.csv --bootstrap 100 --top 3` | **PASS as a plumbing smoke only** under BTC config; uses gold prices, so its P&L is explicitly not BTC evidence |
| `tests/test_deploy_services.sh` | **PASS 3/3** — default gold-only, explicit Phase 2 opt-in includes BTC, legacy singular override preserved |

## 7. Phase 0 commands (run on `scalping`)

```bash
cd /root/scalper
python3 btc/server_check.py                                      # §0 evidence block first (read-only)
mt5env/bin/python btc/recon.py --bars 20000                      # spec + stats + data/BTCUSD_M5.csv
mt5env/bin/python btc/recon.py --timeframe M1 --bars 60000 --out data/BTCUSD_M1.csv
mt5env/bin/python btc/tool.py --check                            # instance isolation, no bridge
ss -tlnp | grep -E '8088|8089'                                   # 8089 free?
# shared-bridge concurrency: with the gold bot running, this must not disturb it
mt5env/bin/python - <<'PY'
import rpyc, time
c = rpyc.classic.connect("localhost", 18812); mt5 = c.modules.MetaTrader5
mt5.initialize(); mt5.symbol_select("BTCUSD", True)
t0 = time.time()
for _ in range(20):
    r = rpyc.classic.obtain(mt5.copy_rates_from_pos("BTCUSD", mt5.TIMEFRAME_M5, 0, 1050))
    assert r is not None and len(r) > 0
print("20x BTC fetches ok in %.1fs" % (time.time() - t0))
# deliberately no mt5.shutdown() - the gold bot shares this terminal session
PY
journalctl -u scalper-bot -n 20 --no-pager                       # gold bot unchanged
```

Then Phase 1 (all under the BTC config, no bridge needed once the CSV exists):

```bash
mt5env/bin/python btc/tool.py btc/derive_params.py --csv data/BTCUSD_M5.csv
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --verify
# Compare both outputs; if counts/P&L/exits differ, STOP before reading any sweep.
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep sl
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep tp
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep be
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep rsi
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep spread
mt5env/bin/python btc/tool.py btc/train_select.py --csv data/BTCUSD_M5.csv
mt5env/bin/python btc/tool.py research/loss_analysis.py
```

Do **not** use `research/strategy_sweep.py --oos` or `--candidates` as BTC
selection: those reports hard-code gold's adopted parameters and calendar
regime. `btc/train_select.py` is the BTC-specific train-only selector; it
prints OOS only after freezing one winner, and never changes config.

## 8. Risks / open questions

1. **Edge risk (the big one).** Gold's book survives on a thin tail (top-5
   winners = 57% of net; 28.2% WR vs 28.6% structural break-even). The same
   shape may have no edge on BTC — Phase 1 decides, and "no" is a valid answer.
2. **Shared-bridge concurrency.** One RPyC server, two clients, one MT5 module
   instance. §7 measures it. Fallback: second container on :18813 with its own
   Wine prefix (same image, one more compose service + login).
3. **Swap/financing** on 24/7 crypto CFDs: an open scalp can straddle the daily
   charge; nothing models swap **P&L** today (gold has the same gap, masked by
   market hours). Half-addressed 10-03: the engine can now refuse to *open* into
   a named UTC window (`ENTRY_BLACKOUTS_ENABLED`), and `btc/config.py` carries
   the rollover + Saturday-maintenance candidates **disabled** until recon
   confirms the terminal's UTC offset (a wrong offset blanks the wrong hour).
   Still open: pricing the charge for positions that do straddle it.
4. **Weekend gap fills** in the CFD; pessimistic SL-first helps but no slippage
   model exists.
5. **Shared account before LIVE:** two bots on one XM balance each keep their
   own daily-loss gate — each can look "within risk" while the account is not.
   The user confirmed on 10-03 that BTC will use **the same account and
   terminal** as gold; that is fine for two paper books, and it makes this the
   single hardest blocker at the LIVE flip. Own account (or a hard combined
   gate) required first.
6. **Risk gates are placeholders** (`MAX_DAILY_LOSS=8`): at 0.01 lots BTC risks
   ~$1–3/trade, so gold's $30 would be a dead gate next to the 15-trade cap.
   Re-derive from Phase 1 data before the paper book means anything.
7. Open: once either book goes LIVE, split deploy/restart per service (and
   reconsider one-repo vs separate checkout).

## 9. Changelog

| Date | Change | Why |
|---|---|---|
| 10-03 | **BTCUSD Phase 1b completed: FAIL / No-Go — negative result recorded (`arena/01a102c4-scalper`)** — ran the full §5 Phase 1b sequence on the real `data/BTCUSD_M5.csv` (20,000 bars, `2026-07-25 21:55` .. `2026-10-03 13:40` UTC, 5,600 weekend bars, 24/24 hours) on `scalping` at `2026-10-03T17:07:55+00:00`, `/root/scalper` clean at `f5e76c8`, and wrote the mandated one-page negative result to **`docs/btc_phase1_result_2026-10-03.md`**. Gate order held: `strategy_sweep.py --verify` reproduced `backtest.py` exactly (**433 trades / −$165.84 / PF 0.74 / WR 23.8% / 103W-330L / avgR −0.46 / maxDD $169.46 / 107 TP · 59 BE · 267 SL**), then `btc/train_select.py` ranked the 60-config grid on TRAIN only (floors `zero/p10/p25/p50/p75 = 0.00/19.94/40.22/65.06/113.14`; replay veto `1.25× TRAIN p90 = 6,250` pts, vetoing 0.00% of TRAIN quotes vs **100.00%** for the `MAX_SPREAD_POINTS=1500` placeholder), froze `ATR p75=113.14 SL=2.0 BE=off` (`44 tr, +$33.43, PF 1.29`), then read cold OOS: **winner `n=70, −$46.11, PF 0.75, maxDD $56.29, P(net>0)=0.138`** and **baseline `n=217, −$95.50, PF 0.72, P(net>0)=0.025`** → **FAIL** (`net < 0` and `PF < 1.2`). `derive_params.py` explains why it cannot work: median price $77,304.55, `PRICE_DIGITS=2`, $0.0100 per 1.00 move, ATR(14) p50 81.62 / p90 179.03, spread mean 4,242 pts = 42.41 px = **$0.4242** round trip at 0.01 lots → **spread/median-ATR 52.0%**, **spread/risk 26.0%**, break-even WR 28.6% → **~36.0%** with spread vs **23.8%** actual. `research/loss_analysis.py`: gross profit $465.72 / gross loss $631.55, SL 267 exits = **96.0%** of gross loss (−$606.26) vs BE 59 = 3.9% (−$24.90), **net before spread +$17.16 (+$0.04/trade) vs $183.00 spread paid (28% of gross profit, avg $0.42/trade, 1R = avg $1.82)**; all 4 months, all 4 ATR quartiles, 6/7 weekdays and both directions negative; 76 losing streaks, mean 4.34, max 20. One-variable sweeps all net-negative (SL 1.0× −$338.79 → 3.0× −$6.96; BE 0.5R −$320.29 → off −$119.42; RSI 30/70 −$129.03 … 45/55 −$177.76; spread fallback 5.00 −$4.49 PF 0.99 vs per-bar CSV −$165.84). Server state confirmed read-only: gold `scalper-bot`/`scalper-dashboard` active (`SIM: $128.62 \| SimEquity: $131.03`, open paper position undisturbed, `:8088` up), `scalper-btc-bot`/`scalper-btc-dashboard` **disabled + inactive** (`:8089` not listening; BTC bot stopped `16:50:21 UTC` after 0 trades with `high_spread` skips at ~4,000 pts), bridge `18812` listening, deploy cron `*/15 * * * * DEPLOY_BRANCH=main` with **no** `DEPLOY_SERVICES` override, last deploy line `restarted scalper-bot at f5e76c8… (was d8add56…) branch=main` (gold-only restart confirmed). **Documentation only: `config.py`, `btc/config.py`, `strategy.py`, `run.py` untouched, `TRADING_MODE` still `FORWARD_TEST` on both instances, no BTC unit installed/enabled/started.** Gold + BTC tests re-run locally: `backtest.py` **255 / +$456.58 / PF 1.32 / max DD $108.65 / 72-43-140** (identical to the §6 baseline), `parity_test.py` **PASS** (460 signals, 0 mismatches, 20× cache reduction, blackout check clean), `btc/tool.py --check` **11/11**, `btc/train_select_test.py` **PASS**, `tests/test_deploy_services.sh` **PASS 3/3**. | §5 requires that when the cold-OOS gate fails, a one-page negative result is the deliverable and there is **no service**, with no tuning on OOS. Recording the measured verdict — and its structural cause (a ~52% spread-to-ATR ratio, i.e. a ~36% required win rate against 23.8% actual) — is what stops a later session from re-litigating the same dataset, loosening the spread gate, or copying gold parameters onto an instrument where they cannot pay for the spread. |
| 10-03 | **BTC dashboard price-card label + `server_check.py` cron output (`arena/01a102b0-scalper`)** — confirmed `ssh scalping` and `/root/scalper/data/BTCUSD_M5.csv` remain unreachable from the Arena container (`e2b.local`), so no real-file Phase 1b result or live server state is claimed from the local checkout. Audited the BTC dashboard (`btc/dashboard.py` → `dashboard.py` → `templates/index.html`) and engine (`btc/run.py` → `run.py` → `mt5_bridge.py` → `logger.py`): `live.bid`, `live.ask`, and `live.spread` on `:8089` are genuine `BTCUSD` quotes read from `btc/logs/live_status.json`, while `templates/index.html` line 132 still had `<h2>GOLD Price</h2>` hard-coded. Replaced it with `<h2>{{ config.symbol if config is defined and config.symbol else "GOLD" }} Price</h2>` (`GOLD Price` on gold, `BTCUSD Price` on BTC) and added a template check in `btc/tool.py --check` (11/11 PASS). Also fixed `btc/server_check.py` `to_markdown()` to emit the already-collected `crontab -l` (`r["cron"]`) block, and documented why the transition deploy from `a4d6ecf` → `d8add56` started the disabled `scalper-btc-bot` unit (the pre-PR-#17 `deploy.sh` bound `SERVICES` before `git pull`). All gold regressions (`backtest.py` 255 / +$456.58 / PF 1.32, `parity_test.py`, `paper_exit_test.py`) and BTC tests (`e2e_smoke.py`, `train_select_test.py`, `test_deploy_services.sh`) PASS. | Fix the hard-coded "GOLD Price" card heading on the BTC dashboard and ensure `btc/server_check.py` prints `crontab -l` in markdown mode. |
| 10-03 | **BTC Phase 1b prep + deploy safety (`arena/01a101b6-scalper`, PR #17)** — the real BTC file/server is unavailable from this Arena checkout, so no BTC result is claimed. Added `btc/train_select.py` (fixed ATR-floor × SL × BE grid; floors and spread veto derived on TRAIN only; rank TRAIN only; then cold-read one frozen candidate + baseline) and optional `Params.max_spread_points` in the replay engine (default `None`, so gold is unchanged). Documented that generic `--oos`/`--candidates` are gold-specific. Changed `deploy.sh` default to gold-only because a restart starts a disabled-but-installed BTC unit; BTC now requires explicit Phase 2 opt-in. Verified with helper tests, gold backtest/parity/paper-exit regressions, BTC isolation/e2e, and mocked deploy-service test. Selector smoke on `GOLD_M5.csv` is plumbing-only, not evidence. | Make Phase 1b reproducible without overreading gold-specific reports, and prevent a cron deploy from unintentionally starting the not-yet-authorized BTC unit. |
| 10-03 | **Pre-data follow-through (`arena/01a1016f-scalper`)** — everything in the plan that does not need the server. §4 item 9: `--sweep spread` and `--sweep honest` now derive their price levels from the loaded CSV's own `spread` column (`csv_spread_stats`, POINT-aware) instead of gold's 0.30/0.47/0.51 literals. §4 item 10: `parity_test`'s fake tick is built from the bar it belongs to (close + that bar's spread × POINT) instead of 4000.00/4000.45. New §4 item 11: optional **entry blackout windows** (`ENTRY_BLACKOUTS_ENABLED`, `ENTRY_BLACKOUT_WINDOWS` — UTC `HH:MM` + minutes + optional weekdays, wraps midnight) implemented once in `strategy.py` and mirrored in the replay engine (`blackout_mask` → `signal_at(..., blocked)`), so live/backtest parity still holds on a 24/7 instrument; `parity_test` grew a dedicated check that forces two synthetic windows, asserts 0 live-vs-replay mismatches over 874 compared bars, that 40 real signals were actually suppressed (non-vacuous) and that the skip reason is `blackout:<name>`. `btc/config.py` ships the XM rollover + Saturday-maintenance candidates **disabled**. New tools: **`btc/server_check.py`** (§0 checklist as one read-only, MT5-free command; markdown or `--json`) and **`btc/derive_params.py`** (CSV → measured ATR/spread distributions → candidate `PRICE_DIGITS`/`ATR_MIN`/`MAX_SPREAD_POINTS`/`SPREAD_COST_PRICE`/`MAX_DAILY_LOSS` + spread-vs-risk economics and the structural break-even WR). New doc **`docs/btc_market_reference_2026-10-03.md`**: cited web priors (contract 1 BTC/lot, 0.01 min, leverage 1:250 vs 1:500 *conflict*, Standard spread ~500 pts ≈ $5/lot, 24/7, Sat 10:05–10:35 GMT+2 maintenance, crypto triple swap Fri→Sat), each line mapped to the command that confirms it. **Gold re-verified after every change: `backtest.py` 255 / +$456.58 / PF 1.32 / max DD $108.65 / 72-43-140, `parity_test.py` PASS (460 signals, 0 mismatches, + the new blackout check), `paper_exit_test.py` PASS (M5 OHLC 48 / +$89.43 / PF 1.35), `btc/tool.py --check` 10/10, `btc/e2e_smoke.py` ALL PASS on both the BTC instance and the gold config dir.** Sanity check on the new deriver: run on `data/GOLD_M5.csv` it reproduces gold's documented facts (spread mean $0.47, break-even WR 28.6%, suggested daily loss $31.3 vs the adopted $30). | User asked to follow through the pending work and to add a web reference for BTC like the gold material. Phase 0/1 still need the server, so this closes every item that does not. |
| 10-03 | **PR #14 merged into `main`** at 10:11:28 UTC as `bfb1dff` ([PR #14](https://github.com/shashidaren/scalper/pull/14); head `arena/01a10125-scalper`). The code is integrated; that does **not** establish post-merge server state. Before merge the BTC units were absent, and §0 now requires a server-side observation before claiming a deployment, runtime state, open port, or BTC dataset. | Integrate the separately verified BTC handoff/plumbing while keeping the next action evidence-led. |
| 10-03 | **`btc/e2e_smoke.py` added; BTC-config pipeline dry-run clean (`arena/01a10125-scalper`)**: committed end-to-end smoke test (fake MT5 over a real RPyC `SlaveService` socket, ephemeral port, temp instance + log dir, refuses LIVE/FORWARD_TEST-violating configs, instance-generic via `--config-dir`) — passes 7/7 on the BTC instance and on the gold config dir, proving the contract-size hook per instrument (−$3.45 vs −$344.72 on the same 344.7-point stop). Fixed two harness bugs found this way (buffered prints lost at `os._exit`; the fake *tick* spread must respect the instance's `MAX_SPREAD_POINTS`, since the live gate reads the tick, not the CSV). Ran the full BTC pipeline (sweep `--verify`, `--oos`, `loss_analysis`) under the BTC config on synthetic BTC-shaped bars: tooling runs, `--verify` agrees, session filter off shows as `session=off`. Gold re-checked after the small shared-code cleanups (`loss_analysis` session-off display, "Price Δ%" header, order-comment hook): backtest, parity and paper-exit all unchanged. | Finish the plumbing verification end-to-end and prove the runbook works before real BTC data exists. |
| 10-03 | **Phase 1 plumbing built + verified (`arena/01a10125-scalper`)**: ten backwards-compatible hooks in shared code (contract size, price digits/POINT, `LOG_DIR`, ATR floor + SL/TP multiples, indicator periods, dashboard title); `btc/config.py` (all BTC values, placeholders flagged), `btc/_instance.py`, `btc/run.py`, `btc/dashboard.py`, `btc/tool.py`; `services/scalper-btc-{bot,dashboard}.service`; `deploy.sh` multi-service restart that skips uninstalled units. Verified: gold `backtest.py` and `parity_test.py` unchanged, `btc/tool.py --check` 9/9, a gold-identical instance config reproduces gold's numbers exactly, sweep ≡ backtest under the BTC config, both shims resolve the right engine/config, template renders both titles. | User chose to build the plumbing in parallel with the server-side Phase 0 recon. |
| 10-03 | Created this file + `btc/recon.py` (read-only Phase 0 probe; `--self-test` verified) and a pointer/record in the gold `HANDOFF.md`. | User asked whether a BTC scalper is cheaper given the gold work, and asked for a separate handoff. |
