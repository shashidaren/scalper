#!/usr/bin/env python3
"""Unit tests for `scalp_view` — the dashboard's SCALP tab.

The tab is only allowed to *read*. What has to hold:

  * an entry/exit pair becomes one trade with the right outcome, R multiple and
    hold time, and the win/loss tally matches the book's own convention
    (`paper.py`: `is_win = profit > 0`, TIME exits excluded) so the tab cannot
    disagree with `paper_account.json`;
  * a `paper.py --reset` does not resurrect the previous book's trades — only
    the last `closed` pairs are the current book (same rule as check_data.py);
  * the ledger and the raw-log tail are merged without duplicating the rows
    they share;
  * a trailing entry with no exit is the open trade, and the open-trade panel
    stays arithmetic: unrealized $, unrealized R, distance to stop/target and
    band progress, including after the stop has ratcheted to breakeven;
  * LIVE rows (no fill price on `ENTRY`) are marked unpriced instead of being
    given a made-up entry.

Hermetic: every case builds its own temp book and injects bid/ask.
Run:  python3 tests/test_scalp_view.py      # exit 0 = PASS
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scalp_view  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append(bool(ok))


def book(events, state=None, trades=None, prefix="sv_"):
    """Write a throwaway logs dir. `trades` writes a raw trades.jsonl too."""
    logs = Path(tempfile.mkdtemp(prefix=prefix)) / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    if events is not None:
        with open(logs / "ledger.jsonl", "w") as f:
            for row in events:
                f.write(json.dumps(row) + "\n")
    if trades is not None:
        with open(logs / "trades.jsonl", "w") as f:
            for row in trades:
                f.write(json.dumps(row) + "\n")
    if state is not None:
        (logs / "paper_account.json").write_text(json.dumps(state))
    return logs


def entry(side="BUY", price=4000.0, sl_dist=10.0, tp_dist=25.0, volume=0.01,
          time="2026-10-20 10:00:00", event="SIM_ENTRY"):
    return {"time": time, "event": event, "side": side, "entry": price,
            "sl": price - sl_dist if side == "BUY" else price + sl_dist,
            "tp": price + tp_dist if side == "BUY" else price - tp_dist,
            "sl_dist": sl_dist, "tp_dist": tp_dist, "volume": volume}


def exit_row(price, profit, reason="TP", time="2026-10-20 11:30:00", side="BUY",
             balance_after=300.0, event="SIM_EXIT"):
    return {"time": time, "event": event, "side": side, "entry": 4000.0,
            "exit": price, "reason": reason, "profit": profit,
            "balance_after": balance_after}


def main() -> int:
    # ---------------------------------------------------------------- pairing
    print("pairing an entry with its exit")
    logs = book(
        [
            entry("BUY", 4000.0, 10.0, 25.0),
            exit_row(4025.0, 25.0, "TP", "2026-10-20 11:30:00", "BUY", 325.0),
            entry("SELL", 4050.0, 10.0, 25.0, time="2026-10-21 09:00:00"),
            exit_row(4060.0, -10.0, "SL", "2026-10-21 09:45:00", "SELL", 315.0),
            entry("BUY", 4060.0, 8.0, 20.0, time="2026-10-22 09:00:00"),
            exit_row(4060.0, 0.0, "BE", "2026-10-22 10:00:00", "BUY", 315.0),
        ],
        state={"balance": 315.0, "position": None, "closed": 3,
               "wins": 1, "losses": 2, "time_exits": 0},
    )
    view = scalp_view.build(logs, live={"bid": 4000.0, "ask": 4000.2})
    trades, stats = view["trades"], view["stats"]
    check("three trades paired", stats["n"] == 3, f"n={stats['n']}")
    check("newest first", trades[0]["outcome"] == "BE" and trades[-1]["outcome"] == "WIN",
          f"{[t['outcome'] for t in trades]}")
    check("R multiple from stop distance",
          [t["r"] for t in reversed(trades)] == [2.5, -1.0, 0.0],
          f"{[t['r'] for t in reversed(trades)]}")
    check("risk in dollars", [t["risk"] for t in reversed(trades)] == [10.0, 10.0, 8.0])
    check("hold time", trades[-1]["hold_min"] == 90.0, f"{trades[-1]['hold_min']}")
    check("book convention: BE counts as a loss, as in paper.py",
          (stats["wins"], stats["losses"], stats["be"]) == (1, 2, 1),
          f"{(stats['wins'], stats['losses'], stats['be'])}")
    check("gross figures", (stats["gross_win"], stats["gross_loss"], stats["net"])
          == (25.0, 10.0, 15.0), f"{(stats['gross_win'], stats['gross_loss'], stats['net'])}")
    check("profit factor", stats["pf"] == 2.5, f"{stats['pf']}")
    check("no position when the state file is flat", view["position"] is None)

    # ------------------------------------------------------------- the reset
    print("a paper.py --reset does not resurrect the old book")
    old = [entry("BUY", 3900.0, 10.0, 10.0), exit_row(3890.0, -10.0, "SL")]
    cur = [entry("BUY", 4000.0, 10.0, 10.0, time="2026-10-24 10:00:00"),
           exit_row(4010.0, 10.0, "TP", "2026-10-24 11:00:00")]
    logs = book(old + cur, state={"balance": 310.0, "position": None, "closed": 1,
                                 "wins": 1, "losses": 0, "time_exits": 0})
    view = scalp_view.build(logs)
    check("only the current book is shown", view["stats"]["n"] == 1,
          f"n={view['stats']['n']}")
    check("and it is the right one", view["trades"][0]["profit"] == 10.0)
    check("balance start is the reset", view["stats"]["net"] == 10.0)
    check("equity curve restarts at the book's first trade",
          view["stats"]["equity_curve"] == [10.0], f"{view['stats']['equity_curve']}")

    # ----------------------------------------------------- ledger + tail merge
    print("ledger and raw-log tail are merged without duplicates")
    shared = [entry("BUY", 4000.0, 10.0, 10.0),
              exit_row(4010.0, 10.0, "TP"),
              entry("BUY", 4020.0, 10.0, 10.0, time="2026-10-25 10:00:00")]
    logs = book(shared, trades=shared + [{"time": "2026-10-25 10:05:00",
                                          "event": "SIGNAL", "signal": "NONE"}],
                state={"balance": 310.0, "position": None, "closed": 1,
                       "wins": 1, "losses": 0, "time_exits": 0})
    view = scalp_view.build(logs)
    check("no duplicated trade", view["stats"]["n"] == 1, f"n={view['stats']['n']}")
    check("both sources reported",
          set(view["sources"]["sources"]) == {"ledger.jsonl", "trades.jsonl"},
          f"{view['sources']['sources']}")
    check("a trailing entry is the open trade (fallback)",
          view["position"] is not None and view["position"]["side"] == "BUY",
          f"{view['position'] and view['position']['side']}")

    # ------------------------------------------------------- the open position
    print("open position: unrealized, R, distances, band progress")
    pos = {"side": "BUY", "entry": 4000.0, "sl": 3990.0, "tp": 4025.0,
           "sl_dist": 10.0, "tp_dist": 25.0, "volume": 0.01, "be_armed": False,
           "time": "2026-10-26 09:00:00"}
    pv = scalp_view.position_view(pos, bid=4010.0, ask=4010.2, contract_size=100.0,
                                  digits=2, now="2026-10-26 10:00:00")
    check("mark at the bid for a long", pv["mark"] == 4010.0, f"{pv['mark']}")
    check("unrealized $", pv["unrealized"] == 10.0, f"{pv['unrealized']}")
    check("unrealized R", pv["unrealized_r"] == 1.0, f"{pv['unrealized_r']}")
    check("risk / reward / rr", (pv["risk"], pv["reward"], pv["rr"]) == (10.0, 25.0, 2.5),
          f"{(pv['risk'], pv['reward'], pv['rr'])}")
    check("distance to stop in points", pv["to_sl_points"] == 2000,
          f"{pv['to_sl_points']}")
    check("distance to target in points", pv["to_tp_points"] == 1500,
          f"{pv['to_tp_points']}")
    check("band progress is measured from the stop (20 of 35 points)",
          pv["progress_pct"] == 57.1, f"{pv['progress_pct']}")
    check("held minutes", pv["held_min"] == 60.0, f"{pv['held_min']}")

    short = {"side": "SELL", "entry": 4000.0, "sl": 4010.0, "tp": 3975.0,
             "sl_dist": 10.0, "tp_dist": 25.0, "volume": 0.01, "time": "2026-10-26 09:00:00"}
    pv = scalp_view.position_view(short, bid=3999.8, ask=4000.0, contract_size=100.0,
                                  digits=2, now="2026-10-26 09:30:00")
    check("mark at the ask for a short", pv["mark"] == 4000.0, f"{pv['mark']}")
    check("short unrealized flat at entry", pv["unrealized"] == 0.0, f"{pv['unrealized']}")
    check("no negative zero in a currency field", str(pv["unrealized"]) == "0.0",
          f"{pv['unrealized']!r}")

    be_pos = dict(pos, sl=4000.0, be_armed=True)     # ratcheted to breakeven
    pv = scalp_view.position_view(be_pos, bid=4012.5, ask=4012.7, contract_size=100.0,
                                  digits=2, now="2026-10-26 09:30:00")
    check("progress re-bases on the ratcheted stop", pv["progress_pct"] == 50.0,
          f"{pv['progress_pct']}")
    check("breakeven flag survives", pv["be_armed"] is True)

    no_tp = {"side": "BUY", "entry": 4000.0, "sl": 3990.0, "tp": 0.0,
             "sl_dist": 10.0, "volume": 0.01, "time": "2026-10-26 09:00:00"}
    pv = scalp_view.position_view(no_tp, bid=4005.0, ask=4005.2, contract_size=100.0,
                                  digits=2, now="2026-10-26 09:30:00")
    check("MT5's tp=0 means 'no target'", pv["tp"] is None, f"{pv['tp']!r}")
    check("no band progress without a target", pv["progress_pct"] is None)
    check("but R still works", pv["unrealized_r"] == 0.5, f"{pv['unrealized_r']}")

    pv = scalp_view.position_view(pos, bid=None, ask=None, contract_size=100.0)
    check("a missing quote degrades instead of crashing",
          pv is not None and pv["unrealized"] is None and pv["live"] is False)

    # ------------------------------------------------------- persisted position
    print("the state file's open position drives the panel")
    logs = book([entry("BUY", 4000.0, 10.0, 25.0, time="2026-10-26 09:00:00")],
                state={"balance": 300.0, "closed": 0, "wins": 0, "losses": 0,
                       "time_exits": 0,
                       "position": {"side": "BUY", "entry": 4000.0, "sl": 3990.0,
                                    "tp": 4025.0, "sl_dist": 10.0, "tp_dist": 25.0,
                                    "volume": 0.01, "be_armed": False,
                                    "time": "2026-10-26 09:00:00"}})
    view = scalp_view.build(logs, live={"bid": 4010.0, "ask": 4010.2, "balance": 300.0},
                            now="2026-10-26 10:00:00")
    check("position found", view["position"] is not None)
    check("unrealized computed from the live quote", view["position"]["unrealized"] == 10.0,
          f"{view['position']['unrealized']}")
    check("no duplicate pending entry", view["pending_entry"] is None)
    check("an open trade is not in the closed record", view["stats"]["n"] == 0)
    check("tab is still 'available'", view["available"] is True)

    # ------------------------------------------------------------------- LIVE
    print("LIVE rows are marked unpriced rather than guessed")
    logs = book(
        [
            {"time": "2026-10-26 09:00:00", "event": "ENTRY", "side": "BUY",
             "ticket": 123, "volume": 0.01, "sl_dist": 10.0, "tp_dist": 25.0},
            {"time": "2026-10-26 10:00:00", "event": "LIVE_EXIT", "ticket": 456,
             "side": "BUY", "price": 4010.0, "volume": 0.01, "profit": 9.5,
             "swap": 0.0, "commission": 0.5, "pnl": 10.0,
             "closed_at": "2026-10-26 10:00:00"},
        ],
        state={"balance": 310.0, "position": None, "closed": 1, "wins": 1,
               "losses": 0, "time_exits": 0},
    )
    view = scalp_view.build(logs)
    t = view["trades"][0] if view["trades"] else {}
    check("LIVE trade paired", t.get("outcome") == "WIN", f"{t.get('outcome')}")
    check("no invented entry price", t.get("entry") is None and t.get("priced") is False)
    check("P&L still recorded", t.get("profit") == 10.0, f"{t.get('profit')}")
    check("no invented R multiple", t.get("r") is None and t.get("risk") is None)
    check("unpriced count surfaced", view["stats"]["unpriced"] == 1,
          f"{view['stats']['unpriced']}")

    # ------------------------------------------------------------- statistics
    print("statistics")
    profits = [5.0, -3.0, -4.0, 8.0, 0.0, -2.0, 6.0]
    rows = []
    for i, p in enumerate(profits):
        rows.append(entry("BUY", 4000.0, 10.0, 25.0, time=f"2026-10-2{i} 09:00:00"))
        rows.append(exit_row(4000.0 + p, p, "TP" if p > 0 else ("BE" if p == 0 else "SL"),
                             f"2026-10-2{i} 10:00:00"))
    logs = book(rows, state={"balance": 310.0, "position": None, "closed": len(profits),
                             "wins": 3, "losses": 4, "time_exits": 0})
    stats = scalp_view.build(logs)["stats"]
    check("net", stats["net"] == 10.0, f"{stats['net']}")
    check("expectancy", stats["expectancy"] == round(10.0 / 7, 2), f"{stats['expectancy']}")
    check("max loss streak", stats["max_loss_streak"] == 2, f"{stats['max_loss_streak']}")
    check("current streak is a win", (stats["current_streak_kind"], stats["current_streak"])
          == ("WIN", 1), f"{(stats['current_streak_kind'], stats['current_streak'])}")
    check("max drawdown is peak-to-trough of the curve", stats["max_drawdown"] == 7.0,
          f"{stats['max_drawdown']}")
    check("win rate", stats["win_rate"] == round(300 / 7, 1), f"{stats['win_rate']}")

    no_losses = [entry("BUY", 4000.0, 10.0, 10.0), exit_row(4010.0, 10.0, "TP")]
    stats = scalp_view.summarize(scalp_view.pair_trades(no_losses)[0])
    check("PF is None, not infinite, when there are no losses", stats["pf"] is None)
    check("empty book summarises to zeros", scalp_view.summarize([])["n"] == 0)
    check("win_rate of an empty book is None", scalp_view.win_rate({}) is None)

    # --------------------------------------------------------------- the view
    print("filters, limits and the sparkline")
    logs = book(rows, state={"balance": 310.0, "position": None, "closed": len(profits),
                             "wins": 3, "losses": 4, "time_exits": 0})
    wins = scalp_view.build(logs, result="wins")
    losses = scalp_view.build(logs, result="losses")
    be = scalp_view.build(logs, result="breakeven")
    check("wins filter", len(wins["trades"]) == 3 and wins["filtered"]["count"] == 3)
    check("losses filter", len(losses["trades"]) == 3, f"{len(losses['trades'])}")
    check("breakeven filter catches the flat exit", len(be["trades"]) == 1)
    check("filtered stats are the filter's own",
          wins["filtered"]["stats"]["net"] == 19.0, f"{wins['filtered']['stats']['net']}")
    check("unfiltered stats survive a filter",
          wins["stats"]["net"] == 10.0, f"{wins['stats']['net']}")
    limited = scalp_view.build(logs, limit=2)
    check("limit", len(limited["trades"]) == 2)
    check("bad limit falls back", len(scalp_view.build(logs, limit="x")["trades"]) == 7)
    check("bad filter falls back to all",
          scalp_view.build(logs, result="nonsense")["filtered"]["key"] == "all")
    check("empty book is 'unavailable', not an error",
          scalp_view.build(book([], state=None))["available"] is False)

    spark = scalp_view.sparkline_points([0.0, -5.0, 10.0])
    pts = spark["points"].split()
    check("sparkline starts at x=0 and ends at the full width",
          spark and pts[0].startswith("0.0,") and pts[-1] == "100.0,0.0",
          f"{spark.get('points') if spark else spark}")
    check("sparkline puts the low at the bottom", pts[1] == "50.0,30.0", f"{pts[1]}")
    check("sparkline marks the zero line", spark["zero_y"] == 20.0, f"{spark['zero_y']}")
    check("sparkline needs two points", scalp_view.sparkline_points([1.0]) == {})
    check("sparkline of a flat line is empty", scalp_view.sparkline_points([0.0, 0.0]) == {})

    passed = sum(1 for r in RESULTS if r)
    print(f"\n{passed}/{len(RESULTS)} checks passed")
    if passed != len(RESULTS):
        print("FAIL")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
