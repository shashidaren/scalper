#!/usr/bin/env python3
"""
Simple FastAPI dashboard for the Gold Scalper.
Run with:  uvicorn dashboard:app --host 0.0.0.0 --port 8088
"""

import json
import traceback
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import config

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
TRADES_FILE = LOG_DIR / "trades.jsonl"
SYSTEM_FILE = LOG_DIR / "system.jsonl"
DAILY_STATS_FILE = LOG_DIR / "daily_stats.json"
CONNECTION_STATUS_FILE = LOG_DIR / "connection_status.json"

app = FastAPI(title="Gold Scalper Dashboard", version="1.2")
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


def get_daily_stats() -> dict:
    default = {"date": datetime.now().date().isoformat(), "pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
    try:
        if not DAILY_STATS_FILE.exists():
            return default
        return json.loads(DAILY_STATS_FILE.read_text())
    except Exception:
        return default


def get_connection_status() -> dict:
    default = {
        "connected": False,
        "reconnect_count": 0,
        "connected_since": None,
        "last_tick_time": None,
        "last_error": None,
        "uptime_seconds": 0,
        "updated_at": None
    }
    try:
        if not CONNECTION_STATUS_FILE.exists():
            return default
        data = json.loads(CONNECTION_STATUS_FILE.read_text())
        # ensure all keys exist
        for k, v in default.items():
            if k not in data:
                data[k] = v
        return data
    except Exception:
        return default


def get_live_mt5():
    """Fetch live data from MT5. Always returns a safe dict, never raises."""
    fallback = {
        "connected": False,
        "error": "MT5 unavailable",
        "balance": 0.0,
        "equity": 0.0,
        "margin_free": 0.0,
        "bid": 0.0,
        "ask": 0.0,
        "spread": 0,
        "positions": []
    }
    try:
        from mt5_bridge import MT5Bridge
        bridge = MT5Bridge()
        try:
            acc = bridge.get_account_info()
            tick = bridge.get_live_tick()
            sym = bridge.get_symbol_info()
            positions = []

            if acc and tick and sym:
                try:
                    raw_positions = bridge.mt5.positions_get(symbol=config.SYMBOL)
                    if raw_positions:
                        for p in raw_positions:
                            if p.magic == config.MAGIC_NUMBER:
                                positions.append({
                                    "ticket": p.ticket,
                                    "type": "BUY" if p.type == 0 else "SELL",
                                    "volume": float(p.volume),
                                    "price_open": float(p.price_open),
                                    "sl": float(p.sl),
                                    "tp": float(p.tp),
                                    "profit": float(p.profit),
                                    "time": datetime.fromtimestamp(p.time).strftime("%Y-%m-%d %H:%M:%S")
                                })
                except Exception:
                    positions = []

                return {
                    "connected": True,
                    "error": None,
                    "balance": float(getattr(acc, "balance", 0) or 0),
                    "equity": float(getattr(acc, "equity", 0) or 0),
                    "margin_free": float(getattr(acc, "margin_free", 0) or 0),
                    "bid": float(getattr(tick, "bid", 0) or 0),
                    "ask": float(getattr(tick, "ask", 0) or 0),
                    "spread": round((tick.ask - tick.bid) / sym.point) if sym.point else 0,
                    "positions": positions
                }
            else:
                fallback["error"] = "Incomplete market data"
                return fallback
        finally:
            try:
                bridge.close()
            except Exception:
                pass
    except Exception as e:
        fallback["error"] = str(e)[:120]
        return fallback


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        live = get_live_mt5()
        stats = get_daily_stats()
        conn = get_connection_status()
        recent_trades = read_jsonl(TRADES_FILE, limit=40)
        recent_system = read_jsonl(SYSTEM_FILE, limit=30)

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
                "stats": stats,
                "conn": conn,
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
                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "error": None
            }
        )
    except Exception as e:
        # Absolute last resort – never return 500
        tb = traceback.format_exc()
        print("DASHBOARD ERROR:", tb)
        return HTMLResponse(
            content=f"""
            <html><body style="background:#0f172a;color:#e2e8f0;font-family:sans-serif;padding:2rem">
            <h1>Dashboard temporarily unavailable</h1>
            <p style="color:#94a3b8">{e}</p>
            <pre style="background:#1e293b;padding:1rem;border-radius:8px;overflow:auto;font-size:0.8rem">{tb}</pre>
            <p><a href="/" style="color:#3b82f6">Retry</a></p>
            </body></html>
            """,
            status_code=200
        )


@app.get("/api/status")
async def api_status():
    try:
        return {
            "live": get_live_mt5(),
            "stats": get_daily_stats(),
            "connection": get_connection_status(),
            "trades": read_jsonl(TRADES_FILE, limit=20),
            "system": read_jsonl(SYSTEM_FILE, limit=15),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}
