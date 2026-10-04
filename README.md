# Python MT5 Gold Scalper & Backtester Framework

An experimental algorithmic trading and backtesting framework for **GOLD / XAUUSD** using MetaTrader 5 inside a Docker container (Wine) bridged to a host Python environment via RPyC.

---

## Changelog

### 2026-10-01 – Trade-frequency tuning (RSI 40/60, session 07–20 UTC)

- User feedback: the bot was taking very few trades (174 over ~101 days of
  backtest, ~2.5/day in a 10h session). Re-swept RSI thresholds and the
  session window with `research/strategy_sweep.py`; **RSI 40/60 combined with
  widening the session end from 17:00 to 20:00 UTC** (still before the daily
  21:00–22:00 UTC rollover break) gives **255 trades (+47%), net +$456.58
  (was +$52.80), PF 1.32 (was 1.06), bootstrap P(net>0)=0.96 (was 0.60,
  i.e. the old config's CI spanned zero)** — more trades *and* a better
  backtested edge, profitable in every calendar month and both halves of the
  data. Full analysis: `docs/strategy_iteration_2026-10-01.md`.
- Note: RSI 40/60 alone was tested and rejected on 2026-09-30 (flagged
  "non-monotone") under the *old* session window; the 2026-10-01 fine-grained
  re-scan (36/64 … 44/56) shows a smooth, non-fragile hump around 40/60 once
  combined with the wider session, not a one-off fluke.
- Fixed a floating-point precision bug in `research/strategy_sweep.py`'s fast
  replay engine (`_rolling_mean` now uses `pandas.Series.rolling` instead of
  a cumsum, which could disagree with the live `strategy.py` path by ~1e-11
  at a bar whose RSI exactly ties a threshold). `backtest.py`/live were never
  affected; `research/parity_test.py` now passes with 0 mismatches.
- Still in `TRADING_MODE="FORWARD_TEST"` — this is a backtested frequency/
  quality improvement, not a validated live edge; the launch criteria in
  `HANDOFF.md` §5 are unchanged.

### 2026-09-30 – Strategy iteration + honest backtest measurement

- **Breakeven ratchet moved from +0.75R to +1.5R** (`BE_TRIGGER_R`): with a 5R
  target the 0.75R ratchet scratched ~half of all trades at entry (each paying a
  full spread) and almost no winner reached target. Monotone across the ladder
  0.5R → off; 1.5R is the conservative end of the plateau
- **Indicator window pinned to `INDICATOR_WINDOW_BARS = 1000`**, shared by the
  strategy guard, the bridge fetch and the backtester. Previously the live path
  fetched 250 bars and the backtester used 202, and because
  `ewm(adjust=False)` keeps `(1-α)^(n-1)` weight on its seed the "EMA200" was
  silently a much shorter average — and a *different* one in each path
- **Backtester now prices the real spread** from the data's `spread` column
  (mean $0.47) instead of a flat $0.30, and prints the spread source, the window
  size and the TP/BE/SL exit split
- Added `research/strategy_sweep.py`: fast one-variable-at-a-time parameter
  sweeps, verified to reproduce `backtest.py` exactly
- Rejected after testing: session 08–16 UTC, H1 trend confirmation, RSI 40/60,
  wider/narrower ATR multiples (details in `docs/strategy_iteration_2026-09-30.md`)

### 2026-09-15 – Forward-Test (Paper) Trading Mode

- Ported the `FORWARD_TEST` approach from `shashidaren/gold-trading-bot`:
  real MT5 ticks, fully simulated balance/positions — **no orders are sent**
- `paper.py`: crash-safe simulated account ($300 start, was $200 until 2026-10-04), SL/TP exit logic,
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
risk gates on **real MT5 ticks**, but fills are simulated against a $300
paper balance (`SIM_START_BALANCE`, was $200 until 2026-10-04). Open simulated positions survive bot
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
