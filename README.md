# Python MT5 Gold Scalper & Backtester Framework

An experimental algorithmic trading and backtesting framework for **GOLD / XAUUSD** using MetaTrader 5 inside a Docker container (Wine) bridged to a host Python environment via RPyC.

---

## Changelog

### 2026-09-15 – MT5 Engine Hardening

- Actionable connection errors: refused vs timeout vs MT5 init vs symbol failures
- Exponential reconnect backoff (10s → 60s cap) instead of hammering every 10s
- Bounded RPyC request timeout (`RPC_TIMEOUT_SECONDS`) so a frozen MT5 terminal can't hang the engine
- Stale-tick detection: warns when the feed stops moving, forces a reconnect if it stays frozen
- `wait_for_mt5.py` readiness gate used as `ExecStartPre` so the service waits for the MT5 Docker container after boot
- Logs are always written to `<repo>/logs` regardless of the working directory

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

## Troubleshooting: "Connection refused" / "MT5 bridge unreachable"

The bot talks to MT5 through an RPyC server (default `localhost:18812`) that
runs inside the MT5 Docker container. "Connection refused" means nothing is
listening on that port — almost always the MT5 container being down or still
booting (common right after a host reboot):

```bash
# 1. Is the MT5 container running?
docker ps

# 2. Is the RPyC port open on the host?
ss -tlnp | grep 18812

# 3. Restart the MT5 container (adjust name to yours)
docker restart mt5

# 4. Wait until the bridge is fully ready (TCP + MT5 initialized)
cd ~/scalper && mt5env/bin/python wait_for_mt5.py --timeout 120
```

No need to restart the bot — it retries with backoff and reconnects
automatically once the container is back. If you change the service files,
re-install them:

```bash
cp services/scalper-bot.service services/scalper-dashboard.service /etc/systemd/system/
systemctl daemon-reload && systemctl restart scalper-bot
```

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
