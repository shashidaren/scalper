# BTCUSD Phase 1b — session bootstrap (2026-10-03)

## 1. Current state and stale instructions

This file replaces an earlier bootstrap whose branch/bundle instructions are no
longer current. **PR #16** (`a4d6ecf`), **PR #17** (`d8add56`) and **PR #18**
(`f5e76c8`) are already merged into `main`. Do not fetch/apply the old private
bundle or patch series, and do not switch away from the Arena-assigned branch
for the session you are in — `arena/01a102b0-scalper` for the dashboard-label
session, `arena/01a102c4-scalper` for the Phase 1b record.

At the start of the earlier session, the expected tree hash
(`614f0e512e99efc226a8cdff9f569fd9c4d2c56b`) did not match the checkout
(`993c8d7e4dcbfbf280246af1d4f1c39ac507e05`). That tree hash was specified
for the separate private branch/bundle in the old instructions, which is
not available here. The referenced `server_phase1b_commands.sh`, bundle,
and patch files are not present in the checkout.

## 2. Mission

> ### ✅ OUTCOME 2026-10-03 — mission complete: **FAIL / No-Go.** This bootstrap is now historical.
>
> Phase 1b **was run on real XM BTCUSD data** on `scalping` at
> `2026-10-03T17:07:55+00:00` (`/root/scalper` clean at
> `f5e76c8344d8393fe5779b4b29f053348a85ed94` on `main`, branch
> `arena/01a102c4-scalper`) and **the strategy does not clear the spread.**
> Full write-up: **`docs/btc_phase1_result_2026-10-03.md`**; handoff records in
> `btc/HANDOFF.md` (status banner + §9) and `HANDOFF.md` (§1, §3, §5).
>
> - `research/strategy_sweep.py --verify` reproduced `backtest.py` exactly:
>   **433 trades, −$165.84, PF 0.74, WR 23.8% (103W/330L), avgR −0.46, maxDD
>   $169.46, 107 TP / 59 BE / 267 SL.**
> - `btc/train_select.py` — the decision gate — **FAILED**: the frozen TRAIN
>   winner (`ATR p75=113.14, SL=2.0, BE=off`; TRAIN `44 tr, +$33.43, PF 1.29`)
>   reads **n=70, net −$46.11, PF 0.75, maxDD $56.29, P(net>0)=0.138** on cold
>   OOS, and the pre-registered baseline is worse (**n=217, −$95.50, PF 0.72,
>   P(net>0)=0.025**). Gate needs positive cold-OOS net **and** PF ≳ 1.2.
> - Mechanism, measured: **spread / median ATR = 52.0%**, **spread / risk =
>   26.0%**, so required WR ≈ **36.0%** vs **23.8%** actual; net before spread
>   **+$17.16 (+$0.04/trade)** vs **$183.00** spread paid. Structural, not
>   tunable — every one-variable sweep (SL/TP/BE/RSI/spread) is net-negative.
> - Therefore: **no BTC service, no BTC config change, no OOS tuning.**
>   `scalper-btc-bot` and `scalper-btc-dashboard` are `disabled`/`inactive`
>   (`:8089` not listening), `deploy.sh` keeps its gold-only default, and the
>   deploy crontab has no `DEPLOY_SERVICES` override. Phase 2 is blocked.
>   `config.py`, `btc/config.py`, `strategy.py` and `run.py` were left
>   untouched; `TRADING_MODE` stays `"FORWARD_TEST"` on both instances.
>
> The remaining sections below describe the mission as it stood *before* that
> run. Read them for method and gates, not for current state.

Determine from **real XM BTCUSD M5 data** whether the EMA200 + RSI-pullback +
ATR stop/target strategy can clear the near-fixed spread. A negative result is
valid; never tune until a result looks positive. Do not change BTC config values
or start a BTC service unless all handoff gates pass and the user explicitly
authorizes paper deployment. Gold must remain unchanged.

**Result: the negative result is the answer.** See the outcome block above and
`docs/btc_phase1_result_2026-10-03.md`.

## 3. Carry-over report — superseded by the 2026-10-03 17:07:55 UTC server check

> **This section is stale.** It records what an earlier session could only
> infer. A real server check (`python3 btc/server_check.py --journal 20` plus
> `crontab -l`) and the full Phase 1b run were completed on `scalping` at
> `2026-10-03T17:07:55+00:00` with `/root/scalper` clean at `f5e76c8`. The
> deltas that matter:
>
> | Item | Carry-over (16:47 UTC) | Observed (17:07:55 UTC) |
> |---|---|---|
> | HEAD | `d8add56` (PR #17) | **`f5e76c8` (PR #18)**, `git status --short` `<clean>` |
> | `scalper-btc-bot` | `disabled` but **active** (0 trades, `high_spread` skips) | **`disabled` + `inactive`** — stopped `16:50:21 UTC` after 0 trades |
> | `scalper-btc-dashboard` | `enabled` + `active` on `:8089` | **`disabled` + `inactive`**, `:8089` **not** listening |
> | Gold | active, open paper position | still `enabled`/`active`, `SIM: $128.62 \| SimEquity: $131.03`, open position undisturbed |
> | Deploy cron | unknown (`crontab -l` was missing from the report) | `*/15 * * * * DEPLOY_BRANCH=main …`, **no** `DEPLOY_SERVICES`/`DEPLOY_SERVICE`; last line `restarted scalper-bot at f5e76c8… (was d8add56…) branch=main` |
> | Phase 1b | not run (no BTC CSV in Arena) | **run on the real CSV — FAIL / No-Go** |
>
> The 433-trade / −$165.84 / PF 0.74 figure below was a carry-over *lead*; it is
> now **confirmed** by the verified `--verify` replay on the real file.

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
DNS resolution (re-confirmed 2026-10-03 on `arena/01a102c4-scalper`:
`ssh: Could not resolve hostname scalping`), so the BTC research was **not**
run from this sandbox — it was run on `scalping` itself and its output reported
back. The bridge concurrency probe is still outstanding (moot while no BTC unit
is installed). **Provenance matters when quoting these numbers: the BTC figures
are the server run's recorded output; the gold regressions and the BTC
isolation/selector/deploy tests were re-run locally and did pass here.**

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
