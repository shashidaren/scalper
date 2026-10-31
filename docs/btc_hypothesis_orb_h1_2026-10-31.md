# BTC hypothesis D — pre-registration: European opening-range breakout on H1

**Hypothesis ID:** `BTC-ORB-EU-H1` · **Date locked:** 2026-10-31 · **Status:** PRE-REGISTERED, DATA NOT YET PULLED

**Nothing trades differently because of this document.** `TRADING_MODE` stays
`FORWARD_TEST`, `BTC_STRATEGY` stays `scalp`, `btc/config.py` is untouched, and
no service unit is changed. This is a research protocol: it fixes the shape, the
grid, the split and the gate *before* one bar of the deciding data is read. The
untouched XM window is reserved and the hashes are still PENDING (§5.3) because
this checkout cannot reach the MT5 bridge — one command on `scalping` fills them
(`btc/freeze.py`, §5.2).

---

## 0. The decision, and the three options it rejected

Executing `plans/btc.json` phase 1 ("pre-register a new BTC hypothesis on
untouched bars") required choosing *which* new shape may consume the one
untouched XM era this repo has left. The repo's own screen-first rule
(`docs/btc_spread_edge_analysis_2026-10-06.md` §6.5) says that choice is made on
proxy bars first, and that a screen is a hypothesis, never a selection.

**Decision: pre-register `BTC-ORB-EU-H1`** — a session-anchored opening-range
breakout on XM H1, stop-entry at the range boundary, ATR stop, hard time-flat at
20:00 UTC, no take-profit, no breakeven ratchet, no trailing stop, nothing held
overnight. It is the only family of the three screened whose **gross edge pays
the spread in every proxy era** (§2.2), and it is mechanically unlike both
failed shapes.

Rejected, with the reason:

| option | why not |
|---|---|
| **Re-test the failed Donchian shape** on the untouched pre-2024 window | Forbidden by the plan's hard rules ("never re-tune the RSI-pullback / Donchian shape"), and a failed shape is not a hypothesis. The 2026-10-31 screen also shows the slow-trend family is the one that keeps its 2021–24 proxy edge — i.e. the *feed* question is not the open one. |
| **Session momentum** (`momentum`: 07:00 body → 08:00 close) | Screened: all six cells lose money net over 8 years (PF 0.86–0.98, −$50 to −$679) and 2021–22 is negative in every cell. No untouched pull spent. |
| **Prior-day range breakout** (`pdr`) | Screened: its EMA200 cells are positive (+$383 to +$568, PF 1.09–1.15) but it is a level breakout of the *previous day's* range — mechanically the closest of the three to the failed Donchian family, which is exactly what a new hypothesis was supposed to avoid — and its 2025 cells are negative (PF 0.73–0.91). Kept on file as the runner-up, not chosen. |
| **Close-entry ORB** (the engine's existing closed-bar convention) | Screened: all six cells lose money (PF 0.88–0.89). The family only survives at the *stop-entry* fill, which is also the correct way to trade an opening range (§2.1). |

The honest summary: this is a **thin, tail-dependent candidate** (§2.3), not a
rediscovered edge. Its proxy prior for the exact era being reserved is close to
flat (§2.4), so the most likely outcome is a fail that closes the intraday
family class. It is worth the window because either outcome is decisive and the
window is otherwise idle.

---

## 1. What "untouched" means here

Two XM pulls are inspected, and their union is the inspected era:

| file | span (UTC) | sha256 | state |
|---|---|---|---|
| `data/BTCUSD_M5.csv` (Phase 1b) | 2026-07-25 21:55 → 2026-10-03 13:40 | — | burnt |
| `data/BTCUSD_H1.csv` (Phase 1c) | **2024-06-25 22:00 → 2026-10-07 05:00** | `f73054611e9b27a589b55c63f4a9a4f734ac9c423c1f528d1b6c344bc023ab21` | burnt |

The H1 file spans both, so **every bar at or after `2024-06-25 22:00 UTC` is
inspected.** The only XM bars this repo has never read are therefore
`time < 2024-06-25 22:00 UTC`, which is the era this hypothesis is allowed to
use. `btc/freeze.py` refuses a cutoff later than that (`--inspection-start`) and
refuses the burnt sha256, so the boundary cannot be widened by a later session
by accident.

Two disclosures:

- **Proxy history is not XM history.** The screen in §2 read Binance spot klines
  through 2025-06. It is a prior, not evidence, and it cannot be quoted as an XM
  result (`btc/HANDOFF.md` "Do not").
- **The current paper book is not evidence.** `btc/logs/` is an observation feed
  running the shape that already failed Phase 1. No trade in it counts here.

---

## 2. The screen (proxy, diagnostic only — not a selection)

Tool: [`btc/session_screen.py`](../btc/session_screen.py), stdlib-only, with an
offline self-test. Data: `BTC_1h.csv` from `github.com/Pennyihui/data`
(Binance spot, 68,331 bars, 2017-08-17 04:00 → 2025-06-08 14:00 UTC,
sha256 `f18231d1b2b3e2c579652b0ffacadc7f6bc701f11779414cd8d22e4127dc2ac3`).
Cost: 5.486 bp of price per round trip — the measured XM Standard spread
(`docs/btc_spread_edge_analysis_2026-10-06.md` §2). Warm-up 1,000 bars.

```bash
python3 btc/session_screen.py --csv /tmp/proxy/BTC_1h.csv --eras --detail
python3 btc/session_screen.py --csv /tmp/proxy/BTC_1h.csv --family orb \
        --entry-mode stop --eras
```

`grossR` is mean R with cost at zero, `costR` is mean (spread ÷ stop distance),
`netR = grossR − costR`, and `net$` is at 0.01 lots. A family only deserves an
untouched pull when **grossR > costR** on the eras that matter.

### 2.1 Fill mode is the whole difference

The same ORB rule with the engine's existing closed-bar fill (enter at the close
of the bar that has already broken out):

| stop × filter | n | grossR | costR | netR | PF | net$ |
|---|---|---|---|---|---|---|
| 1.0 × off | 1982 | +0.088 | 0.083 | +0.005 | 0.89 | −426.72 |
| 1.0 × ema200 | 1445 | +0.079 | 0.084 | −0.005 | 0.89 | −301.58 |
| 1.5 × off | 1982 | +0.070 | 0.055 | +0.014 | 0.88 | −544.14 |
| 1.5 × ema200 | 1445 | +0.073 | 0.056 | +0.017 | 0.89 | −368.35 |
| 2.0 × off | 1982 | +0.051 | 0.042 | +0.009 | 0.88 | −581.84 |
| 2.0 × ema200 | 1445 | +0.060 | 0.042 | +0.018 | 0.88 | −416.23 |

With a resting order at the range boundary (fill **at the level**, a gap-through
fills at the open):

| stop × filter | n | grossR | costR | netR | PF | net$ |
|---|---|---|---|---|---|---|
| 1.0 × off | 2299 | +0.112 | 0.084 | +0.028 | 0.90 | −459.84 |
| **1.0 × ema200** | **1798** | **+0.295** | **0.085** | **+0.210** | **1.14** | **+457.60** |
| 1.5 × off | 2299 | +0.074 | 0.056 | +0.018 | 0.93 | −360.56 |
| **1.5 × ema200** | **1798** | **+0.196** | **0.056** | **+0.140** | **1.11** | **+409.32** |
| 2.0 × off | 2299 | +0.063 | 0.042 | +0.021 | 0.95 | −298.17 |
| **2.0 × ema200** | **1798** | **+0.159** | **0.042** | **+0.117** | **1.12** | **+486.77** |

Two facts this fixes, both of which the pre-registration must live with:

1. **The fill convention is load-bearing.** A late fill destroys the family
   (0.88 PF); the level fill is what makes `grossR` (0.16–0.30) four to seven
   times `costR` (0.04–0.09). Phase 2 must therefore implement a stop-entry, not
   reuse the closed-bar path.
2. **The EMA(200) filter is load-bearing.** Every `off` cell is net-negative, so
   the shape is "trend-filtered session breakout", not a pure breakout. EMA(200)
   is also the one element this shape shares with the failed Donchian family; it
   is a *filter* here, not the entry, and it stays a **grid axis** rather than
   being baked in — if TRAIN selects `off`, the shape must still pass.

### 2.2 Era profile (stop-entry, EMA200 filter; net R / net PF)

| stop | 2017–18 | 2019–20 | 2021–22 | 2023–24 | 2025 |
|---|---|---|---|---|---|
| 1.0 | +0.245 / 1.21 | +0.500 / 1.69 | **+0.012 / 1.02** | **+0.100 / 1.15** | +0.267 / 1.17 |
| 1.5 | +0.172 / 1.20 | +0.348 / 1.66 | **−0.004 / 1.01** | **+0.050 / 1.06** | +0.213 / 1.21 |
| 2.0 | +0.130 / 1.16 | +0.269 / 1.68 | **−0.006 / 0.98** | **+0.065 / 1.09** | +0.207 / 1.31 |

The bold cells are the proxy eras that overlap the reserved XM window
(2021-09 → 2024-06): **net R between −0.006 and +0.100, PF 0.98–1.15.** That is
outside the gate (PF ≥ 1.2). For comparison, the other two families:

| family (stop-entry where it has a level) | best net$ | best PF | 2021–22 |
|---|---|---|---|
| `orb` (chosen) | +486.77 | 1.14 | −0.006 … +0.012 |
| `pdr` | +568.43 | 1.15 | −0.050 … +0.112 (2025 PF 0.73–0.91) |
| `momentum` (close fill only) | −50.31 | 0.98 | −0.094 … −0.226 (all cells) |

### 2.3 Concentration and cost sensitivity — the caveats

For the three chosen cells (stop-entry, EMA200), over 8 years:

- **tail dependence:** the best five trades are **44% / 49% / 41%** of total net
  profit (stop 1.0 / 1.5 / 2.0). Five trades out of 1,798 carry the result.
- **yearly net $** (stop 1.0): 2018 +39, 2019 +50, 2020 +106, 2021 +46,
  **2022 −27**, 2023 +69, 2024 +100, 2025 +75. One losing year, small wins
  everywhere else.
- **cost sensitivity** (stop 1.0 / 1.5 / 2.0): at the measured 5.486 bp the net
  is +$458 / +$409 / +$487 (PF 1.11–1.14); at **double** the spread (11 bp, a
  proxy for real slippage) it is **+$138 / +$90 / +$168 (PF 1.02–1.04)**. The
  edge exists, but it is thin enough that execution quality decides it.
- average hold 4.5–6.2 h, stops 598–1076 vs time exits 722–1200 of ~1800.

### 2.4 Multiplicity, disclosed

The screen ran **3 families × 6 cells in both fill modes where a level exists to rest an order on = 36 runs**,
and the positive cells were noticed *after* the close-fill run came back
negative. That is exactly the search that manufactures false positives, so the
pre-registration compensates rather than hides it:

- the deciding data (the XM window) is read by **none** of those 36 cells;
- the grid is fixed at 6 cells, no cell is dropped for looking bad;
- the gate (§6) is fixed here, includes a slippage stress, and is not revisable;
- the proxy prior for the reserved era is **flat-to-thin** (§2.2), i.e. the
  screen does *not* predict a pass. A pass would be a genuine surprise in the
  right direction; a fail is the base case.

---

## 3. The exact rule (frozen)

Bars: XM `BTCUSD` **H1**, bar open-times in **UTC**, no DST conversion anywhere
(§5.5). All thresholds are below; no other condition may be added later.

For each UTC day `D` (Saturday skipped, §3.6):

1. **Opening range** `R(D)` = min(low) and max(high) of the three H1 bars whose
   open times are **07:00, 08:00 and 09:00 UTC**. If any of the three bars is
   missing, or `high == low`, the day produces no trade.
2. **Entry window** — H1 bars opening **10:00 … 15:00 UTC** (closes 11:00 …
   16:00). For each bar in time order:
   - long if `high ≥ R.high`, fill at `max(open, R.high)`;
   - short if `low ≤ R.low`, fill at `min(open, R.low)`;
   - a bar that spans both sides takes the side of its body
     (`close > open` → long, `close < open` → short); a doji bar is skipped.
3. **One trade per day.** The first trigger wins; no re-entry after a stop, no
   second entry after a time exit. Never more than one position open.
4. **Stop** = entry ∓ `k × ATR(14)` (ATR on the bar that triggered the entry,
   simple rolling mean of true range, the `strategy.py` definition), `k` from the
   grid.
5. **Exit** = the stop, **or** the close of the H1 bar whose open time is
   **19:00 UTC** (= 20:00 wall clock) — always, in profit or loss. **No
   take-profit, no breakeven ratchet, no trailing stop, no opposite-signal exit.**
   If the 19:00 bar is missing, exit at the next available close; if the day has
   no later bar, exit at its last close.
6. **No entries on Saturday UTC.** XM halts crypto for maintenance at 10:05–10:35
   *server* time, which lands at 08:05–08:35 UTC in winter and 07:05–07:35 UTC in
   summer — inside the range/entry window in one of the two states. Blocking the
   whole UTC day is DST-proof. Positions are flat by 20:00 UTC every day, so
   nothing is ever held over a weekend or a rollover.
7. **Trend filter** (grid axis): `ema200` takes a long only if `close > EMA(200)`
   and a short only if `close < EMA(200)`; `off` disables it. EMA is seeded on
   the first close of the analysis window (`pandas ewm(span=200, adjust=False)`,
   the `strategy.py` definition).
8. **Spread veto:** an entry is skipped when the bar's own `spread` column
   exceeds the replay threshold (1.25 × TRAIN p90, computed from TRAIN only and
   recorded). `btc/config.py`'s `MAX_SPREAD_POINTS` is **not** edited by this
   research.

---

## 4. The grid and the selection statistic (frozen)

| knob | values | cells |
|---|---|---|
| `ORB_STOP_ATR_MULT` | 1.0, 1.5, 2.0 | 3 |
| `ORB_TREND_FILTER` | `off`, `ema200` | 2 |

**6 combinations, cap 12.** Nothing else varies. No session-hour scan, no
lookback scan, no TP/BE/trailing variant, no "robustness" cell that only exists
if the first six disappoint.

**Selection — TRAIN only, in this order:**

1. discard any cell with **TRAIN n < 80** or **TRAIN grossR ≤ costR**;
2. rank the survivors by **mean net R per trade** on TRAIN;
3. break ties by TRAIN PF, then by trade count;
4. freeze exactly one winner, and write its TRAIN row down **before** the OOS
   run.

If no cell survives step 1, the hypothesis is **closed as infeasible** and the
cold OOS is never read. That is a valid outcome, not a reason to widen the grid.

---

## 5. Data protocol (frozen; hashes pending)

### 5.1 Pull

On `scalping`, from `/root/scalper` (read-only; safe while gold trades):

```bash
mkdir -p /root/ops/collect-2026-10-31
mt5env/bin/python btc/recon.py --timeframe H1 --bars 44000 \
    --out data/BTCUSD_H1_pre2024.csv \
    --json /tmp/btc_pre2024_recon.json 2>&1 | tee /root/ops/collect-2026-10-31/recon.txt
```

44,000 H1 bars ≈ 5.0 years, so the pull must reach back past 2021-10. **Do not
pull `--bars 20000`**: 20,000 H1 bars start in 2024-06, i.e. entirely inside the
inspected era, and the freeze will (correctly) reject the run.

`btc/recon.py` prints whole-file coverage and spread/ATR economics — that is
broker recon, and this doc records no return statistic from it. It writes the
CSV in the repo format (`time,open,high,low,close,tick_volume,spread`).

### 5.2 Freeze — before any sweep

```bash
python3 btc/freeze.py --csv data/BTCUSD_H1_pre2024.csv --timeframe H1 \
    --cutoff "2024-06-25 22:00:00" --train-frac 0.60 --embargo-bars 200 \
    --warmup 1000 --min-kept 18000 --min-train 10000 --min-oos 7000 \
    --hypothesis BTC-ORB-EU-H1 --doc docs/btc_hypothesis_orb_h1_2026-10-31.md \
    --out btc/manifests/btc_orb_eu_h1_2026-10-31.json
```

It refuses a known-inspected sha256, a cutoff inside the inspected era, duplicate
or out-of-order timestamps, a pull too short for the minimums, and it will not
overwrite an existing manifest. It exits 2 and writes nothing when any check
fails. Commit the manifest (`data/*.csv` stays off git, the manifest does not).

### 5.3 The manifest is the hash record — this table is what it must fill

| field | value |
|---|---|
| raw sha256 of `data/BTCUSD_H1_pre2024.csv` | **PENDING — `btc/freeze.py` on `scalping`** |
| raw bars / span | PENDING (expected ≈44,000 bars, ≈2021-10 → 2026-10) |
| cutoff enforced | `< 2024-06-25 22:00:00` |
| TRAIN first/last bar + bars | PENDING (expected ≈13,400 bars, ≈560 days) |
| embargo | 200 bars after TRAIN, excluded from both segments |
| cold-OOS first/last bar + bars | PENDING (expected ≈8,800 bars, ≈365 days) |
| integrity | duplicates, out-of-order, gaps > 1.5 × H1, missing UTC hours |

**Phase 1 is not done until this manifest is committed** (`state: "frozen"`,
`results_inspected: false`) with no sweep run against it.

### 5.4 Splits and embargo

- `kept` = rows with `time < 2024-06-25 22:00:00`.
- `start` = `warmup − 1` = 999 bars of indicator warm-up, consumed from the kept
  bars so no warm-up uses inspected data.
- **TRAIN** = earliest 60% of the playable kept bars.
- **Embargo** = the next 200 bars, used by neither segment (a stop or a time exit
  must not straddle the boundary).
- **Cold OOS** = everything after the embargo, read once (§6).

### 5.5 Clock rule

Every window is a **UTC clock time**, and the engine must evaluate it in UTC with
no timezone database and no server-offset arithmetic. This is why the anchor is
07:00 UTC: the European cash open is 08:00 London local, which is 07:00 UTC in
both GMT and BST, so the range is the same three bars all year. A US-session
anchor (13:30/14:30 UTC) would move an hour twice a year, and this repo already
has a scar from a server-offset bug (`docs/btc_market_reference_2026-10-03.md`
§3, `btc/HANDOFF.md` weekend-flat section). Saturday is blocked as a whole day
for the same reason.

---

## 6. The gate — fixed before the OOS is read

Run the frozen TRAIN winner **once** over the cold OOS slice. All of:

1. **net > 0** — both mean net R > 0 and total net USD at 0.01 lots > 0;
2. **PF ≥ 1.2**;
3. **n ≥ 60** closed OOS trades;
4. **gross R > cost R** over those same OOS trades (the shape must be paying for
   the spread, not surviving on a lucky tail);
5. **slippage stress:** 1–4 still hold when every entry is charged an extra
   **half-spread** against the trade — a stop-entry is a market order in a fast
   move, and §2.3 shows the edge is thin enough for this to matter. This is a
   pre-registered *strengthening* of the plan's four conditions, declared before
   any data exists.

Reported alongside, not gating: bootstrap 95% CI of mean R (10,000 resamples),
P(net > 0), max drawdown, exit mix, per-calendar-year rows, and the same numbers
at 2× spread.

**One look.** No re-selection, no re-split, no re-pull, no parameter change, no
extra variant, and no "the winner was unlucky, try the second cell".

---

## 7. What a pass means — and does not

A pass means only that `BTC-ORB-EU-H1` is **eligible** for the next phase
(`btc-hypothesis-test` → `btc-parameters` → drill → forward cohort in
`plans/btc.json`). It does **not**:

- authorise `BTC_STRATEGY=orb` on the paper book, or any config edit;
- touch `TRADING_MODE`, `MAX_SPREAD_POINTS` or a service unit;
- count as LIVE readiness. The paper book starts at zero, and the forward
  cohort is the only evidence that the edge still exists in 2026 — the reserved
  window ends in **June 2024**, and the current regime is a different market.

A pass on a 2021–2024 window with a 2022 drawdown, 44% of its profit in five
trades and PF 1.1 on proxy is a *question*, not an answer. Treat it as one.

---

## 8. Closure rules

- **No cell qualifies on TRAIN** (n < 80, or `grossR ≤ costR`): close as
  infeasible, do not read OOS, do not widen the grid.
- **The winner fails any of §6.1–6.5:** record a dated negative result, close
  `BTC-ORB-EU-H1` **and the intraday session family class**, and do not re-tune
  it on these bars or those of the inspected era.
- **The freeze is rejected** (too few bars, bad integrity): the phase stays
  `active`; capture more history (`--bars 60000`) and re-run. Never lower
  `--min-kept` to make a short pull pass.
- **After a close:** the next BTC hypothesis needs its own pre-registration and
  its own untouched timestamps. The pre-2024 era is consumed by this test, so
  the next one is either forward-collected (2026-11-01 onward) or a genuinely
  new mechanism that clears a screen first.

---

## 9. What phase 2 has to build (not this phase)

This document changes no code path that trades. Before the gate can run, phase 2
must:

1. add family `orb` to `research/strategy_sweep.py` (stop-entry fill at the
   level, ATR stop, 19:00-UTC time exit, one entry/day, Saturday off) and to
   `btc/strategy_btc.py` as a `BTC_STRATEGY`-selectable strategy with
   `BAR_CLOSE_EXITS` semantics;
2. prove live/replay parity on synthetic bars the way
   `btc/strategy_btc_test.py` does for `scalp` and `donchian` — including the
   stop-entry fill and the gap-through-open rule, bar-for-bar;
3. add the five `ORB_*` keys to `btc/config.py` (range hours, entry hours, flat
   hour, stop multiple, trend filter) with `BTC_STRATEGY` still defaulting to
   `scalp`;
4. run the sweep through `btc/tool.py` so `btc/config.py` is the active config
   (`btc/HANDOFF.md`, "Research plumbing").

Until all four exist, there is nothing to run the gate with — which is why the
manifest, not a chart, is this phase's deliverable.

---

## 10. Reproduction

```bash
# the screen (§2) — no XM data, no config import
python3 btc/session_screen.py --csv /tmp/proxy/BTC_1h.csv --eras --detail
python3 btc/session_screen.py --csv /tmp/proxy/BTC_1h.csv --family orb --entry-mode stop --eras
python3 btc/session_screen.py --self-test

# the freeze (§5) — needs the XM pull, guards the boundary
python3 btc/freeze.py --self-test
python3 tools/execution_plan.py bitcoin --validate

# the gate (§6) — phase 2, once the family exists
mt5env/bin/python btc/tool.py btc/edge_screen.py --family orb --csv data/BTCUSD_H1_pre2024.csv
mt5env/bin/python btc/tool.py btc/train_select.py --family orb --csv data/BTCUSD_H1_pre2024.csv
```

Numbers in §2 come from the first two commands on the proxy file above; the
proxy sha256 is printed in §2 and is not committed (proxy data is not repo data).
`tools/smoke_test.py` runs both self-tests as part of the deploy gate, so a
broken screen or freeze fails the gate rather than a research session.

---

## 11. Status line

| date | event |
|---|---|
| 2026-10-31 | `BTC-ORB-EU-H1` pre-registered. Screen (3 families × 6 cells × 2 fills) rejects `momentum` and close-entry `orb`, keeps stop-entry `orb` and `pdr`; `orb` chosen. Grid 6 cells, gate fixed, untouched pre-2024-06-25 window reserved, freeze manifest **pending** on `scalping`. No config, mode, unit or strategy parameter changed. |
