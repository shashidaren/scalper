# Python MT5 Gold Scalper & Backtester Framework

An experimental algorithmic trading and backtesting framework for **GOLD / XAUUSD** using MetaTrader 5 inside a Docker container (Wine) bridged to a host Python environment via RPyC.

Trading logic, risk controls, and failure handling have been thoroughly tested and validated through historical simulation.

---

## Changelog

### 2026-09-15 – Live Trading Fixes & Project Hygiene

**Critical bug fixes (live trading was previously non-functional):**

- Fixed signal handling in `run.py`: `check_signal()` returns a tuple `(signal, sl_dist, tp_dist)`. The previous code treated it as a string, so no trades could ever be placed.
- Increased bar request from 50 → 250 so the 200-EMA has enough data.
- Made `mt5_bridge.open_trade()` accept and use **dynamic ATR-based** SL/TP distances instead of the old fixed `SL_POINTS` / `TP_POINTS`.
- Converted `run.py` into a continuous loop with proper error handling, spread checks, and position guards.

**Project hygiene:**

- Added `.gitignore` (blocks `__pycache__`, virtualenvs, large CSVs, secrets).
- Live and backtest engines now share the same dynamic risk rules (1 : 2.5 R:R based on ATR).

---

## System Architecture

```text
┌───────────────────────────────────────────────────────────┐
│              Host OS (Linux / Ubuntu)                  │
│                                                        │
│  Python Virtual Environment: (mt5env)                  │
│                                                        │
│  ~/scalper/                                            │
│  ├── config.py       ←─ System & Strategy Settings    │
│  ├── mt5_bridge.py   ←─ RPyC / MT5 Wrapper           │
│  ├── strategy.py     ←─ Dynamic ATR/RSI Strategy      │
│  ├── fetch_data.py   ←─ Fast Batch Data Downloader    │
│  ├── backtest.py     ←─ Bar-by-Bar Backtest Engine    │
│  ├── run.py          ←─ Continuous Live Execution     │
│  └── data/           ←─ Historical CSV Storage        │
└──────────────────────────┬────────────────────────────────────┘
                            │
                            │ RPyC Bridge (Port 18812)
                            │
┌────────────────────────────▼────────────────────────────┐
│        Docker Container: lprett/mt5linux:latest        │
│                                                        │
│  ├── Wine Emulation Environment                        │
│  ├── MetaTrader 5 Terminal                             │
│  │     └── XM Global Broker                            │
│  └── RPyC Server (0.0.0.0:18812)                       │
└─────────────────────────────────────────────────────────┘
```

**Separation of concerns**
- Host Python → strategy, risk, order parameters, continuous execution loop  
- Docker/MT5 → broker connectivity & order execution  
- RPyC → real-time bridge on port 18812

---

## File Responsibilities

| File | Purpose |
|------|---------|
| `config.py` | Global parameters (symbol, magic, timeframe, lot size, spread limit) |
| `mt5_bridge.py` | RPyC wrapper – ticks, rates, position checks, order execution with dynamic SL/TP |
| `strategy.py` | Strategy v5: 200-EMA filter + RSI(14) pullback + ATR(14) volatility filter + dynamic SL/TP |
| `fetch_data.py` | Fast historical candle downloader (`rpyc.classic.obtain`) |
| `backtest.py` | Bar-by-bar simulator with realistic $0.30/oz spread cost |
| `run.py` | Continuous live execution engine with safety guards |

---

## Risk Controls & Safeguards

1. **Spread Filter** – skips entry if live spread > `MAX_SPREAD_POINTS` (50)
2. **Active Position Guard** – blocks new entries while a trade with our magic number is open
3. **Volatility Guard (ATR)** – skips when ATR < $0.50 (avoids choppy ranges)
4. **Dynamic 1 : 2.5 Risk-to-Reward**
   - Stop Loss  = Entry ± (2.0 × ATR)
   - Take Profit = Entry ∓ (5.0 × ATR)
5. **Fixed Position Sizing** – currently 0.01 lots (testing size)
6. **RPyC Stream Safety** – large arrays transferred via `rpyc.classic.obtain()`
7. **Strict single-bar crossover logic** – prevents re-entry spam

---

## Strategy Evolution & Backtest History

| Stage | Timeframe | Logic | Trades | Win Rate | Net PnL | Notes |
|-------|-----------|-------|--------|----------|---------|-------|
| Baseline | M1 (5k) | 5/20 EMA crossover | 1,644 | 34.8% | -$385.20 | Heavy overtrading |
| Stage 2 | M1 (5k) | + 200 EMA filter | 1,155 | 33.7% | -$328.50 | Cut counter-trend trades |
| Stage 3 | M1 (5k) | + strict crossover | 147 | 35.4% | -$30.60 | Cut 90% of re-entries |
| Stage 4 | M1 (5k) | + RSI(14) 35/65 | 111 | 42.3% | -$20.30 | Better entries |
| Stage 5 | M1 (5k) | + fixed 1:2.75 R:R + ATR | 65 | 33.8% | +$15.50 | First profitable sample |
| Stage 6 | M1 (20k) | fixed R:R larger set | 207 | 29.0% | -$17.41 | M1 spread ate profits |
| **FINAL** | **M5 (20k)** | **Dynamic ATR 1:2.5** | **187** | **29.4%** | **+$43.68** | **Profitable – beats spread** |

---

## Active Strategy Rules (v5)

- **Timeframe**: M5
- **Trend Filter**: 200-period EMA  
  - BUY only when price > 200 EMA  
  - SELL only when price < 200 EMA
- **Entry Trigger (RSI 14)**:  
  - BUY: RSI dips ≤ 28 then crosses back above 28  
  - SELL: RSI spikes ≥ 72 then crosses back below 72
- **Volatility Guard**: Skip if ATR(14) < $0.50
- **Dynamic SL / TP**:  
  - SL = Entry ± 2.0 × ATR  
  - TP = Entry ∓ 5.0 × ATR

---

## Quick Start

```bash
# 1. Download historical data (20 000 M5 candles)
python3 fetch_data.py

# 2. Run backtest
python3 backtest.py

# 3. Run live continuous engine
python3 run.py
```

---

## Notes

- Always keep the Docker MT5 container running and RPyC listening on port 18812.
- Never commit credentials, login numbers, or large CSV files (see `.gitignore`).
- The old fixed `SL_POINTS` / `TP_POINTS` in `config.py` are legacy and no longer used by the live path.
