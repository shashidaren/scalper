# HANDOFF — Bitcoin (BTCUSD) Scalper — **PLAN ONLY** (nothing built, nothing deployed)

> **Status: PLANNING.** No code, no config change, no server change, no deploy.
> Read `HANDOFF.md` (gold) first — this file assumes its conventions
> (§8 session protocol, the "keep it honest" rule, fake-bridge testing, and the
> train-select → cold-OOS discipline that killed every "obvious fix" in
> `docs/loss_analysis_2026-10-02.md`).
>
> Opened 2026-10-03, branch `arena/01a10125-scalper`, in answer to: *"is it
> easier to set up a bitcoin scalper based on what we have gathered?"*
> **Short answer: the plumbing is ~70% reusable and roughly a day of work; the
> edge is 0% reusable and is the actual project.** Details in §1–§2.

---

## 1. Verdict: what is and is not reusable

Reusable **verbatim** (infrastructure — this is the expensive part and it is
already proven on the server):

| Asset | Why it carries over |
|---|---|
| Patched MT5 container + RPyC bridge (`docker-compose.yml`, §4 of the gold handoff) | Symbol-agnostic. One terminal can serve both symbols — `symbol_select("BTCUSD")` is all it takes (subject to the concurrency test in §5/Phase 0). |
| `mt5_bridge.py` | Nothing gold-specific except `config.SYMBOL`. Digits, filling mode, margin pre-flight and stops all come from `symbol_info` at runtime. Also carries the 20× rate-cache fix. |
| `run.py` engine loop | Risk gates, kill switch, stale-tick watchdog, backoff, 1s paper-exit polling. All `config.*`-driven. |
| `live_ledger.py` | Magic-matched deal polling; state file moves with the per-instance log dir. |
| `research/parity_test.py`, `research/paper_exit_test.py` | Method transfers as-is; fixtures need a BTC price instead of the hard-coded 4000.0. |
| `fetch_data.py` | Already takes `--symbol`; no change needed to pull `data/BTCUSD_M5.csv`. |
| `deploy.sh` + cron + systemd pattern + dashboard code | Pattern and files copy over; only the unit name and port change. |
| The whole *methodology* (backtest → `--verify` → `--oos` → `--candidates` → parity → paper) | The reason a BTC bot is cheap to do **honestly**. |

Needs a small, backwards-compatible hook (see §4) — all four are gold config
values hard-coded in shared code:

| Asset | Hook needed |
|---|---|
| `logger.py` | `LOG_DIR` must come from `config` (else both bots share one `logs/`) |
| `paper.py` | contract size (XAU 100 oz vs BTC 1 BTC) + digits-aware rounding |
| `backtest.py` / `research/strategy_sweep.py` | contract size + point value instead of `*100` / `*0.01` |
| `strategy.py` | ATR floor and the 2.0 SL / 5.0 TP multiples are literals in code, not config |

Reusable **as a hypothesis only, never as values**:

| Asset | Reality |
|---|---|
| The strategy *shape* (EMA200 trend + RSI pullback + ATR SL/TP) | Untested on BTC. It may simply not have an edge there — that is Phase 1's job to find out, and "no" is an acceptable answer. |
| Every gold parameter: RSI 40/60, session 07–20 UTC, BE 1.5R, SL 2.0×ATR, TP 5.0×ATR, `MAX_SPREAD_POINTS=80`, `atr_min=0.50`, `MAX_DAILY_LOSS=30`, `MAX_TRADES_PER_DAY=15` | **Zero transfer.** Each is a fitted value (or a dead one — `atr_min=0.50` never binds on gold). Copying `MAX_SPREAD_POINTS=80` to BTC would skip essentially every trade (XM Standard BTCUSD runs ~500 points); copying the risk gates would make them dead code (§4.8). |

Rough split: **infrastructure ~70% reusable, strategy parameters 0%.**

## 2. Proposed architecture

Same server, same repo, same MT5 container — a second *instance directory*:

```
/root/scalper/                    <- repo root (UNCHANGED gold bot)
  config.py  run.py  strategy.py  logger.py  paper.py  mt5_bridge.py  ...   (shared engine)
  data/GOLD_M5.csv                data/BTCUSD_M5.csv
  logs/                           <- gold runtime files only
  btc/                            <- NEW: the BTC instance
    config.py                     <- same key names + CONTRACT_SIZE / LOG_DIR
    run.py  dashboard.py          <- 5-line shims (see below)
    logs/                         <- BTC runtime files only
    HANDOFF.md                    <- this file
  services/
    scalper-bot.service           (gold, unchanged, :8088 dashboard)
    scalper-btc-bot.service       <- NEW  (BTC, dashboard :8089)
    scalper-btc-dashboard.service <- NEW
```

**The one trick that makes this cheap:** every shared module does a plain
`import config`, so whichever `config.py` is first on `sys.path` *is* the
instance. Run the BTC bot with `WorkingDirectory=/root/scalper/btc` and
`ExecStart=.../python -u /root/scalper/btc/run.py` — Python puts the script's
own directory first, so `btc/config.py` wins and `strategy.py`, `paper.py`,
`run.py` etc. are imported from the repo root unchanged. The gold bot keeps
`WorkingDirectory=/root/scalper`, so its resolution is untouched. `btc/run.py`
is then just:

```python
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)   # instance dir must be FIRST on sys.path
sys.path.append(ROOT)          # shared engine modules, LAST (see trap below)
import run                     # repo-root engine; its `import config` -> btc/config.py
if __name__ == "__main__":
    run.main()
```

(and `btc/config.py` sets `LOG_DIR = Path(__file__).parent / "logs"`).

> **Trap:** the shim must *append* the repo root, never `insert(0, ROOT)` — the
> first `config` on `sys.path` wins, so putting the root in front would silently
> run the BTC bot on the **gold** config (and write into the gold log dir).
> Keep the same rule for research tools on BTC data:
> `cd btc && PYTHONPATH=/root/scalper mt5env/bin/python -m research.strategy_sweep --verify`
> (`-m` puts the cwd first, so `btc/config.py` wins).

Why not the alternatives:

- **Separate repo `scalper-btc`** — total isolation, but every bridge/engine fix
  is applied twice and the two copies drift. Only worth it if the gold bot goes
  LIVE and you want independent deploy cadence.
- **Full refactor into `core/` + symbol profiles** — cleanest long-term, but it
  touches the live gold paper path for zero immediate benefit. Revisit if a
  third symbol ever appears.

One caveat to accept up front: because both instances live on `main`, the
existing 15-minute deploy cron will restart **both** services whenever either
changes. Harmless in paper mode (restarts are cheap and idempotent — the paper
book is crash-safe); once either book goes LIVE, teach `deploy.sh` to restart
only the service whose files changed (`git diff --name-only $BEFORE $AFTER`).

## 3. BTCUSD on XM — facts to *verify on the server* before designing anything

Web sources agree on the contract but conflict on leverage, and none of this is
verified against your actual account yet:

| Item | Expected | Note |
|---|---|---|
| Symbol name | `BTCUSD` | Verify with `symbols_get("*BTC*")` — suffixes (`.r`, `#`) are common |
| Contract size | 1 BTC per lot | vs gold's 100 oz per lot — this is hook §4.1 |
| Min / max volume | 0.01 / 80 lots | 0.01 = same `LOT_SIZE` as gold, but ~1/100th of the dollar exposure per $1 move |
| Leverage / margin | 1:250–1:500 (sources conflict) | At 0.01 lots margin is a few dollars — the `$200` sim balance is not the binding constraint it was for gold |
| Typical spread | ~500 points ≈ $5.00/lot on Standard (~225 / $2.25 Ultra Low) | ≈ $0.05 round-trip at 0.01 lots. Compare gold: $0.47 at 0.01 lots |
| Trading hours | 24/7 (Mon 00:00 – Sun 24:00) | **Gold's 21:00–22:00 rollover break does not exist** — the session filter's original rationale is gone |
| Swap | Daily financing, triple on one weekday | Gold's engine does **not** model swap; with 24/7 hours a scalp can straddle the charge time |
| Digits / point | 2 digits, point 0.01 (expected) | Assumed by `spread * 0.01` in `backtest.py`; must be confirmed |

Consequences to think about *before* Phase 1 tuning: with 24/7 hours the bot has
no natural "closed" period, so the session filter should start as **wide or
disabled** and be earned from data (crypto liquidity still varies by hour, and
weekend spread is usually wider). Profit per trade at 0.01 lots is ~10× smaller
than gold, so `SIM_START_BALANCE` / `MAX_DAILY_LOSS` must be re-derived from
measured BTC P&L, not copied.

## 4. Gold assumptions that will silently break BTC

Found by reading the tree this session (file evidence included). Each is a
Phase-1 blocker; none are open questions.

1. `paper.py:23` — `CONTRACT_SIZE = 100.0` (XAU: 1 lot = 100 oz). BTC is 1.
   **Impact if unchanged: the BTC paper book reports P&L 100× wrong.** It also
   rounds prices to 2 decimals, which is right for both symbols only while
   digits == 2.
2. `backtest.py` (close-out block) — `dollar_pnl = pnl * (config.LOT_SIZE * 100)`.
   Same 100× error in every backtest/sweep number.
3. `backtest.py` + `research/strategy_sweep.py:223` — `spread * 0.01`
   (point→price), which bakes in 2-digit pricing. Fine for XM BTCUSD *if*
   `symbol_info.digits == 2`; make it `10 ** -digits` from config instead.
4. `strategy.py` — the ATR floor (`current_atr < 0.50`) and `sl = ATR*2.0` /
   `tp = ATR*5.0` are **literals in code**, not config. On BTC the floor is a
   no-op and the multiples are untested; lift all three into config (the sweep
   tool already models `atr_min`, `sl_atr_mult`, `tp_atr_mult`).
5. `logger.py:7` — `LOG_DIR = BASE_DIR / "logs"` anchored to the repo, so a
   second instance would append to the **same** `trades.jsonl`,
   `daily_stats.json` and `paper_account.json`, corrupting both books. Same
   pattern in `dashboard.py` (`LOG_DIR = BASE_DIR / "logs"`) and `run.py`'s
   `KILL_SWITCH_FILE`.
6. `dashboard.py` + `templates/index.html` — "Gold Scalper Dashboard" is
   hard-coded in 4 places; needs a title from config (and port 8089).
7. `mt5_bridge.open_trade` — comment `"Gold Scalper v7"` (cosmetic) and
   `config.MAGIC_NUMBER = 999111` must become e.g. `999112` so LIVE deal
   matching (`positions_get`/`LiveLedger`) can never confuse the two books.
8. `config.py` risk gates — `MAX_DAILY_LOSS=30` / `MAX_TRADES_PER_DAY=15` are
   calibrated to gold's ~$6 median loss. At 0.01 BTC lots a stop-out risks
   ~$1–3, so −$30/day would need ~10–15 consecutive stop-outs: a gate that can
   barely fire before the 15-trade cap. Re-derive both from measured BTC P&L
   or they are dead code (exactly the class of problem the gold handoff
   documented for `MAX_CONSECUTIVE_LOSSES` and `atr_min`).
9. `research/strategy_sweep.py` — `CONTRACT_SIZE = 100.0` (line 41) and the
   gold-dollar spread sweep list (0.30–0.51). Method reusable, values not.
10. `research/parity_test.py` — fake tick at 4000.0 (gold price). Harmless, but
    the parity fixture should use something near the BTC price.

## 5. Plan, with decision gates

**Phase 0 — server recon (~15 min, read-only).** Run `btc/recon.py` on
`scalping` (commands below). It prints the contract spec, account leverage,
spread-vs-ATR economics, weekday/hour coverage (to confirm 24/7 and find any
maintenance break), and writes `data/BTCUSD_M5.csv` + `data/BTCUSD_M1.csv` in
the same format as `GOLD_M5.csv`. *Gate: symbol exists, tick/point math sane,
enough bars — otherwise stop.*

**Phase 1 — does the strategy shape have an edge on BTC at all?** Wire the
backwards-compatible hooks (§4.1–4.4, 4.5) behind defaults equal to today's
values, prove gold is untouched (§6), then run the existing tooling on BTC
data: `--verify` → `--sweep` (RSI / session / BE / SL / TP / ATR floor) →
`--oos` (train-select, cold read) → `--candidates` → `loss_analysis.py`.
*Gate: train-only selection that stays positive cold on OOS with PF ≳ 1.2 and
sane spread economics. If BTC fails this, the honest output is a one-page
negative result and no service — the tooling costs nothing to run and this is
the whole reason to use it.*

**Phase 2 — the service (~1–2 h).** `btc/config.py`, shims, per-instance log
dir, `scalper-btc-bot.service` + `scalper-btc-dashboard.service` (:8089),
`deploy.sh` restarting both, `.gitignore` for `btc/logs/`. `TRADING_MODE =
"FORWARD_TEST"` from day one.

**Phase 3 — paper in parallel with gold.** The BTC book earns its own launch
criteria (its own 100+ trades clock from its first deploy). Only then a LIVE
conversation — and a separate one from gold's.

## 6. Gold-safety rules (non-negotiable while both bots share the tree)

- A shared-file change is only acceptable if **all** of these still hold:
  - `python backtest.py` → `255 trades / +$456.58 / PF 1.32 / max DD $108.65 /
    72 TP / 43 BE / 140 SL` (verified reproducible in the Arena sandbox on
    2026-10-03 — took ~45 s);
  - `python research/parity_test.py` → PASS, 0 mismatches;
  - `TRADING_MODE` stays `"FORWARD_TEST"` and no gold parameter changes.
- Every new config key must default to today's value so the gold path is
  bit-identical when the key is absent.
- New code lives in `btc/`; shared files receive hooks only, never refactors.
- Both bots write **only** to their own log directory.

Local harness (sandbox has no pandas by default):

```bash
python3 -m venv /tmp/v1 && /tmp/v1/bin/pip install pandas numpy rpyc
cd /home/user/scalper && /tmp/v1/bin/python backtest.py     # expect 255 / +$456.58 / PF 1.32
# server equivalent (existing venv, already has everything):
cd /root/scalper && mt5env/bin/python backtest.py
```

## 7. Phase 0 commands (run on `scalping`)

```bash
cd /root/scalper
mt5env/bin/python btc/recon.py --bars 20000            # spec + stats + data/BTCUSD_M5.csv
mt5env/bin/python btc/recon.py --bars 20000 --timeframe M1 --out data/BTCUSD_M1.csv
ss -tlnp | grep -E '8088|8089'                          # confirm 8089 is free for the 2nd dashboard
# concurrency check: with the gold bot running, this must not disturb it
mt5env/bin/python - <<'PY'
import rpyc, time
c = rpyc.classic.connect("localhost", 18812); mt5 = c.modules.MetaTrader5
mt5.initialize(); mt5.symbol_select("BTCUSD", True)
t0 = time.time()
for _ in range(20):
    r = rpyc.classic.obtain(mt5.copy_rates_from_pos("BTCUSD", mt5.TIMEFRAME_M5, 0, 1050))
    assert r is not None and len(r) > 0
print("20x BTC fetches ok in %.1fs" % (time.time() - t0))
# NOTE: deliberately no mt5.shutdown() - the gold bot shares this terminal session
PY
journalctl -u scalper-bot -n 20 --no-pager               # gold bot must show no new errors
```

`recon.py` is read-only (no orders, no `shutdown()`), so it is safe to run
against the live paper bot. `fetch_data.py` does call `mt5.shutdown()` — prefer
`recon.py` for BTC pulls while gold is running.

## 8. Risks / open questions

1. **Edge risk (the big one).** Gold's own book only survives on a thin tail
   (top-5 winners = 57% of net; WR 28.2% vs 28.6% structural break-even). There
   is no reason to assume the same shape works on BTC — Phase 1 exists to test
   that, and may end in "no".
2. **Shared-bridge concurrency.** One RPyC server, two clients, one
   `MetaTrader5` module instance inside the container. Phase 0 measures it.
   Fallback: a second container (`mt5-btc`) on port 18813 with its own Wine
   prefix — same image, add a compose service; costs RAM and a second login.
   *Not needed unless the test is flaky.*
3. **24/7 → swap exposure.** A BTC trade opened near the financing time can be
   charged; nothing in the engine models this today (already flagged for gold
   in the gold handoff §5). Decide: avoid entries near the swap hour, or model
   swap in the paper book — don't ignore it silently.
4. **Weekend gap fills.** Crypto CFDs can gap on the weekly open; pessimistic
   SL-first resolution (already in `paper.py`/`backtest.py`) helps but does not
   model slippage.
5. **Account sharing.** If BTC and gold ever run LIVE on the *same* XM account,
   they share balance/margin while each keeps its own daily-loss gate — two
   bots can each think they are within risk while the account is not. Decide
   now whether BTC gets its own account.
6. **Data source.** XM CFD bars (same bridge, same instrument we would trade,
   includes the real spread column) versus exchange data (tighter spreads, but
   not the thing we trade). Recommend XM; revisit only if BTC backtests are
   spread-dominated.
7. Open: should the BTC instance live on `main` with gold (simplest, one cron)
   or on its own long-lived branch/repo (independent cadence, double
   maintenance)? Recommendation: `main` while both are paper-only.

## 9. Changelog

| Date | Change | Why |
|---|---|---|
| 10-03 | Created this file: reusability audit, proposed instance-dir architecture, gold-hardcoded-assumption list (§4), phased plan with decision gates, Phase 0 recon script `btc/recon.py`. **No gold code touched, nothing deployed.** | User asked whether a BTC scalper is cheaper to set up given the gold work, and asked for a separate handoff. |
