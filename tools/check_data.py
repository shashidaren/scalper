#!/usr/bin/env python3
"""Integrity check for the paper books — the scalper's `check_data.py`.

Ported in spirit from gold-trading-bot's `tools/check_data.py`. That repo keeps
a CSV ledger; this one keeps JSONL + JSON state, so the checks are:

  * every line of `ledger.jsonl` (or `trades.jsonl` when no ledger exists yet)
    is a valid JSON object (NaN/Infinity rejected —
    Python's json accepts them by default, which is how a `NaN` balance can
    reach a state file unnoticed);
  * every `SIM_EXIT` row has a finite numeric `profit` and `balance_after`;
  * the running balance chains inside the CURRENT book (a `paper.py --reset`
    legitimately breaks the chain in the raw log, so only the last `closed`
    exits, as reported by the state file, are chained);
  * `paper_account.json` parses, its balance is finite, and any open position has
    positive, finite geometry (entry/sl/sl_dist/volume, tp absent-or-positive);
  * `daily_stats.json` parses and its counters are numeric;
  * `live_status.json` parses and any advertised position has sane geometry;
  * the last 200 lines of `system.jsonl` parse.

Read-only. Advisory in autosync (a fail raises a line in the digest, it does not
roll a deploy back). Exit 0 = no failures.

    python3 tools/check_data.py [--root DIR] [--json]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOOKS = (("gold", ROOT), ("btc", ROOT / "btc"))


def _reject_constant(name):
    raise ValueError(f"non-finite JSON constant {name}")


def _loads(text):
    return json.loads(text, parse_constant=_reject_constant)


def _finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _positive(x):
    return _finite(x) and float(x) > 0.0


def _read_jsonl(path, tail=None):
    """(rows, errors). Unparseable lines are reported, never raised."""
    rows, errors = [], []
    if not path.exists():
        return rows, errors
    lines = path.read_text(errors="replace").splitlines()
    if tail:
        lines = lines[-tail:]
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            obj = _loads(line)
        except Exception as e:
            errors.append(f"{path.name} line {n}: {e}")
            continue
        if not isinstance(obj, dict):
            errors.append(f"{path.name} line {n}: not a JSON object")
            continue
        rows.append(obj)
    return rows, errors


class Report:
    def __init__(self):
        self.fails: list[str] = []
        self.warns: list[str] = []

    def fail(self, msg):
        self.fails.append(msg)

    def warn(self, msg):
        self.warns.append(msg)


def check_book(name: str, book: Path, rep: Report):
    logs = book / "logs"
    # The durable record is the compact ledger (lifecycle events only). The raw
    # event log is 11k+ rows/day of SIGNAL/SKIP telemetry; when a ledger exists
    # it is the authority, and the event log is only checked for shape.
    ledger = logs / "ledger.jsonl"
    trades = ledger if ledger.exists() else logs / "trades.jsonl"
    rows, errors = _read_jsonl(trades)
    for err in errors:
        rep.fail(f"{name}: {err}")
    if ledger.exists() and (logs / "trades.jsonl").exists():
        _, raw_errors = _read_jsonl(logs / "trades.jsonl", tail=500)
        if raw_errors:
            rep.warn(f"{name}: {raw_errors[0]} (in trades.jsonl; not the durable record)")

    exits = [r for r in rows if r.get("event") == "SIM_EXIT"]
    # Shape checks on every exit ever logged (cheap, and a NaN row is an
    # incident whether or not it belongs to the current book).
    for i, r in enumerate(exits):
        if not _finite(r.get("profit")):
            rep.fail(f"{name}: SIM_EXIT #{i} has non-finite profit {r.get('profit')!r}")
        if not _finite(r.get("balance_after")):
            rep.fail(f"{name}: SIM_EXIT #{i} has non-finite balance_after "
                     f"{r.get('balance_after')!r}")

    # The balance chain is only meaningful inside ONE book. `paper.py --reset`
    # zeroes the counters and the balance but deliberately leaves trades.jsonl
    # alone, so a reset leaves a permanent, legitimate break in the file. The
    # state file says how many exits the CURRENT book has (`closed`), so chain
    # -check exactly those. Checking from the beginning of time produced two
    # phantom failures on the box (2026-10-19: both books were reset 10-04).
    prev_balance = None
    state_closed = None

    state = logs / "paper_account.json"
    state_balance = None
    if state.exists():
        try:
            data = _loads(state.read_text())
        except Exception as e:
            rep.fail(f"{name}: paper_account.json unreadable: {e}")
            data = None
        if isinstance(data, dict):
            bal = data.get("balance")
            if not _finite(bal):
                rep.fail(f"{name}: paper_account.json balance is {bal!r}")
            else:
                state_balance = float(bal)
            pos = data.get("position")
            if pos is not None:
                if not isinstance(pos, dict):
                    rep.fail(f"{name}: paper_account position is not an object")
                else:
                    for key in ("entry", "sl", "sl_dist", "volume"):
                        if not _positive(pos.get(key)):
                            rep.fail(f"{name}: open position has {key}={pos.get(key)!r}")
                    tp = pos.get("tp")
                    if tp is not None and not _positive(tp):
                        rep.fail(f"{name}: open position has tp={tp!r} (must be None or > 0)")
            for key in ("closed", "wins", "losses", "time_exits"):
                if key in data and not isinstance(data[key], int):
                    rep.fail(f"{name}: paper_account {key} is not an int ({data[key]!r})")
            if isinstance(data.get("closed"), int):
                state_closed = data["closed"]

            # --- chain over the current book only ---------------------------
            if state_closed is not None:
                if state_closed > len(exits):
                    rep.fail(f"{name}: state says {state_closed} closed trades but the "
                             f"log only has {len(exits)} exits (ledger truncated?)")
                book = exits[-state_closed:] if state_closed else []
                for i, r in enumerate(book):
                    profit, bal = r.get("profit"), r.get("balance_after")
                    if not _finite(profit) or not _finite(bal):
                        continue          # already reported above
                    if prev_balance is not None:
                        expected = round(prev_balance + float(profit), 2)
                        if abs(expected - float(bal)) > 0.01:
                            rep.fail(f"{name}: balance chain breaks {len(book) - i} "
                                     f"trade(s) from the end: {prev_balance} + "
                                     f"{profit} != {bal}")
                    prev_balance = float(bal)

                # Counters must describe the same book as the chain.
                if book:
                    wins = sum(1 for r in book
                               if r.get("reason") != "TIME" and float(r.get("profit", 0)) > 0)
                    losses = sum(1 for r in book
                                 if r.get("reason") != "TIME" and float(r.get("profit", 0)) <= 0)
                    times = sum(1 for r in book if r.get("reason") == "TIME")
                    got = (wins, losses, times)
                    want = (data.get("wins"), data.get("losses"), data.get("time_exits", 0))
                    if all(isinstance(v, int) for v in want) and got != want:
                        rep.fail(f"{name}: state counters {want} disagree with the last "
                                 f"{len(book)} exits {got}")
            elif exits:
                # No usable counter: fall back to the whole file, and treat a
                # break as a warning (it may be a historical reset).
                for i, r in enumerate(exits):
                    profit, bal = r.get("profit"), r.get("balance_after")
                    if not _finite(profit) or not _finite(bal):
                        continue
                    if prev_balance is not None and \
                            abs(round(prev_balance + float(profit), 2) - float(bal)) > 0.01:
                        rep.warn(f"{name}: balance chain breaks at SIM_EXIT #{i} "
                                 f"({prev_balance} + {profit} != {bal}) - reset, or an edit?")
                    prev_balance = float(bal)

            if (state_balance is not None and prev_balance is not None
                    and abs(state_balance - prev_balance) > 0.01):
                rep.fail(f"{name}: state balance ${state_balance:.2f} != the last exit's "
                         f"${prev_balance:.2f} - the ledger and the state disagree")
            if state_closed == 0 and exits:
                rep.warn(f"{name}: state says 0 closed but the log has {len(exits)} exits "
                         f"(book reset since the log was started - expected)")
    elif rows:
        rep.warn(f"{name}: trades.jsonl exists but paper_account.json does not")

    daily = logs / "daily_stats.json"
    if daily.exists():
        try:
            d = _loads(daily.read_text())
            if not isinstance(d, dict):
                raise ValueError("not a JSON object")
            for key in ("pnl", "trades", "wins", "losses"):
                if key in d and not _finite(d[key]):
                    rep.fail(f"{name}: daily_stats.{key}={d[key]!r}")
        except Exception as e:
            rep.fail(f"{name}: daily_stats.json unreadable: {e}")

    live = logs / "live_status.json"
    if live.exists():
        try:
            s = _loads(live.read_text())
            if not isinstance(s, dict):
                raise ValueError("not a JSON object")
            for p in s.get("positions") or []:
                if not isinstance(p, dict):
                    rep.fail(f"{name}: live_status position is not an object")
                    continue
                for key in ("price_open", "sl", "volume"):
                    if not _positive(p.get(key)):
                        rep.fail(f"{name}: live_status position has {key}={p.get(key)!r}")
        except Exception as e:
            rep.fail(f"{name}: live_status.json unreadable: {e}")

    system = logs / "system.jsonl"
    if system.exists():
        _, sys_errors = _read_jsonl(system, tail=200)
        for err in sys_errors[:3]:
            rep.fail(f"{name}: {err}")
        if len(sys_errors) > 3:
            rep.fail(f"{name}: ... {len(sys_errors) - 3} more unparseable system.jsonl lines")

    position_open = False
    if state.exists():
        try:
            position_open = _loads(state.read_text()).get("position") is not None
        except Exception:
            position_open = False

    closed_note = f", {state_closed} in the current book" if state_closed is not None else ""
    print(f"== {name}: {len(rows)} ledger rows, {len(exits)} exits{closed_note}, "
          f"balance {('%.2f' % state_balance) if state_balance is not None else 'n/a'}"
          f"{' (position open)' if position_open else ''}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(ROOT), help="repo root (default: this repo)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve()
    rep = Report()
    for name, book in (("gold", root), ("btc", root / "btc")):
        check_book(name, book, rep)

    for w in rep.warns:
        print(f"== warn: {w}")
    for f in rep.fails:
        print(f"== FAIL: {f}")
    verdict = f"{len(rep.fails)} fail, {len(rep.warns)} warn"
    print(f"== result: {verdict}")

    if args.json:
        print(json.dumps({"fails": rep.fails, "warns": rep.warns,
                          "verdict": verdict}, indent=2))
    return 1 if rep.fails else 0


if __name__ == "__main__":
    sys.exit(main())
