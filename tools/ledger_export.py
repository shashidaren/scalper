#!/usr/bin/env python3
"""Build the compact, publishable trade ledger from the event log.

`logs/trades.jsonl` is NOT a trade ledger. `run.py` writes a `SIGNAL` row on
every loop iteration (~4/min per book, 24/7) plus a `SKIP` row whenever the
spread gate vetoes, so the file grows by roughly 11,500 rows (~1.7 MB) a day.
Publishing it every 15 minutes is what put 187,406 rows into `data collection 1`
on the first autosync run (2026-10-19).

This tool filters it down to the events that describe trades:

    SIM_ENTRY  SIM_ENTRY_FAILED  SIM_EXIT
    ENTRY      ENTRY_FAILED      ENTRY_SKIPPED
    EXIT

and writes `logs/ledger.jsonl` (per book). That file is a few hundred bytes a
day, diffs cleanly, and is what git should carry. The raw event log stays
local — it is the full telemetry, useful on the box and worthless as history.

    python3 tools/ledger_export.py                  # both books
    python3 tools/ledger_export.py --book gold
    python3 tools/ledger_export.py --check          # exit 1 if stale
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOKS = {"gold": ROOT, "btc": ROOT / "btc"}

# Everything that is part of a trade's life. Everything else (SIGNAL, SKIP) is
# sampling telemetry and stays on the box.
LIFECYCLE_EVENTS = frozenset({
    "SIM_ENTRY", "SIM_ENTRY_FAILED", "SIM_EXIT",
    "ENTRY", "ENTRY_FAILED", "ENTRY_SKIPPED",
    "EXIT",
})


def _reject_constant(name):
    raise ValueError(f"non-finite JSON constant {name}")


def build(source: Path):
    """Read `source` and return the ledger text ('' when there is no source)."""
    if not source.exists():
        return ""
    out = []
    with open(source, errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line, parse_constant=_reject_constant)
            except Exception:
                # A torn final line (the engine appends while we read) is
                # expected; drop it rather than refusing to export.
                continue
            if isinstance(row, dict) and row.get("event") in LIFECYCLE_EVENTS:
                out.append(json.dumps(row, separators=(",", ":"), sort_keys=True))
    return ("\n".join(out) + "\n") if out else ""


def export_book(book_dir: Path, check_only=False):
    """Return (status, detail) where status is written/unchanged/stale/missing."""
    logs = book_dir / "logs"
    src = logs / "trades.jsonl"
    dst = logs / "ledger.jsonl"
    if not src.exists():
        return "missing", f"{src} does not exist"
    want = build(src)
    have = dst.read_text(errors="replace") if dst.exists() else None
    if have == want:
        return "unchanged", dst
    if check_only:
        return "stale", dst
    tmp = dst.with_name(dst.name + ".tmp")
    tmp.write_text(want)
    tmp.replace(dst)
    return "written", dst


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help="repo root (default: this repo)")
    ap.add_argument("--book", choices=("gold", "btc", "all"), default="all")
    ap.add_argument("--check", action="store_true",
                    help="only report; exit 1 when a ledger is out of date")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    books = {"gold": root, "btc": root / "btc"}
    names = ["gold", "btc"] if args.book == "all" else [args.book]

    stale = False
    for name in names:
        status, detail = export_book(books[name], check_only=args.check)
        if status == "stale":
            stale = True
        if not args.quiet:
            print(f"{name}: {status} ({detail})")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
