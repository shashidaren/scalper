# Python MT5 Gold Scalper & Backtester Framework

An experimental algorithmic trading and backtesting framework for **GOLD / XAUUSD** using MetaTrader 5 inside a Docker container (Wine) bridged to a host Python environment via RPyC.

---

## Changelog

### 2026-09-15 – Forward-Test (Paper) Trading Mode

- Ported the `FORWARD_TEST` approach from `shashidaren/gold-trading-bot`:
  real MT5 ticks, fully simulated balance/positions — **no orders are sent**
- `paper.py`: crash-safe simulated account ($200 start), SL/TP exit logic,
  breakeven ratchet at +0.75R (same as the gold bot)
- Simulated closes update the daily stats, so all risk gates apply in paper mode
- Dashboard shows a `(PAPER)` badge and the simulated balance
- Inspect/reset the sim account: `python paper.py` / `python paper.py --reset`
- Go real by flipping `TRADING_MODE = "LIVE"` in `config.py`

### 2026-09-15 – MT5 Container via docker-compose + .env Secrets

- `docker-compose.yml` runs the MT5 container (RPyC bridge) with ports 18812/5901/8080
- Credentials live in `.env` (gitignored) — see `.env.example`; never committed

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

## MT5 Container & Secrets (.env)

The MT5 terminal runs in Docker (`lprett/mt5linux` image) and exposes the RPyC
bridge the bot connects to on port 18812. Its credentials live in `.env`,
which is **gitignored — never commit it**.

```bash
cd ~/scalper
cp .env.example .env
nano .env                     # fill in MT5_LOGIN / MT5_PASSWORD / MT5_SERVER / VNC_PASSWORD
docker compose up -d          # (re)creates the mt5 container with those secrets
```

Notes:

- `docker-compose.yml` contains no secrets and is safe to commit.
- The image uses the credentials only for its first-run auto-login. Once the
  Wine prefix exists, the login is stored inside it — manage it via the noVNC
  UI at `http://<server-ip>:8080`.
- If you rotate the MT5 password, change it in MT5 (noVNC), then keep `.env`
  in sync for the record.
- Requires the Docker Compose plugin (`docker compose version`); if missing:
  `apt-get install docker-compose-plugin`.

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

## Forward-Test (Paper) Mode

`TRADING_MODE = "FORWARD_TEST"` (default) runs the exact same strategy and
risk gates on **real MT5 ticks**, but fills are simulated against a $200
paper balance (`SIM_START_BALANCE`). Open simulated positions survive bot
restarts (`logs/paper_account.json`), exits resolve SL-first like the gold
bot, and every simulated close counts toward the daily trade/loss limits.

When the paper book proves out, set `TRADING_MODE = "LIVE"` in `config.py`
and restart the service — same engine, real orders.

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
