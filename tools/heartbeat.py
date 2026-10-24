#!/usr/bin/env python3
"""Publish a small "is the engine alive?" heartbeat that survives into git.

Why this exists
---------------
The published paper state (`ledger.jsonl`, `daily_stats.json`,
`paper_account.json`) only moves when a trade does. With the gold book flat
from Friday 20:00 to Monday 00:00 UTC, and BTC quiet whenever the market is,
those three files can sit unchanged for ~52 hours. From a repo checkout
"healthy and idle" then looks exactly like "died on Friday night" - which is
exactly the question they cannot answer.

The engine's real heartbeat (`live_status.json`, `connection_status.json`,
`system.jsonl`) is machine-local and deliberately NOT published: it changes
every 15 s and would turn autosync into a commit generator.

So this writes one small derived file, `logs/heartbeat.json`, holding just the
*ages* and the last known state. It is published by `tools/autosync.sh`, and
because it is derived (not a stream) it is safe to overwrite.

Commit noise
------------
Rewriting it every 15 minutes would be ~96 commits a day for one boolean. So
the file is only rewritten when
  * the time bucket changes (default: hourly), or
  * the verdict changes (e.g. an engine goes stale or comes back),
and `--force` bypasses that. Between writes the content is up to one bucket
old, which is why every write carries an explicit `as_of_utc`: a stale file
says so about itself.

Read-only with respect to the engine. Stdlib only, on purpose: it must run
inside `autosync.sh` on a box where the venv may be broken, and it must never
be the reason a deploy fails.

    python3 tools/heartbeat.py                  # write it if due
    python3 tools/heartbeat.py --force          # write it now
    python3 tools/heartbeat.py --check          # print it, never write; exit 1 if stale
    python3 tools/heartbeat.py --bucket-minutes 0   # rewrite every run

Environment: `HEARTBEAT_STALE_MINUTES` (default 10) is how old a
`live_status.json` may be before the engine counts as not running.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_REL = Path("logs") / "heartbeat.json"

# book -> log dir (relative to the repo root)
BOOKS = {"gold": Path("logs"), "btc": Path("btc") / "logs"}

DEFAULT_STALE_MIN = float(os.environ.get("HEARTBEAT_STALE_MINUTES", "10") or 10)
DEFAULT_BUCKET_MIN = int(os.environ.get("AUTOSYNC_HEARTBEAT_BUCKET_MINUTES", "60") or 60)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path):
    """Return parsed JSON, or None. Never raises: a heartbeat must not crash."""
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _age_minutes(path: Path, now_ts: float | None = None):
    """Age of a file in minutes by mtime; None if it does not exist.

    mtime rather than the file's own `updated_at` on purpose: the engine writes
    local naive timestamps, and a heartbeat should not depend on the box's
    timezone being what we assume.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    now_ts = time.time() if now_ts is None else now_ts
    return round(max(0.0, (now_ts - st.st_mtime)) / 60.0, 1)


def _last_ledger_event(path: Path):
    """Timestamp of the last line of a jsonl ledger, without reading it all."""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            back = min(size, 8192)
            f.seek(size - back)
            chunk = f.read().decode("utf-8", "replace").strip().splitlines()
        for line in reversed(chunk):
            try:
                return json.loads(line).get("time")
            except Exception:
                continue
    except OSError:
        return None
    return None


def book_state(root: Path, name: str, stale_min: float, now_ts: float):
    log_dir = root / BOOKS[name]
    live = _read_json(log_dir / "live_status.json") or {}
    conn = _read_json(log_dir / "connection_status.json") or {}
    paper = _read_json(log_dir / "paper_account.json") or {}

    age = _age_minutes(log_dir / "live_status.json", now_ts)
    if age is None:
        verdict = "unknown"          # never report a missing file as healthy
    elif age > stale_min:
        verdict = "stale"
    else:
        verdict = "ok"

    gate = live.get("spread_gate") or {}
    return {
        "verdict": verdict,
        "engine_status_age_min": age,
        "engine_connected": live.get("connected"),
        "mode": live.get("mode"),
        "spread_gate_state": gate.get("state") if isinstance(gate, dict) else None,
        "open_positions": len(live.get("positions") or []),
        "paper_balance": paper.get("balance"),
        "paper_closed": paper.get("closed"),
        "paper_updated_at": paper.get("updated_at"),
        "last_ledger_event": _last_ledger_event(log_dir / "ledger.jsonl"),
        "reconnects": conn.get("reconnect_count"),
    }


def build(root: Path, stale_min: float, now_ts: float | None = None) -> dict:
    now_ts = time.time() if now_ts is None else now_ts
    now = _now_utc()
    books = {name: book_state(root, name, stale_min, now_ts) for name in BOOKS}

    states = {b["verdict"] for b in books.values()}
    if "stale" in states:
        verdict = "stale"
    elif "unknown" in states:
        verdict = "unknown"
    else:
        verdict = "ok"

    notes = []
    for name, b in books.items():
        if b["verdict"] == "unknown":
            notes.append(f"{name}: no live_status.json - engine has never run, "
                         f"or the log dir is wrong")
        elif b["verdict"] == "stale":
            notes.append(f"{name}: live_status.json is {b['engine_status_age_min']:.0f}"
                         f" min old (limit {stale_min:.0f}) - engine is not looping")
        if b["paper_updated_at"] and b["verdict"] == "ok":
            # A fresh engine with no recent trade is normal; say so, because
            # this is the exact ambiguity the file exists to resolve.
            notes.append(f"{name}: engine alive; last paper change "
                         f"{b['paper_updated_at']} (quiet periods are normal)")

    return {
        "as_of_utc": _iso(now),
        "host": os.uname().nodename if hasattr(os, "uname") else "?",
        "verdict": verdict,
        "stale_after_minutes": stale_min,
        "books": books,
        "notes": notes,
    }


def _bucket(now_ts: float, bucket_min: int) -> str:
    """A label that is identical for every run inside the same time bucket."""
    if bucket_min <= 0:
        return "every-run"
    return str(int(now_ts // (bucket_min * 60)))


def write_if_due(root: Path, data: dict, bucket: str, force: bool) -> tuple[bool, str]:
    """Write the heartbeat only when it is due. Returns (wrote, reason)."""
    out = root / OUT_REL
    previous = _read_json(out) or {}
    if not force:
        if previous.get("bucket") == bucket and previous.get("verdict") == data["verdict"]:
            return False, (f"not due (bucket {bucket}, verdict {data['verdict']} "
                           f"unchanged since {previous.get('as_of_utc')})")
        # A verdict flip is worth a commit immediately, even mid-bucket: that
        # is the one transition the file exists to record.
        reason = "verdict changed" if previous.get("bucket") == bucket else "bucket rolled"
        return _write(out, data, bucket), reason
    return _write(out, data, bucket), "forced"


def _write(out: Path, data: dict, bucket: str) -> bool:
    payload = dict(data, bucket=bucket)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    try:
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, out)          # atomic: a reader never sees half a file
        return True
    except Exception as e:            # never break the caller
        print(f"heartbeat: could not write {out}: {e}", file=sys.stderr)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Write the published engine liveness heartbeat.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(ROOT), help="repo checkout to inspect")
    ap.add_argument("--force", action="store_true", help="write even if not due")
    ap.add_argument("--check", action="store_true",
                    help="print the heartbeat, never write; exit 1 unless verdict is ok")
    ap.add_argument("--bucket-minutes", type=int, default=DEFAULT_BUCKET_MIN,
                    help=f"how often to rewrite (default {DEFAULT_BUCKET_MIN}; 0 = every run)")
    ap.add_argument("--stale-minutes", type=float, default=DEFAULT_STALE_MIN,
                    help=f"age at which the engine counts as not running "
                         f"(default {DEFAULT_STALE_MIN:g})")
    ap.add_argument("--json", action="store_true", help="emit the payload on stdout")
    args = ap.parse_args(argv)

    root = Path(args.repo).resolve()
    now_ts = time.time()
    data = build(root, args.stale_minutes, now_ts)

    if args.check:
        print(json.dumps(data, indent=2, sort_keys=True))
        return 0 if data["verdict"] == "ok" else 1

    wrote, reason = write_if_due(root, data, _bucket(now_ts, args.bucket_minutes), args.force)
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        detail = " ".join(
            f"{n}={b['verdict']}"
            + (f"({b['engine_status_age_min']:.0f}m)" if b["engine_status_age_min"] is not None
               else "(no file)")
            for n, b in data["books"].items())
        print(f"heartbeat: {data['as_of_utc']} verdict={data['verdict']} {detail}"
              f" -> {'wrote' if wrote else 'skipped'}: {reason}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
