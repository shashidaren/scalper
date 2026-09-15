# Python MT5 Gold Scalper & Backtester Framework

An experimental algorithmic trading and backtesting framework for **GOLD / XAUUSD** using MetaTrader 5 inside a Docker container (Wine) bridged to a host Python environment via RPyC.

Trading logic, risk controls, and failure handling have been thoroughly tested and validated through historical simulation.

---

## Changelog

### 2026-09-15 (later) – Critical Safety Layer

- Added `logger.py` – structured trade + system logging (JSONL files in `/logs`)
- Added daily loss limit (`MAX_DAILY_LOSS`) and max trades per day
- Improved connection recovery (auto-reconnect after repeated errors)
- Cleaned `config.py` – removed dead SL/TP points, added risk parameters
- Added `requirements.txt`
- Live loop now logs every signal, entry attempt, and system event

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

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Download data
python3 fetch_data.py

# Backtest
python3 backtest.py

# Live engine
python3 run.py
```

Logs are written to the `logs/` folder (`trades.jsonl`, `system.jsonl`, `daily_stats.json`).

---

## Next Planned Improvements

1. Web dashboard for easy monitoring
2. Trailing stop / partial close logic
3. Session / news filters
4. Better position sizing (% risk)
5. Telegram alerts
