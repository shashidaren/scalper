# BTC spread/edge analysis — 2026-10-06 (why the BTC bot shows `high_spread` and 0 trades, and what the data says about improving it)

**Status:** `TRADING_MODE="FORWARD_TEST"` on both instances; no BTC service, no BTC
config value changed by this session. This document is analysis + diagnostics.
It does **not** adopt a parameter and does **not** re-open the Phase-1b decision.

**Question asked:** *the BTC instance logs `high_spread` and never trades — is
something broken, and can the scalper be improved from the previous data?*

**Short answer (measured, not asserted):**

1. Nothing is broken. `run.py` refuses to enter while `spread_points >
   config.MAX_SPREAD_POINTS`; `btc/config.py` ships `MAX_SPREAD_POINTS = 1500`
   as an explicit placeholder, and the real XM BTCUSD feed quotes **4,000–5,000
   points**. The gate is therefore vetoed **100%** of the time: the bot is
   connected, polls, and can never evaluate a signal. 0 trades here is a
   *configuration statement*, not a market statement.
2. Loosening the gate would not create an edge. The right way to read a run like
   this is in R units (1R = the stop distance):

   | quantity | gold (real, M5) | XM BTCUSD M5 (real, Phase 1b) |
   |---|---|---|
   | gross edge **g** (spread charged at zero) | **+0.157R** | **+0.02R** |
   | cost ratio **c** (spread ÷ stop) | 0.051R (5.1%) | 0.23–0.26R |
   | net | +0.106R → PF 1.32 | −0.21R → PF 0.74 |

   A shape can only pay for the spread when **g > c**. Gold clears by 3×; the
   BTC shape is ~13× short, and every stop/target/RSI variant in the Phase-1b
   sweep stayed net-negative.
3. Screening the same shape on proxy BTC bars across timeframes/eras (this doc)
   says the failure is **not** only the spread: since 2021 the pullback signal's
   *gross* edge is ~zero on every timeframe tested (gross PF 0.96–1.02 per
   era), and at zero cost the 8-year H1 book is still only PF 1.01. Cost-tier
   changes (hypothesis B) cannot fix a signal with no gross edge.
4. A **different family** — long-lookback Donchian breakout on H1 — does show a
   gross edge that survives the measured XM spread through 2024 (net PF 1.13–1.28
   per era, net +$406 over 8 years at 0.01 lots). That is the first candidate
   worth a *pre-registered, untouched-data* test, and it is the only route this
   analysis recommends. It is proxy evidence, not a result.

---

## 1. Why `high_spread` and 0 trades (code + numbers)

`run.py` computes the spread from the live tick and vetoes the cycle:

```python
spread_points = round((tick.ask - tick.bid) / sym.point)     # run.py
...
if not gate_pass:                                            # gate_pass = spread <= MAX_SPREAD_POINTS
    log_trade("SKIP", {"reason": "high_spread", "spread": spread_points})
    ...
    continue                                                 # check_signal() is never reached
```

Measured on the real XM BTCUSD file (server run 2026-10-03): spread **mean
4,242 points**, "mostly 4,000–5,000". `btc/config.py` ships `MAX_SPREAD_POINTS =
1500` with the comment *“PLACEHOLDER: derive from recon spread p90”*. A gate
below the instrument's p10 vetoes every quote; the derived value from TRAIN data
would be 1.25 × p90 = **6,250 points** — i.e. the placeholder sits ~4× *below*
the feed's own level, which is exactly why no quote has ever passed it.

Two consequences, both now handled in code rather than in a comment:

* the engine publishes a **spread-gate snapshot** (`spread_gate.py` →
  `live_status.json` → dashboard banner) and logs **one** `SPREAD GATE
  INFEASIBLE` warning instead of leaving the operator to infer it from 5,760
  `SKIP` lines a day;
* **`btc/preflight.py`** grades a gate before a bot is started: live quote
  sample + bar-file economics, verdict `OK / STARVED / INFEASIBLE / UNKNOWN`,
  exit codes 0/1/2/3 so a runbook can gate on it.

Reproduce the diagnosis without touching the server data:

```bash
# gate vs the real spread distribution in the file the server produced
mt5env/bin/python btc/preflight.py --offline --csv data/BTCUSD_M5.csv   # → INFEASIBLE, exit 2
python3 btc/preflight.py --config-dir . --offline --csv data/GOLD_M5.csv # → OK, exit 0 (gold)
```

---

## 2. The measurement that matters: gross edge vs cost, in R

Absolute points are not comparable across instruments or price regimes. The
scale-free pair is:

* **g** — mean R per trade with the spread charged at **zero** (does the signal
  have an edge?);
* **c** — mean (round-trip spread ÷ stop distance) per trade (what the
  instrument charges for the privilege);
* the book is viable only when **g > c**; tuning SL/TP moves g only slightly and
  moves c only via the stop size.

XM's measured quote is **42.41 px at a $77,304.55 price = 5.486 basis points of
price**, which is the honest way to charge a proxy bar from a different price
level (a 2017 bar at $9,000 cannot be charged $42).

**Gold validation (method check, real data).** `btc/edge_screen.py` on
`data/GOLD_M5.csv` reproduces `backtest.py` exactly — 255 trades, +$456.58,
PF 1.32, WR 28.2%, 72 TP/43 BE/140 SL — and splits it into g = **+0.157R**,
c = **0.051R**, net +0.106R. That matches the documentation (~5.3% spread per
stop) and proves the decomposition is not inventing its own accounting
(`btc/edge_screen_test.py` asserts this).

**Real BTC (Phase 1b, recorded 2026-10-03).** 433 trades, −$165.84, PF 0.74:
gross **+$17.16** (+$0.04/trade ≈ **+0.02R**) against **$183.00** of spread paid
(**0.232R** per trade averaged over realised stops; **0.26R** at the median
2×ATR stop of $1.63). Required win rate 36.0% vs 23.8% actual.

---

## 3. Proxy screen of the shipped shape (diagnostic, not evidence)

Exchange APIs are unreachable from this sandbox, so the screen uses **Binance
spot klines committed to public GitHub repos** (no spread column; the XM cost is
charged as a fixed 5.486 bp of price):

| dataset | bars | span | median ATR(14) | analytic c = 5.486 bp ÷ (2×ATR) | measured c (baseline) |
|---|---|---|---|---|---|
| `lth-elm/Backtrading-Python-Binance` 15m | 117,143 | 2017-08-17 → 2020-12-25 | 34.45 px = **42.43 bp** | 0.065 | 0.071 |
| same repo 1h | 29,307 | 2017-08-17 → 2020-12-25 | 71.70 px = **88.29 bp** | 0.031 | 0.039 |
| `Pennyihui/data` 1h | 68,319 | 2017-08-17 → 2025-06-08 | 175.21 px = **77.79 bp** | 0.035 | 0.038 |

(The discrepancy between the last two columns is real and expected: the analytic
ratio charges the spread against 2×ATR, while the measured `c` is the average
over *realised* stops, which include the BE/TP exits and any stop that was wider
or tighter than 2×ATR at entry.)

Caveat that matters: the proxy regimes are **2–8× more volatile in relative
terms** than XM's 2026 feed (XM M5 ATR = 81.62 px = 10.6 bp of price, i.e. ≈18 bp
at M15 and ≈37 bp at H1). At XM's own 2026 volatility the analytic cost ratios
would be c ≈ 0.15 (M15) and c ≈ 0.075 (H1) — see §6.

### 3.1 The shipped shape, one variable at a time (`btc/edge_screen.py`)

H1 2017-2025, baseline = the BTC config (RSI 40/60, SL 2×ATR, TP 5×ATR, BE 1.5R).
(An ATR floor — Phase 1b's TRAIN winner — is not listed: the TRAIN-selected floor
is not a value this screen can evaluate without a train split, and the real
Phase-1b OOS read of it was PF 0.75, i.e. it does not clear the gate.):

| geometry | trades | grossR g | costR c | netR | net PF | net $ |
|---|---|---|---|---|---|---|
| baseline | 1,342 | +0.034 | 0.038 | −0.004 | 0.96 | −200.93 |
| RSI 35/65 | 1,087 | +0.044 | 0.039 | +0.005 | 1.00 | −1.20 |
| SL 3.0×ATR | 862 | +0.026 | 0.024 | +0.002 | 0.94 | −319.36 |
| TP 10×ATR (let winners run) | 1,042 | +0.091 | 0.038 | +0.053 | 0.99 | −46.37 |
| BE off | 1,161 | +0.085 | 0.038 | +0.048 | 0.97 | −148.10 |
| time stop 12 bars | 2,032 | −0.027 | 0.044 | −0.071 | 0.86 | −657.81 |
| BE 2.0R | 1,218 | +0.064 | 0.038 | +0.027 | 1.00 | −0.26 |
| RSI 45/55 | 1,519 | +0.011 | 0.039 | −0.027 | 0.88 | −632.04 |
| SL 1.5×ATR | 1,698 | +0.004 | 0.053 | −0.050 | 0.94 | −247.71 |
| session 07–20 UTC | 1,080 | +0.003 | 0.043 | −0.039 | 0.98 | −78.06 |

Same shape on M15 2017-2020 (c = 0.071, i.e. the *proxy* cost ratio — XM 2026
volatility would be ≈0.15): baseline g = +0.047 vs c = 0.071 → net −0.024R,
PF 0.99. Four of the sixteen variants get g > c there (RSI 30/70 +0.038R on
PF 1.12 / +$88.85 proxy, RSI 35/65 +0.003R, SL 3.0 +0.007R, TP 10 +0.043R), and
none of them is a book you would fund. The ranking does not survive a timeframe
change either: RSI 30/70 is the *best* M15 row above and the **worst** H1 row
(−0.084R, PF 0.89), which is the cleanest demonstration that these screens can
describe economics but can never select a parameter.

### 3.2 Is it the cost or the signal? Era buckets, one full run each

Net of cost (5.486 bp), pullback baseline, bucketed by entry time — no
slice/warm-up artefacts:

| era | n | net PF | net $ |
|---|---|---|---|
| 2017–2018 | 218 | 1.14 | +47.97 |
| 2019–2020 | 318 | 1.20 | +59.77 |
| **2021–2022** | 364 | **0.94** | **−124.83** |
| **2023–2024** | 363 | **0.90** | **−152.22** |
| **2025 (H1)** | 79 | **0.94** | **−31.63** |
| total | 1,342 | — | **−200.93** |

And with the spread charged at **zero** (gross): 1.17 / 1.26 / **0.98** /
**0.96** / 1.02 — the 2021–2024 half loses money even before the spread.

So since 2021 the pullback signal has no gross edge; the cost only makes it
look worse. This is consistent with the real 2026 XM run (gross
+$0.04/trade, PF ≈1.0 before cost) and it is why "tune the stop / the tier / the
session" cannot rescue the family.

Supporting measurements on the same 8-year H1 set:

* **bootstrap** (2,000 resamples): net R/trade −0.0045, 95% CI [−0.081, +0.073],
  P(>0) = 45.2%; net $ −$200.93, CI [−$982, +$608], P(>0) = 31.7% — a coin flip.
* **ATR quintiles** (gross R): +0.006 / +0.132 / +0.073 / −0.030 / −0.011 — no
  monotone volatility effect, i.e. an ATR floor is not a structural lever (and
  Phase-1b's TRAIN winner, an ATR floor, failed OOS as predicted by this).
* **cost sensitivity** (baseline, 8 years): 0 bp → PF 1.01, +$38.87; 0.65 bp
  (the web-prior 500-point spread) → PF 1.00, +$10.45; 2.74 bp (Ultra-Low
  hypothesis, half) → PF 0.98, −$81.04; 5.486 bp (measured Standard) → PF 0.96,
  −$200.93. **Even free, the book is flat.** Hypothesis B (cheaper tier) is not
  the binding constraint; hypothesis A (higher timeframe) removes most of the
  cost but the gross edge is gone there too.

---

## 4. A different family: long-lookback breakout (hypothesis C prototype)

> **Provenance note (added 2026-10-06, later session):** the table below was
> computed with `btc/breakout_screen.py` **v1**, whose loop evaluated
> signal+entry on the loop bar itself and could not re-open a position on the
> bar the previous one closed. When hypothesis C was wired into the engine
> (see `btc/HANDOFF.md` 10-06 Phase-1c-plumbing block), the screen was aligned
> to the engine convention (**v2**: signal on the last *closed* bar, fill at
> that close, re-entry allowed on the exit bar — exactly what
> `research/strategy_sweep.py` family="donchian" and the live path do, proven
> trade-for-trade equivalent by `btc/strategy_btc_test.py`). Re-running the
> screen now therefore gives slightly different trade counts/net around
> re-entry-after-exit; treat the v2/replay numbers as the reference and this
> table as the original screen that motivated the pre-registration. The
> conclusion (a gross edge that pays the measured spread through 2024) is
> unchanged in direction, and none of it is XM evidence either way.

Same proxy data, same cost model, `btc/breakout_screen.py` (Donchian breakout on
the closed bar, fill at that close, fixed ATR stop, opposite Donchian channel as
the exit, EMA200 trend filter, one spread per trade):

| geometry (H1 2017-2025) | n | gross PF / R | net PF / R / $ |
|---|---|---|---|
| donchian20 exit10 sl2.0 | 1,428 | 1.04 / +0.281 | 0.98 / +0.240 / −76.67 |
| donchian20 exit10 sl2.5 + time stop 100 | 1,374 | 1.08 / +0.246 | 1.02 / +0.214 / +104.25 |
| donchian50 exit25 sl2.0 | 858 | 1.00 / +0.370 | 0.96 / +0.333 / −146.99 |
| donchian55 exit20 sl3.0 (no EMA) | 864 | 0.95 / +0.173 | 0.91 / +0.148 / −355.98 |
| **donchian100 exit50 sl2.0** | **532** | **1.21 / +0.678** | **1.16 / +0.642 / +406.20** |
| donchian150 exit75 sl2.0 | 368 | 1.43 / +1.201 | 1.38 / +1.167 / +702.41 |
| donchian200 exit100 sl2.5 | 288 | 1.42 / +1.115 | 1.38 / +1.088 / +627.30 |
| donchian100 exit50 sl1.5 | 590 | 1.31 / +0.836 | 1.25 / +0.789 / +558.62 |

Era buckets for donchian100/exit50/sl2.0 (gross → net):

| era | n | gross PF | net PF | net $ |
|---|---|---|---|---|
| 2017–2018 | 84 | 1.51 | 1.47 | +66.97 |
| 2019–2020 | 124 | 1.95 | 1.88 | +136.09 |
| **2021–2022** | 143 | 1.32 | **1.28** | +264.90 |
| **2023–2024** | 145 | 1.18 | **1.13** | +110.05 |
| **2025 (H1)** | 36 | 0.58 | **0.55** | −171.80 |

Read honestly:

* this family keeps a real gross edge **through 2024** (the two eras where the
  pullback lost money) and — because H1 stops are large — it *pays* the XM
  spread (net stays close to gross: cost R 0.036 vs 0.678 gross);
* the most recent bucket (2025 H1, only 36 trades) is negative and lumpy: two
  trades with ~4,000 px stops produced most of the −$172 (2024-12 −$101,
  2025-01 −$119, at 0.01 lots). With ~5–7 trades a month at 0.01 lots this book
  is a small, low-frequency, drawdown-lumpy trend system;
* M15 breakouts are negative on the same test (don20/10 sl2.0 net PF 0.80,
  don50/25 net PF 0.88) — the edge, where it exists, lives on H1;
* the lookback scan 20 → 200 is a *scan*: PF improves with lookback, which is
  exactly the pattern multiple testing can manufacture. Only a pre-registered
  cold-OOS run on untouched XM bars can decide it.

---

## 5. What this does **not** establish

* Proxy bars are exchange **spot** klines from GitHub repos, not XM CFD bars.
  XM's feed, its bar construction, weekend gaps and maintenance windows differ.
  Nothing here is evidence about XM bars and nothing here may be quoted as a
  Phase-1 result. (The repo rule stands: *Binance proxy runs are not evidence
  for XM BTCUSD.*)
* The proxy regimes are more volatile than XM 2026; at XM's volatility the
  cost ratios are larger (M15 ≈0.15, H1 ≈0.075) and the 8-year *average* gross
  edges above would be thinner. The breakout family's 2021-2024 net PFs of
  1.13–1.28 would shrink accordingly.
* `btc/edge_screen.py` / `btc/breakout_screen.py` are diagnostics. They never
  select, never write config, and are not wired into the engine.

## 6. What follows for the plan (amendment to the Phase-1c pre-registration)

Pre-registered 2026-10-04 (`docs/btc_phase1c_hypotheses_2026-10-04.md`); this is
an **amendment made before any untouched data was pulled**, on proxy evidence:

1. **Hypothesis A (M15/H1 same shape) is deprioritised, not deleted.** Proxy:
   the gross edge is ~0 in 2021+ at every timeframe (gross PF 0.96–1.02) and the
   real Phase-1b gross edge was +0.02R. Removing cost cannot fix that.
2. **Hypothesis B (Ultra-Low / cheaper tier) is not the binding constraint.**
   At H1, free cost is worth PF 1.01 vs 0.96 measured — ~0.05 PF. Any future
   B test must first show a gross edge (g > c on the tier's *measured* spread);
   do not expect the tier itself to produce one. Also note the measured
   Standard spread (5.486 bp) is **~8.5× wider** than the 500-point web prior
   in `docs/btc_market_reference_2026-10-03.md`, so tier economics must be
   measured on the demo account, never assumed.
3. **Hypothesis C is re-specified as the priority**: long-lookback Donchian
   breakout on **H1** with a fixed ATR stop and a channel exit. Pre-register a
   *single* geometry (donchian100/exit50/sl2.0-2.5/EMA200 filter, and the
   time-stop variant as the robustness check), implement it in
   `btc/strategy_btc.py` with the usual live/replay parity proof, then run the
   unchanged Phase-1 gate on **untouched** XM H1 bars: frozen TRAIN winner must
   show **net > 0 and PF ≳ 1.2 on cold OOS with n ≥ 60**.
4. **New precondition, before the cold-OOS read ever happens**: run
   `btc/edge_screen.py` (or the C prototype) and require the measured **g > c**
   on the same bars. A shape whose gross edge is smaller than the instrument's
   cost ratio cannot pass the gate, and reading its OOS is a waste of the
   cleanest evidence available.
5. **Screen-first rule**: new families are screened on proxy/other-instrument
   bars *before* they consume an untouched XM pull, and the screen result is
   recorded as a hypothesis — never as a selection. Binance proxies remain
   non-evidence for XM.
6. **No change** to the gate itself: `MAX_SPREAD_POINTS` stays 1500 until a
   Phase-1 pass justifies a derived value, and `TRADING_MODE` stays
   `FORWARD_TEST`. The difference now is that the *consequence* of the
   placeholder is measured, logged, banner-ed and pre-flight-checked instead of
   silently producing 0 trades.

## 7. Operational changes shipped with this doc

| change | where | effect |
|---|---|---|
| `spread_gate.SpreadGateMonitor` | new shared module | counts quotes/vetoes per window, grades the gate `ok / starved / infeasible`, rate-limits warnings |
| engine telemetry | `run.py` | feeds every tick to the monitor, writes `spread_gate` into `live_status.json`, logs one `SPREAD GATE INFEASIBLE` warning (+ a recovery INFO) instead of silently skipping forever |
| dashboard banner | `templates/index.html` + `dashboard.py` | "⛔ NO ENTRY IS POSSIBLE WITH THIS CONFIGURATION" with the observed spread distribution; amber "STARVED" variant; veto% in the price card |
| `btc/preflight.py` | new tool | pre-start feasibility verdict from live quotes and/or a bar file, with exit codes 0/1/2/3 |
| `btc/edge_screen.py` | new tool | per-geometry **gross edge vs cost ratio** decomposition for any CSV (cost from the file, or relative bp) |
| `btc/breakout_screen.py` | new prototype | hypothesis-C screen (proxy only, not the engine) |

## 8. Provenance and reproduction

* **Real XM numbers** (spread 4,242 pts, ATR 81.62 px, Phase-1b results) are the
  server run recorded in `btc/HANDOFF.md` §9 / `docs/btc_phase1_result_2026-10-03.md`
  — this sandbox cannot reach `scalping` and holds no BTC file.
* **Gold numbers** were re-run locally on `data/GOLD_M5.csv` with the tools above
  and match `backtest.py` bit-for-bit (255 / +$456.58 / PF 1.32).
* **Proxy data** (not committed, `data/*.csv` is ignored):

```bash
git clone --depth 1 --filter=blob:none --sparse https://github.com/lth-elm/Backtrading-Python-Binance /tmp/proxy/lth
cd /tmp/proxy/lth && git sparse-checkout set --no-cone '/data/BTCUSDT-2017-2020-15m.csv' '/data/BTCUSDT-2017-2020-1h.csv'
git clone --depth 1 --filter=blob:none --sparse https://github.com/Pennyihui/data /tmp/proxy/Penny
cd /tmp/proxy/Penny && git sparse-checkout set --no-cone '/BTC_1h.csv'
# both write epoch-ms OHLCV with NO spread column; normalise to
# time,open,high,low,close,tick_volume and screen with the relative cost:
python3 btc/edge_screen.py --csv /tmp/proxy/btc_1h_2017_2025.csv --cost bp --spread-bp 5.486 --detail
python3 btc/breakout_screen.py --csv /tmp/proxy/btc_1h_2017_2025.csv --eras
```

* Tests: `python3 btc/edge_screen_test.py` (11/11, includes the gold
  cross-check), `python3 btc/preflight_test.py` (9/9),
  `python3 tests/test_spread_gate.py` (21/21), plus the standing set
  (`backtest.py`, `research/parity_test.py`, `btc/tool.py --check`,
  `btc/e2e_smoke.py`, `btc/train_select_test.py`, `tests/test_deploy_services.sh`).
* Correction made while writing this doc: the era buckets originally used
  inclusive end dates (`<= "2024-12-31"` compares against midnight), which
  silently dropped trades on 31 Dec. Buckets are now half-open
  (`>= a & < b`) in `btc/breakout_screen.py`, and the pullback table above is
  the corrected one — 2023–2024 moves from an earlier −$134.12 (n=362) to
  **−$152.22 (n=363)** and the buckets now sum exactly to the −$200.93 total.
  The breakout numbers were unaffected (its buckets already summed).
