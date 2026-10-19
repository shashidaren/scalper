#!/usr/bin/env python3
"""Quarantine phantom P&L rows and restore a consistent paper ledger.

The counterpart to the guards in `paper.py`. Those stop NEW bad rows; this
repairs a book that already has some — the failure mode gold-trading-bot hit on
2026-10-19, when twenty rows with blank entry times and zero take-profits booked
-$58,544.65 of money that never existed.

What counts as suspect (a `SIM_EXIT` row):
  * `profit` or `balance_after` missing, non-numeric, NaN or infinite;
  * `side` not BUY/SELL, or `entry`/`exit` not finite and positive;
  * `|profit|` larger than `--max-abs-profit` (default 5000) — a single gold
    trade at 0.01 lots cannot legitimately move that much;
  * a `balance_after` that does not equal `previous + profit` (the chain break
    that makes every later balance wrong).

Defaults to a DRY RUN: it prints the verdict and changes nothing. `--apply`:
  1. refuses while the engine looks alive (pass `--force` to override);
  2. copies `trades.jsonl` and `paper_account.json` into
     `logs/quarantine/<timestamp>/` (the original is never destroyed);
  3. rewrites `trades.jsonl` without the suspect rows;
  4. rewrites `paper_account.json` with a balance recomputed from the surviving
     rows (or from `--reference-balance`, which is how gold restored $150.69)
     and counters recomputed from those rows.

    python3 tools/repair_phantom_ledger.py                    # dry run, both books
    python3 tools/repair_phantom_ledger.py --book gold
    python3 tools/repair_phantom_ledger.py --book gold --apply --reference-balance 150.69
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOKS = {"gold": ROOT, "btc": ROOT / "btc"}
DATA_EVENTS = {"SIM_ENTRY", "SIM_EXIT"}


def _finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _positive(x):
    return _finite(x) and float(x) > 0.0


def _reject_constant(name):
    raise ValueError(f"non-finite JSON constant {name}")


def _parse(line):
    return json.loads(line, parse_constant=_reject_constant)


def engine_alive() -> list[str]:
    """Best-effort liveness probe. Never fatal: it only gates `--apply`."""
    alive = []
    for unit in ("scalper-bot", "scalper-btc-bot"):
        try:
            r = subprocess.run(["systemctl", "is-active", "--quiet", unit],
                               capture_output=True, timeout=5)
            if r.returncode == 0:
                alive.append(unit)
        except Exception:
            pass
    try:
        r = subprocess.run(["pgrep", "-f", r"python.*(run\.py|btc/run\.py)"],
                           capture_output=True, text=True, timeout=5)
        if r.stdout.strip():
            alive.append("a run.py process")
    except Exception:
        pass
    return alive


def scan(rows, max_abs_profit):
    """Return (suspect_indexes:set, reasons:dict, recomputed_balance:float|None)."""
    suspect, reasons = set(), {}
    balance = None
    for i, (raw, row) in enumerate(rows):
        if not isinstance(row, dict):
            suspect.add(i)
            reasons[i] = "not a JSON object"
            continue
        if row.get("event") != "SIM_EXIT":
            continue
        profit, bal = row.get("profit"), row.get("balance_after")
        why = None
        if not _finite(profit):
            why = f"non-finite profit {profit!r}"
        elif not _finite(bal):
            why = f"non-finite balance_after {bal!r}"
        elif abs(float(profit)) > max_abs_profit:
            why = f"|profit| ${abs(float(profit)):.2f} exceeds ${max_abs_profit:.0f}"
        elif row.get("side") not in ("BUY", "SELL"):
            why = f"side {row.get('side')!r}"
        elif not _positive(row.get("entry")) or not _positive(row.get("exit")):
            why = f"entry/exit {row.get('entry')!r}/{row.get('exit')!r}"
        elif balance is not None and abs(round(balance + float(profit), 2) - float(bal)) > 0.01:
            why = (f"chain break: {balance} + {profit} = "
                   f"{round(balance + float(profit), 2)} != {bal}")
        if why:
            suspect.add(i)
            reasons[i] = why
            continue
        balance = float(bal)
    return suspect, reasons, balance


def counters(rows, suspect):
    wins = losses = time_exits = closed = 0
    for i, (_, row) in enumerate(rows):
        if i in suspect or not isinstance(row, dict) or row.get("event") != "SIM_EXIT":
            continue
        closed += 1
        reason = row.get("reason")
        if reason == "TIME":
            time_exits += 1
        elif float(row.get("profit", 0)) > 0:
            wins += 1
        else:
            losses += 1
    return {"closed": closed, "wins": wins, "losses": losses, "time_exits": time_exits}


def repair_book(name, book, args, report) -> int:
    logs = book / "logs"
    trades = logs / "trades.jsonl"
    state = logs / "paper_account.json"
    if not trades.exists():
        print(f"{name}: no trades.jsonl - nothing to do")
        return 0

    raw_lines = trades.read_text(errors="replace").splitlines()
    rows = []
    for n, line in enumerate(raw_lines, 1):
        if not line.strip():
            continue
        try:
            rows.append((line, _parse(line)))
        except Exception as e:
            rows.append((line, {"__error__": str(e), "__line__": n}))

    suspect, reasons, ledger_balance = scan(rows, args.max_abs_profit)
    # Unparseable lines are suspect too.
    for i, (_, row) in enumerate(rows):
        if isinstance(row, dict) and "__error__" in row:
            suspect.add(i)
            reasons[i] = f"line {row['__line__']}: {row['__error__']}"

    print(f"{name}: {len(rows)} row(s), {len(suspect)} suspect")
    for i in sorted(reasons):
        row = rows[i][1]
        ev = row.get("event") if isinstance(row, dict) else "?"
        print(f"  line {i + 1}: {ev}: {reasons[i]}")
    if not suspect:
        return 0

    cnt = counters(rows, suspect)
    if args.reference_balance is not None:
        new_balance = float(args.reference_balance)
    elif ledger_balance is not None:
        new_balance = ledger_balance
    else:
        new_balance = float(getattr(args, "start_balance", 300.0))
    print(f"  surviving exits -> balance ${new_balance:.2f}, "
          f"{cnt['wins']}W/{cnt['losses']}L/{cnt['time_exits']}T")

    if not args.apply:
        print("  dry run - nothing written (use --apply)")
        report.append(name)
        return 0

    alive = engine_alive()
    if alive and not args.force:
        print(f"  REFUSED: {', '.join(alive)} is running. Stop it, or pass --force.")
        return 2

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    qdir = logs / "quarantine" / stamp
    qdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(trades, qdir / "trades.jsonl")
    if state.exists():
        shutil.copy2(state, qdir / "paper_account.json")
    with open(qdir / "quarantined_rows.jsonl", "w") as f:
        for i in sorted(suspect):
            f.write(json.dumps({"line": i + 1, "reason": reasons[i],
                                "row": rows[i][1]}) + "\n")

    kept = [line for i, (line, _) in enumerate(rows) if i not in suspect]
    tmp = trades.with_name(trades.name + ".tmp")
    tmp.write_text("\n".join(kept) + ("\n" if kept else ""))
    tmp.replace(trades)

    prev = {}
    if state.exists():
        try:
            prev = json.loads(state.read_text(), parse_constant=_reject_constant)
        except Exception:
            prev = {}
    pos = prev.get("position")
    if not isinstance(pos, dict) or not _positive(pos.get("entry")) \
            or not _positive(pos.get("sl")) or not _positive(pos.get("volume")):
        pos = None
    new_state = {
        "balance": round(new_balance, 2),
        "position": pos,
        "closed": cnt["closed"],
        "wins": cnt["wins"],
        "losses": cnt["losses"],
        "time_exits": cnt["time_exits"],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    stmp = state.with_name(state.name + ".tmp")
    stmp.write_text(json.dumps(new_state, indent=2))
    stmp.replace(state)

    print(f"  quarantined to {qdir} ({len(suspect)} row(s)); "
          f"ledger now ${new_balance:.2f}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help="repo root (default: this repo)")
    ap.add_argument("--book", choices=("gold", "btc", "all"), default="all")
    ap.add_argument("--apply", action="store_true", help="write the repair (default: dry run)")
    ap.add_argument("--force", action="store_true", help="apply even if the engine is running")
    ap.add_argument("--reference-balance", type=float, default=None,
                    help="balance to restore (gold used 150.69 after its 2026-10-19 incident)")
    ap.add_argument("--start-balance", type=float, default=300.0,
                    help="fallback when no balance can be recomputed (default: 300)")
    ap.add_argument("--max-abs-profit", type=float, default=5000.0,
                    help="a single |profit| above this is suspect (default: 5000)")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    books = {"gold": root, "btc": root / "btc"}
    names = ["gold", "btc"] if args.book == "all" else [args.book]

    report = []
    rc = 0
    for name in names:
        rc = max(rc, repair_book(name, books[name], args, report))
    if report and not args.apply:
        print(f"\ndry run: {', '.join(report)} would be repaired. "
              f"Re-run with --apply once the engine is stopped.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
