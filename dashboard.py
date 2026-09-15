#!/usr/bin/env python3
"""
Simple FastAPI dashboard for the Gold Scalper.
Run with:  uvicorn dashboard:app --host 0.0.0.0 --port 8088
"""

import json
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import config
from logger import get_connection_status

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
TRADES_FILE = LOG_DIR / "trades.jsonl"
SYSTEM_FILE = LOG_DIR / "system.jsonl"
DAILY_STATS_FILE = LOG_DIR / "daily_stats.json"

app = FastAPI(title="Gold Scalper Dashboard", version="1.1")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def read_jsonl(path: Path, limit: int = 50) -> list:
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


def get_daily_stats() -> dict:
    if not DAILY_STATS_FILE.exists():
        return {"date": datetime.now().date().isoformat(), "pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
    try:
        return json.loads(DAILY_STATS_FILE.read_text())
    except Exception:
        return {"date": datetime.now().date().isoformat(), "pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}


def get_live_mt5():
    """Try to fetch live data from MT5. Returns dict with connected=False on failure."""
    try:
        from mt5_bridge import MT5Bridge
        bridge = MT5Bridge()
        acc = bridge.get_account_info()
        tick = bridge.get_live_tick()
        sym = bridge.get_symbol_info()
        positions = []

        raw_positions = bridge.mt5.positions_get(symbol=config.SYMBOL)
        if raw_positions:
            for p in raw_positions:
                if p.magic == config.MAGIC_NUMBER:
                    positions.append({
                        "ticket": p.ticket,
                        "type": "BUY" if p.type == 0 else "SELL",
                        "volume": p.volume,
                        "price_open": p.price_open,
                        "sl": p.sl,
                        "tp": p.tp,
                        "profit": p.profit,
                        "time": datetime.fromtimestamp(p.time).strftime("%Y-%m-%d %H:%M:%S")
                    })

        data = {
            "connected": True,
            "balance": float(acc.balance) if acc else 0.0,
            "equity": float(acc.equity) if acc else 0.0,
            "margin_free": float(acc.margin_free) if acc else 0.0,
            "bid": float(tick.bid) if tick else 0.0,
            "ask": float(tick.ask) if tick else 0.0,
            "spread": round((tick.ask - tick.bid) / sym.point) if (tick and sym) else 0,
            "positions": positions
        }
        bridge.close()
        return data
    except Exception as e:
        return {
            "connected": False,
            "error": str(e),
            "balance": 0,
            "equity": 0,
            "bid": 0,
            "ask": 0,
            "spread": 0,
            "positions": []
        }


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    live = get_live_mt5()
    stats = get_daily_stats()
    conn = get_connection_status()
    recent_trades = read_jsonl(TRADES_FILE, limit=40)
    recent_system = read_jsonl(SYSTEM_FILE, limit=30)

    # Human-readable uptime
    uptime_str = "—"
    if conn.get("uptime_seconds", 0) > 0:
        secs = conn["uptime_seconds"]
        hours, rem = divmod(secs, 3600)
        mins, secs = divmod(rem, 60)
        uptime_str = f"{hours}h {mins}m {secs}s"

    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "live": live,
            "stats": stats,
            "conn": conn,
            "uptime_str": uptime_str,
            "trades": recent_trades,
            "system_logs": recent_system,
            "config": {
                "symbol": config.SYMBOL,
                "lot_size": config.LOT_SIZE,
                "max_spread": config.MAX_SPREAD_POINTS,
                "max_daily_loss": config.MAX_DAILY_LOSS,
                "max_trades": config.MAX_TRADES_PER_DAY,
            },
            "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    )


@app.get("/api/status")
async def api_status():
    return {
        "live": get_live_mt5(),
        "stats": get_daily_stats(),
        "connection": get_connection_status(),
        "trades": read_jsonl(TRADES_FILE, limit=20),
        "system": read_jsonl(SYSTEM_FILE, limit=15),
        "timestamp": datetime.now().isoformat()
    }
