# Python MT5 Gold Scalper & Backtester Framework

An experimental algorithmic trading and backtesting framework for **GOLD / XAUUSD** using MetaTrader 5 inside a Docker container (Wine) bridged to a host Python environment via RPyC.

---

## Changelog

### 2026-09-15 – Dashboard Fix + Systemd Services

- Fixed FastAPI/Starlette `TemplateResponse` compatibility issue
- Added systemd service files so bot + dashboard survive reboots
- Services located in `services/` folder

### 2026-09-15 – Web Dashboard Added

- FastAPI dashboard with live account, price, positions, logs
- Auto-refresh every 15s + JSON API

### 2026-09-15 – Safety Layer + Live Fixes

- Daily loss limit, max trades/day, structured logging, auto-reconnect
- Fixed critical signal unpacking bug + dynamic ATR SL/TP in live path

---

## Quick Start (Manual)

```bash
cd ~/scalper
source mt5env/bin/activate

# Terminal 1
python run.py

# Terminal 2
uvicorn dashboard:app --host 0.0.0.0 --port 8088
```

Dashboard: http://YOUR_SERVER_IP:8088

---

## Run as System Services (Recommended)

```bash
cd ~/scalper
git pull origin main

# Copy service files
cp services/scalper-bot.service /etc/systemd/system/
cp services/scalper-dashboard.service /etc/systemd/system/

# Reload and enable
systemctl daemon-reload
systemctl enable scalper-bot scalper-dashboard
systemctl start scalper-bot scalper-dashboard

# Check status
systemctl status scalper-bot
systemctl status scalper-dashboard

# View logs
journalctl -u scalper-bot -f
journalctl -u scalper-dashboard -f
```

Both services will now start automatically after reboot.

---

## Risk Controls

- Spread filter, position guard, ATR filter
- Dynamic 1:2.5 R:R
- Daily loss limit ($30)
- Max trades/day (15)
- Auto-reconnect

---

## Strategy (v5)

- M5 | 200 EMA trend filter | RSI(14) pullback | ATR volatility filter | Dynamic SL/TP
