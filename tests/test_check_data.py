#!/usr/bin/env python3
"""Unit tests for tools/check_data.py.

Two things are load-bearing:

  * a `paper.py --reset` leaves a legitimate break in trades.jsonl (the reset
    zeroes the balance but does NOT rewrite the log). Checking the chain from
    the beginning of time produced two phantom failures on the real box
    (2026-10-19); the check must chain only the CURRENT book, sized by the
    state file's own `closed` counter.
  * the incident classes must still fail: non-finite P&L, invalid position
    geometry, state/ledger disagreement, counters that do not match the log.

Run:  python3 tests/test_check_data.py      # exit 0 = PASS
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append(bool(ok))


def load_tool():
    spec = importlib.util.spec_from_file_location("check_data", ROOT / "tools" / "check_data.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def book(root: Path, exits, state, name="gold"):
    """Write a minimal book. `exits` are (profit, balance_after, extra) tuples."""
    base = root if name == "gold" else root / "btc"
    logs = base / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with open(logs / "trades.jsonl", "w") as f:
        for profit, bal, extra in exits:
            row = {"event": "SIM_EXIT", "side": "BUY", "entry": 4000.0, "exit": 4010.0,
                   "profit": profit, "balance_after": bal}
            row.update(extra)
            f.write(json.dumps(row) + "\n")
    (logs / "paper_account.json").write_text(json.dumps(state))
    return logs


def run(tool, root):
    return tool.main(["--root", str(root)])


def main() -> int:
    tool = load_tool()

    print("a reset does not break the check (the real-box false positive)")
    tmp = Path(tempfile.mkdtemp(prefix="cd_reset_"))
    # Old book: started at 200, ran down, then the 2026-10-04 reset to 300.
    old = [(10.0, 210.0, {}), (-20.0, 190.0, {})]
    # Current book: 300 -> 310 -> 304 (closed=2), i.e. the chain restarts.
    cur = [(10.0, 310.0, {}), (-6.0, 304.0, {})]
    book(tmp, old + cur, {"balance": 304.0, "position": None,
                          "closed": 2, "wins": 1, "losses": 1, "time_exits": 0})
    rc = run(tool, tmp)
    check("pre-reset rows are ignored", rc == 0, f"rc={rc}")

    print("a break INSIDE the current book still fails")
    tmp = Path(tempfile.mkdtemp(prefix="cd_break_"))
    book(tmp, old + [(10.0, 310.0, {}), (-6.0, 999.0, {})],
         {"balance": 999.0, "position": None, "closed": 2,
          "wins": 1, "losses": 1, "time_exits": 0})
    rc = run(tool, tmp)
    check("chain break in the current book fails", rc == 1, f"rc={rc}")

    print("state/ledger disagreement fails")
    tmp = Path(tempfile.mkdtemp(prefix="cd_state_"))
    book(tmp, cur, {"balance": 500.0, "position": None, "closed": 2,
                    "wins": 1, "losses": 1, "time_exits": 0})
    rc = run(tool, tmp)
    check("state balance != last exit fails", rc == 1, f"rc={rc}")

    print("counters must describe the same book")
    tmp = Path(tempfile.mkdtemp(prefix="cd_count_"))
    book(tmp, cur, {"balance": 304.0, "position": None, "closed": 2,
                    "wins": 9, "losses": 1, "time_exits": 0})
    rc = run(tool, tmp)
    check("wrong win count fails", rc == 1, f"rc={rc}")

    print("TIME is its own bucket")
    tmp = Path(tempfile.mkdtemp(prefix="cd_time_"))
    book(tmp, [(0.0, 300.0, {"reason": "TIME"}), (5.0, 305.0, {"reason": "TP"})],
         {"balance": 305.0, "position": None, "closed": 2,
          "wins": 1, "losses": 0, "time_exits": 1})
    rc = run(tool, tmp)
    check("a TIME exit is not counted as a loss", rc == 0, f"rc={rc}")

    print("the incident class still fails")
    tmp = Path(tempfile.mkdtemp(prefix="cd_nan_"))
    logs = book(tmp, cur, {"balance": 304.0, "position": None, "closed": 2,
                           "wins": 1, "losses": 1, "time_exits": 0})
    with open(logs / "trades.jsonl", "a") as f:
        f.write('{"event": "SIM_EXIT", "reason": "TP", "profit": NaN, '
                '"balance_after": 304.0}\n')
    rc = run(tool, tmp)
    check("NaN profit fails", rc == 1, f"rc={rc}")

    tmp = Path(tempfile.mkdtemp(prefix="cd_geom_"))
    book(tmp, cur, {"balance": 304.0, "position": {
        "side": "BUY", "entry": 0, "sl": 1, "tp": 0, "sl_dist": 0, "volume": 0.01},
        "closed": 2, "wins": 1, "losses": 1, "time_exits": 0})
    rc = run(tool, tmp)
    check("invalid open-position geometry fails", rc == 1, f"rc={rc}")

    print("truncated ledger")
    tmp = Path(tempfile.mkdtemp(prefix="cd_trunc_"))
    book(tmp, cur, {"balance": 304.0, "position": None, "closed": 7,
                    "wins": 1, "losses": 6, "time_exits": 0})
    rc = run(tool, tmp)
    check("closed > logged exits fails", rc == 1, f"rc={rc}")

    print("fresh book")
    tmp = Path(tempfile.mkdtemp(prefix="cd_fresh_"))
    logs = book(tmp, [], {"balance": 300.0, "position": None, "closed": 0,
                          "wins": 0, "losses": 0, "time_exits": 0})
    (logs / "trades.jsonl").write_text("")
    rc = run(tool, tmp)
    check("an empty book is healthy", rc == 0, f"rc={rc}")

    failed = RESULTS.count(False)
    print(f"\n{'ALL PASS' if failed == 0 else str(failed) + ' FAILED'}: "
          f"{RESULTS.count(True)}/{len(RESULTS)} check_data checks")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
