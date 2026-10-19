#!/usr/bin/env python3
"""Unit tests for the paper-account safety guards.

These cover the ports from gold-trading-bot (2026-10-20) that must not change
the book's behaviour when the inputs are sane:

  * invalid / non-finite / zero geometry never moves money
  * a persisted position that fails the check is quarantined, not trusted
  * the optional time stop (MAX_HOLD_MINUTES) is its own neutral bucket
  * price exits still take priority over the time stop

Pure standard library + the repo modules. No MT5, no bridge, no network.
Run:  python3 tests/test_paper_guards.py      # exit 0 = PASS
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import paper  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append(bool(ok))


def _silence():
    """Send the module's side effects to /dev/null for the whole test."""
    paper.log_system = lambda *a, **k: None
    paper.log_trade = lambda *a, **k: None
    paper.update_daily_pnl = lambda *a, **k: None


def _fresh(tmp, **kw):
    return paper.PaperAccount(state_file=tmp / "paper_account.json", **kw)


def main() -> int:
    _silence()
    tmp = Path(tempfile.mkdtemp(prefix="paper_guards_"))

    print("position geometry")
    good = {"side": "BUY", "entry": 4000.0, "sl": 3990.0, "tp": 4025.0,
            "sl_dist": 10.0, "tp_dist": 25.0, "volume": 0.01, "be_armed": False,
            "time": "2026-10-20 00:00:00"}
    check("a well-formed position is valid", paper.valid_position(good))
    for key, bad in (("entry", 0), ("entry", float("nan")), ("sl", -1),
                     ("sl_dist", 0), ("volume", 0), ("tp", 0),
                     ("tp", float("inf")), ("side", "HOLD")):
        p = dict(good)
        p[key] = bad
        check(f"rejects {key}={bad!r}", not paper.valid_position(p))
    p = dict(good)
    p["tp"] = None
    check("no-TP shape (tp=None) is valid", paper.valid_position(p))
    check("rejects a non-dict", not paper.valid_position(["BUY"]))

    print("open() refuses bad geometry")
    acc = _fresh(tmp / "a")
    check("NaN entry refused", acc.open("BUY", float("nan"), 10.0, 25.0) is None)
    check("zero sl_dist refused", acc.open("BUY", 4000.0, 0.0, 25.0) is None)
    check("negative volume refused",
          acc.open("BUY", 4000.0, 10.0, 25.0, volume=-0.01) is None)
    check("unknown side refused", acc.open("HOLD", 4000.0, 10.0, 25.0) is None)
    check("nothing was opened", acc.position is None)
    check("balance untouched", acc.balance == 300.0)

    print("on_tick() refuses bad quotes and bad geometry")
    acc = _fresh(tmp / "b")
    acc.open("BUY", 4000.0, 10.0, 25.0)
    check("NaN bid ignored", acc.on_tick(float("nan"), 4001.0) is None)
    check("zero ask ignored", acc.on_tick(4000.0, 0.0) is None)
    check("position survives a bad tick", acc.position is not None)
    acc.position["entry"] = 0.0                     # corrupt it the way the
    check("corrupt geometry blocks booking", acc.on_tick(4026.0, 4027.0) is None)
    check("still open, no P&L booked", len(acc.position) > 0 and acc.balance == 300.0)

    print("close() refuses an invalid exit")
    acc = _fresh(tmp / "c")
    acc.open("SELL", 4000.0, 10.0, 25.0)
    check("NaN exit refused", acc.close(float("nan"), "TP") is None)
    check("zero exit refused", acc.close(0.0, "TP") is None)
    check("position kept open", acc.position is not None and acc.balance == 300.0)

    print("valid closes still book exactly")
    acc = _fresh(tmp / "d")
    acc.open("BUY", 4000.0, 10.0, 25.0)
    info = acc.close(4010.0, "TP")
    # 10 USD * 0.01 lots * 100 oz = $10
    check("P&L is exact", info is not None and info["profit"] == 10.0, str(info))
    check("balance is exact", acc.balance == 310.0 and acc.wins == 1)
    check("state file parses after save",
          json.loads((tmp / "d" / "paper_account.json").read_text())["balance"] == 310.0)

    print("persisted-state guards")
    bad_dir = tmp / "e"
    bad_dir.mkdir(parents=True)
    (bad_dir / "paper_account.json").write_text(json.dumps({
        "balance": 250.0,
        "position": {"side": "BUY", "entry": 0, "sl": 1, "tp": 0,
                     "sl_dist": 0, "volume": 0.01},
        "closed": 5, "wins": 1, "losses": 4,
    }))
    acc = paper.PaperAccount(state_file=bad_dir / "paper_account.json")
    check("invalid persisted position is dropped", acc.position is None)
    check("its counters are kept", acc.closed == 5 and acc.losses == 4)
    moved = list(bad_dir.glob("paper_account.json.invalid-*"))
    check("the bad file is quarantined, not deleted", len(moved) == 1)
    check("quarantine still holds the evidence",
          moved and json.loads(moved[0].read_text())["balance"] == 250.0)

    nan_dir = tmp / "f"
    nan_dir.mkdir(parents=True)
    (nan_dir / "paper_account.json").write_text(
        '{"balance": NaN, "position": null, "closed": 0}')
    acc = paper.PaperAccount(state_file=nan_dir / "paper_account.json")
    check("non-finite balance falls back to SIM_START_BALANCE", acc.balance == 300.0)

    zero_dir = tmp / "g"
    zero_dir.mkdir(parents=True)
    (zero_dir / "paper_account.json").write_text(
        '{"balance": -12.5, "position": null, "closed": 3}')
    acc = paper.PaperAccount(state_file=zero_dir / "paper_account.json")
    check("a finite negative balance is kept honestly", acc.balance == -12.5)

    print("time stop (MAX_HOLD_MINUTES, opt-in)")
    acc = _fresh(tmp / "h", max_hold_minutes=240)
    acc.open("BUY", 4000.0, 10.0, 100.0)          # TP far away, SL far away
    acc.position["time"] = (datetime.now() - timedelta(minutes=239)).strftime(
        "%Y-%m-%d %H:%M:%S")
    check("not yet due at 239 min", acc.on_tick(4001.0, 4002.0) is None)
    acc.position["time"] = (datetime.now() - timedelta(minutes=241)).strftime(
        "%Y-%m-%d %H:%M:%S")
    info = acc.on_tick(4001.0, 4002.0)
    check("closes at 241 min with reason TIME",
          info is not None and info["reason"] == "TIME", str(info))
    check("TIME is its own bucket",
          acc.time_exits == 1 and acc.wins == 0 and acc.losses == 0)
    check("TIME still moves the balance", acc.balance != 300.0)

    print("price exits win over the time stop")
    acc = _fresh(tmp / "i", max_hold_minutes=10)
    acc.open("BUY", 4000.0, 10.0, 100.0)
    acc.position["time"] = (datetime.now() - timedelta(minutes=600)).strftime(
        "%Y-%m-%d %H:%M:%S")
    info = acc.on_tick(3985.0, 3986.0)            # through the SL
    check("SL prints, not TIME", info is not None and info["reason"] == "SL", str(info))
    check("counted as a loss", acc.losses == 1 and acc.time_exits == 0)

    print("default book is unchanged")
    acc = _fresh(tmp / "j")
    check("MAX_HOLD_MINUTES defaults to 0 (disabled)", acc._max_hold() == 0)
    acc.open("BUY", 4000.0, 10.0, 25.0)
    acc.position["time"] = (datetime.now() - timedelta(days=30)).strftime(
        "%Y-%m-%d %H:%M:%S")
    check("no time exit when disabled", acc.on_tick(4001.0, 4002.0) is None)

    acc = _fresh(tmp / "k")
    acc.open("BUY", 4000.0, 10.0, 25.0)
    acc.on_tick(4016.0, 4017.0)                   # +1.6R -> BE arms (1.5R)
    check("BE ratchet still arms at config.BE_TRIGGER_R",
          acc.position["be_armed"] is True and acc.position["sl"] == 4000.0)

    failed = RESULTS.count(False)
    print(f"\n{'ALL PASS' if failed == 0 else str(failed) + ' FAILED'}: "
          f"{RESULTS.count(True)}/{len(RESULTS)} paper-guard checks")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
