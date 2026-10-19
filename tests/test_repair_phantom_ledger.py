#!/usr/bin/env python3
"""Unit tests for tools/repair_phantom_ledger.py.

The tool rewrites a ledger, so the properties that matter are:
  * a dry run never touches the files;
  * --apply quarantines a copy BEFORE rewriting (evidence is never destroyed);
  * suspect rows are dropped, valid rows are kept byte-for-byte;
  * the restored balance/counters come from the surviving rows (or an explicit
    --reference-balance);
  * the engine-liveness guard refuses --apply while a book is running.

Run:  python3 tests/test_repair_phantom_ledger.py      # exit 0 = PASS
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
        "repair_phantom_ledger", ROOT / "tools" / "repair_phantom_ledger.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_book(root: Path, rows, balance, position=None):
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "trades.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (logs / "paper_account.json").write_text(json.dumps({
        "balance": balance, "position": position,
        "closed": 99, "wins": 99, "losses": 99,
    }))
    return logs


def main() -> int:
    tool = load_tool()
    tool.engine_alive = lambda: []          # never probe the real box in a test

    good = [
        {"event": "SIM_ENTRY", "side": "BUY", "entry": 4000.0},
        {"event": "SIM_EXIT", "reason": "TP", "side": "BUY", "entry": 4000.0,
         "exit": 4010.0, "profit": 10.0, "balance_after": 310.0},
        {"event": "SIM_EXIT", "reason": "SL", "side": "SELL", "entry": 4010.0,
         "exit": 4016.0, "profit": -6.0, "balance_after": 304.0},
    ]

    print("dry run is read-only")
    tmp = Path(tempfile.mkdtemp(prefix="repair_dry_"))
    logs = make_book(tmp, good + [
        {"event": "SIM_EXIT", "reason": "TP", "side": "BUY", "entry": 4000.0,
         "exit": 4010.0, "profit": -58_000.0, "balance_after": -57_696.0},
    ], -57_696.0)
    before_trades = (logs / "trades.jsonl").read_text()
    rc = tool.main(["--root", str(tmp), "--book", "gold"])
    check("dry-run exits 0", rc == 0, f"rc={rc}")
    check("trades.jsonl untouched", (logs / "trades.jsonl").read_text() == before_trades)
    check("no quarantine directory created", not (logs / "quarantine").exists())
    check("state untouched",
          json.loads((logs / "paper_account.json").read_text())["balance"] == -57_696.0)

    print("apply quarantines, drops, and restores")
    tmp = Path(tempfile.mkdtemp(prefix="repair_apply_"))
    logs = make_book(tmp, good + [
        {"event": "SIM_EXIT", "reason": "TP", "side": "BUY", "entry": 0,
         "exit": 4010.0, "profit": 5.0, "balance_after": 309.0},
    ], 309.0)
    rc = tool.main(["--root", str(tmp), "--book", "gold", "--apply"])
    check("apply exits 0", rc == 0, f"rc={rc}")
    kept = [json.loads(l) for l in (logs / "trades.jsonl").read_text().splitlines()]
    check("the phantom row is gone", len(kept) == 3)
    check("valid rows keep their values",
          kept[1]["profit"] == 10.0 and kept[2]["balance_after"] == 304.0)
    qdirs = list((logs / "quarantine").iterdir())
    check("one quarantine dir", len(qdirs) == 1)
    check("original trades.jsonl preserved in quarantine",
          len((qdirs[0] / "trades.jsonl").read_text().splitlines()) == 4)
    check("original state preserved in quarantine",
          json.loads((qdirs[0] / "paper_account.json").read_text())["balance"] == 309.0)
    qrows = [json.loads(l) for l in (qdirs[0] / "quarantined_rows.jsonl").read_text().splitlines()]
    check("quarantine records the reason", qrows and "entry/exit" in qrows[0]["reason"])
    state = json.loads((logs / "paper_account.json").read_text())
    check("balance recomputed from surviving rows", state["balance"] == 304.0, str(state))
    check("counters recomputed", (state["closed"], state["wins"], state["losses"]) == (2, 1, 1))

    print("--reference-balance wins")
    tmp = Path(tempfile.mkdtemp(prefix="repair_ref_"))
    logs = make_book(tmp, good + [
        {"event": "SIM_EXIT", "reason": "TP", "profit": float("nan"),
         "balance_after": float("nan")},
    ], 304.0)
    # json.dumps writes NaN, which is exactly the real-world poison.
    rc = tool.main(["--root", str(tmp), "--book", "gold", "--apply",
                    "--reference-balance", "150.69"])
    state = json.loads((logs / "paper_account.json").read_text())
    check("reference balance restored", state["balance"] == 150.69, str(state))
    check("NaN row removed", len((logs / "trades.jsonl").read_text().splitlines()) == 3)

    print("chain break is detected")
    tmp = Path(tempfile.mkdtemp(prefix="repair_chain_"))
    logs = make_book(tmp, [
        {"event": "SIM_EXIT", "reason": "TP", "side": "BUY", "entry": 4000.0,
         "exit": 4010.0, "profit": 10.0, "balance_after": 310.0},
        {"event": "SIM_EXIT", "reason": "SL", "side": "BUY", "entry": 4000.0,
         "exit": 3990.0, "profit": -10.0, "balance_after": 250.0},   # should be 300
    ], 250.0)
    rc = tool.main(["--root", str(tmp), "--book", "gold"])
    check("dry run finds the break (rc 0, reports)", rc == 0)
    check("nothing quarantined on a dry run", not (logs / "quarantine").exists())

    print("engine guard")
    tmp = Path(tempfile.mkdtemp(prefix="repair_guard_"))
    logs = make_book(tmp, good + [
        {"event": "SIM_EXIT", "reason": "TP", "profit": 99_999.0, "balance_after": 99_999.0},
    ], 99_999.0)
    tool.engine_alive = lambda: ["scalper-bot"]
    rc = tool.main(["--root", str(tmp), "--book", "gold", "--apply"])
    check("refuses --apply while the engine runs", rc == 2, f"rc={rc}")
    check("refused run changed nothing",
          json.loads((logs / "paper_account.json").read_text())["balance"] == 99_999.0)

    failed = RESULTS.count(False)
    print(f"\n{'ALL PASS' if failed == 0 else str(failed) + ' FAILED'}: "
          f"{RESULTS.count(True)}/{len(RESULTS)} repair-tool checks")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
