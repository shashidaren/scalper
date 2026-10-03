# BTCUSD Phase 1b — session bootstrap (2026-10-03)

## 1. Current state and stale instructions

This file replaces an earlier bootstrap whose branch/bundle instructions are no
longer current. **PR #16** (`a4d6ecf`) and **PR #17** (`d8add56`) are already
merged into `main`. Do not fetch/apply the old private bundle or patch series,
and do not switch away from the Arena-assigned branch (`arena/01a102b0-scalper`
in this session).

At the start of the earlier session, the expected tree hash
(`614f0e512e99efc226a8cdff9f569fd9c4d2c56b`) did not match the checkout
(`993c8d7e4dcbfbf280246af1d4f1c39ac507e05`). That tree hash was specified
for the separate private branch/bundle in the old instructions, which is
not available here. The referenced `server_phase1b_commands.sh`, bundle,
and patch files are not present in the checkout.

## 2. Mission

Determine from **real XM BTCUSD M5 data** whether the EMA200 + RSI-pullback +
ATR stop/target strategy can clear the near-fixed spread. A negative result is
valid; never tune until a result looks positive. Do not change BTC config values
or start a BTC service unless all handoff gates pass and the user explicitly
authorizes paper deployment. Gold must remain unchanged.

## 3. Carry-over report — not freshly verified by this session

The prior bootstrap and user-reported server check (`2026-10-03 16:47 UTC`)
report the following server observations from `scalping`. Treat them as useful
leads, **not a fresh server check from Arena**:

- `/root/scalper` was clean at `d8add5678d74a1b6381c6e702432a0e1f0a0ce62` (PR #17).
- `data/BTCUSD_M5.csv`: 20,000 bars, 2026-07-25 21:55 to 2026-10-03 13:40 UTC,
  including about 5,600 weekend bars (`data/BTCUSD_M1.csv` absent).
- Median BTC price $77,304.55; ATR(14) p10/p25/p50/p75/p90 about
  29.58/48.32/81.62/121.31/179.03; spread mean 4,242 points ($42.41), mostly
  4,000–5,000 points. The old `MAX_SPREAD_POINTS=1500` placeholder vetoes
  entries at ~4,000 points.
- Gold parameters replayed on that BTC file reportedly gave 433 trades,
  −$165.84, PF 0.74. Binance proxy runs are **not evidence** for XM BTCUSD.
- Runtime finding (user-reported 16:47 UTC): `scalper-btc-bot` was `disabled`
  but **active** (SIM mode, 0 trades, repeated `high_spread` skips at 4,000
  points vs the 1,500-point placeholder), and `scalper-btc-dashboard` was
  `enabled` and `active` on `:8089`. Why `scalper-btc-bot` started on the first
  deploy after PR #17 merged: in `deploy.sh`, `SERVICES` is evaluated at line 17
  *before* `git pull --ff-only` at line 33, so the pre-PR-#17 script (`a4d6ecf`)
  still held `SERVICES="scalper-bot scalper-btc-bot"` in memory during the pull
  to `d8add56` and restarted both units one final time. Later cron runs on
  `d8add56` default to `scalper-bot` only (unless `crontab` overrides
  `DEPLOY_SERVICES`/`DEPLOY_SERVICE`), which does not stop an already-running
  process.
- Dashboard finding (verified & fixed in `arena/01a102b0-scalper`): the BTC
  dashboard (`:8089`) already displays real `BTCUSD` `bid`/`ask`/`spread` from
  `btc/logs/live_status.json`, while `templates/index.html` line 132 had
  `<h2>GOLD Price</h2>` hard-coded; now parameterized as
  `<h2>{{ config.symbol if config is defined and config.symbol else "GOLD" }} Price</h2>`.
  Also fixed `btc/server_check.py` `to_markdown()` to render `crontab -l`.

The current Arena workspace contains only `GOLD_M1.csv` and `GOLD_M5.csv`; it
has no BTC CSV. A read-only SSH attempt to host alias `scalping` failed with
DNS resolution, so this session could not run `btc/server_check.py` on
`scalping`, the real-file BTC sweep, or the bridge concurrency probe. **No new
BTC result or live server status is claimed from the Arena sandbox.**

## 4. Next steps — run on the server with the real BTC CSV

First collect current observed state (read-only):

```bash
cd /root/scalper
python3 btc/server_check.py --journal 20
```

Check that the BTC CSV exists and inspect the reported cron. `deploy.sh` now
defaults to restarting **only** `scalper-bot`; `DEPLOY_SERVICES` must not
include BTC before Phase 2. Then run the BTC research from the repository root:

```bash
mt5env/bin/python btc/tool.py btc/derive_params.py --csv data/BTCUSD_M5.csv
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --verify
# Compare trades, net, max drawdown, and TP/BE/SL exits in both outputs.
# Stop if they differ; --verify prints both engines side-by-side.

mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep sl
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep tp
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep be
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep rsi
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep spread
mt5env/bin/python btc/tool.py btc/train_select.py --csv data/BTCUSD_M5.csv
mt5env/bin/python btc/tool.py research/loss_analysis.py
```

`btc/train_select.py` is the BTC-specific replacement for the missing
provisional `/tmp/btc_train_select.py`: it derives ATR floors and a spread veto
from TRAIN bars only, ranks the fixed candidate grid using TRAIN net only, then
reads only a frozen winner and pre-registered baseline on cold OOS. It models
the per-bar spread cost and a TRAIN-derived spread veto, but not slippage, swap
P&L, daily account gates, or weekend gaps. `BE off` is represented by `None`;
never use `0` (it arms breakeven at entry).

Do **not** treat `research/strategy_sweep.py --oos` or `--candidates` as BTC
selection reports: those functions hard-code gold's RSI/session/ATR settings
and the gold calendar regime split. Use the BTC selector above, and keep the
OOS read cold.

## 5. Phase gates and safety

- The sweep verification is the first gate. Do not interpret later results if
  it does not reproduce `backtest.py` for the same BTC config and CSV.
- Derive `PRICE_DIGITS` / spread units from terminal specs. The live engine has
  an entry spread veto; do not start BTC with the 1,500-point placeholder if
  quotes remain near 4,000–5,000 points.
- Run the shared-bridge concurrency probe while observing gold before any BTC
  unit is installed or started.
- Phase 1 passes only if train-only selection remains positive on cold OOS,
  PF is approximately 1.2 or higher, trade count is adequate, and spread
  economics are sane. Otherwise write `docs/btc_phase1_result_<date>.md` as a
  negative result and keep BTC services stopped.
- Both configs remain `TRADING_MODE="FORWARD_TEST"`. The bots currently share
  one XM account/terminal; a separate account or hard combined-account risk
  gate is mandatory before any LIVE flip.
- Phase 2 needs a separate explicit user decision. Only then should the server
  opt in with `DEPLOY_SERVICES="scalper-bot scalper-btc-bot"` and install/start
  the BTC units. A deploy cron pulls `main`; it does **not** push commits to
  GitHub. Arena must push/merge the PR for the server cron to see a change.

Keep `HANDOFF.md` and `btc/HANDOFF.md` current with dated, observed evidence.
Do not record proxy data, unverified server state, or the gold-data smoke run of
the BTC selector as a BTC result.
