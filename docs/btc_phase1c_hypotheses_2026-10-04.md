# BTC Phase-1c Hypotheses — pre-registered 2026-10-04 (hybrid redesign)

**Status:** `TRADING_MODE="FORWARD_TEST"` on both instances. BTC service remains
`disabled/inactive` (`:8089` not listening). No LIVE.

Phase-1b **FAIL/No-Go** is recorded (`docs/btc_phase1_result_2026-10-03.md`):
20k BTCUSD M5 on XM Standard → `-165.84 PF 0.74`, `spread/risk 26%` (gold `5%`),
required WR `36%` vs actual `23.8%`, gross `+0.04$/trade` vs `0.42$` spread.
Re-searching that file is *tuning on inspected data* and is forbidden
(`btc/HANDOFF.md` §5, §9). Phase-1c needs **untouched data** + a **new shape**.

Per the 2026-10-04 redesign (user choices: `hybrid` + `revisit_strategy` +
`keep_split` dashboards + `portfolio` gate, `ACCOUNT_MODE=shared|isolated`),
the plumbing now supports either topology without code change. This doc
pre-registers the three hypotheses that may be tried next — each gets its own
`btc/train_select.py`-style train→cold-OOS gate.

---

## Data hygiene — what is "untouched"?

- **Inspected window:** `2026-07-25 21:55` .. `2026-10-03 13:40` UTC (20k M5)
  — every bar in it is compromised for future selection.
- **Untouched:** any bars whose `time < 2026-07-25 21:55` **or** whose pull starts
  *after* this doc's date and is evaluated on a **cold split the selector never
  sees during ranking**. Easiest on `scalping` (where the bridge lives):

```bash
cd /root/scalper
# Pre-inspected M5 — strict out-of-sample for the old shape
mt5env/bin/python fetch_data.py --symbol BTCUSD --timeframe M5 --bars 20000 --start-pos 20000 --out data/BTCUSD_M5_pre_inspected.csv
# Fresh forward window (collect after today; not yet existent until history accumulates)
mt5env/bin/python fetch_data.py --symbol BTCUSD --timeframe M5 --bars 20000 --out data/BTCUSD_M5_forward.csv
# M15 / H1 where stop dwarfs spread
mt5env/bin/python fetch_data.py --symbol BTCUSD --timeframe M15 --bars 20000 --out data/BTCUSD_M15.csv
mt5env/bin/python fetch_data.py --symbol BTCUSD --timeframe H1  --bars 20000 --out data/BTCUSD_H1.csv
```

Every Phase-1c run must be `btc/tool.py btc/train_select.py --csv <untouched file>`.
The existing `research/strategy_sweep.py --oos / --candidates` reports are **gold-specific**
and must not be read as BTC selection.

---

## Hypothesis A — M15 / H1, same shape, larger stop

**Idea:** The signal family (EMA200 + RSI pullback + ATR SL/TP + BE) is spread-dominated on M5
because `SL ≈ 163 px = $1.63` and spread `42 px = $0.42` → `26%`. On M15/H1 the same
`2×ATR` stop is `~$5–10` (derive via `btc/derive_params.py --csv data/BTCUSD_M15.csv`),
so `spread/risk` falls to `~7–10%`. Fewer trades, but each pays less spread.

**What to vary:** `TIMEFRAME = M15|H1`, re-derive `ATR_MIN` from that timeframe's ATR quartiles,
re-derive `MAX_SPREAD_POINTS` from its spread p90 ×1.25. Keep RSI/SL/TP grid but rank on TRAIN only.

**Gate (same as Phase-1b, on untouched file):**
- `btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M15.csv --verify` must match
  `backtest.py` on that CSV first; else STOP.
- `btc/tool.py btc/train_select.py --csv data/BTCUSD_M15.csv` — frozen TRAIN winner must be
  `net > 0` **and** `PF ≥ 1.2` on **cold OOS**, with `n ≥ 60` and `spread/risk < 15%`.

**Why it might win:** Cost arithmetic improves mechanically; gold's 1000-bar EMA window still converges on M15.

**Why it might still lose:** Fewer bars → fewer regimes, wider stops → larger drawdowns, same coin-flip gross.

---

## Hypothesis B — Lower-spread account tier (XM Ultra Low)

**Idea:** Standard `500 pt ≈ $5/lot` vs Ultra Low `~225 pt ≈ $2.25/lot` → halves `spread/risk` from `26%` to `~12%`
without changing timeframe. If the raw gross `+$0.04/trade` is unbiased, halving cost turns `-0.38/trade` to `-0.17/trade`
— not enough alone, but paired with A it crosses.

**How to test:** Open a **demo** Ultra Low BTCUSD account, run `btc/recon.py` + `btc/derive_params.py` on it to measure
its real spread p90/mean and `PRICE_DIGITS`/`contract_size`. Then pull an **Ultra Low** bar file (bridge logs into that terminal)
and repeat Phase-1b gate on *that* file — never compare Standard bars at Ultra Low cost.

**Gate:** Same TRAIN→cold-OOS PF/net gate on the Ultra Low bar file, with cost from *that* file's spread column.
Also require live paper `tick spread` (via `get_live_tick`) to stay `< MAX_SPREAD_POINTS` in paper.

**Risk:** Demo vs real slippage, commission (Ultra Low charges commission), swap. Must model commission (`deal.commission`) in replay.

---

## Hypothesis C — New family: Donchian breakout + time-stop (no RSI, no BE ratchet)

**Idea:** Phase-1b anatomy shows `96%` of gross loss is full SL and `BE` costs only `3.9%` (`$24.90`) — exit management has nothing to give,
and the gross edge is `+$0.04/trade`. A family that *doesn't* optimize BE/RSI but seeks a larger gross edge (breakout captures
tails) might clear the same spread where the pullback mean-reversion cannot.

**Shape (example to pre-register):**
- Donchian(20) close-breakout with EMA200 trend filter, `ATR_MIN` as before, `SL = 2.5×ATR`, `TP = none` + **time-stop 18 bars (90 min M5)**,
  no BE ratchet (or `BE=off`). Session filter `off`, entry blackout windows still respected.

**Where to implement:** `btc/strategy_btc.py` — implement `class BtcStrategy` with `check_signal(rates, when=None) -> (signal, sl_dist, tp_dist)`
using the same closed-bar, one-shot-per-bar, blackout semantics as `ScalpStrategy`. Wire via `btc/config.py:BTC_STRATEGY="donchian"` and
teach `research/strategy_sweep.py` a `params_from_config` branch for it.

**Gate:** Same train-select grid (now over breakout-channel / time-stop) on **untouched** M5, then also on M15 (C+M15 interaction).
Must pass `--verify` equivalence, then TRAIN-selection → cold-OOS net/PF gate. Also require live paper to not straddle swap (entry blackout enabled after recon).

**Why it might win:** Tail capture vs mean-reversion; time-stop trims dead losers that never reach TP.

**Why it might lose:** Breakouts are also spread-sensitive; time-stop can cut winners.

---

## What is NOT allowed

- Re-using the `2026-07-25..10-03` 20k for ranking (you may still run diagnostics on it, but never select).
- Loosening `MAX_SPREAD_POINTS` to let a negative-EV shape show trades (that is `high_spread` skips at ~4000 pt vs `1500` placeholder — the placeholder was the bug, not the market).
- Copying gold's `TP 5.0 / BE 1.5 / RSI 40/60 / session 07-20` onto BTC without re-ranking.

## Minimal runbook once a hypothesis is chosen

```bash
# 1. Verify plumbing on the chosen untouched CSV
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M15.csv --verify   # must match backtest.py
mt5env/bin/python btc/tool.py btc/derive_params.py --csv data/BTCUSD_M15.csv

# 2. Gate (BTC selector, not gold's --oos)
mt5env/bin/python btc/tool.py btc/train_select.py --csv data/BTCUSD_M15.csv --bootstrap 10000

# 3. If PASS (net>0 and PF≥1.2 on cold OOS), and user explicitly authorizes paper:
DEPLOY_SERVICES="scalper-bot scalper-btc-bot"  # opt-in, default deploy stays gold-only
# and enable entry blackout after terminal recon confirms server UTC offset
```

Until a gate **PASSes** on untouched data, `btc/config.py` stays `PLACEHOLDER`, `TRADING_MODE` stays `FORWARD_TEST`,
and both portfolio-aware dashboards keep showing BTC as paper-only (the portfolio banner will show combined PnL but BTC contributes little).

---

## After a PASS — what the redesign already gives you

- **Same .env** — no new secrets: `ACCOUNT_MODE=shared` keeps one login/pool with the new `PORTFOLIO_MAX_DAILY_LOSS=38 / TRADES=25` gate;
  flipping to `isolated` adds a second login (`MT5_BTC_LOGIN` + `MT5_BTC_PORT=18813`) and the bridge lock / no-shutdown fixes already protect both.
- **Split dashboards + portfolio** — `:8088` gold + `:8089` btc both render the same `portfolio` banner and `GET /api/portfolio`.
- **Deploy** — `deploy.sh` defaults to `scalper-bot` only; BTC joins only with explicit `DEPLOY_SERVICES="scalper-bot scalper-btc-bot"`.
