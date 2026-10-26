#!/usr/bin/env python3
"""Deploy gate for tools/autosync.sh — the scalper's `smoke_test.py`.

Autosync reads only this script's exit code (0 = deploy, non-zero = roll back to
the pre-merge SHA), so the checks have to be:

  * **hermetic** — every test below uses a temp dir or pure arithmetic. Nothing
    reads the live `logs/`, the live config state, or the MT5 bridge. A scenario
    that goes red because the paper book had a bad day would roll back a good
    deploy;
  * **fast** — it runs while the engine is stopped, so a wedged check is an
    outage;
  * **honest about skips** — a missing optional dependency is reported as SKIP,
    but the engine-import check below is the thing that decides whether the
    environment can run the bot at all.

What it proves:
  1. every tracked `*.py` still parses;
  2. the engine's own modules import (pandas, numpy, rpyc included);
  3. the pure-logic suites pass (spread gate, risk sizer, paper guards);
  4. the BTC instance suites pass (preflight, edge screen, strategy, deploy
     service policy).

    python3 tools/smoke_test.py            # exit 0 = PASS
    python3 tools/smoke_test.py --list     # show the checks
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", "venv", "mt5env", "logs", "data",
             "__pycache__", "node_modules", "quarantine"}

ENGINE_MODULES = [
    "config", "logger", "strategy", "paper", "spread_gate", "risk_sizer",
    "portfolio", "live_ledger", "live_position", "risk_guard", "mt5_bridge", "run",
    # Read-only projections behind the dashboard's SCALP tab. Imported here so a
    # syntax-OK module that cannot resolve its own imports still fails the gate.
    "scalp_view",
]

# (label, argv-relative-to-root, modules that must be importable)
SCRIPTS = [
    ("spread gate", ["tests/test_spread_gate.py"], []),
    ("risk sizer", ["tests/test_risk_sizer.py"], []),
    ("paper guards", ["tests/test_paper_guards.py"], []),
    ("live position guards", ["tests/test_live_position_guards.py"], []),
    ("mt5 SLTP primitives", ["tests/test_mt5_bridge_sltp.py"], []),
    ("risk guard", ["tests/test_risk_guard.py"], []),
    ("repair tool", ["tests/test_repair_phantom_ledger.py"], []),
    ("check_data", ["tests/test_check_data.py"], []),
    ("heartbeat", ["tests/test_heartbeat.py"], []),
    ("ledger export", ["tests/test_ledger_export.py"], []),
    ("scalp view", ["tests/test_scalp_view.py"], []),
    ("btc preflight", ["btc/preflight_test.py"], ["pandas", "numpy"]),
    ("btc edge screen", ["btc/edge_screen_test.py"], ["pandas", "numpy"]),
    ("btc strategy", ["btc/strategy_btc_test.py"], ["pandas", "numpy", "rpyc"]),
    ("deploy service policy", ["tests/test_deploy_services.sh"], []),
    # Skipped inside autosync's own gate: this suite runs autosync.sh, and
    # autosync runs this gate. Bounded either way, but there is no point
    # paying for eight sandboxes during a deploy.
    ("autosync", ["tests/test_autosync.sh"], []),
]

TIMEOUT = 300


def _python_files():
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def check_syntax():
    bad = []
    for path in _python_files():
        try:
            # compile() only: never leaves a __pycache__ behind in a gate that
            # can run against a read-only-ish checkout.
            compile(path.read_text(errors="replace"), str(path), "exec")
        except SyntaxError as e:
            bad.append(f"{path.relative_to(ROOT)}:{e.lineno}: {e.msg}")
        except Exception as e:                       # unreadable file
            bad.append(f"{path.relative_to(ROOT)}: {e}")
    return bad


def check_imports():
    sys.path.insert(0, str(ROOT))
    bad = []
    for name in ENGINE_MODULES:
        try:
            __import__(name)
        except Exception as e:
            bad.append(f"{name}: {type(e).__name__}: {e}")
    return bad


def check_script(label, rel_argv, needs):
    missing = [m for m in needs if importlib.util.find_spec(m) is None]
    if missing:
        return "SKIP", f"missing {', '.join(missing)}"
    argv = list(rel_argv)
    if argv[0].endswith(".sh"):
        cmd = ["bash"] + [str(ROOT / argv[0])] + argv[1:]
    else:
        cmd = [sys.executable] + [str(ROOT / argv[0])] + argv[1:]
    try:
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                              text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        return "FAIL", f"timed out after {TIMEOUT}s"
    if proc.returncode == 0:
        tail = (proc.stdout or "").strip().splitlines()
        return "PASS", tail[-1] if tail else ""
    tail = (proc.stderr or proc.stdout or "").strip().splitlines()
    return "FAIL", f"exit {proc.returncode}: {tail[-1] if tail else 'no output'}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="list the checks and exit")
    args = ap.parse_args(argv)

    if args.list:
        print("syntax: every *.py parses")
        print(f"imports: {', '.join(ENGINE_MODULES)}")
        for label, rel, needs in SCRIPTS:
            print(f"script: {label} ({rel[0]}" + (f", needs {', '.join(needs)})" if needs else ")"))
        return 0

    print(f"smoke test — {ROOT}")
    results = []

    print("  syntax")
    bad = check_syntax()
    if bad:
        for b in bad[:10]:
            print(f"    [FAIL] {b}")
        results.append(("syntax", False))
    else:
        print("    [PASS] every *.py parses")
        results.append(("syntax", True))

    print("  engine imports")
    bad = check_imports()
    if bad:
        for b in bad:
            print(f"    [FAIL] {b}")
        results.append(("imports", False))
    else:
        print(f"    [PASS] {len(ENGINE_MODULES)} modules import")
        results.append(("imports", True))

    print("  suites")
    for label, rel, needs in SCRIPTS:
        if label == "autosync" and os.environ.get("AUTOSYNC_SMOKE") == "1":
            print("    [SKIP] autosync — would recurse inside the autosync gate")
            results.append((label, True))
            continue
        status, detail = check_script(label, rel, needs)
        print(f"    [{status}] {label}" + (f" — {detail}" if detail else ""))
        results.append((label, status != "FAIL"))

    failed = [name for name, ok in results if not ok]
    skipped = sum(1 for _, _, needs in SCRIPTS
                  if needs and any(importlib.util.find_spec(m) is None for m in needs))
    print()
    if failed:
        print(f"SMOKE TEST FAILED: {', '.join(failed)}")
        if skipped:
            print(f"({skipped} suite(s) skipped for missing optional modules)")
        return 1
    print(f"SMOKE TEST PASSED ({len(results)} checks"
          f"{', ' + str(skipped) + ' skipped' if skipped else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
