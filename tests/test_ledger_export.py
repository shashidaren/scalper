#!/usr/bin/env python3
"""Unit tests for tools/ledger_export.py.

The contract: `ledger.jsonl` contains every trade-lifecycle event and NOTHING
from the SIGNAL/SKIP firehose, is stable across runs (so it does not create a
data commit), and never dies on a torn last line.

Run:  python3 tests/test_ledger_export.py      # exit 0 = PASS
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
    spec = importlib.util.spec_from_file_location(
        "ledger_export", ROOT / "tools" / "ledger_export.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_log(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def main() -> int:
    tool = load_tool()

    print("filtering")
    tmp = Path(tempfile.mkdtemp(prefix="ledger_"))
    logs = tmp / "logs"
    write_log(logs / "trades.jsonl", [
        {"time": "t1", "event": "SIGNAL", "signal": None, "reason": "no_setup"},
        {"time": "t2", "event": "SIM_ENTRY", "side": "BUY", "entry": 4000.0},
        {"time": "t3", "event": "SIGNAL", "signal": None, "reason": "no_setup"},
        {"time": "t4", "event": "SKIP", "reason": "high_spread", "spread": 120},
        {"time": "t5", "event": "SIM_EXIT", "reason": "TP", "profit": 10.0,
         "balance_after": 310.0},
        {"time": "t6", "event": "ENTRY_SKIPPED", "reason": "risk_sizer:below_volume_min"},
    ])
    status, _ = tool.export_book(tmp)
    check("writes a ledger", status == "written", status)
    rows = [json.loads(l) for l in (logs / "ledger.jsonl").read_text().splitlines()]
    check("keeps exactly the lifecycle events", len(rows) == 3, str(len(rows)))
    events = [r["event"] for r in rows]
    check("order preserved", events == ["SIM_ENTRY", "SIM_EXIT", "ENTRY_SKIPPED"], str(events))
    check("SIGNAL is dropped", "SIGNAL" not in events)
    check("SKIP is dropped", "SKIP" not in events)

    print("stability")
    status, _ = tool.export_book(tmp)
    check("a second run changes nothing", status == "unchanged", status)
    check("--check is happy", tool.main(["--root", str(tmp), "--book", "gold", "--check",
                                         "--quiet"]) == 0)

    print("appending one trade only adds one row")
    with open(logs / "trades.jsonl", "a") as f:
        f.write(json.dumps({"time": "t7", "event": "SIGNAL"}) + "\n")
        f.write(json.dumps({"time": "t8", "event": "SIM_ENTRY", "side": "SELL",
                            "entry": 4010.0}) + "\n")
    check("--check reports stale", tool.main(["--root", str(tmp), "--book", "gold",
                                              "--check", "--quiet"]) == 1)
    tool.export_book(tmp)
    rows = (logs / "ledger.jsonl").read_text().splitlines()
    check("one new lifecycle row", len(rows) == 4, str(len(rows)))

    print("robustness")
    with open(logs / "trades.jsonl", "a") as f:
        f.write('{"time": "t9", "event": "SIM_EXIT", "profit": NaN}\n')
        f.write('{"time": "t10", "event": "SIM_EXIT", "pro')   # torn write
    status, _ = tool.export_book(tmp)
    rows = (logs / "ledger.jsonl").read_text().splitlines()
    check("NaN and torn lines do not crash the export", status in ("written", "unchanged"))
    check("neither is written to the ledger", len(rows) == 4, str(len(rows)))
    check("the ledger is byte-identical (no phantom commit)",
          status == "unchanged", status)

    print("missing source")
    empty = Path(tempfile.mkdtemp(prefix="ledger_empty_"))
    status, _ = tool.export_book(empty)
    check("no event log -> missing, no file created", status == "missing")
    check("no ledger written", not (empty / "logs" / "ledger.jsonl").exists())

    print("size sanity")
    big = Path(tempfile.mkdtemp(prefix="ledger_big_"))
    rows = []
    for i in range(2000):
        rows.append({"time": f"t{i}", "event": "SIGNAL", "reason": "no_setup"})
        if i % 40 == 0:
            rows.append({"time": f"e{i}", "event": "SIM_EXIT", "profit": 1.0,
                         "balance_after": 300.0})
    write_log(big / "logs" / "trades.jsonl", rows)
    tool.export_book(big)
    src = (big / "logs" / "trades.jsonl").stat().st_size
    dst = (big / "logs" / "ledger.jsonl").stat().st_size
    check(f"the ledger is a fraction of the log ({dst} of {src} bytes)", dst < src / 10)

    failed = RESULTS.count(False)
    print(f"\n{'ALL PASS' if failed == 0 else str(failed) + ' FAILED'}: "
          f"{RESULTS.count(True)}/{len(RESULTS)} ledger-export checks")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
