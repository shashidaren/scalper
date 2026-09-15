# Python MT5 Gold Scalper & Backtester Framework

An experimental algorithmic trading and backtesting framework for **GOLD / XAUUSD** using MetaTrader 5 inside a Docker container (Wine) bridged to a host Python environment via RPyC.

Trading logic, risk controls, and failure handling have been thoroughly tested and validated through historical simulation.

---

## Changelog

### 2026-09-15 – Expanded Dependencies + Safety Layer Live

- Expanded `requirements.txt` with libraries needed for the upcoming web dashboard (FastAPI, Uvicorn, Jinja2, etc.) and general analysis (numpy, requests, python-dotenv).
- Confirmed live engine is operational: connects to MT5, applies spread filter, and logs correctly.
- Safety features active: daily loss limit, max trades/day, structured logging, auto-reconnect.

### 2026-09-15 – Critical Safety Layer

- Added `logger.py` – structured trade + system logging (JSONL files in `/logs`)
- Added daily loss limit (`MAX_DAILY_LOSS`) and max trades per day
- Improved connection recovery (auto-reconnect after repeated errors)
- Cleaned `config.py` – removed dead SL/TP points, added risk parameters
- Added `requirements.txt`
- Live loop now logs every signal, entry attempt, and system event

### 2026-09-15 – Live Trading Fixes & Project Hygiene

**Critical bug fixes (live trading was previously non-functional):**

- Fixed signal handling in `run.py`: `check_signal()` returns a tuple `(signal, sl_dist, tp_dist)`. Previous code treated it as a string → no trades could ever be placed.
- Increased bar request from 50 → 250 so the 200-EMA has enough data.
- Made `mt5_bridge.open_trade()` accept and use **dynamic ATR-based** SL/TP distances instead of fixed points.
- Converted `run.py` into a continuous loop with proper error handling, spread checks, and position guards.

**Project hygiene:**

- Added `.gitignore`
- Live and backtest engines now share the same dynamic risk rules (1 : 2.5 R:R based on ATR).

---

## Current Status

| Component              | Status          | Notes                                      |
|------------------------|-----------------|--------------------------------------------|
| Live Engine (`run.py`) | Working         | Spread filter, risk limits, logging active |
| Strategy v5            | Working         | 200 EMA + RSI pullback + ATR filter        |
| Backtester             | Working         |                                            |
| Structured Logging     | Working         | `logs/` folder                             |
| Web Dashboard          | Planned (next)  | FastAPI-based monitoring UI                |
| Trailing / Partial TP  | Planned        |                                            |
| Session Filters        | Planned        |                                            |

---

## System Architecture

```text
Host Python (strategy + risk + logging + live loop)
        ↔ RPyC (port 18812)
Docker MT5 (Wine) + XM Global
```

---

## File Responsibilities

| File | Purpose |
|------|---------|
| `config.py` | All tunable parameters (risk limits, lot size, spread, timing) |
| `mt5_bridge.py` | RPyC wrapper – ticks, rates, positions, order execution |
| `strategy.py` | Strategy v5 (200 EMA + RSI pullback + ATR filter + dynamic SL/TP) |
| `logger.py` | Structured logging of trades and system events |
| `fetch_data.py` | Historical data downloader |
| `backtest.py` | Bar-by-bar backtester |
| `run.py` | Continuous live engine with risk guards |
| `requirements.txt` | Python dependencies |

---

## Risk Controls (Current)

- Spread filter (`MAX_SPREAD_POINTS = 50`)
- Active position guard (magic number)
- ATR volatility filter (< $0.50 → skip)
- Dynamic 1:2.5 R:R (2×ATR SL / 5×ATR TP)
- **Daily loss limit** (`MAX_DAILY_LOSS = $30`)
- **Max trades per day** (`MAX_TRADES_PER_DAY = 15`)
- Auto-reconnect on repeated connection errors

---

## Active Strategy Rules (v5)

- Timeframe: M5
- Trend: 200 EMA (only trade with the trend)
- Entry: RSI(14) pullback (BUY ≤ 28 cross up / SELL ≥ 72 cross down)
- Volatility filter: ATR(14) ≥ $0.50
- SL / TP: dynamic from ATR

---

## Setup & Run

```bash
# Create / activate virtual environment
python3 -m venv mt5env
source mt5env/bin/activate

# Install dependencies
pip install -r requirements.txt

# Download historical data
python fetch_data.py

# Backtest
python backtest.py

# Live engine
python run.py
```

Logs are written to the `logs/` folder (`trades.jsonl`, `system.jsonl`, `daily_stats.json`).

---

## Next Planned Improvements

1. **Web dashboard** for easy monitoring (FastAPI)
2. Trailing stop / partial close logic
3. Session / news filters
4. Better position sizing (% risk of equity)
5. Telegram / Discord alerts
6. Auto-update via cron (optional)
