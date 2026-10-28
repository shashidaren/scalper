#!/usr/bin/env python3
"""
Dashboard for the Scalper bot.

Reads ONLY from status/log files written by the bot (via logger.LOG_DIR, so a
second instance such as btc/ shows its own book). Never opens its own MT5 /
RPyC connection.
"""

import json
import math
import traceback
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

import config
import scalp_view
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

# Contract economics for the SCALP tab's arithmetic ($ and R). Same keys
# paper.py uses, so the tab cannot disagree with the book about a point's worth.
CONTRACT_SIZE = float(getattr(config, "CONTRACT_SIZE", 100.0))
PRICE_DIGITS = int(getattr(config, "PRICE_DIGITS", 2))

app = FastAPI(title=DASHBOARD_TITLE, version="1.5")
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


def config_snapshot() -> dict:
    return {
        "symbol": getattr(config, "SYMBOL", "GOLD"),
        "lot_size": getattr(config, "LOT_SIZE", 0.01),
        "contract_size": getattr(config, "CONTRACT_SIZE", 100.0),
        "max_spread": getattr(config, "MAX_SPREAD_POINTS", 80),
        "max_daily_loss": getattr(config, "MAX_DAILY_LOSS", 30),
        "max_trades": getattr(config, "MAX_TRADES_PER_DAY", 15),
    }


def scalp_rules() -> dict:
    """The strategy/risk settings that shape the trade on the SCALP tab.

    Read with getattr so a second instance (btc/config.py) that has not defined
    one of these renders 'off' instead of raising on the dashboard.
    """
    session_on = bool(getattr(config, "SESSION_FILTER_ENABLED", False))
    return {
        "session": (f"{getattr(config, 'SESSION_START_HOUR_UTC', 0):02d}:00–"
                    f"{getattr(config, 'SESSION_END_HOUR_UTC', 0):02d}:00 UTC")
                   if session_on else None,
        "atr_min": getattr(config, "ATR_MIN", None),
        "tp_atr_mult": getattr(config, "TP_ATR_MULT", None),
        "be_trigger_r": getattr(config, "BE_TRIGGER_R", None),
        "max_hold_minutes": getattr(config, "MAX_HOLD_MINUTES", 0) or 0,
        "weekend_flat": bool(getattr(config, "WEEKEND_FLAT_ENABLED", False)),
        "weekend_flat_hour": getattr(config, "WEEKEND_FLAT_HOUR_UTC", 20),
        "risk_pct": getattr(config, "RISK_PCT", 0) or 0,
    }


def scalp_context(result: str = "all", limit: int = scalp_view.DEFAULT_LIMIT) -> dict:
    """Everything templates/scalp.html needs. Reads files only."""
    live = get_live_status()
    view = scalp_view.build(
        LOG_DIR,
        contract_size=CONTRACT_SIZE,
        digits=PRICE_DIGITS,
        limit=limit,
        result=result,
        live=live,
    )
    return {
        "tab": "scalp",
        "scalp": view,
        "live": live,
        "rules": scalp_rules(),
        "config": config_snapshot(),
        "title": DASHBOARD_TITLE,
        "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def error_page(e: Exception) -> HTMLResponse:
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
        status_code=200,
    )


# --- readiness tab ---------------------------------------------------------
# Forward-evidence reference counts. Gold's "~300+" is the shorthand from the
# 2026-10-23 live-readiness review (~330 trades for 80% power); it is a
# reference, never an approval countdown.
#
# BTC deliberately has NO reference count. The present BTC book runs the
# Phase-1 shape that already failed its cold-OOS gate (PF 0.75), so its trades
# are an observation feed, not a qualifying cohort. Counting them toward a
# launch number would imply an approval path that does not exist.
GOLD_REFERENCE_TRADES = 300
BTC_REFERENCE_TRADES = None


def book_kind() -> str:
    """'gold', 'btc' or 'other' for the running instance.

    Derived from SYMBOL rather than a new config key on purpose: btc/config.py
    is a runtime input for `scalper-btc-bot`, so adding a viewer-only key there
    would restart the BTC engine on deploy for no trading reason.
    """
    symbol = str(getattr(config, "SYMBOL", "GOLD") or "").upper()
    if symbol == "GOLD":
        return "gold"
    if symbol.startswith("BTC"):
        return "btc"
    return "other"


def readiness_snapshot(book: str):
    """(snapshot, warning) from this instance's published paper state.

    Read-only and fail-closed: an unreadable or nonsense state file yields
    (None, warning), so the page says "unknown" instead of implying progress.
    """
    snapshot = None
    warning = None
    try:
        data = json.loads((LOG_DIR / "paper_account.json").read_text())
        closed = data["closed"]
        balance = data["balance"]
        if (type(closed) is not int or closed < 0 or
                type(balance) not in (int, float) or not math.isfinite(balance)):
            raise ValueError("invalid book counters")
        stamp = datetime.fromisoformat(data["updated_at"])
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600
        wins = data.get("wins")
        losses = data.get("losses")
        reference = GOLD_REFERENCE_TRADES if book == "gold" else BTC_REFERENCE_TRADES
        snapshot = {
            "closed": closed,
            "balance": balance,
            "updated_at": data["updated_at"],
            "stale": age > 24 or age < 0,
            # Both are None when the state file predates the counters; the
            # template omits the line rather than printing a fake 0.
            "wins": wins if type(wins) is int else None,
            "losses": losses if type(losses) is int else None,
            # `remaining` exists only where a reference cohort does.
            "reference": reference,
            "remaining": (max(0, reference - closed)
                          if reference is not None else None),
        }
    except (OSError, ValueError, TypeError, KeyError):
        warning = "Paper snapshot unavailable or invalid. Progress is unknown, not passed."
    return snapshot, warning


def readiness_context() -> dict:
    """Planning view for the current instance; never promotes a book or writes
    trading state. Gold and BTC have separate gate documents — a gold milestone
    does not approve BTC, and vice versa."""
    book = book_kind()
    snapshot, warning = readiness_snapshot(book)
    subtitles = {
        "gold": "Gold • Evidence before capital • Planning baseline: 27 October 2026",
        "btc": "Bitcoin (BTCUSD) • Separate gates, separate evidence • Planning baseline: 28 October 2026",
        "other": "No readiness roadmap exists for this instance",
    }
    return {"tab": "readiness", "title": DASHBOARD_TITLE,
            "config": config_snapshot(), "snapshot": snapshot, "warning": warning,
            "book": book, "is_gold": book == "gold",
            # Read-only mode/connection badge for the nav; the file is
            # machine-local, so absent means "no data", never "connected".
            "live": get_live_status(),
            "subtitle": subtitles[book]}


@app.get("/readiness", response_class=HTMLResponse)
async def readiness(request: Request):
    """Per-book planning roadmap. Same route, different document (gold / BTC)."""
    try:
        return templates.TemplateResponse(
            request=request, name="readiness.html", context=readiness_context())
    except Exception as e:
        return error_page(e)


@app.get("/scalp", response_class=HTMLResponse)
async def scalp(request: Request, result: str = "all",
                limit: int = scalp_view.DEFAULT_LIMIT):
    """Current trade + the closed-trade record. Read-only, same files as `/`."""
    try:
        return templates.TemplateResponse(
            request=request, name="scalp.html", context=scalp_context(result, limit)
        )
    except Exception as e:
        return error_page(e)


@app.get("/api/scalp")
async def api_scalp(result: str = "all", limit: int = scalp_view.DEFAULT_LIMIT):
    try:
        context = scalp_context(result, limit)
        return {**context["scalp"], "rules": context["rules"],
                "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"error": str(e), "timestamp": datetime.now().isoformat()}


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
                "config": config_snapshot(),
                "tab": "overview",
                "title": DASHBOARD_TITLE,
                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    except Exception as e:
        return error_page(e)


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
