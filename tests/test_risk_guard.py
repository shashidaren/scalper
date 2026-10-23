#!/usr/bin/env python3
"""Unit tests for `risk_guard` — the clock exits and the equity floor.

What has to hold:

  * the **weekend window** is Friday `WEEKEND_FLAT_HOUR_UTC`:00 -> Monday 00:00
    **UTC**, and nothing else. The engine's other timestamps are local, so
    `_to_utc` must convert rather than relabel.
  * a **latched** floor: once equity touches it, new entries stay blocked even
    after equity bounces, because a floor that un-trips re-enters a broken book.
  * a **bad reading never latches it**: an equity of 0 or NaN is a broker
    hiccup, not a catastrophe.
  * the paper account actually closes on both rules, at the exit-side price,
    with the right reason, and the ordinary SL/TP path is untouched.

Every case pins `now`, so the suite behaves identically on a Tuesday and on a
Saturday night.
Run:  python3 tests/test_risk_guard.py      # exit 0 = PASS
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import risk_guard  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append(bool(ok))


# Wednesday 2026-10-21 12:00 UTC - deliberately not near a boundary.
WED = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
FRI_EARLY = datetime(2026, 10, 23, 19, 59, tzinfo=timezone.utc)
FRI_LATE = datetime(2026, 10, 23, 20, 0, tzinfo=timezone.utc)
SAT = datetime(2026, 10, 24, 3, 0, tzinfo=timezone.utc)
SUN = datetime(2026, 10, 25, 21, 0, tzinfo=timezone.utc)
MON = datetime(2026, 10, 26, 0, 1, tzinfo=timezone.utc)


def _cfg(config=config, **kw):
    """Set-and-restore is overkill here: the suite is one process, and every
    value set below is restored by the next `_cfg` call. Explicit beats magic."""
    for k, v in kw.items():
        setattr(config, k, v)


def main() -> int:
    # ------------------------------------------------------- weekend window
    print("weekend window (UTC)")
    _cfg(WEEKEND_FLAT_ENABLED=True, WEEKEND_FLAT_HOUR_UTC=20, MAX_HOLD_MINUTES=0)
    check("Wednesday is not the weekend", not risk_guard.in_weekend_window(WED))
    check("Friday 19:59 is not the weekend", not risk_guard.in_weekend_window(FRI_EARLY))
    check("Friday 20:00 is the weekend", risk_guard.in_weekend_window(FRI_LATE))
    check("Saturday is the weekend", risk_guard.in_weekend_window(SAT))
    check("Sunday is the weekend", risk_guard.in_weekend_window(SUN))
    check("Monday 00:01 is not the weekend", not risk_guard.in_weekend_window(MON))
    check("the hour is configurable",
          not risk_guard.in_weekend_window(FRI_LATE, hour=21)
          and risk_guard.in_weekend_window(datetime(2026, 10, 23, 21, 0, tzinfo=timezone.utc),
                                           hour=21))
    check("next boundary from Wednesday is that Friday",
          risk_guard.next_weekend_boundary(WED) == FRI_LATE)

    print("timestamp normalisation")
    aware = risk_guard._to_utc(WED)
    naive = risk_guard._to_utc(WED.replace(tzinfo=None))
    check("an aware datetime keeps its instant", aware == WED)
    check("a naive datetime is read as local",
          naive == WED.replace(tzinfo=None).astimezone(timezone.utc))
    epoch = risk_guard._to_utc(WED.timestamp())
    check("an epoch is absolute", epoch == WED)
    check("a string is parsed", risk_guard._to_utc("2026-10-21 12:00:00") is not None)
    check("junk is None, not a crash", risk_guard._to_utc("not-a-date") is None
          and risk_guard._to_utc(None) is None)

    # ------------------------------------------------------------- due_exit
    print("due_exit")
    check("no rule fires on a Wednesday", risk_guard.due_exit("2026-10-21 11:00:00", WED) is None)
    opened_friday = "2026-10-23 10:00:00"
    check("the weekend flat fires inside the window",
          risk_guard.due_exit(opened_friday, FRI_LATE + timedelta(minutes=5)) == "WEEKEND")
    check("nothing fires just before the window",
          risk_guard.due_exit(opened_friday, FRI_EARLY) is None)
    check("a hold cap fires after the limit",
          risk_guard.due_exit("2026-10-21 09:00:00", WED, max_hold_minutes=60) == "TIME")
    check("a hold cap does not fire before the limit",
          risk_guard.due_exit("2026-10-21 11:30:00", WED, max_hold_minutes=60) is None)
    check("0 disables the hold cap",
          risk_guard.due_exit("2026-10-21 00:00:00", WED, max_hold_minutes=0) is None)
    check("the weekend rule wins when both fire",
          risk_guard.due_exit("2026-10-23 10:00:00", FRI_LATE + timedelta(hours=5),
                              max_hold_minutes=60) == "WEEKEND")
    check("an unparseable open time does not crash the hold cap",
          risk_guard.due_exit(None, WED, max_hold_minutes=60) is None)
    _cfg(WEEKEND_FLAT_ENABLED=False)
    check("WEEKEND_FLAT_ENABLED=False disables the flat",
          risk_guard.due_exit(opened_friday, FRI_LATE + timedelta(minutes=5)) is None)
    _cfg(WEEKEND_FLAT_ENABLED=True)

    # ---------------------------------------------------------- equity floor
    print("equity floor")
    tmp = Path(tempfile.mkdtemp(prefix="risk_guard_"))
    _cfg(EQUITY_FLOOR_ENABLED=True, EQUITY_FLOOR_MODE="start", EQUITY_FLOOR_PCT=50.0)
    logs = []
    fl = risk_guard.EquityFloor(state_file=tmp / "floor.json",
                                log=lambda lv, m: logs.append((lv, m)))
    fl.observe(300.0)
    check("the first observation sets the reference", fl.start == 300.0)
    fl.observe(420.0)
    check("the peak tracks new highs", fl.peak == 420.0)
    check("a 50% floor of start is $150", fl.floor_value() == 150.0)
    check("equity above the floor is not blocked", fl.blocked(280.0)[0] is False)
    check("the reference does not creep up as the account grows", fl.start == 300.0)
    blocked, reason = fl.blocked(150.0)
    check("touching the floor blocks entries", blocked is True, reason)
    check("the trip is latched with a timestamp", fl.halted_at is not None)
    check("the trip is logged at ERROR",
          any(lv == "ERROR" and "EQUITY FLOOR HIT" in m for lv, m in logs))
    check("a recovery does NOT un-block (latched)", fl.blocked(400.0)[0] is True)
    check("the halted state survives a restart",
          risk_guard.EquityFloor(state_file=tmp / "floor.json").blocked()[0] is True)

    print("equity floor: bad readings and modes")
    fl2 = risk_guard.EquityFloor(state_file=tmp / "floor2.json",
                                 log=lambda lv, m: logs.append((lv, m)))
    fl2.observe(300.0)
    for bad in (0, -5, float("nan"), float("inf"), None, "abc"):
        fl2.observe(bad)
        fl2.blocked(bad)
    check("a zero/NaN/unparseable equity never latches", fl2.halted_at is None)
    check("a bad reading does not move the reference", fl2.start == 300.0)

    _cfg(EQUITY_FLOOR_MODE="peak")
    fl3 = risk_guard.EquityFloor(state_file=tmp / "floor3.json", log=lambda *a: None)
    fl3.observe(300.0)
    fl3.observe(600.0)
    fl3.observe(400.0)
    check("peak mode trails the high-water mark", fl3.floor_value() == 300.0)
    check("peak mode blocks below the trailing floor", fl3.blocked(299.0)[0] is True)

    _cfg(EQUITY_FLOOR_ENABLED=False)
    fl4 = risk_guard.EquityFloor(state_file=tmp / "floor4.json", log=lambda *a: None)
    fl4.observe(300.0)
    check("disabled means no floor at all",
          fl4.floor_value() is None and fl4.blocked(1.0)[0] is False)
    _cfg(EQUITY_FLOOR_ENABLED=True, EQUITY_FLOOR_MODE="start")

    print("equity floor: reset")
    (tmp / "floor5.json").write_text(json.dumps({"start": 300.0, "peak": 300.0,
                                                 "halted_at": "2026-10-20 10:00:00",
                                                 "halt_equity": 150.0}))
    fl5 = risk_guard.EquityFloor(state_file=tmp / "floor5.json", log=lambda *a: None)
    check("a latched floor reloads as latched", fl5.blocked()[0] is True)
    (tmp / "floor5.json").unlink()
    fl5 = risk_guard.EquityFloor(state_file=tmp / "floor5.json", log=lambda *a: None)
    check("deleting the state file clears the latch", fl5.blocked()[0] is False)

    # ------------------------------------------------- paper account wiring
    print("paper account: the same rules, actually applied")
    import paper as paper_mod

    paper_mod.log_system = lambda *a, **k: None
    paper_mod.log_trade = lambda *a, **k: None
    paper_mod.update_daily_pnl = lambda *a, **k: None
    _cfg(MAX_HOLD_MINUTES=0, WEEKEND_FLAT_ENABLED=True, BE_TRIGGER_R=1.5)

    def fresh(name, **kw):
        return paper_mod.PaperAccount(state_file=tmp / name, **kw)

    acc = fresh("p_weekend.json")
    acc.open("BUY", 4000.0, 8.0, 20.0)
    acc.position["time"] = "2026-10-23 10:00:00"
    info = acc.on_tick(4001.0, 4002.0, now=FRI_LATE + timedelta(minutes=5))
    check("paper closes at the Friday boundary", info and info["reason"] == "WEEKEND", str(info))
    check("the weekend close is booked into the balance", acc.closed == 1)
    check("the weekend counter moved", acc.weekend_exits == 1)
    check("a weekend close counts in the win/loss tally", acc.wins + acc.losses == 1)
    check("the exit price is the exit-side quote (bid for a BUY)",
          round(acc.balance, 2) == round(300.0 + (4001.0 - 4000.0) * 0.01 * 100, 2),
          str(acc.balance))

    acc = fresh("p_noweekend.json")
    acc.open("BUY", 4000.0, 8.0, 20.0)
    acc.position["time"] = "2026-10-21 11:00:00"
    check("nothing closes on a Wednesday",
          acc.on_tick(4001.0, 4002.0, now=WED) is None)

    _cfg(MAX_HOLD_MINUTES=60)
    acc = fresh("p_hold.json")
    acc.open("SELL", 4000.0, 8.0, 20.0)
    acc.position["time"] = "2026-10-21 11:30:00"      # 30 min before WED
    check("the hold cap does not fire early",
          acc.on_tick(4000.0, 4001.0, now=WED) is None)
    info = acc.on_tick(4000.0, 4001.0, now=WED + timedelta(hours=1, minutes=1))
    check("the hold cap closes at market", info and info["reason"] == "TIME", str(info))
    check("a TIME exit stays out of the win/loss tally", acc.time_exits == 1)
    _cfg(MAX_HOLD_MINUTES=0)

    acc = fresh("p_sl.json")
    acc.open("BUY", 4000.0, 8.0, 20.0)
    acc.position["time"] = "2026-10-23 10:00:00"
    info = acc.on_tick(3991.0, 3991.5, now=FRI_LATE + timedelta(minutes=5))
    check("a price exit still wins over the clock exit", info and info["reason"] == "SL")
    check("the clock rule did not steal the trade", acc.weekend_exits == 0)

    acc = fresh("p_nobe.json")
    acc.position = {"side": "BUY", "entry": 4000.0, "sl": 3992.0, "tp": 4020.0,
                    "sl_dist": 8.0, "tp_dist": 20.0, "volume": 0.01,
                    "be_armed": False, "time": "2026-10-21 11:00:00"}
    acc.on_tick(4016.0, 4016.5, now=WED)
    check("BE arming still works alongside the clock code",
          acc.position is not None and acc.position["sl"] == 4000.0,
          str(acc.position.get("sl") if acc.position else None))

    # ------------------------------------------------------------- wiring
    # The rules only exist if every engine path actually consults them. Pin
    # the three call sites and the ordering in run.py (the floor must be
    # evaluated where equity is known and applied next to the kill switch).
    print("wiring")
    src = (ROOT / "run.py").read_text()
    check("run.py builds the equity floor", src.count("risk_guard.EquityFloor()") == 1)
    check("run.py evaluates it exactly once", src.count("equity_floor.blocked(") == 1)
    floor_block = src.split("if floor_blocked:", 1)[1].split("\n\n", 1)[0] \
        if "if floor_blocked:" in src else ""
    check("the floor is applied as an entry block", "continue" in floor_block)
    check("the floor block sits after the kill switch",
          src.index("if floor_blocked:") > src.index("if kill_active:"))
    check("run.py blocks entries inside the weekend window",
          "risk_guard.in_weekend_window()" in src)
    check("paper exits consult the clock rules",
          "risk_guard.due_exit(" in (ROOT / "paper.py").read_text())
    check("live exits consult the clock rules",
          "risk_guard.due_exit(" in (ROOT / "live_position.py").read_text())

    failed = [i for i, ok in enumerate(RESULTS) if not ok]
    print(f"\n{'ALL PASS' if not failed else 'FAILURES'}: "
          f"{len(RESULTS) - len(failed)}/{len(RESULTS)} risk-guard checks")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
