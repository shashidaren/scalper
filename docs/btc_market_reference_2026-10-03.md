# BTCUSD on XM — web reference sheet (2026-10-03)

**Status: web-sourced, NOT verified against the account.** Everything below was
collected from public broker/reference pages so the BTC work has a written
prior for each instrument number. None of it is evidence: the authority is the
terminal (`symbol_info` / `symbol_info_tick`), and `btc/recon.py` prints every
one of these fields in a single read-only pass. Where sources disagree, both
values are kept and the conflict is flagged — do not silently pick one.

Decision recorded with the user on 2026-10-03: **BTC runs on the same XM
account and the same MT5 terminal/bridge as gold** for the forward test. That
is acceptable while both books are paper (`TRADING_MODE="FORWARD_TEST"`); it is
*not* acceptable at the LIVE flip without a separate account or a hard
combined-account risk gate (`btc/HANDOFF.md` §8 risk 5).

---

## 1. Contract and sizing

| Field | Web value | Source | Confirm with |
|---|---|---|---|
| Contract size | **1 lot = 1 BTC** (gold: 100 oz) | [fxfan XM contract sizes](https://fxfan.club/en/xm/trading/), [XM margin list](https://fxfan.club/en/xm_margin/) | `symbol_info.trade_contract_size` |
| Min / step volume | **0.01 lots** | [XM crypto guide](https://xmsignal.com/en/blog/xm-crypto-trading-guide/), [tiomarkets BTCUSD lot sizing](https://tiomarkets.com/article/how-to-calculate-lot-size-for-btcusd) | `volume_min`, `volume_step` |
| Digits / point | 2 / 0.01 (assumed, typical for BTCUSD CFDs) | — | `symbol_info.digits`, `point` |
| $ per 1.00 of price at 0.01 lots | **$0.01** (0.01 lot × 1 BTC) — gold is $1.00 | derived | `btc/derive_params.py` |
| Leverage | **conflicting: 1:250 vs 1:500** for BTCUSD | 1:500 — [fxsignup crypto CFDs](https://xem.fxsignup.com/en/reason/crypto-cfds.html), [XM margin list](https://fxfan.club/en/xm_margin/); 1:250 — [XM crypto guide](https://xmsignal.com/en/blog/xm-crypto-trading-guide/), [fxsignup leverage](https://xem.fxsignup.com/en/reason/leverage.html) | `account_info.leverage` + `order_calc_margin` |
| Margin at 1 lot | ~$136 at $27k (1:500 example), ~$13 at 0.01 lots | [XM margin list](https://fxfan.club/en/xm_margin/) | `order_calc_margin` for the live price |

At 0.01 lots the economics are ~100× smaller per price unit than gold: a
2×ATR stop of ~$300 of BTC price is about **$3 of risk**, which is why
`MAX_DAILY_LOSS` cannot be inherited from gold's $30.

## 2. Spread

| Account type | Typical BTCUSD spread | Source |
|---|---|---|
| Standard | **500 points ≈ $5.00 per lot** (listed average) | [fxfan XM average spreads](https://fxfan.club/en/xm/trading/) |
| Standard (other listing) | 600 points | [fxfan XM comparison table](https://fxfan.club/en/xm/trading/) |
| Ultra Low | 225 points ≈ $2.25 | [fxfan XM average spreads](https://fxfan.club/en/xm/trading/) |
| Ranges seen elsewhere | $30–80 normal, $100–300 high volatility, $100–200 weekend | [XM crypto guide](https://xmsignal.com/en/blog/xm-crypto-trading-guide/) |

At 0.01 lots a 500-point spread is **$0.05 round trip** (gold's measured cost
is $0.47 at the same lot size). Relative to risk it is what matters: gold pays
~5.3% of a stop in spread (measured, `btc/derive_params.py` on `GOLD_M5.csv`);
BTC must be measured the same way from the CSV's own `spread` column before
`MAX_SPREAD_POINTS` / `SPREAD_COST_PRICE` mean anything. `btc/config.py` starts
deliberately loose at `MAX_SPREAD_POINTS = 1500`, because copying gold's 80
would skip every trade.

## 3. Hours, maintenance, swap — the part gold does not have

| Item | Web value | Source |
|---|---|---|
| Trading hours | 24 hours, 7 days, including weekends and holidays | [fxsignup crypto CFDs](https://xem.fxsignup.com/en/reason/crypto-cfds.html), [fxsignup trading hours](https://xem.fxsignup.com/en/reason/tradingtime.html) |
| Weekly maintenance halt | **Saturday 10:05–10:35 server time (GMT+2)** — crypto suspended | [fxsignup crypto CFDs](https://xem.fxsignup.com/en/reason/crypto-cfds.html) |
| Server time | GMT+2 winter / **GMT+3 in DST** (XM uses US DST dates) | [fxfan XM trading conditions](https://fxfan.club/en/xm/trading/) |
| Swap charge time | daily rollover at ~23:59 server time | [XS crypto specs (industry norm)](https://www.xs.com/en/markets/crypto/) |
| Triple swap day | **crypto/indices: Friday → Saturday** (FX/metals: Wednesday) | [fxfan XM swap rules](https://fxfan.club/en/xm/trading/), [afterprime BTCUSD hours](https://afterprime.com/trading-hours/btcusd) |
| Swap size | broker-specific, e.g. −26 / −19.5 points long/short elsewhere | [afterprime BTCUSD hours](https://afterprime.com/trading-hours/btcusd) |
| Weekend liquidity | spreads widen, order books thinner | [afterprime BTCUSD hours](https://afterprime.com/trading-hours/btcusd), [XS crypto specs](https://www.xs.com/en/markets/crypto/) |

**Implication for the engine.** Gold's market break hides both of these; a 24/7
book does not. Two things follow:

1. The engine still does **not** model swap P&L (true for gold too). For 5-minute
   scalps the exposure is one rollover at most, but it is not zero.
2. Opening a position *into* a rollover or a maintenance halt is avoidable, so
   this PR adds an optional, config-driven **entry blackout** (shared code,
   `ENTRY_BLACKOUTS_ENABLED` / `ENTRY_BLACKOUT_WINDOWS`, empty for gold):
   it only blocks new entries during named UTC windows. `btc/config.py` ships
   the two candidate windows **disabled**, because converting XM's server time
   to UTC depends on the DST state of the terminal, and a wrong offset would
   blank out the wrong hour. Confirm the offset with `btc/recon.py` (it prints
   terminal time vs UTC) before enabling.

Candidate windows currently in `btc/config.py` (winter/GMT+2 assumption):

```python
ENTRY_BLACKOUTS_ENABLED = False     # flip on once recon confirms the offset
ENTRY_BLACKOUT_WINDOWS = [
    {"name": "swap_rollover",  "start": "21:45", "minutes": 30},            # 23:59 GMT+2 = 21:59 UTC
    {"name": "xm_maintenance", "start": "08:00", "minutes": 45, "days": [5]},  # Sat 10:05-10:35 GMT+2
]
```

In DST (GMT+3) both shift one hour earlier: `20:45` and `07:00`.

## 4. How each line gets retired

Nothing above is settled until the matching command has been run **on the
server** and its output recorded in `btc/HANDOFF.md` §9:

```bash
cd /root/scalper
python3 btc/server_check.py                       # §0 evidence block (read-only, no MT5)
mt5env/bin/python btc/recon.py --bars 20000       # §1-§3: specs, spread/ATR, 24/7 coverage
mt5env/bin/python btc/tool.py btc/derive_params.py   # turns the CSV into config candidates
```

`btc/derive_params.py` is the bridge between this sheet and the config: run on
`data/GOLD_M5.csv` it reproduces gold's known facts (spread mean $0.47, 28.6%
structural break-even win rate, `MAX_DAILY_LOSS` ≈ $31 against the adopted
$30), which is why its BTC output can be trusted as a *starting point* — still
subject to the Phase 1 train-select → cold-OOS gate.
