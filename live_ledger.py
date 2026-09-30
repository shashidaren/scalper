"""Realized-PnL tracking for LIVE mode.

In FORWARD_TEST, closes are simulated inside PaperAccount, which also
updates the daily stats that power the risk gates (daily loss limit,
max trades/day). In LIVE mode exits happen broker-side (SL/TP), so the
engine would never see them and those gates would never fire.

LiveLedger polls MT5 deal history every loop, detects new OUT deals for
our symbol + magic number, and records realized PnL
(profit + swap + commission) through the same update_daily_pnl() path
the paper account uses.

State (processed deal tickets) is persisted to logs/live_ledger.json so
a restart neither double-counts nor misses closes.
"""
import json
import time
from datetime import datetime

import config
from logger import LOG_DIR, log_system, log_trade, update_daily_pnl

STATE_FILE = LOG_DIR / "live_ledger.json"

# Re-scan this much history on every poll; dedup by deal ticket keeps it
# idempotent. An hour is far longer than any realistic gap between polls
# (15s loop) while still surviving long outages/restarts.
LOOKBACK_SECONDS = 3600
MAX_SEEN_TICKETS = 500


class LiveLedger:
    def __init__(self):
        self.last_poll_time = 0
        self.seen_tickets = []
        self._load()

    # ------------------------------------------------ persistence
    def _load(self):
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text())
            self.last_poll_time = int(data.get("last_poll_time", 0))
            self.seen_tickets = [int(t) for t in data.get("seen_tickets", [])]
        except Exception:
            pass

    def _save(self):
        STATE_FILE.write_text(json.dumps({
            "last_poll_time": self.last_poll_time,
            "seen_tickets": self.seen_tickets[-MAX_SEEN_TICKETS:],
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }, indent=2))

    # ------------------------------------------------ polling
    def poll(self, bridge):
        """Detect newly closed deals and record their realized PnL.

        Returns a list of close-info dicts recorded this poll (may be empty).
        Never raises: a history-read hiccup must not kill the engine loop.
        """
        now = int(time.time())
        try:
            deals = bridge.mt5.history_deals_get(now - LOOKBACK_SECONDS, now + 60)
        except Exception as e:
            log_system("WARNING", f"Live close detection: history_deals_get failed: {e}")
            return []
        if not deals:
            return []

        try:
            out_entries = {
                int(bridge.mt5.DEAL_ENTRY_OUT),
                int(bridge.mt5.DEAL_ENTRY_INOUT),
                int(bridge.mt5.DEAL_ENTRY_OUT_BY),
            }
            deal_type_buy = int(bridge.mt5.DEAL_TYPE_BUY)
        except Exception:
            out_entries = {1, 3, 4}  # MT5 constants: OUT, INOUT, OUT_BY
            deal_type_buy = 0

        seen = set(self.seen_tickets)
        closed = []
        for deal in deals:
            try:
                if int(deal.magic) != config.MAGIC_NUMBER:
                    continue
                if int(deal.entry) not in out_entries:
                    continue
                ticket = int(deal.ticket)
                if ticket in seen:
                    continue

                pnl = round(float(deal.profit) + float(deal.swap) + float(deal.commission), 2)
                is_win = pnl > 0
                update_daily_pnl(pnl, is_win)
                seen.add(ticket)
                self.seen_tickets.append(ticket)
                self.last_poll_time = now

                closed_at = datetime.fromtimestamp(int(deal.time)).strftime("%Y-%m-%d %H:%M:%S")
                log_trade("LIVE_EXIT", {
                    "ticket": ticket,
                    "side": "BUY" if int(deal.type) == deal_type_buy else "SELL",
                    "price": float(deal.price),
                    "volume": float(deal.volume),
                    "profit": float(deal.profit),
                    "swap": float(deal.swap),
                    "commission": float(deal.commission),
                    "pnl": pnl,
                    "closed_at": closed_at,
                })
                closed.append({"ticket": ticket, "pnl": pnl})
            except Exception as e:
                log_system("WARNING", f"Live close detection: skipping unreadable deal: {e}")
                continue

        if closed:
            self._save()
        return closed
