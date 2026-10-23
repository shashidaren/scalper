"""Account-level guards: the equity floor and the time-based exits.

Both are **risk controls, not alpha**. They exist to bound a tail the backtest
cannot see, and `research/risk_measure.py` prices them before they are switched
on (write-up: `docs/risk_controls_2026-10-23.md`):

* **Weekend flat** (`WEEKEND_FLAT_ENABLED`). Gold trades ~24/5, so a position
  opened on Thursday can sit through the Friday close and re-open Sunday at a
  different price. The M5 file has 15 gaps > 2h, the largest **12.2× ATR**; the
  backtester fills a stop *at* the stop, never through it, so that tail is
  invisible in every P&L number in this repo. Measured cost of closing at the
  Friday 20:00 UTC boundary: **+$5.46** over 255 trades (9 affected, 6 losers
  avoided, 3 winners cut early) - i.e. free insurance, not a give-up.
* **Hold cap** (`MAX_HOLD_MINUTES`, default 0 = off). The counterfactual is
  flat-to-noisy (4h -$31, 6h -$51, 8h +$31, 12h +$115), so it is **not** sold
  as an improvement; the weekend rule already bounds the hold at ~72h. Kept as
  a knob, default off.
* **Equity floor** (`EQUITY_FLOOR_*`). A latched kill switch on total account
  loss. At $300 the measured drawdowns ($104 = 35%) are larger than any floor
  tight enough to be useful - a 20% floor would have halted the paper book at
  trade 18 with $232.94, before it recovered to $294.35 - so the default is a
  catastrophe backstop (50% of start), *not* a drawdown control. Sizing rule
  and the numbers are in the doc; the real control is account size.

Timezone note: the window is **UTC**, while the engine's other timestamps are
written with `datetime.now()` (local). `_to_utc` treats naive values as local
and epoch integers as absolute, so this module is correct on a UTC box and on a
non-UTC one.

Pure standard library + `config`. No MT5, no pandas: `tests/test_risk_guard.py`
drives every branch.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
import logger

STATE_NAME = "equity_floor.json"


# ---------------------------------------------------------------- helpers
def _finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _to_utc(value):
    """Normalise a timestamp to an aware UTC datetime.

    Accepts an aware/naive datetime, an epoch int/float (MT5's `position.time`),
    or the engine's `"%Y-%m-%d %H:%M:%S"` strings. Naive values are local -
    that is how `paper.py` writes them - and are converted, not relabelled.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.astimezone(timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    try:
        parsed = datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(timezone.utc)


def _now_utc():
    return datetime.now(timezone.utc)


def in_weekend_window(now=None, hour=None):
    """True from Friday `hour`:00 UTC until Monday 00:00 UTC.

    The window is a *flat* rule, not an entry filter: the session filter
    already stops entries at `SESSION_END_HOUR_UTC`, so this only ever closes
    what is still open when the market goes into the weekend.
    """
    now = _to_utc(now) or _now_utc()
    hour = int(hour if hour is not None
               else getattr(config, "WEEKEND_FLAT_HOUR_UTC", 20))
    weekday = now.weekday()          # Mon=0 .. Sun=6
    if weekday == 4:                 # Friday
        return now.hour >= hour
    return weekday in (5, 6)         # Saturday, Sunday


def weekend_flat_enabled():
    return bool(getattr(config, "WEEKEND_FLAT_ENABLED", True))


def hold_limit_minutes():
    try:
        return float(getattr(config, "MAX_HOLD_MINUTES", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def held_minutes(opened_at, now=None):
    """Minutes since `opened_at`, or None when it cannot be parsed."""
    opened = _to_utc(opened_at)
    if opened is None:
        return None
    return ((_to_utc(now) or _now_utc()) - opened).total_seconds() / 60.0


def due_exit(opened_at, now=None, max_hold_minutes=None, cfg=config):
    """Reason this position must be closed now: "WEEKEND", "TIME" or None.

    Weekend wins over the hold cap: it is the harder constraint and the one
    that is not modelled anywhere else. `max_hold_minutes=None` reads
    `config.MAX_HOLD_MINUTES`; the caller can pass a per-book override (the
    paper account has one).
    """
    now_utc = _to_utc(now) or _now_utc()
    if weekend_flat_enabled() and in_weekend_window(
            now_utc, getattr(cfg, "WEEKEND_FLAT_HOUR_UTC", 20)):
        return "WEEKEND"
    limit = hold_limit_minutes() if max_hold_minutes is None else max_hold_minutes
    try:
        limit = float(limit or 0)
    except (TypeError, ValueError):
        limit = 0.0
    if limit > 0:
        minutes = held_minutes(opened_at, now_utc)
        if minutes is not None and minutes >= limit:
            return "TIME"
    return None


def next_weekend_boundary(now=None, hour=None):
    """The next Friday `hour`:00 UTC - used for log lines and diagnostics."""
    now_utc = _to_utc(now) or _now_utc()
    hour = int(hour if hour is not None
               else getattr(config, "WEEKEND_FLAT_HOUR_UTC", 20))
    days = (4 - now_utc.weekday()) % 7
    boundary = (now_utc + timedelta(days=days)).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    if boundary <= now_utc:
        boundary += timedelta(days=7)
    return boundary


# ------------------------------------------------------------ equity floor
class EquityFloor:
    """Latched total-loss kill switch, measured on account equity.

    Two references:

    * `"start"` (default) - `start * (1 - pct/100)`. Predictable, and it does
      not creep up as the account grows.
    * `"peak"` - `peak * (1 - pct/100)`. A trailing floor; it protects gains but
      gets progressively tighter as the account makes new highs.

    The floor **latches**: once tripped it stays tripped, because a floor that
    un-trips as soon as equity bounces is a floor that keeps re-entering a
    broken book. Reset it deliberately with
    `python risk_guard.py --reset` (or delete `logs/equity_floor.json`).

    A non-finite or non-positive equity reading is ignored rather than latched:
    a broker hiccup that reports 0 must not halt the book for good.
    """

    def __init__(self, state_file=None, log=None):
        self.state_file = Path(state_file) if state_file is not None else (
            Path(getattr(config, "LOG_DIR", logger.LOG_DIR)) / STATE_NAME)
        self._log = log or logger.log_system
        self.start = None
        self.peak = None
        self.halted_at = None
        self.halt_equity = None
        self._load()

    # -- config
    @property
    def enabled(self):
        return bool(getattr(config, "EQUITY_FLOOR_ENABLED", True))

    @property
    def mode(self):
        mode = str(getattr(config, "EQUITY_FLOOR_MODE", "start")).lower()
        return mode if mode in ("start", "peak") else "start"

    @property
    def pct(self):
        try:
            return max(0.0, float(getattr(config, "EQUITY_FLOOR_PCT", 50.0)))
        except (TypeError, ValueError):
            return 0.0

    # -- persistence
    def _load(self):
        try:
            if not self.state_file.exists():
                return
            data = json.loads(self.state_file.read_text())
            if not isinstance(data, dict):
                return
            for key in ("start", "peak", "halt_equity"):
                value = data.get(key)
                if _finite(value) and float(value) > 0:
                    setattr(self, key, float(value))
            self.halted_at = data.get("halted_at") or None
        except Exception as e:
            self._log("WARNING", f"[RISK] unreadable {self.state_file} ({e}) - "
                                  f"the equity floor restarts from the current equity")

    def _save(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_name(self.state_file.name + ".tmp")
            with open(tmp, "w") as f:
                json.dump({"start": self.start, "peak": self.peak,
                           "halted_at": self.halted_at,
                           "halt_equity": self.halt_equity,
                           "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                          f, indent=2)
            tmp.replace(self.state_file)
        except Exception as e:
            self._log("WARNING", f"[RISK] could not persist {self.state_file}: {e}")

    # -- api
    def observe(self, equity):
        """Feed the current equity. Sets `start` on first sight, tracks `peak`."""
        if not _finite(equity) or float(equity) <= 0:
            return
        equity = float(equity)
        changed = False
        if self.start is None:
            self.start = equity
            changed = True
        if self.peak is None or equity > self.peak:
            self.peak = equity
            changed = True
        if changed:
            self._save()
        self._check(equity)

    def floor_value(self):
        if not self.enabled:
            return None
        reference = self.start if self.mode == "start" else self.peak
        if reference is None:
            return None
        return reference * (1.0 - self.pct / 100.0)

    def _check(self, equity):
        if self.halted_at is not None or not self.enabled:
            return
        floor = self.floor_value()
        if floor is not None and equity <= floor:
            self.halted_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.halt_equity = equity
            self._save()
            self._log("ERROR",
                      f"[RISK] EQUITY FLOOR HIT: equity ${equity:.2f} <= ${floor:.2f} "
                      f"({self.pct:g}% of {self.mode} ${(self.start if self.mode == 'start' else self.peak):.2f}) "
                      f"- new entries HALTED (latched). Open positions keep their stops. "
                      f"Reset with: python risk_guard.py --reset")

    def blocked(self, equity=None):
        """(blocked, reason). Latched once tripped, even if equity recovers."""
        if equity is not None:
            self.observe(equity)
        if not self.enabled:
            return False, ""
        if self.halted_at is not None:
            return True, (f"equity floor {self.pct:g}% of {self.mode} was hit at "
                          f"${(self.halt_equity or 0):.2f} on {self.halted_at}")
        return False, ""

    def status(self):
        floor = self.floor_value()
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "pct": self.pct,
            "start": round(self.start, 2) if self.start is not None else None,
            "peak": round(self.peak, 2) if self.peak is not None else None,
            "floor": round(floor, 2) if floor is not None else None,
            "halted_at": self.halted_at,
        }


if __name__ == "__main__":
    import sys
    floor = EquityFloor()
    if "--reset" in sys.argv:
        floor.state_file.unlink(missing_ok=True)
        print(f"Equity floor cleared ({floor.state_file})")
    else:
        print(json.dumps(floor.status(), indent=2))
