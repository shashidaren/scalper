import json
from datetime import datetime, date
from pathlib import Path

# Anchor logs to the repository directory (not the process CWD) so logs are
# always in <repo>/logs no matter where the bot is started from.
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

TRADES_FILE = LOG_DIR / "trades.jsonl"
SYSTEM_FILE = LOG_DIR / "system.jsonl"
DAILY_STATS_FILE = LOG_DIR / "daily_stats.json"
CONNECTION_STATUS_FILE = LOG_DIR / "connection_status.json"
LIVE_STATUS_FILE = LOG_DIR / "live_status.json"


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today():
    return date.today().isoformat()


def _empty_stats():
    return {
        "date": _today(),
        "pnl": 0.0,
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "consecutive_losses": 0,
    }


def log_system(level: str, message: str):
    entry = {
        "time": _now(),
        "level": level.upper(),
        "message": message
    }
    print(f"[{entry['time']}] [{entry['level']}] {message}", flush=True)
    with open(SYSTEM_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def log_trade(event: str, data: dict):
    entry = {
        "time": _now(),
        "event": event,
        **data
    }
    print(f"[{entry['time']}] TRADE {event.upper()}: {data}", flush=True)
    with open(TRADES_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


def get_today_stats():
    if not DAILY_STATS_FILE.exists():
        return _empty_stats()

    with open(DAILY_STATS_FILE) as f:
        stats = json.load(f)

    if stats.get("date") != _today():
        stats = _empty_stats()
        save_daily_stats(stats)
    else:
        stats.setdefault("consecutive_losses", 0)

    return stats


def save_daily_stats(stats: dict):
    with open(DAILY_STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def update_daily_pnl(pnl: float, is_win: bool):
    stats = get_today_stats()
    stats["pnl"] += pnl
    stats["trades"] += 1
    if is_win:
        stats["wins"] += 1
        stats["consecutive_losses"] = 0
    else:
        stats["losses"] += 1
        stats["consecutive_losses"] = int(stats.get("consecutive_losses", 0)) + 1
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
    default = {
        "connected": False,
        "reconnect_count": 0,
        "connected_since": None,
        "last_tick_time": None,
        "last_error": None,
        "uptime_seconds": 0,
        "updated_at": None
    }
    if not CONNECTION_STATUS_FILE.exists():
        return default
    try:
        data = json.loads(CONNECTION_STATUS_FILE.read_text())
        for k, v in default.items():
            if k not in data:
                data[k] = v
        return data
    except Exception:
        return default


def update_live_status(
    balance: float = 0.0,
    equity: float = 0.0,
    margin_free: float = 0.0,
    bid: float = 0.0,
    ask: float = 0.0,
    spread: int = 0,
    positions: list = None,
    connected: bool = True,
    error: str = None,
    mode: str = None
):
    """Write full live market + account snapshot for the dashboard."""
    status = {
        "connected": connected,
        "error": error,
        "balance": balance,
        "equity": equity,
        "margin_free": margin_free,
        "bid": bid,
        "ask": ask,
        "spread": spread,
        "positions": positions or [],
        "mode": mode,
        "updated_at": _now()
    }
    with open(LIVE_STATUS_FILE, "w") as f:
        json.dump(status, f, indent=2)
    return status


def get_live_status() -> dict:
    default = {
        "connected": False,
        "error": "No data yet",
        "balance": 0.0,
        "equity": 0.0,
        "margin_free": 0.0,
        "bid": 0.0,
        "ask": 0.0,
        "spread": 0,
        "positions": [],
        "mode": None,
        "updated_at": None
    }
    if not LIVE_STATUS_FILE.exists():
        return default
    try:
        data = json.loads(LIVE_STATUS_FILE.read_text())
        for k, v in default.items():
            if k not in data:
                data[k] = v
        return data
    except Exception:
        return default
