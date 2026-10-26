"""Read-only projections for the dashboard's SCALP tab.

The dashboard is a *reader*: it never talks to MT5 and never writes a ledger.
This module turns what is already on disk into the two things a scalp tab has to
answer:

  1. **What is open right now?** — side, entry, stop, target, distance to each,
     unrealized $ and R, and how far the trade is through its own band.
  2. **How did the closed trades go?** — a win/loss record paired from the
     lifecycle events, with R multiples, streaks, drawdown and profit factor.

Nothing here is new state. The sources are exactly the ones the rest of the
system already publishes:

    logs/ledger.jsonl        compact lifecycle ledger (tools/ledger_export.py)
    logs/trades.jsonl        raw event log — read as a TAIL only, for freshness
                             between ledger exports (it is ~11k rows/day)
    logs/paper_account.json  the open simulated position, with sl_dist/be_armed
    logs/live_status.json    current bid/ask + broker-side positions (LIVE)

Pairing rule
------------
Trades are paired in file order: an entry opens a slot, the next exit closes it.
`paper.py --reset` deliberately leaves the old rows in the log, so the current
book is the last `closed` completed trades (the same rule `tools/check_data.py`
uses to chain balances). An entry with no exit at the end of the log is the
open trade — used only as a fallback when `paper_account.json` is unreadable.

LIVE caveat
-----------
`ENTRY` rows carry no fill price (only the ticket, side, volume and distances)
and `LIVE_EXIT` rows carry only the deal's price, so a LIVE trade is recorded
here with `priced=False`: P&L is real (MT5 profit+swap+commission), the entry
price and therefore the R multiple are not recoverable from the log. The tab
says so rather than inventing a number. Gold and BTC both run FORWARD_TEST, so
in practice every row is a priced paper trade.

No dependencies beyond the standard library on purpose: this must import in the
deploy gate and in a test without fastapi, pandas or rpyc.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

# Lifecycle events, mirroring tools/ledger_export.py. SIGNAL / SKIP rows are
# sampling telemetry and are ignored here.
ENTRY_EVENTS = frozenset({"SIM_ENTRY", "ENTRY"})
EXIT_EVENTS = frozenset({"SIM_EXIT", "EXIT", "LIVE_EXIT"})

# Only the tail of the raw log is read. 512 KB is ~3,500 rows, which is many
# hours of SIGNAL telemetry — far more than one open trade needs — and it keeps
# a 15-second auto-refresh from re-reading a 40 MB file.
TRADES_TAIL_BYTES = 512 * 1024

DEFAULT_LIMIT = 40
RESULT_FILTERS = ("all", "wins", "losses", "breakeven")


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _num(x):
    """A float, or None when `x` is not a finite number."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):      # NaN / inf
        return None
    return v


def _r2(x):
    """Round for display, without the `-0.0` that upsets a currency column."""
    v = round(float(x), 2)
    return 0.0 if v == 0 else v


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def _minutes_between(start, end):
    a, b = _parse_ts(start), _parse_ts(end)
    if a is None or b is None:
        return None
    delta = (b - a).total_seconds() / 60.0
    return round(delta, 1) if delta >= 0 else None


def _tail_lines(path: Path, max_bytes: int = TRADES_TAIL_BYTES):
    """Last whole lines of `path`, reading backwards rather than loading it."""
    try:
        size = path.stat().st_size
        if size == 0:
            return []
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                f.readline()          # drop the truncated first line
            data = f.read()
        return data.decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def _full_lines(path: Path):
    try:
        return path.read_text(errors="replace").splitlines()
    except OSError:
        return []


def _rows(lines):
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            # A torn final line (the engine appends while we read) is expected.
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def load_events(logs_dir):
    """Lifecycle events from the compact ledger plus a fresh tail of the raw log.

    Returns (events, info). `events` is chronological and de-duplicated: the
    ledger is a filtered copy of the raw log, so the overlap is dropped by
    canonical JSON key.
    """
    logs_dir = Path(logs_dir)
    ledger_path = logs_dir / "ledger.jsonl"
    trades_path = logs_dir / "trades.jsonl"

    seen = set()
    events = []
    info = {"ledger": False, "trades_tail": False, "sources": []}

    for key, label, lines in (
        ("ledger", "ledger.jsonl", _full_lines(ledger_path)),
        ("trades_tail", "trades.jsonl", _tail_lines(trades_path)),
    ):
        rows = _rows(lines)
        if rows:
            info[key] = True
            info["sources"].append(label)
        for row in rows:
            if row.get("event") not in ENTRY_EVENTS and row.get("event") not in EXIT_EVENTS:
                continue
            key = json.dumps(row, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            events.append(row)

    # Stable sort by timestamp: both files are chronological on their own, and
    # the ledger's copy of a row is identical to the raw log's copy.
    decorated = [(str(r.get("time") or ""), i, r) for i, r in enumerate(events)]
    decorated.sort(key=lambda t: (t[0], t[1]))
    return [r for _, _, r in decorated], info


def read_state(logs_dir):
    """`paper_account.json` as a dict, or {} when missing/unreadable."""
    path = Path(logs_dir) / "paper_account.json"
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# --------------------------------------------------------------------------- #
# pairing events into trades
# --------------------------------------------------------------------------- #
def pair_trades(events, contract_size=100.0, state_closed=None):
    """Pair entry/exit events into trade records, oldest first.

    Returns (trades, open_entry) where `open_entry` is a trailing entry that
    never closed (a dict shaped like a trade, or None).
    """
    contract = _num(contract_size) or 100.0
    trades = []
    open_t = None
    unpaired_exits = 0

    for row in events:
        event = row.get("event")
        if event in ENTRY_EVENTS:
            if open_t is not None:
                # The engine only ever holds one position. A second entry
                # without an exit means the log was truncated mid-trade; keep
                # the first one rather than inventing a close.
                continue
            open_t = {
                "seq": len(trades) + 1,
                "event": event,
                "side": row.get("side"),
                "entry_time": row.get("time"),
                "entry": _num(row.get("entry")),        # absent on LIVE ENTRY rows
                "sl_dist": _num(row.get("sl_dist")),
                "tp_dist": _num(row.get("tp_dist")),
                "volume": _num(row.get("volume")),
                "ticket": row.get("ticket"),
            }
            continue

        if event not in EXIT_EVENTS:
            continue
        if open_t is None:
            unpaired_exits += 1     # log starts mid-trade or after a reset
            continue

        # LIVE_EXIT carries MT5's raw `profit` plus `pnl` (= profit + swap +
        # commission). The ledger and the daily stats book `pnl`, so this tab
        # does too or the two records disagree by the cost.
        profit = _num(row.get("pnl"))
        if profit is None:
            profit = _num(row.get("profit"))
        exit_price = _num(row.get("exit"))
        if exit_price is None:
            exit_price = _num(row.get("price"))     # LIVE_EXIT carries `price`

        risk = None
        if open_t["entry"] is not None and open_t["sl_dist"] and open_t["volume"]:
            risk = open_t["sl_dist"] * open_t["volume"] * contract
        r_mult = None
        if risk and profit is not None:
            r_mult = round(profit / risk, 2)

        reason = row.get("reason") or ("LIVE" if event == "LIVE_EXIT" else "—")
        if reason == "TIME":
            outcome = "TIME"
        elif profit is None:
            outcome = "—"
        elif profit > 0:
            outcome = "WIN"
        elif profit < 0:
            outcome = "LOSS"
        else:
            outcome = "BE"

        trade = dict(open_t)
        trade.update({
            "event": event,
            "exit_time": row.get("time") or row.get("closed_at"),
            "exit": exit_price,
            "profit": round(profit, 2) if profit is not None else None,
            "reason": reason,
            "outcome": outcome,
            "risk": round(risk, 2) if risk is not None else None,
            "r": r_mult,
            "balance_after": _num(row.get("balance_after")),
            "hold_min": _minutes_between(open_t.get("entry_time"),
                                         row.get("time") or row.get("closed_at")),
            # paper rows carry an entry price; LIVE ENTRY rows do not.
            "priced": open_t["entry"] is not None,
        })
        trades.append(trade)
        open_t = None

    # The trailing entry, shaped like a trade with no exit yet.
    pending = None
    if open_t is not None:
        pending = dict(open_t)
        pending.update({"exit_time": None, "exit": None, "profit": None,
                        "reason": None, "outcome": "OPEN", "r": None,
                        "risk": None, "balance_after": None, "hold_min": None,
                        "priced": open_t["entry"] is not None})
        if open_t["entry"] is not None and open_t["sl_dist"] and open_t["volume"]:
            pending["risk"] = round(open_t["sl_dist"] * open_t["volume"] * contract, 2)

    # Current book only: the last `closed` completed trades (see module docstring).
    if isinstance(state_closed, int) and 0 <= state_closed <= len(trades):
        trades = trades[-state_closed:] if state_closed else []
        for i, t in enumerate(trades, 1):
            t["seq"] = i

    return trades, pending, unpaired_exits


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def summarize(trades):
    """Aggregate a chronological trade list.

    Win/loss follow the book's own convention (`paper.py`: `is_win = profit > 0`,
    TIME exits excluded from the tally), so the numbers here agree with
    `paper_account.json` and `daily_stats.json` instead of quietly disagreeing
    by the breakeven count.
    """
    stats = {
        "n": len(trades), "wins": 0, "losses": 0, "be": 0, "time_exits": 0,
        "gross_win": 0.0, "gross_loss": 0.0, "net": 0.0,
        "pf": None, "expectancy": None, "avg_win": None, "avg_loss": None,
        "avg_r": None, "sum_r": None, "best": None, "worst": None,
        "max_win_streak": 0, "max_loss_streak": 0, "current_streak": 0,
        "current_streak_kind": None, "max_drawdown": 0.0, "equity_curve": [],
        "avg_hold_min": None, "by_reason": {},
        "last10_win_rate": None, "last20_win_rate": None,
        "priced": 0, "unpriced": 0,
    }
    if not trades:
        return stats

    win_streak = loss_streak = 0
    cum = 0.0
    peak = 0.0
    holds = []
    rs = []

    for t in trades:
        profit = t.get("profit")
        reason = t.get("reason")
        stats["by_reason"][reason] = stats["by_reason"].get(reason, 0) + 1
        if t.get("priced"):
            stats["priced"] += 1
        else:
            stats["unpriced"] += 1
        if t.get("hold_min") is not None:
            holds.append(t["hold_min"])
        if t.get("r") is not None:
            rs.append(t["r"])

        if profit is None:
            continue

        if reason == "TIME":
            stats["time_exits"] += 1
        elif profit > 0:
            stats["wins"] += 1
            stats["gross_win"] += profit
        else:
            stats["losses"] += 1
            if profit == 0:
                stats["be"] += 1
            else:
                stats["gross_loss"] += -profit

        if reason != "TIME":
            if profit > 0:
                win_streak += 1
                loss_streak = 0
                stats["current_streak_kind"] = "WIN"
            else:
                loss_streak += 1
                win_streak = 0
                stats["current_streak_kind"] = "LOSS"
            stats["max_win_streak"] = max(stats["max_win_streak"], win_streak)
            stats["max_loss_streak"] = max(stats["max_loss_streak"], loss_streak)
            stats["current_streak"] = max(win_streak, loss_streak)

        cum += profit
        stats["equity_curve"].append(round(cum, 2))
        peak = max(peak, cum)
        stats["max_drawdown"] = max(stats["max_drawdown"], round(peak - cum, 2))

    stats["net"] = round(cum, 2)
    if stats["gross_loss"] > 0:
        stats["pf"] = round(stats["gross_win"] / stats["gross_loss"], 2)
    elif stats["gross_win"] > 0:
        stats["pf"] = None            # no losses: PF is undefined, not infinite
    stats["gross_win"] = round(stats["gross_win"], 2)
    stats["gross_loss"] = round(stats["gross_loss"], 2)

    decided = stats["wins"] + stats["losses"]
    if decided:
        stats["expectancy"] = round(stats["net"] / decided, 2)
    if stats["wins"]:
        stats["avg_win"] = round(stats["gross_win"] / stats["wins"], 2)
    if stats["losses"]:
        stats["avg_loss"] = round(stats["gross_loss"] / stats["losses"], 2)

    profits = [t["profit"] for t in trades if t.get("profit") is not None]
    if profits:
        stats["best"] = max(profits)
        stats["worst"] = min(profits)
    if holds:
        stats["avg_hold_min"] = round(sum(holds) / len(holds), 1)
    if rs:
        stats["sum_r"] = round(sum(rs), 2)
        stats["avg_r"] = round(sum(rs) / len(rs), 2)

    for window, key in ((10, "last10_win_rate"), (20, "last20_win_rate")):
        recent = [t for t in trades[-window:]
                  if t.get("profit") is not None and t.get("reason") != "TIME"]
        if recent:
            won = sum(1 for t in recent if t["profit"] > 0)
            stats[key] = round(100.0 * won / len(recent), 1)

    return stats


def win_rate(stats):
    decided = (stats or {}).get("wins", 0) + (stats or {}).get("losses", 0)
    if not decided:
        return None
    return round(100.0 * stats["wins"] / decided, 1)


def sparkline_points(values, width=100.0, height=30.0):
    """SVG polyline points for an equity curve, plus the zero baseline.

    Returns {} when there is nothing to draw, so the template can test for it.
    """
    vals = [v for v in (values or []) if _num(v) is not None]
    if len(vals) < 2:
        return {}
    lo, hi = min(vals), max(vals)
    lo = min(lo, 0.0)
    hi = max(hi, 0.0)
    span = hi - lo
    if span <= 0:
        return {}
    step = width / (len(vals) - 1)

    def y(v):
        return round(height - (v - lo) / span * height, 2)

    points = " ".join(f"{round(i * step, 2)},{y(v)}" for i, v in enumerate(vals))
    return {
        "points": points,
        "zero_y": y(0.0),
        "width": width,
        "height": height,
        "lo": round(lo, 2),
        "hi": round(hi, 2),
    }


# --------------------------------------------------------------------------- #
# the open trade
# --------------------------------------------------------------------------- #
def _normalise_position(position):
    """Accept either `paper_account.json`'s shape or `live_status.json`'s."""
    if not isinstance(position, dict):
        return None
    side = position.get("side") or position.get("type")
    if side not in ("BUY", "SELL"):
        return None
    entry = _num(position.get("entry"))
    if entry is None:
        entry = _num(position.get("price_open"))
    if entry is None:
        return None
    sl = _num(position.get("sl"))
    tp = _num(position.get("tp"))
    sl_dist = _num(position.get("sl_dist"))
    if sl_dist is None and sl:
        sl_dist = abs(entry - sl) or None
    tp_dist = _num(position.get("tp_dist"))
    if tp_dist is None and tp:
        tp_dist = abs(tp - entry) or None
    return {
        "side": side,
        "ticket": position.get("ticket", "SIM"),
        "entry": entry,
        "sl": sl,
        "tp": tp if (tp and tp > 0) else None,     # MT5 encodes "no TP" as 0
        "sl_dist": sl_dist,
        "tp_dist": tp_dist,
        "volume": _num(position.get("volume")),
        "be_armed": bool(position.get("be_armed")),
        "opened": position.get("time") or position.get("opened"),
    }


def position_view(position, bid=None, ask=None, contract_size=100.0,
                  digits=2, now=None):
    """Everything the 'current scalp' panel shows for one open trade."""
    pos = _normalise_position(position)
    if pos is None:
        return None

    contract = _num(contract_size) or 100.0
    digits = int(digits if isinstance(digits, int) and 0 <= digits <= 8 else 2)
    point = 10.0 ** -digits
    bid, ask = _num(bid), _num(ask)
    long_side = pos["side"] == "BUY"

    # Mark at the price the position would actually be closed at.
    mark = bid if long_side else ask
    if mark is None:
        mark = bid if bid is not None else ask

    view = dict(pos)
    view["mark"] = mark
    view["digits"] = digits
    view["live"] = mark is not None
    view["risk"] = None
    view["reward"] = None
    view["rr"] = None
    view["unrealized"] = None
    view["unrealized_r"] = None
    view["to_sl_points"] = None
    view["to_tp_points"] = None
    view["progress_pct"] = None
    view["held_min"] = _minutes_between(pos["opened"], now)

    volume = pos["volume"]
    if volume is not None and pos["sl_dist"]:
        view["risk"] = _r2(pos["sl_dist"] * volume * contract)
    if volume is not None and pos["tp_dist"]:
        view["reward"] = _r2(pos["tp_dist"] * volume * contract)
    if pos["sl_dist"] and pos["tp_dist"]:
        view["rr"] = round(pos["tp_dist"] / pos["sl_dist"], 2)

    if mark is None:
        return view

    direction = 1.0 if long_side else -1.0
    move = (mark - pos["entry"]) * direction
    if volume is not None:
        view["unrealized"] = _r2(move * volume * contract)
    if pos["sl_dist"]:
        view["unrealized_r"] = round(move / pos["sl_dist"], 2)

    if pos["sl"]:
        view["to_sl_points"] = int(round(abs(mark - pos["sl"]) / point))
    if pos["tp"]:
        view["to_tp_points"] = int(round(abs(pos["tp"] - mark) / point))

    # How far through its own stop→target band the trade has travelled. This is
    # a price-band reading, so it stays honest when the stop has been ratcheted
    # to breakeven (progress then restarts from the new stop).
    if pos["sl"] is not None and pos["tp"] is not None and pos["tp"] != pos["sl"]:
        pct = (mark - pos["sl"]) / (pos["tp"] - pos["sl"]) * 100.0
        view["progress_pct"] = round(max(0.0, min(100.0, pct)), 1)
    return view


# --------------------------------------------------------------------------- #
# assembling the whole tab
# --------------------------------------------------------------------------- #
def _stamp(now=None):
    if isinstance(now, datetime):
        return now.strftime("%Y-%m-%d %H:%M:%S")
    if now:
        return str(now)
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def build(logs_dir, contract_size=100.0, digits=2, limit=DEFAULT_LIMIT,
          result="all", live=None, now=None):
    """The dashboard's SCALP context: open trade + filtered trade record."""
    logs_dir = Path(logs_dir)
    live = live if isinstance(live, dict) else {}
    state = read_state(logs_dir)
    state_closed = state.get("closed") if isinstance(state.get("closed"), int) else None

    events, info = load_events(logs_dir)
    trades, pending, unpaired = pair_trades(events, contract_size=contract_size,
                                            state_closed=state_closed)

    # Prefer the persisted open position (it knows sl_dist / be_armed); fall
    # back to a live broker position, then to an unclosed entry in the log.
    raw_position = state.get("position")
    if not raw_position and live.get("positions"):
        raw_position = live["positions"][0]
    if not raw_position and pending:
        raw_position = pending

    position = position_view(
        raw_position,
        bid=live.get("bid"), ask=live.get("ask"),
        contract_size=contract_size, digits=digits, now=now,
    )

    stats = summarize(trades)
    stats["win_rate"] = win_rate(stats)

    result = result if result in RESULT_FILTERS else "all"
    if result == "wins":
        shown = [t for t in trades if t["outcome"] == "WIN"]
    elif result == "losses":
        shown = [t for t in trades if t["outcome"] == "LOSS"]
    elif result == "breakeven":
        shown = [t for t in trades if t["outcome"] in ("BE", "TIME")]
    else:
        shown = list(trades)

    shown = list(reversed(shown))            # newest first
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT

    filtered_stats = summarize([t for t in reversed(shown)]) if result != "all" else stats

    return {
        "available": bool(trades or position),
        "sources": info,
        "events": len(events),
        "unpaired_exits": unpaired,
        "state_closed": state_closed,
        "balance": _num(live.get("balance")) if live.get("balance") is not None
                   else _num(state.get("balance")),
        "position": position,
        "pending_entry": pending if not raw_position else None,
        "trades": shown[:limit],
        "stats": stats,
        "filtered": {"key": result, "count": len(shown), "stats": filtered_stats},
        "limit": limit,
        "sparkline": sparkline_points(stats["equity_curve"]),
        "generated": _stamp(now),
    }
