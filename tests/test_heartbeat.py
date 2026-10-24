#!/usr/bin/env python3
"""Unit tests for tools/heartbeat.py.

The file exists to answer one question from a repo checkout — "is the engine
actually looping, or did it die on Friday night?" — so the things that must
hold are:

  * a MISSING live_status.json is never reported as ok (that would be the exact
    false reassurance the tool was built to prevent);
  * an OLD live_status.json is reported as stale, at the documented threshold;
  * a fresh one is ok, and a quiet book is still ok (idle != dead);
  * it does not rewrite the file on every run (the commit-noise guard), but
    does rewrite when the bucket rolls or the verdict flips;
  * it never raises on a broken/missing repo, and it only ever writes
    logs/heartbeat.json inside the repo it was pointed at.

Run:  python3 tests/test_heartbeat.py      # exit 0 = PASS
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append(bool(ok))


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "heartbeat", ROOT / "tools" / "heartbeat.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_repo(tmp: Path, *, gold_age_min=None, btc_age_min=None,
              gold_state=None, btc_state=None) -> Path:
    """A fake checkout. Age is set by backdating the file's mtime."""
    for name, age, state in (("gold", gold_age_min, gold_state),
                             ("btc", btc_age_min, btc_state)):
        log_dir = tmp / "logs" if name == "gold" else tmp / "btc" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        (log_dir / "paper_account.json").write_text(json.dumps(
            {"balance": 300.0, "position": None, "closed": 0,
             "wins": 0, "losses": 0, "updated_at": "2026-10-24 00:00:00"}))
        if age is not None:
            live = log_dir / "live_status.json"
            live.write_text(json.dumps(state or {
                "connected": True, "mode": "FORWARD_TEST", "positions": [],
                "spread_gate": {"state": "ok"}, "updated_at": "x"}))
            when = time.time() - age * 60.0
            os.utime(live, (when, when))
    return tmp


def run(tool, *argv):
    buf = io.StringIO()
    with redirect_stdout(buf), redirect_stderr(buf):
        rc = tool.main([str(a) for a in argv])
    return rc, buf.getvalue()


def main() -> int:
    tool = load_tool()

    # --- 1. missing live_status.json is UNKNOWN, never "ok" ---------------
    tmp = Path(tempfile.mkdtemp(prefix="hb_missing_"))
    make_repo(tmp)
    data = tool.build(tmp, stale_min=10)
    check("a missing live_status.json -> btc verdict unknown",
          data["books"]["btc"]["verdict"] == "unknown")
    check("... and the overall verdict is unknown",
          data["verdict"] == "unknown")
    check("... and a note explains it rather than staying silent",
          any("no live_status.json" in n for n in data["notes"]))

    # --- 2. freshness thresholds ------------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="hb_stale_"))
    make_repo(tmp, gold_age_min=0.5, btc_age_min=120)
    data = tool.build(tmp, stale_min=10)
    check("an engine 30 s old -> ok", data["books"]["gold"]["verdict"] == "ok",
          f"age={data['books']['gold']['engine_status_age_min']}m")
    check("an engine 2 h old -> stale", data["books"]["btc"]["verdict"] == "stale")
    check("one stale book makes the overall verdict stale",
          data["verdict"] == "stale")
    check("the note names the age and the limit",
          any("is not looping" in n and "limit 10" in n for n in data["notes"]))

    # --- 3. idle is not dead ----------------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="hb_idle_"))
    make_repo(tmp, gold_age_min=0.2, btc_age_min=0.2)
    data = tool.build(tmp, stale_min=10)
    check("both engines fresh with no recent trade -> ok",
          data["verdict"] == "ok")
    check("... and the note says a quiet book is normal",
          any("quiet periods are normal" in n for n in data["notes"]))

    # --- 4. the commit-noise guard ----------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="hb_bucket_"))
    make_repo(tmp, gold_age_min=0.2, btc_age_min=0.2)
    out = tmp / "logs" / "heartbeat.json"

    rc, txt = run(tool, "--repo", tmp, "--bucket-minutes", 60)
    check("first run writes the file", out.exists(), txt.strip()[-70:])
    first = json.loads(out.read_text())
    check("the write records a bucket and an as_of timestamp",
          bool(first.get("bucket")) and first.get("as_of_utc", "").endswith("Z"))

    before = out.read_text()
    rc, txt = run(tool, "--repo", tmp, "--bucket-minutes", 60)
    check("a second run in the same bucket does not rewrite",
          out.read_text() == before and "not due" in txt, txt.strip()[-60:])
    check("... and still exits 0", rc == 0, f"rc={rc}")

    rc, txt = run(tool, "--repo", tmp, "--bucket-minutes", 60, "--force")
    check("--force rewrites within the bucket",
          "forced" in txt and rc == 0, txt.strip()[-60:])

    # a verdict flip must be published immediately, mid-bucket
    make_repo(tmp, gold_age_min=0.2, btc_age_min=999)
    rc, txt = run(tool, "--repo", tmp, "--bucket-minutes", 60)
    check("a verdict flip rewrites immediately (mid-bucket)",
          json.loads(out.read_text())["verdict"] == "stale" and "verdict changed" in txt,
          txt.strip()[-60:])

    # bucket 0 = rewrite every run
    run(tool, "--repo", tmp, "--bucket-minutes", 0)
    check("bucket 0 rewrites on every run",
          json.loads(out.read_text()).get("bucket") == "every-run")

    # --- 5. --check never writes and signals staleness ---------------------
    tmp = Path(tempfile.mkdtemp(prefix="hb_check_"))
    make_repo(tmp, gold_age_min=0.2, btc_age_min=999)
    out = tmp / "logs" / "heartbeat.json"
    rc, txt = run(tool, "--repo", tmp, "--check")
    check("--check exits 1 when a book is stale", rc == 1, f"rc={rc}")
    check("--check does not write", not out.exists())
    check("--check emits parseable json", "verdict" in json.loads(txt))

    tmp = Path(tempfile.mkdtemp(prefix="hb_check_ok_"))
    make_repo(tmp, gold_age_min=0.2, btc_age_min=0.2)
    rc, _ = run(tool, "--repo", tmp, "--check")
    check("--check exits 0 when both books are alive", rc == 0, f"rc={rc}")

    # --- 6. robustness and containment ------------------------------------
    tmp = Path(tempfile.mkdtemp(prefix="hb_broken_"))
    (tmp / "logs").mkdir()
    (tmp / "logs" / "live_status.json").write_text("{not json")
    (tmp / "logs" / "paper_account.json").write_text("also not json")
    rc, txt = run(tool, "--repo", tmp)
    check("unparseable state files do not raise", rc == 0, f"rc={rc}")
    check("... and degrade to unknown, not ok",
          json.loads((tmp / "logs" / "heartbeat.json").read_text())["verdict"]
          != "ok")

    tmp = Path(tempfile.mkdtemp(prefix="hb_empty_repo_"))
    rc, _ = run(tool, "--repo", tmp)
    check("a repo with no logs/ at all does not raise", rc == 0, f"rc={rc}")
    written = sorted(p.relative_to(tmp).as_posix() for p in tmp.rglob("*.json"))
    check("it writes nothing but logs/heartbeat.json",
          written == ["logs/heartbeat.json"], f"{written}")

    failed = RESULTS.count(False)
    print(f"\n{'ALL PASS' if failed == 0 else str(failed) + ' FAILED'}: "
          f"{RESULTS.count(True)}/{len(RESULTS)} heartbeat checks")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
