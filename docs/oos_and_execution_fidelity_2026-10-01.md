# Out-of-Sample Validation, Paper Exit Fidelity & Bridge Rate Caching — 2026-10-01

**Questions.** A post-PR #11 review flagged three remaining gaps:
1. **Out-of-sample (OOS) validation:** Every threshold adopted so far (`BE_TRIGGER_R=1.5` in PR #7, `RSI 40/60` and `session 07:00–20:00 UTC` in PR #11) was discovered and validated on the same 20,000-bar `data/GOLD_M5.csv` file (`2026-06-02` → `2026-09-11`), making the full-file bootstrap `P(net>0) = 0.96` in-sample.
2. **Paper-mode exit fidelity:** `paper.py`'s `on_tick()` was only called once per `CHECK_INTERVAL_SECONDS = 15` loop in `run.py`, so fast intra-window wicks through SL/BE/TP that reversed inside 15s were missed — flattering the paper book relative to both `backtest.py` (bar high/low fills) and real `LIVE` mode (broker-side resting SL/TP).
3. **Redundant MT5 bridge fetches:** `MT5Bridge.get_rates()` pulled the full 1,050-bar M5 window over RPyC every 15s while flat, even though a new M5 bar only closes every 300s (~20× redundant bridge load).

---

## 1. Out-of-Sample & Walk-Forward Validation (`research/strategy_sweep.py --oos`)

### 1a. MT5 bridge reachability & dataset regime structure

- **Environment constraint:** The MT5 Docker container (`localhost:18812`) runs on the `scalping` production host, not inside the Arena cloud sandbox (`probe_bridge` returns `Connection refused by localhost:18812`). Pulling pre-June-2026 or post-Sept-11-2026 bars therefore has to run on `scalping`. `fetch_data.py` now supports `--bars`, `--start-pos`, and `--out` so a single server command can pull both a longer continuous history (e.g. 60,000 M5 bars ≈ 300 days) and a disjoint earlier window (`--start-pos 20000`).
- **Correction to the earlier "single +19% bull regime" note:** `docs/strategy_iteration_2026-09-30.md` quoted the sample's min low (`3,942`) and max high (`4,696`) as if gold rose monotonically start-to-finish. Inspecting `data/GOLD_M5.csv` by calendar month shows **four distinct market regimes** (overall start-to-end `4,506.57` → `4,387.55`, **−2.64%**):

| Month | M5 Bars | Open | Close | Δ % | Low – High Range | Regime |
|---|---:|---:|---:|---:|---|---|
| `2026-06` | 5,542 | 4,502.74 | 4,007.30 | **−11.00%** | 3,942.15 – 4,515.20 | Sharp sell-off (−12.5% peak-to-trough) |
| `2026-07` | 6,299 | 4,011.16 | 4,043.35 | **+0.80%** | 3,959.38 – 4,202.87 | Range / consolidation |
| `2026-08` | 5,796 | 4,081.14 | 4,448.89 | **+9.01%** | 4,018.85 – 4,696.53 | Strong breakout rally (+16.9% trough-to-peak) |
| `2026-09` (1–11) | 2,363 | 4,448.80 | 4,387.55 | **−1.38%** | 4,282.32 – 4,510.65 | Post-peak pullback / mean-reversion |

### 1b. Chronological Train / Cold-OOS Splits

We evaluate `run_slice()` (which feeds the exact `warmup_bars - 1 = 999` preceding bars into the indicator warm-up so the OOS slice has zero warm-up loss and zero trade leakage across the split boundary) under two chronological splits:
1. **50/50 Playable-Bar Split:**
   - **TRAIN (H1):** bars `999..10,499` (`2026-06-08 09:20` → `2026-07-27 04:05 UTC`, June crash + July range)
   - **COLD OOS (H2):** bars `10,499..20,000` (`2026-07-27 04:10` → `2026-09-11 16:25 UTC`, August rally + Sept pullback)
2. **Regime Split (`Jun–Jul` Bear/Range vs `Aug–Sep` Bull/Pullback):**
   - **TRAIN:** `2026-06-08` → `2026-07-31` (net gold change −10.2%)
   - **COLD OOS:** `2026-08-03` → `2026-09-11` (net gold change +7.5%)

| Split / Slice | Config | Trades | Net $ | PF | WR % | Avg R | Max DD $ | TP / BE / SL | Exp $/tr | 95% Bootstrap CI (10k) | P(net>0) |
|---|---|---:|---:|---:|---:|---:|---:|---|---:|---|---:|
| **50/50 TRAIN** | Orig v7 (35/65, 07–17, BE 0.75) | 98 | −122.44 | 0.68 | 11.2 | −0.16 | 134.79 | 11 / 49 / 38 | −1.25 | [−$311.1, +$81.9] | 0.115 |
| **50/50 OOS** | Orig v7 (35/65, 07–17, BE 0.75) | 100 | −147.83 | 0.61 | 11.0 | −0.23 | 161.71 | 11 / 45 / 44 | −1.48 | [−$321.9, +$42.5] | 0.060 |
| **50/50 TRAIN** | Sep-30 (35/65, 07–17, BE 1.5) | 90 | −20.22 | 0.96 | 21.1 | −0.11 | 63.08 | 19 / 18 / 53 | −0.22 | [−$290.2, +$276.9] | 0.430 |
| **50/50 OOS** | Sep-30 (35/65, 07–17, BE 1.5) | 84 | +73.03 | 1.17 | 26.2 | −0.01 | 75.36 | 22 / 11 / 51 | +0.87 | [−$175.0, +$347.1] | 0.694 |
| **50/50 TRAIN** | **Adopted (40/60, 07–20, BE 1.5)** | **131** | **+286.06** | **1.37** | **29.0** | **+0.11** | **76.79** | **38 / 19 / 74** | **+2.18** | **[−$112.0, +$694.9]** | **0.919** |
| **50/50 OOS** | **Adopted (40/60, 07–20, BE 1.5)** | **124** | **+170.52** | **1.27** | **27.4** | **+0.10** | **108.65** | **34 / 24 / 66** | **+1.38** | **[−$159.1, +$524.9]** | **0.838** |
| **Regime TRAIN (Jun–Jul)** | **Adopted (40/60, 07–20, BE 1.5)** | **154** | **+283.86** | **1.32** | **28.6** | **+0.09** | **76.79** | **44 / 22 / 88** | **+1.84** | **[−$118.0, +$708.9]** | **0.913** |
| **Regime OOS (Aug–Sep)** | **Adopted (40/60, 07–20, BE 1.5)** | **101** | **+172.72** | **1.33** | **27.7** | **+0.13** | **108.65** | **28 / 21 / 52** | **+1.71** | **[−$135.4, +$497.6]** | **0.858** |

**Directional balance across opposite regimes (Adopted config):**
- `Jun–Jul` (Bear/Range): `BUY` 72 trades, **+$79.13** (PF 1.18); `SELL` 82 trades, **+$204.73** (PF 1.46).
- `Aug–Sep` (Bull/Pullback): `BUY` 54 trades, **+$118.47** (PF 1.42); `SELL` 47 trades, **+$54.25** (PF 1.22).
Both long and short sides remain net-positive in both the sell-off/range half and the breakout-rally half.

### 1c. Train-Only Parameter Discovery Check (Would H1 Alone Pick the Same Config?)

If we had tuned one variable at a time **strictly on TRAIN (`2026-06-08..2026-07-27`) without ever viewing H2**:

1. **BE trigger (`RSI 35/65, session 07–17`):**
   - TRAIN net rises monotonically from `0.75R` (−$122.44, PF 0.68) → `1.0R` (−$67.63, PF 0.85) → plateau at `1.25R..1.5R` (−$19.23 / −$20.22, PF 0.96).
   - Cold OOS confirms the exact same ordering: `0.75R` (−$147.83, PF 0.61) → `1.5R` (**+$73.03, PF 1.17**).
2. **RSI thresholds (`BE 1.5R, session 07–17`):**
   - On TRAIN alone: `30/70` (−$57.85, PF 0.84) → `35/65` (−$20.22, PF 0.96) → `38/62` (+$134.49, PF 1.25) → **`40/60` (+$195.60, PF 1.34, peak on TRAIN)** → `42/58` (+$31.60, PF 1.05) → `45/55` (+$41.00, PF 1.06).
   - Cold OOS on `40/60`: **107 trades, +$156.74, PF 1.33, P(net>0) = 0.876** (and the surrounding `38/62..45/55` band is uniformly profitable OOS: +$98 to +$210, PF 1.22–1.43).
3. **Session end (`BE 1.5R, RSI 40/60`):**
   - Extending `07–17` → `07–20` on TRAIN increases trades 106 → 131 (+24%) and net +$195.60 → **+$286.06** (PF 1.34 → 1.37).
   - Cold OOS on `07–20`: **124 trades, +$170.52, PF 1.27, P(net>0) = 0.838**.
4. **Full 60-config grid check (`5 BE × 6 RSI × 2 Session`):**
   - Ranked purely by TRAIN (H1) net profit, **`BE=1.5, RSI=40/60, Session=07–20` is #1 out of 60 on TRAIN** (+$286.06, PF 1.37), and delivers **+$170.52 (PF 1.27)** cold on H2.

### 1d. 4-Fold Walk-Forward & Honest Caveats (Why This Still Isn't a Live Flip)

Splitting the playable range into 4 equal ~23-day quarters (`research/strategy_sweep.py --oos`) exposes two honest limitations:

| Fold | Period | Gold Δ % | Trades | Net $ | PF | WR % | Max DD $ | Exp $/tr | 95% Bootstrap CI | P(net>0) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| **Q1** | `2026-06-08..2026-07-01` | −5.07% | 64 | +174.07 | 1.42 | 29.7 | 58.81 | +2.72 | [−$128.6, +$499.4] | 0.868 |
| **Q2** | `2026-07-01..2026-07-27` | +0.52% | 67 | +111.99 | 1.32 | 28.4 | 76.79 | +1.67 | [−$124.5, +$369.8] | 0.811 |
| **Q3** | `2026-07-27..2026-08-19` | +5.59% | 70 | **+5.81** | **1.02** | **25.7** | **108.65** | **+0.08** | **[−$206.7, +$231.8]** | **0.510** |
| **Q4** | `2026-08-19..2026-09-11` | +1.20% | 54 | +164.71 | 1.59 | 29.6 | 73.86 | +3.05 | [−$89.8, +$427.0] | 0.894 |

1. **OOS shrinkage & Q3 flat stretch:** Expectancy shrinks 37% from H1 Train (`+$2.18/trade`, PF 1.37) to H2 OOS (`+$1.38/trade`, PF 1.27), and `Q3` (`2026-07-27..2026-08-19`) is a 3.5-week flat/drawdown period (`+$5.81` over 70 trades, PF 1.02, max DD `$108.65`).
2. **Sub-sample statistical power:** Because a 2.5:1 RR strategy has ~28% win rate and high per-trade variance, a 100–125 trade OOS slice at PF ~1.3 has `P(net>0) ≈ 0.84–0.86` (95% CI `[-$159, +$525]`), which still spans zero until ~250+ trades accumulate.
3. **Retrospective vs. truly untouched history:** Because `data/GOLD_M5.csv` was already viewed when choosing PR #7 and PR #11, this split is retrospective. To run a **strictly untouched** historical OOS test on the `scalping` server (where the MT5 bridge is live), run:
   ```bash
   # 1) Pull 20,000 M5 bars immediately PRIOR to the June–Sept sample (start_pos=20000)
   mt5env/bin/python fetch_data.py --bars 20000 --start-pos 20000 --out data/GOLD_M5_pre_jun.csv
   mt5env/bin/python research/strategy_sweep.py --csv data/GOLD_M5_pre_jun.csv --detail --bootstrap 10000

   # 2) Or pull a 60,000-bar (~300-day) continuous M5 file and run the OOS report
   mt5env/bin/python fetch_data.py --bars 60000 --out data/GOLD_M5_60k.csv
   mt5env/bin/python research/strategy_sweep.py --csv data/GOLD_M5_60k.csv --oos
   ```

---

## 2. Paper-Mode Exit Fidelity (`run.poll_paper_position` + `research/paper_exit_test.py`)

### 2a. Why 15s snapshot polling flatters the paper book

On the 4,003-bar overlapping window between `data/GOLD_M5.csv` and `data/GOLD_M1.csv` (`2026-08-24` → `2026-09-11`, 20,000 M1 bars), `research/paper_exit_test.py` replays the exact same entry signals under four exit-sampling fidelities:

| Exit Resolution | Trades | Net $ | PF | WR % | Avg R | Max DD $ | TP / BE / SL | Exp $/tr |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| M5 close-only (300s snapshot, no wicks) | 46 | +321.78 | 2.33 | 41.3 | +0.48 | 46.36 | 19 / 4 / 23 | +7.00 |
| M1 close-only (60s snapshot, no wicks) | 44 | +133.08 | 1.55 | 31.8 | +0.25 | 75.55 | 14 / 8 / 22 | +3.02 |
| **M1 OHLC (sub-bar chronological wicks)** | **48** | **+81.69** | **1.31** | **27.1** | **+0.11** | **73.86** | **13 / 10 / 25** | **+1.70** |
| **M5 OHLC (`backtest.py` reference)** | **48** | **+89.43** | **1.35** | **27.1** | **+0.13** | **73.86** | **13 / 11 / 24** | **+1.86** |

Coarse snapshot sampling misses fast intra-bar wicks that either stop a trade out (`SL`) or arm `+1.5R` breakeven and scratch it on pullback (`BE`), artificially inflating TP count and PF (`1.55` at 60s close-only and `2.33` at 300s close-only vs `1.31–1.35` with wicks).

### 2b. Fix implemented

- Added `config.POSITION_CHECK_INTERVAL_SECONDS = 1` (1s tick-poll interval while a paper position is open, vs `CHECK_INTERVAL_SECONDS = 15` while flat).
- Added `run.poll_paper_position(bridge, paper)` and replaced the end-of-loop and active-position sleeps with it:
  - **When flat (`not paper.has_position()`):** sleeps the full `15s` in one call with **zero** extra MT5 bridge calls.
  - **When a paper position is open (`paper.has_position()`):** polls `bridge.get_live_tick(retries=1)` every `1s`, skips unchanged `time_msc` ticks, evaluates `paper.on_tick(tick.bid, tick.ask)`, and exits the fast-poll loop immediately once an `SL`, `BE`, or `TP` closes the position (including during the very first 15s immediately after `SIM_ENTRY`).
  - Does not call `get_account_info()`, `get_symbol_info()`, `positions_get()`, or `get_rates()` during the 1s sub-polls, and keeps `stale_tick_cycles` anchored to the 15s outer loop so the 5-min warning (`STALE_TICK_WARN_CYCLES=20`) and 30-min reconnect (`STALE_TICK_RECONNECT_CYCLES=120`) thresholds are unchanged.
  - Moved the active-position check in `run.py` ahead of the `high_spread` entry-skip gate so an open paper position continues to be fast-polled even when spread temporarily widens above `MAX_SPREAD_POINTS`.
- Verified with `research/paper_exit_test.py` (fake-bridge tests for intra-15s SL wick, intra-15s `+1.5R` BE arm + scratch wick, intra-15s TP wick, and zero-load when flat).

---

## 3. Redundant MT5 Bridge Rate Fetches (`mt5_bridge.py` + `strategy.py` + `research/parity_test.py`)

### 3a. Fix implemented

- **`MT5Bridge.get_rates(count=None, tick=None, force=False)`:**
  - Caches the last full `INDICATOR_WINDOW_BARS + INDICATOR_FETCH_MARGIN` (1,050-bar) array along with `_cached_closed_bar_ts` (`rates[-2]['time']`) and `_cached_forming_bar_ts` (`rates[-1]['time']`).
  - **Fast path (when `tick` is passed from `run.py`):** if `tick.time` (or `tick.time_msc // 1000`) lies inside the current forming M5 bar `[forming_ts, forming_ts + 300)`, no new bar has closed — returns the cached window with **0 RPyC calls**. Once `tick.time >= forming_ts + 300`, a tick in the new M5 bar has arrived, so it refetches the full 1,050-bar window immediately (within ~15s of bar close).
  - **Probe fallback (when called without `tick`):** performs a 2-bar `copy_rates_from_pos(symbol, tf, 0, 2)` check and only pulls the full 1,050-bar window when `probe[-2]['time'] != _cached_closed_bar_ts`.
- **`ScalpStrategy.check_signal(rates, when=None)`:**
  - Caches the computed closed-bar indicator tuple `(close, ema200, atr, rsi_curr, rsi_prev)` keyed by `(bar_ts, len(rates), rates[0]['close'], rates[-2]['close'])` so repeated 15s calls inside the same 5-minute bar do not rebuild a 1,000-row pandas DataFrame 20 times.
- **Verification (`research/parity_test.py`):**
  - Simulates 60 M5 bars × 20 (15s) cycles = 1,200 live-loop evaluations in both `with_tick` and `probe_only` modes: confirms **60 full 1,050-bar fetches instead of 1,200 (20× reduction)**, immediate reaction on cycle 0 of each new bar, proper `duplicate_bar` suppression on cycles 1..19, and **0 signal mismatches** across the entire dataset.
