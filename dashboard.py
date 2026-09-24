#!/usr/bin/env python3
"""
Dashboard for Gold Scalper.
Reads ONLY from status/log files written by the bot.
Never opens its own MT5 / RPyC connection.
"""

import json
import traceback
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import config
from logger import LOG_DIR, get_connection_status, get_live_status, get_today_stats

BASE_DIR = Path(__file__).parent
TRADES_FILE = LOG_DIR / "trades.jsonl"
SYSTEM_FILE = LOG_DIR / "system.jsonl"
PAPER_FILE = LOG_DIR / "paper_account.json"
CONTRACT_SIZE = 100.0

app = FastAPI(title="Gold Scalper Dashboard", version="1.4.1")
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


def _idle_signal(entry: dict) -> bool:
    if entry.get("event") != "SIGNAL":
        return False
    sig = entry.get("signal")
    return sig in (None, "", "None")


def _heartbeat_system(entry: dict) -> bool:
    msg = str(entry.get("message") or "")
    return msg.startswith("SIM:") or "SimEquity:" in msg or msg.startswith("Balance:")


def read_trade_events(limit: int = 30) -> list:
    raw = read_jsonl(TRADES_FILE, limit=400)
    out = [e for e in raw if not _idle_signal(e)]
    return out[:limit]


def read_system_events(limit: int = 25) -> list:
    raw = read_jsonl(SYSTEM_FILE, limit=400)
    out = [e for e in raw if not _heartbeat_system(e)]
    return out[:limit]


def get_paper_book() -> dict:
    default = {
        "balance": None,
        "closed": 0,
        "wins": 0,
        "losses": 0,
        "position": None,
        "updated_at": None,
    }
    if not PAPER_FILE.exists():
        return default
    try:
        data = json.loads(PAPER_FILE.read_text())
        for k, v in default.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return default


def session_state(when=None):
    when = when or datetime.now(timezone.utc)
    if getattr(config, "WEEKEND_FLAT_ENABLED", False) and when.weekday() >= 5:
        return False, "weekend flat"
    if getattr(config, "FRIDAY_CUTOFF_ENABLED", False):
        cutoff = getattr(config, "FRIDAY_CUTOFF_HOUR_UTC", 16)
        if when.weekday() == 4 and when.hour >= cutoff:
            return False, f"Friday cutoff (>={cutoff}:00 UTC)"
    if not getattr(config, "SESSION_FILTER_ENABLED", False):
        return True, "filter off"
    start = getattr(config, "SESSION_START_HOUR_UTC", 8)
    end = getattr(config, "SESSION_END_HOUR_UTC", 16)
    inside = start <= when.hour < end
    return inside, f"{start:02d}–{end:02d} UTC"


def enrich_positions(live: dict) -> None:
    """Fill floating PnL for paper SIM rows that store profit=0."""
    bid = float(live.get("bid") or 0)
    ask = float(live.get("ask") or 0)
    for p in live.get("positions") or []:
        if p.get("ticket") != "SIM":
            continue
        side = p.get("type")
        entry = float(p.get("price_open") or 0)
        vol = float(p.get("volume") or 0)
        if not entry or not vol:
            continue
        px = bid if side == "BUY" else ask
        if not px:
            continue
        diff = (px - entry) if side == "BUY" else (entry - px)
        p["profit"] = round(diff * vol * CONTRACT_SIZE, 2)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    try:
        live = get_live_status()
        stats = get_today_stats()
        conn = get_connection_status()
        paper = get_paper_book()
        recent_trades = read_trade_events(30)
        recent_system = read_system_events(25)
        enrich_positions(live)

        uptime_str = "—"
        try:
            secs = int(conn.get("uptime_seconds") or 0)
            if secs > 0:
                hours, rem = divmod(secs, 3600)
                mins, secs = divmod(rem, 60)
                uptime_str = f"{hours}h {mins}m {secs}s"
        except Exception:
            uptime_str = "—"

        in_session, session_label = session_state()
        max_cl = int(getattr(config, "MAX_CONSECUTIVE_LOSSES", 0) or 0)
        consec = int(stats.get("consecutive_losses") or 0)
        paused = max_cl > 0 and consec >= max_cl

        return templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "live": live,
                "stats": stats,
                "conn": conn,
                "paper": paper,
                "uptime_str": uptime_str,
                "trades": recent_trades,
                "system_logs": recent_system,
                "in_session": in_session,
                "session_label": session_label,
                "paused": paused,
                "config": {
                    "symbol": getattr(config, "SYMBOL", "GOLD"),
                    "mode": getattr(config, "TRADING_MODE", "FORWARD_TEST"),
                    "lot_size": getattr(config, "LOT_SIZE", 0.01),
                    "max_spread": getattr(config, "MAX_SPREAD_POINTS", 80),
                    "max_daily_loss": getattr(config, "MAX_DAILY_LOSS", 30),
                    "max_trades": getattr(config, "MAX_TRADES_PER_DAY", 15),
                    "max_consec": max_cl,
                    "session": session_label,
                    "rsi_buy": getattr(config, "RSI_BUY_LEVEL", 30),
                    "rsi_sell": getattr(config, "RSI_SELL_LEVEL", 70),
                    "rsi_buy_max": getattr(config, "RSI_BUY_MAX", 40),
                    "rsi_sell_min": getattr(config, "RSI_SELL_MIN", 60),
                    "min_atr": getattr(config, "MIN_ATR", 0.8),
                    "min_sl_spread": getattr(config, "MIN_SL_SPREAD_MULT", 3),
                    "strategy": "v12",
                },
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
        live = get_live_status()
        enrich_positions(live)
        in_session, session_label = session_state()
        return {
            "live": live,
            "stats": get_today_stats(),
            "paper": get_paper_book(),
            "connection": get_connection_status(),
            "session": {"open": in_session, "label": session_label},
            "trades": read_trade_events(20),
            "system": read_system_events(15),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}
