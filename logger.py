import os
import json
from datetime import datetime, date
from pathlib import Path

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

TRADES_FILE = LOG_DIR / "trades.jsonl"
SYSTEM_FILE = LOG_DIR / "system.jsonl"
DAILY_STATS_FILE = LOG_DIR / "daily_stats.json"
CONNECTION_STATUS_FILE = LOG_DIR / "connection_status.json"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return date.today().isoformat()


def log_system(level: str, message: str):
    """Log system events (info, warning, error)."""
    entry = {
        "time": _now(),
        "level": level.upper(),
        "message": message
    }
    print(f"[{entry['time']}] [{entry['level']}] {message}")
    with open(SYSTEM_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def log_trade(event: str, data: dict):
    """Log trade-related events (signal, entry, exit, skip, etc.)."""
    entry = {
        "time": _now(),
        "event": event,
        **data
    }
    print(f"[{entry['time']}] TRADE {event.upper()}: {data}")
    with open(TRADES_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_today_stats():
    """Return today's realized PnL and trade count."""
    if not DAILY_STATS_FILE.exists():
        return {"date": _today(), "pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}

    with open(DAILY_STATS_FILE) as f:
        stats = json.load(f)

    if stats.get("date") != _today():
        stats = {"date": _today(), "pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
        save_daily_stats(stats)

    return stats


def save_daily_stats(stats: dict):
    with open(DAILY_STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def update_daily_pnl(pnl: float, is_win: bool):
    """Update daily stats after a trade closes."""
    stats = get_today_stats()
    stats["pnl"] += pnl
    stats["trades"] += 1
    if is_win:
        stats["wins"] += 1
    else:
        stats["losses"] += 1
    save_daily_stats(stats)
    return stats


def update_connection_status(
    connected: bool,
    reconnect_count: int = 0,
    connected_since: str = None,
    last_tick_time: str = None,
    last_error: str = None,
    uptime_seconds: int = 0
):
    """Write current MT5 connection health to a status file."""
    status = {
        "connected": connected,
        "reconnect_count": reconnect_count,
        "connected_since": connected_since,
        "last_tick_time": last_tick_time,
        "last_error": last_error,
        "uptime_seconds": uptime_seconds,
        "updated_at": _now()
    }
    with open(CONNECTION_STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)
    return status


def get_connection_status() -> dict:
    if not CONNECTION_STATUS_FILE.exists():
        return {
            "connected": False,
            "reconnect_count": 0,
            "connected_since": None,
            "last_tick_time": None,
            "last_error": None,
            "uptime_seconds": 0,
            "updated_at": None
        }
    try:
        return json.loads(CONNECTION_STATUS_FILE.read_text())
    except Exception:
        return {"connected": False, "reconnect_count": 0}
