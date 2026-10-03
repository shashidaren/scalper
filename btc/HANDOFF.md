# HANDOFF — Bitcoin (BTCUSD) Scalper

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

One caveat accepted up front: both instances live on `main`, so the 15-minute
deploy cron restarts both bots when either changes. `deploy.sh` now takes a
`DEPLOY_SERVICES` list and skips units that are not installed, so the existing
cron keeps working and the BTC unit joins it when installed. Revisit
restart-only-what-changed before either book goes LIVE.

## 3. BTCUSD on XM — still to confirm on the server (Phase 0)

Web sources agree on the contract, conflict on leverage, and none of it is
verified against the account yet — `btc/recon.py` answers all of it in one run:

| Item | Expected | Note |
|---|---|---|
| Symbol name | `BTCUSD` | check `symbols_get("*BTC*")` — suffixes are common |
| Contract size | 1 BTC / lot | vs gold 100 oz — now `CONTRACT_SIZE` in `btc/config.py` |
| Min volume | 0.01 lots | same `LOT_SIZE` as gold, ~1/100th of the $ per $1 move |
| Leverage / margin | 1:250–1:500 (conflicting) | at 0.01 lots margin is a few dollars |
| Typical spread | ~500 pts ≈ $5/lot (Standard) | ≈ $0.05 round trip at 0.01 lots (gold: $0.47) |
| Trading hours | 24/7 | **gold's 21:00–22:00 rollover break does not exist** |
| Swap | daily financing, triple one weekday | nothing in the engine models swap yet |
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
| 6 | dashboard title/branding hard-coded | `config.DASHBOARD_TITLE` + `{{ title }}` | ✅ done (gold name preserved) |
| 7 | `MAGIC_NUMBER 999111`, "Gold Scalper v7" order comment | BTC = 999112; comment cosmetic | ✅ magic done; comment left |
| 8 | risk gates calibrated to gold P&L | `MAX_DAILY_LOSS=8` placeholder in `btc/config.py` | ⚠️ must be re-derived from BTC trade data |
| 9 | sweep's `CONTRACT_SIZE` + gold spread sweep list | config-driven now; spread list still gold's | ⚠️ pass `--set spread_price=…` for BTC |
| 10 | `parity_test` fake tick at 4000.0 | harmless | ⚠️ cosmetic |

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

**Phase 1b — does the shape have an edge on BTC at all?** On BTC data:
`btc/tool.py research/strategy_sweep.py --verify` (must agree with `backtest.py`
first) → `--sweep` RSI/session/BE/SL/TP/ATR-floor → `--oos` (train-select, cold
read) → `--candidates` → `research/loss_analysis.py`. Derive, in this order:
`PRICE_DIGITS`/spread gate from recon, `ATR_MIN` from the ATR distribution,
session (probably none — 24/7), RSI levels, BE, SL/TP multiples, then the two
risk gates. *Gate: train-only selection stays positive cold on OOS with
PF ≳ 1.2 and sane spread economics. If BTC fails, the deliverable is a
one-page negative result and no service.*

**Phase 2 — service (mostly built already).** Install the two systemd units,
add `DEPLOY_SERVICES="scalper-bot scalper-btc-bot"` to the deploy cron, open
:8089. Paper only.

**Phase 3 — paper in parallel with gold**, own 100-trade clock, own LIVE
decision, and a separate XM account before that decision (§1).

## 6. Gold-safety rules and the verification actually run

Rules while both bots share the tree: any shared-file change must keep
`backtest.py` at **255 trades / +$456.58 / PF 1.32 / max DD $108.65 / WR 28.2% /
72 TP · 43 BE · 140 SL** and `research/parity_test.py` at **PASS**; new config
keys must default to today's values; new code lives in `btc/`.

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
| `btc/tool.py --check` | 9/9 PASS: btc config wins, `btc/logs` isolated, contract size, magic, mode |
| Instance-regression: `/tmp/inst_test` config (gold values, only `LOG_DIR` diverted) driving the hooked engine | **255 / +$456.58 / PF 1.32** — plumbing is behaviour-neutral |
| `btc/tool.py research/strategy_sweep.py --csv data/GOLD_M5.csv --verify` under the **BTC** config | sweep engine ≡ `backtest.py` (both 377 trades / +$2.83 / PF 1.13) — numbers meaningless on gold data, equivalence is the point |
| `btc/run.py` + `btc/dashboard.py` executed via `runpy` | engine resolved from repo root, app title "Bitcoin Scalper Dashboard", port 8089, `LOG_DIR=btc/logs` |
| `research/paper_exit_test.py` (gold) | **PASS** — fake-bridge scenarios + M1/M5 table unchanged (`M5 OHLC 48 / +$89.43 / PF 1.35`) |
| `btc/e2e_smoke.py` on the **BTC** instance | **7/7 PASS** — signal → SIM_ENTRY → SL exit −$3.45 (344.7 px × 0.01 × 1 BTC), no ENTRY, gold `logs/` untouched |
| `btc/e2e_smoke.py --config-dir .` (**gold** config) | **7/7 PASS** — same path, −$344.72 (× 100 oz): the contract hook is correctly per-instrument |
| BTC-config pipeline dry-run on synthetic BTC-shaped bars (`/tmp`, disposable) | `--verify` sweep ≡ backtest (both 333 / −$140.42 / PF 0.80); `--oos` (train/cold, OAT, 4-fold walk-forward) and `loss_analysis` run clean; `loss_analysis` prints `session=off` and BTC-scale anatomy. **Synthetic numbers are noise — the point is the tooling runs under the BTC config.** |
| `templates/index.html` render (jinja2) | renders for both gold and BTC titles |
| `git check-ignore` | `btc/logs/*` and `data/*.csv` ignored |

## 7. Phase 0 commands (run on `scalping`)

```bash
cd /root/scalper
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
mt5env/bin/python btc/tool.py research/strategy_sweep.py --verify
mt5env/bin/python btc/tool.py research/strategy_sweep.py --sweep rsi
mt5env/bin/python btc/tool.py research/strategy_sweep.py --oos
mt5env/bin/python btc/tool.py research/strategy_sweep.py --candidates
mt5env/bin/python btc/tool.py research/loss_analysis.py
```

## 8. Risks / open questions

1. **Edge risk (the big one).** Gold's book survives on a thin tail (top-5
   winners = 57% of net; 28.2% WR vs 28.6% structural break-even). The same
   shape may have no edge on BTC — Phase 1 decides, and "no" is a valid answer.
2. **Shared-bridge concurrency.** One RPyC server, two clients, one MT5 module
   instance. §7 measures it. Fallback: second container on :18813 with its own
   Wine prefix (same image, one more compose service + login).
3. **Swap/financing** on 24/7 crypto CFDs: an open scalp can straddle the daily
   charge; nothing models swap today (gold has the same gap, masked by market
   hours). Decide: avoid entries near the swap time, or model it.
4. **Weekend gap fills** in the CFD; pessimistic SL-first helps but no slippage
   model exists.
5. **Shared account before LIVE:** two bots on one XM balance each keep their
   own daily-loss gate — each can look "within risk" while the account is not.
   Own account (or a hard combined gate) required first.
6. **Risk gates are placeholders** (`MAX_DAILY_LOSS=8`): at 0.01 lots BTC risks
   ~$1–3/trade, so gold's $30 would be a dead gate next to the 15-trade cap.
   Re-derive from Phase 1 data before the paper book means anything.
7. Open: once either book goes LIVE, split deploy/restart per service (and
   reconsider one-repo vs separate checkout).

## 9. Changelog

| Date | Change | Why |
|---|---|---|
| 10-03 | **PR #14 merged into `main`** at 10:11:28 UTC as `bfb1dff` ([PR #14](https://github.com/shashidaren/scalper/pull/14); head `arena/01a10125-scalper`). The code is integrated; that does **not** establish post-merge server state. Before merge the BTC units were absent, and §0 now requires a server-side observation before claiming a deployment, runtime state, open port, or BTC dataset. | Integrate the separately verified BTC handoff/plumbing while keeping the next action evidence-led. |
| 10-03 | **`btc/e2e_smoke.py` added; BTC-config pipeline dry-run clean (`arena/01a10125-scalper`)**: committed end-to-end smoke test (fake MT5 over a real RPyC `SlaveService` socket, ephemeral port, temp instance + log dir, refuses LIVE/FORWARD_TEST-violating configs, instance-generic via `--config-dir`) — passes 7/7 on the BTC instance and on the gold config dir, proving the contract-size hook per instrument (−$3.45 vs −$344.72 on the same 344.7-point stop). Fixed two harness bugs found this way (buffered prints lost at `os._exit`; the fake *tick* spread must respect the instance's `MAX_SPREAD_POINTS`, since the live gate reads the tick, not the CSV). Ran the full BTC pipeline (sweep `--verify`, `--oos`, `loss_analysis`) under the BTC config on synthetic BTC-shaped bars: tooling runs, `--verify` agrees, session filter off shows as `session=off`. Gold re-checked after the small shared-code cleanups (`loss_analysis` session-off display, "Price Δ%" header, order-comment hook): backtest, parity and paper-exit all unchanged. | Finish the plumbing verification end-to-end and prove the runbook works before real BTC data exists. |
| 10-03 | **Phase 1 plumbing built + verified (`arena/01a10125-scalper`)**: ten backwards-compatible hooks in shared code (contract size, price digits/POINT, `LOG_DIR`, ATR floor + SL/TP multiples, indicator periods, dashboard title); `btc/config.py` (all BTC values, placeholders flagged), `btc/_instance.py`, `btc/run.py`, `btc/dashboard.py`, `btc/tool.py`; `services/scalper-btc-{bot,dashboard}.service`; `deploy.sh` multi-service restart that skips uninstalled units. Verified: gold `backtest.py` and `parity_test.py` unchanged, `btc/tool.py --check` 9/9, a gold-identical instance config reproduces gold's numbers exactly, sweep ≡ backtest under the BTC config, both shims resolve the right engine/config, template renders both titles. | User chose to build the plumbing in parallel with the server-side Phase 0 recon. |
| 10-03 | Created this file + `btc/recon.py` (read-only Phase 0 probe; `--self-test` verified) and a pointer/record in the gold `HANDOFF.md`. | User asked whether a BTC scalper is cheaper given the gold work, and asked for a separate handoff. |
