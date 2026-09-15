# Python MT5 Gold Scalper & Backtester Framework

An experimental algorithmic trading and backtesting framework for **GOLD / XAUUSD** using MetaTrader 5 inside a Docker container (Wine) bridged to a host Python environment via RPyC.

Trading logic, risk controls, and failure handling have been thoroughly tested and validated through historical simulation.

---

## 🏗️ System Architecture

```text
┌────────────────────────────────────────────────────────┐
│              Host OS (Linux / Ubuntu)                  │
│                                                        │
│  Python Virtual Environment: (mt5env)                  │
│                                                        │
│  ~/scalper/                                            │
│  ├── config.py       <-- System & Strategy Settings    │
│  ├── mt5_bridge.py   <-- RPyC / MT5 Wrapper           │
│  ├── strategy.py     <-- Dynamic ATR/RSI Strategy      │
│  ├── fetch_data.py   <-- Fast Batch Data Downloader    │
│  ├── backtest.py     <-- Bar-by-Bar Backtest Engine    │
│  ├── run.py          <-- Execution Engine              │
│  └── data/           <-- Historical CSV Storage        │
└───────────────────────────┬────────────────────────────┘
                            │
                            │ RPyC Bridge
                            │ Port 18812
                            │
┌───────────────────────────▼────────────────────────────┐
│        Docker Container: lprett/mt5linux:latest        │
│                                                        │
│  ├── Wine Emulation Environment                        │
│  ├── MetaTrader 5 Terminal                             │
│  │     └── XM Global Broker                            │
│  │                                                     │
│  └── RPyC Server                                       │
│        └── Listening on 0.0.0.0:18812                  │
└────────────────────────────────────────────────────────┘
```

### Architecture Overview
The system strictly separates trading logic from the MetaTrader 5 execution environment:
* **Host Python Environment (`mt5env`)**: Runs the strategy analysis, data processing, backtesting engine, and live execution loop cleanly on Linux.
* **Docker Container (`lprett/mt5linux`)**: Provides the Windows-compatible MT5 terminal via Wine without polluting the host OS.
* **RPyC Bridge (Port 18812)**: Enables real-time, bi-directional remote function calls between host Python and the Wine MT5 library.
* **Separation of Concerns**: MT5 handles broker connectivity and raw execution; host Python determines signals, risk management, and order parameter calculations.

---

## 🐳 Docker Deployment Setup

Container launch command mapping web UI (8080), VNC (5901), and RPyC bridge (18812):

```bash
docker run -d \
  --name mt5 \
  -p 8080:8080 \
  -p 5901:5901 \
  -p 18812:18812 \
  -e VNC_PASSWORD=XXX \
  -e MT5_LOGIN=420568040 \
  -e MT5_PASSWORD="" \
  -e MT5_SERVER="XMGlobal-MT5 17" \
  lprett/mt5linux:latest
```

---

## 📁 File Structure & Component Responsibilities

| File | Purpose |
| :--- | :--- |
| **`config.py`** | Holds global parameters: symbol (GOLD), magic number (999111), timeframe (M5), lot size (0.01), spread limits. |
| **`mt5_bridge.py`** | RPyC wrapper for connection handling, tick/candle data streams, active order queries, and live order execution. |
| **`strategy.py`** | Core Trading Strategy v5: 200 EMA trend filter + RSI(14) pullback signals + ATR(14) volatility filter + dynamic SL/TP. |
| **`fetch_data.py`** | High-speed historical candle downloader using `rpyc.classic.obtain()` to store local CSV data. |
| **`backtest.py`** | Bar-by-bar simulator accounting for $0.30/oz spread cost, dynamic SL/TP checks, and net PnL tracking. |
| **`run.py`** | Live trading execution engine with pre-trade safety checks and position guards. |

---

## 🛡️ Risk Controls & Safeguards

* **Spread Filter Guard**: Checks live market spread prior to trade execution (`MAX_SPREAD_POINTS = 50`). Skips entry if spread spikes.
* **Active Position Guard**: Checks open positions via `MAGIC_NUMBER` before placing orders, preventing duplicate re-entries.
* **Volatility Guard (ATR)**: Skips trade entries when market volatility drops below $0.50/min (prevents choppy range-bound losses).
* **Dynamic Risk-to-Reward Ratio (1 : 2.5)**:
  * **Stop Loss (SL)**: `Entry ± (2.0 × ATR)`
  * **Take Profit (TP)**: `Entry ∓ (5.0 × ATR)`
* **Fixed Position Sizing**: Controlled lot sizing (0.01 lots for testing) to prevent over-leveraging.

---

## 🛠️ Failure & Error Handling Systems

* **RPyC Stream EOF Prevention**: Solved socket disconnects when pulling large historical arrays by wrapping remote calls in `rpyc.classic.obtain()`.
* **Zero-Price Tick Handling**: Implemented retry delays during MT5 initialization to handle price stream sync delays.
* **Strict Crossover Logic**: Replaced continuous directional conditions with single-bar state triggers to eliminate duplicate trade loops.
* **Spread Deducted Backtesting**: Backtester enforces a realistic $0.30/oz fixed spread deduction per trade to ensure results survive real market friction.

---

## 📊 Strategy Evolution & Backtest History

| Stage | Timeframe | Strategy Logic Description | Total Trades | Win Rate | Net PnL | Result / Key Finding |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Baseline** | M1 (5k) | Raw 5/20 EMA Crossover | 1,644 | 34.8% | -$385.20 | Heavy overtrading in range bound markets |
| **Stage 2** | M1 (5k) | + 200 EMA Trend Filter | 1,155 | 33.7% | -$328.50 | Cut 489 counter-trend trades |
| **Stage 3** | M1 (5k) | + Strict Crossover Trigger | 147 | 35.4% | -$30.60 | Cut 90% of losses by stopping re-entries |
| **Stage 4** | M1 (5k) | + RSI(14) Pullback (35/65) | 111 | 42.3% | -$20.30 | Mean-reversion entries improved win rate |
| **Stage 5** | M1 (5k) | + Fixed 1:2.75 R:R & ATR filter | 65 | 33.8% | +$15.50 | Profitable on 5k sample |
| **Stage 6** | M1 (20k)| Fixed 1:2.75 R:R on larger dataset | 207 | 29.0% | -$17.41 | M1 spread fees ($0.30) ate gross profits |
| **FINAL** | **M5 (20k)**| **Dynamic ATR SL/TP (1:2.5 R:R)** | **187** | **29.4%** | **+$43.68** | **PROFITABLE** (Beats broker spread) |

---

## 🎯 Active Strategy Rules (v5)

* **Timeframe**: 5-Minute Chart (M5).
* **Trend Filter**: 200-period Exponential Moving Average (EMA).
  * Only **BUY** if Price > 200 EMA.
  * Only **SELL** if Price < 200 EMA.
* **Entry Trigger (RSI 14 Pullback)**:
  * **BUY Signal**: RSI dips ≤ 28 (oversold) and crosses back above 28.
  * **SELL Signal**: RSI spikes ≥ 72 (overbought) and crosses back below 72.
* **Volatility Guard (ATR 14)**:
  * Skip entry if current ATR < $0.50 per candle.
* **Dynamic SL / TP Levels**:
  * **Stop Loss**: `Entry ± (2.0 × ATR)`
  * **Take Profit**: `Entry ∓ (5.0 × ATR)`

---

## 🚀 Quick Execution Guide

### 1. Download Historical Data (20,000 M5 Candles)
```bash
python3 fetch_data.py
```

### 2. Run Strategy Backtest
```bash
python3 backtest.py
```

### 3. Run Live Pre-Trade Pipeline
```bash
python3 run.py
```
