# Python MT5 Gold Scalper & Backtester Framework

An experimental algorithmic trading and backtesting framework for **GOLD / XAUUSD** using MetaTrader 5 inside a Docker container (Wine) bridged to a host Python environment via RPyC.

---

## Changelog

### 2026-09-15 – Web Dashboard Added

- New FastAPI dashboard (`dashboard.py` + `templates/index.html`)
- Live view of: connection status, balance/equity, GOLD price & spread, open positions, today PnL, recent trade events and system logs
- Auto-refresh every 15 seconds
- JSON API endpoint at `/api/status`
- Runs on port **8088**

### 2026-09-15 – Expanded Dependencies + Safety Layer Live

- Expanded `requirements.txt` (FastAPI, Uvicorn, numpy, etc.)
- Confirmed live engine operational with spread filter and logging
- Safety features: daily loss limit, max trades/day, auto-reconnect

### 2026-09-15 – Critical Safety Layer

- Added `logger.py` (structured JSONL logging)
- Daily loss limit + max trades per day
- Improved connection recovery
- Cleaned `config.py`

### 2026-09-15 – Live Trading Fixes

- Fixed signal tuple unpacking (critical bug)
- Dynamic ATR-based SL/TP in live path
- Continuous loop + 250 bars for EMA200
- Added `.gitignore`

---

## Current Status

| Component              | Status     | Notes                                      |
|------------------------|------------|--------------------------------------------|
| Live Engine (`run.py`) | Working    | Spread filter, risk limits, logging active |
| Strategy v5            | Working    | 200 EMA + RSI pullback + ATR filter        |
| Backtester             | Working    |                                            |
| Structured Logging     | Working    | `logs/` folder                             |
| **Web Dashboard**      | **Working**| FastAPI on port 8088                       |
| Trailing / Partial TP  | Planned   |                                            |
| Session Filters        | Planned   |                                            |

---

## Quick Start

```bash
# Activate environment
source mt5env/bin/activate

# Install / update deps
pip install -r requirements.txt

# Terminal 1 – Live bot
python run.py

# Terminal 2 – Dashboard
uvicorn dashboard:app --host 0.0.0.0 --port 8088
```

Then open in browser: **http://YOUR_SERVER_IP:8088**

---

## Risk Controls (Current)

- Spread filter (`MAX_SPREAD_POINTS = 50`)
- Active position guard (magic number)
- ATR volatility filter
- Dynamic 1:2.5 R:R
- Daily loss limit (`$30`)
- Max trades per day (`15`)
- Auto-reconnect

---

## Strategy Rules (v5)

- Timeframe: M5
- Trend filter: 200 EMA
- Entry: RSI(14) pullback (≤28 / ≥72)
- Volatility: ATR(14) ≥ $0.50
- SL/TP: 2×ATR / 5×ATR

---

## Next Planned Improvements

1. Trailing stop / partial close
2. Session / news filters
3. Position sizing by % risk
4. Telegram alerts
5. Better backtest realism (slippage, variable spread)
