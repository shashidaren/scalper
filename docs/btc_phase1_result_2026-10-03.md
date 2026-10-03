# BTCUSD Phase 1b — negative result (FAIL / No-Go), 2026-10-03

**Question.** Does the EMA200 + RSI-pullback + ATR stop/target shape have an
edge on real XM `BTCUSD` M5 data after the broker's spread? Phase 1b is the
decision gate in `btc/HANDOFF.md` §5; if it fails, "a one-page negative result
is the deliverable and **no service**; do not tune on OOS."

**Answer: NO. FAIL / No-Go.** The frozen train-selected candidate is
**negative on cold OOS** (`n=70`, **−$46.11**, **PF 0.75**) against a gate that
requires positive cold-OOS net and PF ≳ 1.2. The pre-registered baseline is
worse (`n=217`, −$95.50, PF 0.72). Every one-variable diagnostic sweep over the
full 20,000 bars is also net-negative. BTC stays un-authorised, both BTC
systemd units stay `disabled`/`inactive`, and `deploy.sh` keeps its gold-only
default.

---

## 0. Provenance — read this before quoting a number

| Source | Status |
|---|---|
| Server state, `btc/derive_params.py`, sweep `--verify`, `btc/train_select.py`, diagnostic sweeps, `research/loss_analysis.py` — all on `data/BTCUSD_M5.csv` | **Observed on `scalping` at `2026-10-03T17:07:55+00:00`** (user-reported). `/root/scalper` at `f5e76c8344d8393fe5779b4b29f053348a85ed94`, `git status --short` clean. |
| `backtest.py`, `research/parity_test.py`, `btc/tool.py --check`, `btc/train_select_test.py`, `tests/test_deploy_services.sh` | **Re-run locally this session** (branch `arena/01a102c4-scalper`, HEAD `f5e76c8`) — see §7. |
| Re-running the BTC research itself from this checkout | **Not possible here, and not claimed.** This Arena container has only `data/GOLD_M1.csv` and `data/GOLD_M5.csv` (`data/*.csv` is git-ignored, `btc/HANDOFF.md` §6), and `ssh scalping` still fails DNS resolution from `e2b.local`. The BTC numbers below are the server run's recorded output, not a local reproduction. |

Per `btc/HANDOFF.md` §5, every research run is executed through `btc/tool.py`,
so the operative parameter set is `btc/config.py`'s **placeholders**: RSI 40/60,
`SL_ATR_MULT=2.0`, `TP_ATR_MULT=5.0`, `BE_TRIGGER_R=1.5`, `ATR_MIN=0.0`,
`SESSION_FILTER_ENABLED=False` — i.e. gold's adopted geometry *minus* gold's
07–20 UTC session window and 0.50 ATR floor — combined with BTC's own contract
maths (`CONTRACT_SIZE=1.0`, `PRICE_DIGITS=2`, `LOT_SIZE=0.01`).

**No code, config, or trading/engine parameter was changed to produce this
result.** `config.py`, `btc/config.py`, `strategy.py` and `run.py` are
untouched; `TRADING_MODE` remains `"FORWARD_TEST"` on both instances. This
document is documentation only.

---

## 1. Verdict first

The shape does not survive contact with BTCUSD's spread, and the failure is
**structural, not a tuning problem**:

1. **The raw signal is ~break-even before costs.** Net before spread across all
   433 trades is **+$17.16 = +$0.04/trade**. There is no gross edge for a lower
   cost basis to rescue.
2. **The spread is ~10× that edge.** Spread paid is **$183.00** (28% of gross
   profit, avg **$0.42/trade**). `+$17.16 − $183.00 = −$165.84`, which is
   exactly the reported net.
3. **Spread is enormous relative to the stop.** Median ATR(14) is 81.62 price
   units while mean spread is 42.41 → **spread/median-ATR = 52.0%**. Gold's
   measured equivalent is ~5.3% of a stop (`docs/btc_market_reference_2026-10-03.md`
   §2) — BTC is roughly **5× worse** on the only ratio that matters here.
4. **Therefore the required win rate is unreachable.** At RR 1:2.5 the
   structural break-even WR is **28.6%**; adding the spread pushes it to
   **~36.0%** (+7.4 pp). The strategy's actual WR is **23.8%**. The gap is
   12 percentage points and no exit knob in the grid closes it.
5. **Exit management is not the leak.** 267 stop-outs are **96.0%** of gross
   loss (−$606.26); the 59 breakeven scratches cost **$24.90** (3.9%). This is
   the same anatomy gold has — on gold the tail pays for it, on BTC it does not.
6. **No slice is positive.** All 4 months, all 4 ATR quartiles, 6 of 7
   weekdays, and both directions are net-negative. There is no regime or
   sub-population to retreat into.

**Decision: No-Go.** No BTC service, no BTC config change, no OOS tuning.
Phase 2 is blocked until something in §6 changes.

---

## 2. Server state at the time of the run (read-only, §0 checklist)

`python3 btc/server_check.py --journal 20` and `crontab -l` on `scalping`,
`2026-10-03T17:07:55+00:00`:

| Item | Observed |
|---|---|
| Host / repo | `scalping`, `/root/scalper` |
| HEAD | `f5e76c8344d8393fe5779b4b29f053348a85ed94` on `main` (PR #18: *"BTC: use config.symbol in dashboard price header and print crontab in server_check"*) |
| `git status --short` | `<clean>` |
| Deploy cron | `*/15 * * * * DEPLOY_BRANCH=main /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1` |
| Status cron | `15 1 * * * /root/scalper/scripts/paper_status_daily.sh …`; `0 1 * * 1-5 /root/scalper/scripts/paper_status_daily.sh …` |
| `DEPLOY_SERVICES` / `DEPLOY_SERVICE` in crontab | **Absent** — the gold-only default in `deploy.sh` is what runs. No Phase 2 opt-in exists. |
| Last deploy line | `2026-10-03T17:07:44+00:00 restarted scalper-bot at f5e76c8… (was d8add56…) branch=main` — **gold-only restart confirmed**; the PR #17 `deploy.sh` change is working as intended. |

Units and ports:

| Unit | installed | enabled | active | Notes |
|---|---|---|---|---|
| `scalper-bot` | True | enabled | **active** | `SIM: $128.62 \| SimEquity: $131.03`; open paper position undisturbed by the restart |
| `scalper-dashboard` | True | enabled | **active** | `:8088` listening |
| `scalper-btc-bot` | True | **disabled** | **inactive** | Stopped at `16:50:21 UTC` after **0 trades**, with repeated `high_spread` skips at ~4,000 points vs the 1,500-point placeholder |
| `scalper-btc-dashboard` | True | **disabled** | **inactive** | `:8089` **not** listening |
| MT5 bridge | — | — | — | `18812` listening (`docker-proxy`) |

The unauthorized `scalper-btc-bot` start reported at 16:47 UTC (the
`a4d6ecf` → `d8add56` transition deploy, where the old `deploy.sh` bound
`SERVICES` before `git pull`) is now resolved: the unit is stopped, disabled,
and the current cron default will not restart it. `tests/test_deploy_services.sh`
re-verified that locally (§7).

Datasets:

| File | State |
|---|---|
| `data/BTCUSD_M5.csv` | **20,000 bars**, `2026-07-25 21:55:00 .. 2026-10-03 13:40:00` (~70 days), 5,600 weekend bars, **24/24 hours covered** |
| `data/BTCUSD_M1.csv` | **absent** |

Phase 0's gate ("symbol exists, specs sane, 20k+ bars available") is therefore
satisfied — this Phase 1b result rests on a real, complete XM bar file, not a
proxy. Binance-proxy runs remain **not evidence** for XM BTCUSD.

---

## 3. Instrument economics — `btc/derive_params.py --csv data/BTCUSD_M5.csv`

Price and scale:

| Field | Measured |
|---|---|
| Median price | **$77,304.55** |
| `PRICE_DIGITS` | **2** — matches the `btc/config.py` placeholder, so that placeholder is now measured rather than assumed (still not adopted as a change in this session) |
| $ per 1.00 price move at 0.01 lots | **$0.0100** (`lot 0.01 × contract 1.0`) — 100× smaller per price unit than gold |

ATR(14) distribution (price units):

| p05 | p10 | p25 | p50 | p75 | p90 | max |
|---|---|---|---|---|---|---|
| 18.88 | 29.58 | 48.32 | **81.62** | 121.31 | 179.03 | 597.53 |

Spread (broker `spread` column):

| Unit | mean | p50 | p90 | p99 | max |
|---|---|---|---|---|---|
| points | **4,242** | 4,000 | 5,000 | 5,000 | 5,000 |
| price | **42.41** | 40.00 | 50.00 | — | 50.00 |

At 0.01 lots that is **$0.4242 round trip** — nominally *smaller* than gold's
$0.47, which is exactly why the absolute dollar figure misleads. Against risk:

| Metric | Value |
|---|---|
| SL at 2.0×ATR | 163.24 px = **$1.63 risk** |
| TP at 5.0×ATR | 408.11 px = **$4.08 target** |
| Reward:risk | 1:2.5 |
| **spread / median ATR** | **52.0%** |
| **spread / risk** | **26.0%** |
| Structural break-even WR (before spread) | **28.6%** |
| Spread penalty | **+~7.4 pp** |
| Required WR with spread | **~36.0%** vs **23.8% actual** |

**This is the whole Phase 1b story in one table.** A near-fixed $0.42 cost on a
$1.63 risk unit means the strategy starts every trade a quarter of a stop
behind. Gold pays ~5.3% of a stop in spread; BTC pays 26.0%.

---

## 4. Engine verification, then the decision gate

### 4.1 `research/strategy_sweep.py --csv data/BTCUSD_M5.csv --verify` vs `backtest.py` — **PASS**

The replay engine reproduces the reference backtester exactly on the BTC file,
so every number below comes from the same code path as the live strategy and
not a re-implementation:

| trades | net$ | PF | WR | W/L | avgR | maxDD$ | TP | BE | SL | exp$/trade |
|---|---|---|---|---|---|---|---|---|---|---|
| **433** | **−165.84** | **0.74** | **23.8%** | 103 / 330 | −0.46 | **169.46** | **107** | **59** | **267** | **−0.38** |

107 + 59 + 267 = 433 ✓. §5's "stop if they disagree" gate is cleared.

### 4.2 `btc/train_select.py --csv data/BTCUSD_M5.csv` — **FAIL**

Chronological split, warmup 1,000 bars:

| Segment | Range | Bars |
|---|---|---|
| TRAIN | `2026-07-29 09:10:00 .. 2026-08-31 11:15:00` | 9,500 |
| OOS (cold) | `2026-08-31 11:20:00 .. 2026-10-03 13:40:00` | 9,501 |

**Spread gate derived from TRAIN only:** TRAIN p90 = 5,000.0 pts → replay
`MAX_SPREAD_POINTS = 6,250` (1.25× p90). This vetoes **0.00%** of TRAIN quotes,
so the OOS read is not an artifact of the veto. By contrast the
`btc/config.py` placeholder `MAX_SPREAD_POINTS = 1500` would veto **100.00% of
TRAIN quotes** — a service started with that value would never open a trade,
which is exactly what the `scalper-btc-bot` journal showed at ~4,000 points.

**ATR floors derived from TRAIN only:** `zero=0.00`, `p10=19.94`, `p25=40.22`,
`p50=65.06`, `p75=113.14`.

**Grid:** 60 candidates (5 ATR floors × 3 SL multiples × 4 BE triggers),
minimum 20 TRAIN trades. Ranked on **TRAIN net only**; the winner was frozen
before any OOS read.

Top 10 on TRAIN:

| # | Config | trades | net$ | PF | maxDD$ |
|---|---|---|---|---|---|
| **1** | **ATR p75=113.14, SL=2.0, BE=off** ← *frozen winner* | **44** | **+33.43** | **1.29** | **26.71** |
| 2 | ATR p75=113.14, SL=2.5, BE=off | 42 | +29.05 | 1.23 | 31.57 |
| 3 | ATR p75=113.14, SL=2.5, BE=2R | 42 | +29.05 | 1.23 | 31.57 |
| 4 | ATR p75=113.14, SL=2.0, BE=1.5R | 48 | +24.56 | 1.21 | 26.85 |
| 5 | ATR p75=113.14, SL=3.0, BE=1R | 41 | +24.39 | 1.21 | 24.99 |
| 6 | ATR p75=113.14, SL=3.0, BE=off | 36 | +20.29 | 1.17 | 37.80 |
| 7 | ATR p75=113.14, SL=3.0, BE=2R | 36 | +20.29 | 1.17 | 37.80 |
| 8 | ATR p75=113.14, SL=2.5, BE=1.5R | 46 | +20.26 | 1.16 | 31.64 |
| 9 | ATR p75=113.14, SL=3.0, BE=1.5R | 41 | +18.56 | 1.15 | 24.99 |
| 10 | ATR p75=113.14, SL=2.0, BE=2R | 48 | +16.74 | 1.14 | 30.78 |

Two things about that table are themselves evidence of overfitting:

- **All ten share `ATR p75=113.14`** — the single highest floor in the grid. In
  sample, "trade less, only in the calmest bars" looks like an edge; it is a
  selection artifact, and the 44-trade sample is barely above the 20-trade
  eligibility floor.
- **BE is inert at these multiples** — `BE=off` and `BE=2R` tie exactly at
  SL=2.5 (rows 2/3) and SL=3.0 (rows 6/7), because a 2R breakeven move rarely
  resolves before the 2.5R target or the stop. Exit management has no lever
  here at all.

**Cold OOS read** (nothing below influenced the selection):

| Candidate | n | net$ | PF | maxDD$ | iid 95% CI | P(net>0) |
|---|---|---|---|---|---|---|
| Pre-registered baseline (configured geometry + TRAIN spread gate) | **217** | **−95.50** | **0.72** | 102.01 | [−190.49, +0.45] | 0.025 |
| **TRAIN-selected winner** (ATR p75=113.14, SL=2.0, BE=off) | **70** | **−46.11** | **0.75** | 56.29 | [−126.90, +37.82] | 0.138 |

Per-trade expectancy flips from **+$0.76 on TRAIN to −$0.66 on OOS** — a
**−$1.42/trade** decay, i.e. the entire in-sample edge is selection noise.

> **Screen gate verdict: FAIL.** `Cold-OOS net < 0` **and** `PF 0.75 < 1.2`.
> Both gate conditions fail, for both the selected candidate and the baseline.

---

## 5. Diagnostics — no knob rescues it

### 5.1 One-variable sweeps (all 20,000 bars, net after spread)

| Lever | Setting | trades | net$ | PF |
|---|---|---|---|---|
| **SL** | 1.0× | 664 | −338.79 | 0.44 |
| | 1.5× | 539 | −224.83 | 0.64 |
| | **2.0× (adopted)** | 433 | −165.84 | 0.74 |
| | 2.5× | 341 | −68.94 | 0.88 |
| | 3.0× | 280 | −6.96 | 0.99 |
| **TP** | 2.0× | — | −266.97 | 0.56 |
| | … | — | … | … |
| | 6.0× | — | −157.43 | 0.74 |
| **BE** | 0.50R | — | −320.29 | 0.44 |
| | 0.75R | — | −258.25 | 0.57 |
| | 1.00R | — | −220.01 | 0.64 |
| | 1.25R | — | −176.30 | 0.71 |
| | **1.50R (adopted)** | — | −165.84 | 0.74 |
| | off | 404 | −119.42 | 0.81 |
| **RSI** | 30/70 | 251 | −129.03 | 0.66 |
| | 35/65 | 353 | −182.03 | 0.66 |
| | **40/60 (adopted)** | 433 | −165.84 | 0.74 |
| | 45/55 | 448 | −177.76 | 0.72 |
| **Spread** | 5.00 (config fallback) | — | **−4.49** | 0.99 |
| | 42.41 (CSV mean) | — | −166.49 | 0.74 |
| | 40.00 (CSV median) | — | −156.04 | 0.75 |
| | 50.00 (CSV p90) | — | −199.34 | 0.70 |
| | **per-bar CSV (adopted)** | — | −165.84 | 0.74 |

Every single setting is negative. The `SL` ladder is monotone toward zero as
trades are suppressed (−$338.79 → −$6.96), which is what "cut the losses by
cutting the strategy" looks like — the best case is still a loss, on data that
was already inspected. The `Spread` row is the cleanest possible proof of the
mechanism: charging only the 5.00-price-unit config fallback instead of the
real spread moves the result from **−$165.84 to −$4.49** — a ~$161 swing, i.e.
**essentially the entire loss is the spread.** And even then PF is 0.99, not
above 1: the signal has no gross edge to expose.

### 5.2 Loss anatomy — `research/loss_analysis.py` (433 trades)

Gross profit **$465.72** / gross loss **$631.55** → PF 0.74.

| Exit | n | net$ | share of gross loss |
|---|---|---|---|
| TP | 107 | +465.33 | 0.0% |
| BE | 59 | −24.90 | 3.9% |
| SL | 267 | −606.26 | **96.0%** |

**Cost split — the decisive line:**

```
net before spread     +$17.16   (+$0.04/trade)
spread paid          −$183.00   (28% of gross profit, avg $0.42/trade, 1R = avg $1.82)
                       ---------
net after spread     −$165.84
```

Slices — nothing is positive anywhere:

| Slice | Result |
|---|---|
| Direction | BUY 239 tr, −$91.18, PF 0.76 · SELL 194 tr, −$74.65, PF 0.70 |
| Month | 2026-07 −$6.02 · 2026-08 −$69.74 · 2026-09 −$86.17 · 2026-10 −$3.89 (**4/4 negative**) |
| ATR quartile | q1 ≤46.3 −$58.72 PF 0.24 · q2 −$66.30 PF 0.49 · q3 −$20.62 PF 0.87 · q4 >118.4 −$20.20 PF 0.92 (**4/4 negative**) |
| Weekday | **6 of 7 negative**; Sat −$33.07 PF 0.38, Sun −$55.94 PF 0.24 (weekend liquidity is worst, as `docs/btc_market_reference_2026-10-03.md` §3 predicted) |
| Streaks | 76 losing streaks, mean 4.34, **max 20** |

A 20-trade losing streak at $1.63 risk is ~$33 — over 4× the
`btc/config.py` `MAX_DAILY_LOSS = 8.0` placeholder, so the daily gate would
halt the book repeatedly even if the edge existed. Note the ATR-quartile
gradient (PF 0.24 → 0.92 as volatility rises): the strategy is *least* bad in
the highest-volatility bars, which is exactly why the in-sample selector
gravitated to a high ATR floor — and why that "fix" is a mirage once the
selection is honest (§4.2).

---

## 6. What this does and does not rule out

**Ruled out (with evidence):** this strategy shape, at BTCUSD's current XM
spread, at 0.01 lots, on M5, over `2026-07-25 .. 2026-10-03`. Also ruled out:
every single-knob variation of SL, TP, BE, RSI and spread assumption tested
above, and the "trade only calm bars" ATR-floor rescue.

**Not ruled out — and explicitly *not* to be chased by tuning this dataset:**

1. **A different instrument class of edge.** A ~52% spread-to-ATR ratio is a
   property of this symbol/account, not of the code. A wider timeframe (M15/H1,
   where the stop dwarfs the spread), a lower-spread account tier, or a
   non-spread-dominated strategy family are all untested here.
2. **Cost reduction as a precondition, not a tweak.** At `SPREAD_COST_PRICE =
   5.00` the same trades net −$4.49 (PF 0.99) — still not an edge, so cheaper
   execution is *necessary but not sufficient*.
3. **Swap P&L and slippage remain unmodelled** (`btc/HANDOFF.md` §8 risks 3/4),
   and `data/BTCUSD_M1.csv` is absent, so intra-bar exit ordering is
   unmeasured. Both would make the result **worse**, not better.

**Explicitly prohibited by §5 and not done:** no tuning against the OOS half,
no re-run of the grid after seeing OOS, no adoption of any of the TRAIN
winners. `research/strategy_sweep.py --oos` / `--candidates` were not used as
BTC selection reports (they hard-code gold's settings and the gold regime
split).

### Follow-ups recorded (none executed in this session)

- [ ] **Keep BTC stopped.** `scalper-btc-bot` and `scalper-btc-dashboard` remain
  `disabled`/`inactive`; `deploy.sh` keeps the gold-only default; the deploy
  crontab must **not** gain a `DEPLOY_SERVICES` opt-in. Phase 2 is blocked.
- [ ] **Do not "fix" `MAX_SPREAD_POINTS = 1500` in isolation.** It is now known
  to veto 100.00% of TRAIN quotes, but the correct response to a No-Go is to
  leave the placeholder flagged and the service off — not to loosen a gate so a
  losing strategy can trade. Any future change needs a re-run of this gate.
- [ ] **Re-derive `MAX_DAILY_LOSS` / `MAX_TRADES_PER_DAY` only if Phase 1 is
  ever re-attempted.** Measured: avg 1R = $1.82, max losing streak 20 → the $8
  daily gate and the 15-trade cap are both mis-scaled for this instrument.
- [ ] **If BTC is revisited, it needs a new pre-registered hypothesis first** —
  different timeframe or account tier, its own untouched data pull, and the
  same train-select → cold-OOS gate. Reusing this 20,000-bar file for a fresh
  search would be tuning on inspected data.
- [ ] **Phase 0's shared-bridge concurrency probe was not run** and is now
  moot while no BTC service exists; run it before any future BTC unit is
  installed or started (`btc/HANDOFF.md` §7).

---

## 7. Verification re-run locally this session (gold unchanged)

Branch `arena/01a102c4-scalper`, HEAD `f5e76c8344d8393fe5779b4b29f053348a85ed94`,
local venv (`pandas numpy rpyc jinja2 fastapi uvicorn`). **No source file was
modified** — these confirm the documentation-only change did not disturb
anything, and that the gold-safety baseline in `btc/HANDOFF.md` §6 still holds.

| Check | Command | Result |
|---|---|---|
| Gold backtest | `backtest.py` | **255 trades / +$456.58 / PF 1.32 / max DD $108.65 / WR 28.2% / 72 TP · 43 BE · 140 SL / avgR 0.11** — byte-identical to the §6 baseline |
| Live↔replay parity | `research/parity_test.py` | **PASS** — 460 replay signals, 0 mismatches; window+50 margin 0 mismatches; bridge cache 1,200 loops → 60 fetches (20× reduction), 0 signal/timing mismatches; blackout check 876 bars blocked / 40 real signals suppressed / 0 mismatches |
| BTC instance isolation | `btc/tool.py --check` | **11/11 PASS** — btc config wins, `LOG_DIR=btc/logs`, `CONTRACT_SIZE=1.0`, `PRICE_DIGITS=2`, `MAGIC 999112`, `FORWARD_TEST`, sweep `POINT=10^-2`, template shows `BTCUSD Price` |
| Selector helpers | `btc/train_select_test.py` | **PASS** — 60-config grid (matches the 60 candidates actually ranked in §4.2), no `BE=0`, TRAIN-only ranking, spread-veto integration, split boundaries |
| Deploy guard | `tests/test_deploy_services.sh` | **PASS 3/3** — default `scalper-bot` only; explicit `DEPLOY_SERVICES` opt-in includes BTC; legacy singular `DEPLOY_SERVICE` override preserved |

Gold's numbers are the regression contract for the BTC work: **255 / +$456.58 /
PF 1.32 / max DD $108.65 / 72-43-140**, unchanged.

---

## 8. Reproduce on `scalping`

```bash
cd /root/scalper
python3 btc/server_check.py --journal 20                                   # §2 evidence block
mt5env/bin/python btc/tool.py btc/derive_params.py --csv data/BTCUSD_M5.csv
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --verify
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep sl
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep tp
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep be
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep rsi
mt5env/bin/python btc/tool.py research/strategy_sweep.py --csv data/BTCUSD_M5.csv --sweep spread
mt5env/bin/python btc/tool.py btc/train_select.py --csv data/BTCUSD_M5.csv   # the decision gate
mt5env/bin/python btc/tool.py research/loss_analysis.py
```

**Recorded result: Phase 1b = FAIL / No-Go.** No BTC service, no config change,
no OOS tuning. Gold continues unchanged in `FORWARD_TEST`.
