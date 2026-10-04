"""Portfolio-level risk manager for hybrid shared/isolated mode.

In ACCOUNT_MODE=shared (one XM login, one equity pool) the per-instance
daily loss / max-trades gates are insufficient — the account can be
-2× gate and both bots still enter (btc/HANDOFF.md §8 risk 5). This module
provides a combined gate that both bots check every loop.

In ACCOUNT_MODE=isolated (two logins, two containers) the per-account gates
are authoritative; the portfolio gate becomes advisory (can be disabled).

No new systemd service is needed — both bots import this library and read/write
a single file under the repo logs dir (logs/portfolio.json) with advisory locking.

File layout:
  logs/daily_stats.json          — gold per-instance stats (logger.DAILY_STATS_FILE)
  btc/logs/daily_stats.json      — btc per-instance stats
  logs/portfolio.json            — combined view + blocked flag (written by this module)
  logs/KILL_SWITCH               — gold per-instance kill
  btc/logs/KILL_SWITCH           — btc per-instance kill
  logs/portfolio_KILL_SWITCH     — portfolio-level kill (optional, touching it blocks both)

Usage in run.py:
    from portfolio import portfolio_blocked, portfolio_state
    blocked, reason = portfolio_blocked()
    if blocked:
        log_system("WARNING", f"PORTFOLIO GATE blocked: {reason}")
        time.sleep(300); continue
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Tuple, Dict, Any

import config as gold_config

# Lazy import btc config only when needed to avoid sys.modules hack side-effects
def _btc_config():
    try:
        from pathlib import Path as _P
        import importlib.util
        p = _P(__file__).resolve().parent / "btc" / "config.py"
        if not p.exists():
            return None
        spec = importlib.util.spec_from_file_location("_btc_cfg", str(p))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    except Exception:
        return None

# Repo layout — must match logger.BASE_DIR
BASE_DIR = Path(__file__).resolve().parent
GOLD_LOG_DIR = BASE_DIR / "logs"
BTC_LOG_DIR = BASE_DIR / "btc" / "logs"
PORTFOLIO_FILE = GOLD_LOG_DIR / "portfolio.json"
PORTFOLIO_KILL = GOLD_LOG_DIR / "portfolio_KILL_SWITCH"

def _today() -> str:
    return date.today().isoformat()

def _read_stats(log_dir: Path) -> Dict[str, Any]:
    f = log_dir / "daily_stats.json"
    if not f.exists():
        return {"date": _today(), "pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
    try:
        data = json.loads(f.read_text())
        if data.get("date") != _today():
            return {"date": _today(), "pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}
        # normalize keys
        return {
            "date": data.get("date", _today()),
            "pnl": float(data.get("pnl", 0.0)),
            "trades": int(data.get("trades", 0)),
            "wins": int(data.get("wins", 0)),
            "losses": int(data.get("losses", 0)),
        }
    except Exception:
        return {"date": _today(), "pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}

def _account_mode() -> str:
    # Priority: env var > gold config > "shared"
    env = os.getenv("ACCOUNT_MODE", "").strip().lower()
    if env in ("shared", "isolated"):
        return env
    # allow config.ACCOUNT_MODE if someone sets it
    cfg_val = getattr(gold_config, "ACCOUNT_MODE", None)
    if isinstance(cfg_val, str) and cfg_val.lower() in ("shared", "isolated"):
        return cfg_val.lower()
    return "shared"

def _portfolio_limits() -> Tuple[float, int]:
    """Return (max_daily_loss, max_trades) for portfolio gate.

    In shared mode the combined equity is at risk, so the portfolio gate must be
    explicit — summing the per-instance gates naively (30+8=38) is a starting point,
    re-derived from combined backtest 99th percentile. Both instances should agree
    on the same numbers, so read from gold config with btc fallback.
    """
    # New keys — if absent, derive from per-instance values
    # GOLD config is authority when shared
    p_loss = getattr(gold_config, "PORTFOLIO_MAX_DAILY_LOSS", None)
    p_trades = getattr(gold_config, "PORTFOLIO_MAX_TRADES_PER_DAY", None)
    if p_loss is not None and p_trades is not None:
        return float(p_loss), int(p_trades)
    # Derive: gold 30 + btc 8 = 38, trades 15+15=30 but cap to 25 as per design doc
    # Check btc config for its max values if available
    btc = _btc_config()
    gold_loss = float(getattr(gold_config, "MAX_DAILY_LOSS", 30.0))
    gold_trades = int(getattr(gold_config, "MAX_TRADES_PER_DAY", 15))
    if btc is not None:
        btc_loss = float(getattr(btc, "MAX_DAILY_LOSS", 8.0))
        btc_trades = int(getattr(btc, "MAX_TRADES_PER_DAY", 15))
    else:
        btc_loss, btc_trades = 8.0, 15
    # Design doc §7: portfolio 35-40 / 25; use sum as default but allow override
    loss = float(p_loss) if p_loss is not None else round(gold_loss + btc_loss, 2)
    trades = int(p_trades) if p_trades is not None else min(gold_trades + btc_trades, 25)
    return loss, trades

def portfolio_state() -> Dict[str, Any]:
    """Compute combined portfolio view (does not decide blocking)."""
    gold = _read_stats(GOLD_LOG_DIR)
    btc = _read_stats(BTC_LOG_DIR)
    # Only combine if same date; if one rolled over, its pnl is 0
    combined_pnl = float(gold.get("pnl", 0.0) + btc.get("pnl", 0.0))
    combined_trades = int(gold.get("trades", 0) + btc.get("trades", 0))
    combined_wins = int(gold.get("wins", 0) + btc.get("wins", 0))
    combined_losses = int(gold.get("losses", 0) + btc.get("losses", 0))
    mode = _account_mode()
    max_loss, max_trades = _portfolio_limits()
    blocked, reason = portfolio_blocked_cached(gold, btc, mode, max_loss, max_trades)
    return {
        "date": _today(),
        "mode": mode,
        "pnl": round(combined_pnl, 2),
        "trades": combined_trades,
        "wins": combined_wins,
        "losses": combined_losses,
        "limits": {"max_daily_loss": max_loss, "max_trades": max_trades},
        "blocked": blocked,
        "block_reason": reason,
        "per_instance": {
            "gold": gold,
            "btc": btc,
        },
        "updated_at": _today(),
    }

def _portfolio_blocked_logic(gold: Dict, btc: Dict, mode: str, max_loss: float, max_trades: int) -> Tuple[bool, str]:
    # Portfolio kill file overrides everything
    if PORTFOLIO_KILL.exists():
        return True, f"portfolio_KILL_SWITCH present ({PORTFOLIO_KILL})"
    # Also respect per-instance KILL_SWITCH as portfolio-visible
    # (run.py still checks per-instance separately; this is for the banner)
    # Isolated mode: no combined gate (advisory only) — return not blocked
    # But we still surface the combined numbers; caller can decide to enforce or not.
    # For now, in isolated mode we do NOT block on combined pnl/trades.
    if mode == "isolated":
        return False, ""
    # Shared mode: enforce combined limits
    pnl = float(gold.get("pnl", 0.0) + btc.get("pnl", 0.0))
    trades = int(gold.get("trades", 0) + btc.get("trades", 0))
    if pnl <= -float(max_loss):
        return True, f"combined daily loss ${pnl:.2f} <= -${max_loss:.2f}"
    if trades >= int(max_trades):
        return True, f"combined trades {trades} >= {max_trades}"
    return False, ""

def portfolio_blocked_cached(gold=None, btc=None, mode=None, max_loss=None, max_trades=None) -> Tuple[bool, str]:
    if gold is None:
        gold = _read_stats(GOLD_LOG_DIR)
    if btc is None:
        btc = _read_stats(BTC_LOG_DIR)
    if mode is None:
        mode = _account_mode()
    if max_loss is None or max_trades is None:
        ml, mt = _portfolio_limits()
        if max_loss is None:
            max_loss = ml
        if max_trades is None:
            max_trades = mt
    return _portfolio_blocked_logic(gold, btc, mode, max_loss, max_trades)

def portfolio_blocked() -> Tuple[bool, str]:
    """Public API: is new-entry blocked by portfolio gate? Returns (blocked, reason)."""
    gold = _read_stats(GOLD_LOG_DIR)
    btc = _read_stats(BTC_LOG_DIR)
    mode = _account_mode()
    max_loss, max_trades = _portfolio_limits()
    blocked, reason = _portfolio_blocked_logic(gold, btc, mode, max_loss, max_trades)
    # Persist combined view for dashboards (best-effort, with lock)
    try:
        _write_portfolio_file(gold, btc, mode, max_loss, max_trades, blocked, reason)
    except Exception:
        pass
    return blocked, reason

def _write_portfolio_file(gold, btc, mode, max_loss, max_trades, blocked, reason):
    GOLD_LOG_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "date": _today(),
        "mode": mode,
        "pnl": round(float(gold.get("pnl",0)+btc.get("pnl",0)),2),
        "trades": int(gold.get("trades",0)+btc.get("trades",0)),
        "wins": int(gold.get("wins",0)+btc.get("wins",0)),
        "losses": int(gold.get("losses",0)+btc.get("losses",0)),
        "limits": {"max_daily_loss": max_loss, "max_trades": max_trades},
        "blocked": blocked,
        "block_reason": reason,
        "per_instance": {"gold": gold, "btc": btc},
        "updated_at": date.today().isoformat(),
    }
    # atomic write
    tmp = PORTFOLIO_FILE.with_suffix(".tmp")
    try:
        # Use fcntl advisory lock if available
        import fcntl
        with open(tmp, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(data, f, indent=2)
            f.flush()
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except:
                pass
        tmp.replace(PORTFOLIO_FILE)
    except ImportError:
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(PORTFOLIO_FILE)
    except Exception:
        try:
            PORTFOLIO_FILE.write_text(json.dumps(data, indent=2))
        except:
            pass

def get_portfolio_state() -> Dict[str, Any]:
    """Read last persisted portfolio.json, or compute live if missing/stale."""
    if PORTFOLIO_FILE.exists():
        try:
            data = json.loads(PORTFOLIO_FILE.read_text())
            if data.get("date") == _today():
                return data
        except Exception:
            pass
    # fallback to live computation
    return portfolio_state()

# CLI for manual check
if __name__ == "__main__":
    import sys
    blocked, reason = portfolio_blocked()
    state = get_portfolio_state()
    print(json.dumps(state, indent=2))
    if blocked:
        print(f"\nBLOCKED: {reason}")
        sys.exit(2)
    else:
        print("\nOK — portfolio gate not blocking")
