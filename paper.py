"""Paper (FORWARD_TEST) account: simulate orders on real MT5 ticks.

Ported from the gold-trading-bot repo's FORWARD_TEST approach:
  * simulated balance ledger, restored from a crash-safe state file
  * breakeven ratchet (BE_TRIGGER_R): SL moves to entry once +0.75R
  * pessimistic exit resolution: if SL and TP are both touched in the
    same tick, the SL fill is assumed
  * closed trades update the daily stats, so the existing risk gates
    (max trades/day, daily loss limit) apply to paper trading too

No orders are ever sent to MT5 in this mode.
"""
import json
import sys
from datetime import datetime

import config
from logger import LOG_DIR, log_trade, update_daily_pnl

STATE_FILE = LOG_DIR / "paper_account.json"

# XAU/USD contract: 1.00 lot = 100 oz, so profit = price_diff * volume * 100
CONTRACT_SIZE = 100.0


class PaperAccount:
    def __init__(self):
        self.balance = float(getattr(config, "SIM_START_BALANCE", 200.0))
        self.position = None
        self.closed = 0
        self.wins = 0
        self.losses = 0
        self._load()

    # ------------------------------------------------ persistence
    def _load(self):
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text())
            self.balance = float(data.get("balance", self.balance))
            self.position = data.get("position")
            self.closed = int(data.get("closed", 0))
            self.wins = int(data.get("wins", 0))
            self.losses = int(data.get("losses", 0))
        except Exception:
            pass

    def save(self):
        with open(STATE_FILE, "w") as f:
            json.dump({
                "balance": round(self.balance, 2),
                "position": self.position,
                "closed": self.closed,
                "wins": self.wins,
                "losses": self.losses,
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }, f, indent=2)

    def reset(self):
        self.balance = float(getattr(config, "SIM_START_BALANCE", 200.0))
        self.position = None
        self.closed = self.wins = self.losses = 0
        self.save()

    # ------------------------------------------------ trading
    def has_position(self):
        return self.position is not None

    def open(self, side, price, sl_dist, tp_dist, volume=None):
        """Open a simulated position. Returns the position dict or None."""
        if self.position:
            return None
        volume = float(volume if volume is not None else config.LOT_SIZE)
        price = float(price)
        sl_dist = float(sl_dist)
        tp_dist = float(tp_dist)
        if side == "BUY":
            sl, tp = round(price - sl_dist, 2), round(price + tp_dist, 2)
        else:
            sl, tp = round(price + sl_dist, 2), round(price - tp_dist, 2)
        self.position = {
            "side": side,
            "entry": float(price),
            "sl": sl,
            "tp": tp,
            "sl_dist": float(sl_dist),
            "tp_dist": float(tp_dist),
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

    def on_tick(self, bid, ask):
        """Resolve the open simulated position against live ticks.

        Returns a close-info dict when the position closed, else None.
        """
        p = self.position
        if not p:
            return None
        exit_price = bid if p["side"] == "BUY" else ask

        # Breakeven ratchet: once +BE_TRIGGER_R, move SL to entry
        be_r = getattr(config, "BE_TRIGGER_R", 0.75)
        if be_r and not p["be_armed"] and p["sl_dist"] > 0:
            fav = (exit_price - p["entry"]) if p["side"] == "BUY" else (p["entry"] - exit_price)
            if fav >= be_r * p["sl_dist"]:
                p["sl"] = p["entry"]
                p["be_armed"] = True
                self.save()

        if p["side"] == "BUY":
            hit_sl = bid <= p["sl"]
            hit_tp = bid >= p["tp"]
        else:
            hit_sl = ask >= p["sl"]
            hit_tp = ask <= p["tp"]

        if hit_sl and hit_tp:
            return self.close(p["sl"], "BE" if p["be_armed"] else "SL")  # pessimistic
        if hit_sl:
            return self.close(p["sl"], "BE" if p["be_armed"] else "SL")
        if hit_tp:
            return self.close(p["tp"], "TP")
        return None

    def close(self, exit_price, reason):
        p = self.position
        profit = round(self._pnl(exit_price), 2)
        self.balance = round(self.balance + profit, 2)
        self.closed += 1
        is_win = profit > 0
        if is_win:
            self.wins += 1
        else:
            self.losses += 1
        self.position = None
        self.save()
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
            "tp": p["tp"],
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
            "position": acc.position,
        }, indent=2))
