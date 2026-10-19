"""Paper (FORWARD_TEST) account: simulate orders on real MT5 ticks.

Ported from the gold-trading-bot repo's FORWARD_TEST approach:
  * simulated balance ledger, restored from a crash-safe state file
  * breakeven ratchet (BE_TRIGGER_R): SL moves to entry once +<trigger>R
  * pessimistic exit resolution: if SL and TP are both touched in the
    same tick, the SL fill is assumed
  * closed trades update the daily stats, so the existing risk gates
    (max trades/day, daily loss limit) apply to paper trading too

No orders are ever sent to MT5 in this mode.

Safety hardening ported from gold-trading-bot (2026-10-20, see
docs/port_assessment_2026-10-20.md):
  * invalid / non-finite / zero position geometry is never booked as P&L
    (gold's 2026-10-19 accounting incident: 20 rows with blank entry time and
    zero take-profit booked -$58,544.65 of phantom money);
  * a persisted position that fails that check is moved aside instead of being
    trusted after a restart;
  * the state file is written atomically, so a crash mid-write cannot leave a
    truncated ledger.
"""
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import config
from logger import LOG_DIR, log_system, log_trade, update_daily_pnl

# Module-level default. Tests (btc/strategy_btc_test.py) patch this attribute,
# so PaperAccount resolves it at construction time, never at import time.
STATE_FILE = LOG_DIR / "paper_account.json"

# Contract economics come from config so a second instance (btc/config.py) can
# use its own instrument: XAU/USD is 1.00 lot = 100 oz (price_diff * vol * 100);
# BTCUSD is 1.00 lot = 1 BTC (price_diff * vol * 1). Defaults preserve gold.
CONTRACT_SIZE = float(getattr(config, "CONTRACT_SIZE", 100.0))
PRICE_DIGITS = int(getattr(config, "PRICE_DIGITS", 2))

_BE_UNSET = object()          # sentinel: resolve the BE trigger from config
_MAX_HOLD_UNSET = object()    # sentinel: resolve the time stop from config


# --------------------------------------------------------------------------- #
# Geometry validation. A position is only allowed to move money if every
# number it is built from is finite and positive; otherwise the trade is
# refused and the ledger stays untouched.
# --------------------------------------------------------------------------- #
def _finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _positive(x):
    return _finite(x) and float(x) > 0.0


def _int(x, default=0):
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def valid_position(p):
    """True when `p` is a position whose geometry can be booked safely.

    tp is allowed to be None (the donchian / no-TP shape); it is not allowed to
    be 0, NaN or negative, because `bid >= tp` would then fire on the very next
    tick (gold 2026-10-19: zero-target TPs booked phantom P&L).
    """
    if not isinstance(p, dict):
        return False
    if p.get("side") not in ("BUY", "SELL"):
        return False
    for key in ("entry", "sl", "sl_dist", "volume"):
        if not _positive(p.get(key)):
            return False
    tp = p.get("tp")
    if tp is not None and not _positive(tp):
        return False
    return True


class PaperAccount:
    def __init__(self, be_trigger_r=_BE_UNSET, state_file=None,
                 max_hold_minutes=_MAX_HOLD_UNSET):
        """`be_trigger_r` lets a strategy force the breakeven ratchet to a
        fixed value (None = off) for its book; unset = config.BE_TRIGGER_R,
        which is what gold has always done.

        `state_file` defaults to the module-level STATE_FILE (so a test can
        patch it, and btc/config.py can point LOG_DIR at its own book).
        `max_hold_minutes` unset = config.MAX_HOLD_MINUTES (0 = disabled).
        """
        self.balance = float(getattr(config, "SIM_START_BALANCE", 300.0))
        self.position = None
        self.closed = 0
        self.wins = 0
        self.losses = 0
        self.time_exits = 0
        self.state_file = Path(state_file) if state_file is not None else Path(STATE_FILE)
        self._be_override = be_trigger_r
        self._max_hold_override = max_hold_minutes
        self._load()

    def _be_trigger(self):
        if self._be_override is not _BE_UNSET:
            return self._be_override
        return getattr(config, "BE_TRIGGER_R", 0.75)

    def _max_hold(self):
        if self._max_hold_override is not _MAX_HOLD_UNSET:
            return self._max_hold_override or 0
        return float(getattr(config, "MAX_HOLD_MINUTES", 0) or 0)

    # ------------------------------------------------ persistence
    def _quarantine(self, why):
        """Move a suspect state file aside before ignoring it.

        Never deleted: the repair tool (tools/repair_phantom_ledger.py) and a
        human both need the original evidence.
        """
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            bad = self.state_file.with_name(f"{self.state_file.name}.invalid-{stamp}")
            self.state_file.replace(bad)
            log_system("ERROR", f"[PAPER] State file rejected ({why}) - moved to {bad}")
        except Exception as e:                     # never crash the engine here
            log_system("ERROR", f"[PAPER] State file rejected ({why}); could not quarantine it: {e}")

    def _load(self):
        path = self.state_file
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict):
                raise ValueError("state file is not a JSON object")
        except Exception as e:
            self._quarantine(f"unreadable state file: {e}")
            return

        balance = data.get("balance", self.balance)
        if _finite(balance):
            # A finite negative or zero balance is kept honestly - hiding it
            # would make the book look healthier than it is.
            self.balance = float(balance)
        else:
            log_system("ERROR",
                f"[PAPER] Non-finite balance {balance!r} in {path} - starting from "
                f"SIM_START_BALANCE. Reconcile with tools/repair_phantom_ledger.py.")

        pos = data.get("position")
        if pos is not None and not valid_position(pos):
            self._quarantine(f"invalid open-position geometry: {pos!r}")
            pos = None
        self.position = pos

        self.closed = _int(data.get("closed", 0))
        self.wins = _int(data.get("wins", 0))
        self.losses = _int(data.get("losses", 0))
        self.time_exits = _int(data.get("time_exits", 0))

    def save(self):
        """Atomic write: a crash mid-save cannot truncate the ledger."""
        path = Path(self.state_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w") as f:
            json.dump({
                "balance": round(self.balance, 2),
                "position": self.position,
                "closed": self.closed,
                "wins": self.wins,
                "losses": self.losses,
                "time_exits": self.time_exits,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }, f, indent=2)
        tmp.replace(path)

    def reset(self):
        self.balance = float(getattr(config, "SIM_START_BALANCE", 300.0))
        self.position = None
        self.closed = self.wins = self.losses = self.time_exits = 0
        self.save()

    # ------------------------------------------------ trading
    def has_position(self):
        return self.position is not None

    def open(self, side, price, sl_dist, tp_dist, volume=None):
        """Open a simulated position. Returns the position dict or None."""
        if self.position:
            return None
        if side not in ("BUY", "SELL"):
            log_system("ERROR", f"[PAPER] Entry refused: unknown side {side!r}")
            return None
        if not _positive(price) or not _positive(sl_dist):
            log_system("ERROR",
                f"[PAPER] Entry refused: invalid geometry "
                f"price={price!r} sl_dist={sl_dist!r}")
            return None
        price = float(price)
        sl_dist = float(sl_dist)
        tp_dist = float(tp_dist or 0.0)
        if tp_dist and not _positive(tp_dist):
            log_system("ERROR", f"[PAPER] Entry refused: invalid tp_dist={tp_dist!r}")
            return None
        volume = float(volume if volume is not None else config.LOT_SIZE)
        if not _positive(volume):
            log_system("ERROR", f"[PAPER] Entry refused: invalid volume={volume!r}")
            return None
        # tp_dist <= 0 means NO take-profit (the MT5 tp=0 convention): the
        # breakout family exits on its opposite channel / time stop instead.
        # (With tp == entry a BUY would "hit TP" on the very next tick.)
        has_tp = tp_dist > 0
        if side == "BUY":
            sl = round(price - sl_dist, PRICE_DIGITS)
            tp = round(price + tp_dist, PRICE_DIGITS) if has_tp else None
        else:
            sl = round(price + sl_dist, PRICE_DIGITS)
            tp = round(price - tp_dist, PRICE_DIGITS) if has_tp else None
        self.position = {
            "side": side,
            "entry": price,
            "sl": sl,
            "tp": tp,
            "sl_dist": sl_dist,
            "tp_dist": tp_dist,
            "volume": volume,
            "be_armed": False,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.save()
        return self.position

    def _pnl(self, exit_price):
        p = self.position
        diff = (exit_price - p["entry"]) if p["side"] == "BUY" else (p["entry"] - exit_price)
        return diff * p["volume"] * CONTRACT_SIZE

    def _held_minutes(self, now=None):
        """Minutes since the position was opened, or None if unparseable."""
        p = self.position
        if not p or not p.get("time"):
            return None
        try:
            opened = datetime.strptime(p["time"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return None
        return ((now or datetime.now()) - opened).total_seconds() / 60.0

    def on_tick(self, bid, ask, now=None):
        """Resolve the open simulated position against live ticks.

        Returns a close-info dict when the position closed, else None.
        """
        p = self.position
        if not p:
            return None
        if not _positive(bid) or not _positive(ask):
            log_system("ERROR",
                f"[PAPER] Invalid quote ignored bid={bid!r} ask={ask!r} - position kept open")
            return None
        if not valid_position(p):
            log_system("ERROR",
                "[PAPER] Open position has invalid geometry - refusing to book P&L. "
                "Run tools/repair_phantom_ledger.py before resuming entries.")
            return None
        exit_price = bid if p["side"] == "BUY" else ask

        # Breakeven ratchet: once +BE_TRIGGER_R, move SL to entry
        # (a strategy can force it off via the constructor override)
        be_r = self._be_trigger()
        if be_r and not p["be_armed"] and p["sl_dist"] > 0:
            fav = (exit_price - p["entry"]) if p["side"] == "BUY" else (p["entry"] - exit_price)
            if fav >= be_r * p["sl_dist"]:
                p["sl"] = p["entry"]
                p["be_armed"] = True
                self.save()

        if p["side"] == "BUY":
            hit_sl = bid <= p["sl"]
            hit_tp = p["tp"] is not None and bid >= p["tp"]
        else:
            hit_sl = ask >= p["sl"]
            hit_tp = p["tp"] is not None and ask <= p["tp"]

        if hit_sl and hit_tp:
            return self.close(p["sl"], "BE" if p["be_armed"] else "SL")  # pessimistic
        if hit_sl:
            return self.close(p["sl"], "BE" if p["be_armed"] else "SL")
        if hit_tp:
            return self.close(p["tp"], "TP")

        # Time stop last, so a simultaneous price exit always wins.
        max_hold = self._max_hold()
        if max_hold and max_hold > 0:
            held = self._held_minutes(now)
            if held is not None and held >= max_hold:
                return self.close(exit_price, "TIME")
        return None

    def close(self, exit_price, reason):
        p = self.position
        if not p:
            return None
        if not _positive(exit_price):
            log_system("ERROR",
                f"[PAPER] Refusing to close ({reason}): invalid exit price {exit_price!r}")
            return None
        profit = self._pnl(float(exit_price))
        if not _finite(profit):
            log_system("ERROR",
                f"[PAPER] Refusing to book non-finite P&L ({reason}) - position kept open")
            return None
        profit = round(profit, 2)
        new_balance = round(self.balance + profit, 2)
        if not _finite(new_balance):
            log_system("ERROR",
                f"[PAPER] Refusing to book P&L ${profit:+.2f}: balance would become "
                f"{new_balance!r}")
            return None

        is_win = profit > 0
        self.balance = new_balance
        self.closed += 1
        if reason == "TIME":
            # Neutral bucket (gold's convention): own counter, P&L-signed into
            # the balance, excluded from the win/loss tally.
            self.time_exits += 1
        elif is_win:
            self.wins += 1
        else:
            self.losses += 1
        self.position = None
        self.save()
        # Daily counters still see the trade (it consumed a slot and moved
        # money); only the win/loss *tally above* treats TIME as neutral.
        update_daily_pnl(profit, is_win)
        log_trade("SIM_EXIT", {
            "side": p["side"],
            "entry": p["entry"],
            "exit": float(exit_price),
            "reason": reason,
            "profit": profit,
            "balance_after": self.balance,
        })
        return {"reason": reason, "profit": profit, "balance": self.balance}

    def equity(self, bid, ask):
        if not self.position:
            return round(self.balance, 2)
        if not _positive(bid) or not _positive(ask) or not valid_position(self.position):
            return round(self.balance, 2)
        return round(self.balance + self._pnl(bid if self.position["side"] == "BUY" else ask), 2)

    def snapshot_position(self):
        """Dashboard-shaped position list for the open simulated trade."""
        p = self.position
        if not p:
            return []
        return [{
            "ticket": "SIM",
            "type": p["side"],
            "volume": p["volume"],
            "price_open": p["entry"],
            "sl": p["sl"],
            # no-TP shapes render 0.00 on the dashboard (MT5's own convention)
            "tp": p["tp"] if p["tp"] is not None else 0.0,
            "profit": 0.0,
            "time": p["time"],
        }]


if __name__ == "__main__":
    acc = PaperAccount()
    if "--reset" in sys.argv:
        acc.reset()
        print(f"Paper account reset to ${acc.balance:.2f}")
    else:
        print(json.dumps({
            "balance": acc.balance,
            "closed": acc.closed,
            "wins": acc.wins,
            "losses": acc.losses,
            "time_exits": acc.time_exits,
            "position": acc.position,
        }, indent=2))
