#!/usr/bin/env python3
"""
Dashboard for the Scalper bot.

Reads ONLY from status/log files written by the bot (via logger.LOG_DIR, so a
second instance such as btc/ shows its own book). Never opens its own MT5 /
RPyC connection.
"""

import json
import traceback
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import config
from logger import (
    LOG_DIR, get_connection_status, get_live_status, get_today_stats,
)
try:
    from portfolio import portfolio_state as _get_portfolio_state
except Exception:
    try:
        from portfolio import get_portfolio_state as _get_portfolio_state
    except Exception:
        _get_portfolio_state = None

BASE_DIR = Path(__file__).parent
TRADES_FILE = LOG_DIR / "trades.jsonl"
SYSTEM_FILE = LOG_DIR / "system.jsonl"

# Title is config-driven so a second instance (btc/dashboard.py) is branded
# correctly; gold falls back to the original name.
DASHBOARD_TITLE = getattr(config, "DASHBOARD_TITLE", "Gold Scalper Dashboard")

app = FastAPI(title=DASHBOARD_TITLE, version="1.4")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def read_jsonl(path: Path, limit: int = 50) -> list:
    try:
        if not path.exists():
            return []
        lines = path.read_text().strip().splitlines()
        entries = []
        for line in reversed(lines[-limit:]):
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
        return entries
    except Exception:
        return []


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        live = get_live_status()
        stats = get_today_stats()
        conn = get_connection_status()
        recent_trades = read_jsonl(TRADES_FILE, limit=40)
        recent_system = read_jsonl(SYSTEM_FILE, limit=30)
        portfolio = None
        if _get_portfolio_state is not None:
            try:
                portfolio = _get_portfolio_state()
            except Exception:
                portfolio = None

        uptime_str = "—"
        try:
            secs = int(conn.get("uptime_seconds") or 0)
            if secs > 0:
                hours, rem = divmod(secs, 3600)
                mins, secs = divmod(rem, 60)
                uptime_str = f"{hours}h {mins}m {secs}s"
        except Exception:
            uptime_str = "—"

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "live": live,
                "spread_gate": (live.get("spread_gate") or None),
                "stats": stats,
                "conn": conn,
                "portfolio": portfolio,
                "uptime_str": uptime_str,
                "trades": recent_trades,
                "system_logs": recent_system,
                "config": {
                    "symbol": getattr(config, "SYMBOL", "GOLD"),
                    "lot_size": getattr(config, "LOT_SIZE", 0.01),
                    "max_spread": getattr(config, "MAX_SPREAD_POINTS", 80),
                    "max_daily_loss": getattr(config, "MAX_DAILY_LOSS", 30),
                    "max_trades": getattr(config, "MAX_TRADES_PER_DAY", 15),
                },
                "title": DASHBOARD_TITLE,
                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    except Exception as e:
        tb = traceback.format_exc()
        print("DASHBOARD ERROR:", tb)
        return HTMLResponse(
            content=f"""
            <html><body style="background:#0f172a;color:#e2e8f0;font-family:sans-serif;padding:2rem">
            <h1>Dashboard error</h1>
            <p style="color:#94a3b8">{e}</p>
            <pre style="background:#1e293b;padding:1rem;border-radius:8px;font-size:0.8rem">{tb}</pre>
            <p><a href="/" style="color:#3b82f6">Retry</a></p>
            </body></html>
            """,
            status_code=200
        )


@app.get("/api/status")
async def api_status():
    try:
        data = {
            "live": get_live_status(),
            "stats": get_today_stats(),
            "connection": get_connection_status(),
            "trades": read_jsonl(TRADES_FILE, limit=20),
            "system": read_jsonl(SYSTEM_FILE, limit=15),
            "timestamp": datetime.now().isoformat()
        }
        if _get_portfolio_state is not None:
            try:
                data["portfolio"] = _get_portfolio_state()
            except Exception:
                pass
        return data
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


@app.get("/api/portfolio")
async def api_portfolio():
    if _get_portfolio_state is None:
        return {"error": "portfolio module not available", "timestamp": datetime.now().isoformat()}
    try:
        return _get_portfolio_state()
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}
