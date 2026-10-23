#!/usr/bin/env python3
"""Unit tests for `live_position` — the LIVE-only stop guard.

Two behaviours are load-bearing and must not regress:

  * **proof of a stop.** `TRADE_RETCODE_DONE` is not evidence that the broker
    attached a stop, so every fill is followed by a read-back; a stop that is
    missing (or drifted by slippage) is re-sent, and one that still cannot be
    attached is closed or alerted rather than left naked.
  * **the BE ratchet matches the paper book.** 16.9% of the validated exits
    come from BE at 1.5R, and until 2026-10-23 that rule only existed in
    `paper.py`. LIVE now applies it, once, and only when the modify is
    confirmed.

Two invariants are tested just as hard:

  * `FORWARD_TEST` can never touch a position (defence in depth, even if a
    caller wires this in the wrong branch);
  * **nothing closes a position on a failed read.** `positions_get() -> None`
    is an RPC error, not "the position is gone".

Fake MT5 only: no bridge, no network, no files outside a temp dir.
Run:  python3 tests/test_live_position_guards.py      # exit 0 = PASS
"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config  # noqa: E402
import live_position  # noqa: E402

RESULTS = []

MAGIC = 999111
TICKET = 51_234_567


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append(bool(ok))


# --------------------------------------------------------------- fakes
class Pos:
    def __init__(self, ticket=TICKET, side="BUY", entry=4000.0, sl=0.0,
                 tp=0.0, volume=0.01, magic=MAGIC, profit=0.0):
        self.ticket = ticket
        self.type = 0 if side == "BUY" else 1
        self.volume = volume
        self.price_open = entry
        self.sl = sl
        self.tp = tp
        self.magic = magic
        self.profit = profit


class Sym:
    def __init__(self, point=0.01, digits=2, stops_level=0):
        self.point = point
        self.digits = digits
        self.trade_stops_level = stops_level


class Tick:
    def __init__(self, bid=4000.0, ask=4000.2):
        self.bid = bid
        self.ask = ask


class FakeMT5:
    """Just enough of the MetaTrader5 module for the guard's calls."""

    TRADE_ACTION_SLTP = 6
    TRADE_ACTION_DEAL = 1
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_NO_CHANGES = 10025
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0

    def __init__(self):
        self.positions = {}
        self.sends = []
        self.read_fails = 0          # positions_get() -> None this many times
        self.modify_fails = 0        # reject the next N SLTP requests
        self.modify_retcode = None   # force a specific retcode (e.g. NO_CHANGES)
        self.closes = []

    def order_send(self, request):
        self.sends.append(dict(request))
        if request.get("action") == self.TRADE_ACTION_SLTP:
            if self.modify_fails > 0:
                self.modify_fails -= 1
                return Resp(10013, "invalid stops")
            if self.modify_retcode is not None:
                rc = self.modify_retcode
            else:
                rc = self.TRADE_RETCODE_DONE
            if rc in (self.TRADE_RETCODE_DONE, self.TRADE_RETCODE_NO_CHANGES):
                pos = self.positions.get(request["position"])
                if pos is not None:
                    pos.sl = request["sl"]
                    pos.tp = request["tp"]
            return Resp(rc, "ok")
        if request.get("action") == self.TRADE_ACTION_DEAL:
            self.closes.append(dict(request))
            self.positions.pop(request.get("position"), None)
            return Resp(self.TRADE_RETCODE_DONE, "closed")
        return Resp(self.TRADE_RETCODE_DONE, "")


class Resp:
    def __init__(self, retcode, comment="", order=0):
        self.retcode = retcode
        self.comment = comment
        self.order = order
        self.deal = order


class FakeBridge:
    def __init__(self, mt5, sym=None, tick=None):
        self.mt5 = mt5
        self.sym = sym or Sym()
        self.tick = tick or Tick()

    def get_symbol_info(self):
        return self.sym

    def get_live_tick(self, retries=5):
        return self.tick

    def positions_get(self):
        if self.mt5.read_fails > 0:
            self.mt5.read_fails -= 1
            return None
        return list(self.mt5.positions.values())

    def modify_position_stops(self, ticket, sl, tp=None):
        rc_ok = {self.mt5.TRADE_RETCODE_DONE, self.mt5.TRADE_RETCODE_NO_CHANGES}
        self.mt5.sends.append({"action": self.mt5.TRADE_ACTION_SLTP,
                               "position": int(ticket), "sl": sl, "tp": tp})
        if self.mt5.modify_fails > 0:
            self.mt5.modify_fails -= 1
            return False, 10013, "invalid stops"
        rc = self.mt5.modify_retcode or self.mt5.TRADE_RETCODE_DONE
        if rc in rc_ok:
            pos = self.mt5.positions.get(int(ticket))
            if pos is not None:
                pos.sl = float(sl)
                pos.tp = float(tp or 0.0)
        return rc in rc_ok, rc, "ok"

    def close_position(self, ticket, comment="test"):
        self.mt5.closes.append({"position": int(ticket), "comment": comment})
        self.mt5.positions.pop(int(ticket), None)
        return True, "closed"


class FlakyBridge(FakeBridge):
    """Serves `ok_reads` successful reads, then fails every later one."""

    def __init__(self, mt5, ok_reads=1, **kw):
        super().__init__(mt5, **kw)
        self.ok_reads = ok_reads

    def positions_get(self):
        if self.ok_reads <= 0:
            return None
        self.ok_reads -= 1
        return list(self.mt5.positions.values())


# --------------------------------------------------------------- helpers
_ORIG = {}


@contextmanager
def cfg(**overrides):
    """Patch config for one case and restore every key afterwards."""
    saved = {}
    for k, v in overrides.items():
        saved[k] = getattr(config, k, _ORIG)
        setattr(config, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is _ORIG:
                delattr(config, k)
            else:
                setattr(config, k, v)


def guard_for(tmp, bridge, logs=None, name="live_positions.json"):
    logs = logs if logs is not None else []
    g = live_position.LivePositionGuard(
        bridge=bridge,
        state_file=Path(tmp) / name,
        log=lambda level, msg: logs.append((level, msg)),
        sleep_fn=lambda s: None)
    return g, logs


BASE_CFG = dict(TRADING_MODE="LIVE", LIVE_PROTECT_ENABLED=True,
                LIVE_STOP_VERIFY_ATTEMPTS=3, LIVE_STOP_VERIFY_SLEEP_SECONDS=0.0,
                LIVE_STOP_TOLERANCE_POINTS=5, LIVE_NAKED_POSITION_ACTION="close",
                LIVE_BE_ENABLED=True, LIVE_BE_TRIGGER_R=None, BE_TRIGGER_R=1.5,
                MAGIC_NUMBER=MAGIC, SYMBOL="GOLD", PRICE_DIGITS=2)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="live_guard_"))

    # ---------------------------------------------------------- gating
    print("gating: LIVE only, behind its own switch")
    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**dict(BASE_CFG, TRADING_MODE="FORWARD_TEST")):
        g, logs = guard_for(tmp, br, name="g_forward.json")
        check("FORWARD_TEST is never enabled", g.enabled is False)
        mt5.positions[TICKET] = Pos(sl=0.0)
        st = g.on_fill(Resp(10009), "BUY", 8.0, 20.0, 0.01)
        check("on_fill is a no-op in FORWARD_TEST", st["status"] == "disabled" and not mt5.sends)
        g.manage(list(mt5.positions.values()), Tick())
        check("manage is a no-op in FORWARD_TEST", not mt5.sends)

    with cfg(**dict(BASE_CFG, LIVE_PROTECT_ENABLED=False)):
        g, logs = guard_for(tmp, br, name="g_off.json")
        check("LIVE_PROTECT_ENABLED=False disables the guard", g.enabled is False)
        st = g.on_fill(Resp(10009), "BUY", 8.0, 20.0, 0.01)
        check("disabled guard sends nothing", st["status"] == "disabled" and not mt5.sends)

    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="g_on.json")
        check("LIVE + enabled is active", g.enabled is True)
        check("BE trigger inherits BE_TRIGGER_R (1.5R)", g.be_trigger_r == 1.5)
    with cfg(**dict(BASE_CFG, LIVE_BE_TRIGGER_R=0)):
        g, _ = guard_for(tmp, br, name="g_be0.json")
        check("LIVE_BE_TRIGGER_R=0 turns the ratchet off", g.be_trigger_r == 0.0)
    with cfg(**dict(BASE_CFG, LIVE_BE_ENABLED=False)):
        g, _ = guard_for(tmp, br, name="g_beff.json")
        check("LIVE_BE_ENABLED=False turns the ratchet off", g.be_trigger_r == 0.0)

    # ------------------------------------------------- verification: ok
    print("post-fill verification")
    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_ok.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("a correctly attached stop verifies without a modify",
              st["status"] == "ok" and not mt5.sends, str(st))
        check("the position is tracked", str(TICKET) in g.tracked)
        check("tracked state keeps sl_dist as the R unit",
              g.tracked[str(TICKET)]["sl_dist"] == 8.0)
        saved = json.loads((tmp / "v_ok.json").read_text())
        check("state is persisted to disk", str(TICKET) in saved["positions"])

    # --------------------------------------- verification: naked repair
    print("naked / drifted stops are repaired")
    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_naked.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=0.0, tp=4020.0)
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("a naked position is repaired", st["status"] == "repaired", str(st))
        check("repaired stop sits 2xATR below the entry", mt5.positions[TICKET].sl == 3992.0)
        check("the repair preserves the take-profit", mt5.positions[TICKET].tp == 4020.0)
        check("the repair carries TRADE_ACTION_SLTP",
              mt5.sends and mt5.sends[-1].get("action") == FakeMT5.TRADE_ACTION_SLTP)
        check("the repair carries the position ticket",
              mt5.sends and mt5.sends[-1].get("position") == TICKET)

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_drift.json")
        # Stop attached 0.30 too far out: exactly the slippage the pre-fill
        # tick produces when the fill lands above the ask.
        mt5.positions[TICKET] = Pos(entry=4000.30, sl=3991.70, tp=4020.0)
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("a drifted stop is re-anchored on the actual fill",
              st["status"] == "repaired" and mt5.positions[TICKET].sl == 3992.30,
              f"sl={mt5.positions[TICKET].sl}")

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_tol.json")
        # 0.03 off = 3 points = inside the 5-point tolerance.
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.03, tp=4020.0)
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("a stop inside tolerance is left alone",
              st["status"] == "ok" and not mt5.sends, str(st))

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_sell.json")
        mt5.positions[TICKET] = Pos(side="SELL", entry=4000.0, sl=4008.0, tp=3980.0)
        st = g.on_fill(Resp(10009, order=TICKET), "SELL", 8.0, 20.0, 0.01)
        check("SELL geometry verifies symmetrically", st["status"] == "ok", str(st))
        mt5.positions[TICKET] = Pos(side="SELL", entry=4000.0, sl=0.0, tp=3980.0)
        st = g.on_fill(Resp(10009, order=TICKET), "SELL", 8.0, 20.0, 0.01)
        check("SELL naked repair adds the stop above entry",
              mt5.positions[TICKET].sl == 4008.0, f"sl={mt5.positions[TICKET].sl}")

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_notp.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=0.0, tp=0.0)
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 0.0, 0.01)
        check("a no-TP shape repairs the stop and sends tp=0",
              st["status"] == "repaired" and mt5.sends[-1]["tp"] == 0.0, str(st))

    # ------------------------------------- failure paths never go silent
    print("failure paths: bounded and loud")
    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_reject.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=0.0, tp=4020.0)
        mt5.modify_fails = 99
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("an unattachable stop is reported, not ignored",
              st["status"] == "naked_unrepaired", str(st))
        check("default action closes the naked position", len(mt5.closes) == 1)
        check("the close is logged CRITICAL at ERROR level",
              any(lv == "ERROR" and "EMERGENCY-CLOSED" in m for lv, m in logs))
        check("a closed position is not tracked",
              str(TICKET) not in g.tracked)

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**dict(BASE_CFG, LIVE_NAKED_POSITION_ACTION="alert")):
        g, logs = guard_for(tmp, br, name="v_alert.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=0.0)
        mt5.modify_fails = 99
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("alert mode never closes", not mt5.closes)
        check("alert mode says UNPROTECTED",
              any("UNPROTECTED" in m for lv, m in logs if lv == "ERROR"))

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_blind.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=0.0)
        mt5.read_fails = 99
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("a failed read is not 'position gone'", st["status"] == "not_found")
        check("a failed read never closes a position", not mt5.closes)
        check("a failed read is logged", any(lv == "ERROR" for lv, m in logs))

    # The dangerous false positive: a repair that was accepted but cannot be
    # read back must NOT be treated as "no stop" and closed.
    mt5 = FakeMT5()
    br = FlakyBridge(mt5, ok_reads=1)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_unconfirmed.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=0.0, tp=4020.0)
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("an unreadable confirmation is not 'naked'",
              st["status"] == "unconfirmed", str(st))
        check("an unreadable confirmation never closes the position", not mt5.closes)
        check("the unconfirmed state is logged as such",
              any("never confirmed" in m for lv, m in logs if lv == "ERROR"))
        check("the modify was still sent", len(mt5.sends) >= 1)

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_missing.json")
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("an unfindable fill is reported", st["status"] == "not_found")
        check("an unfindable fill never closes anything", not mt5.closes)

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_late.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        mt5.read_fails = 1     # the fill is not visible on the first read
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("a fill that appears on a later read is verified",
              st["status"] == "ok", str(st))

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="v_geom.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=0.0)
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", float("nan"), 20.0, 0.01)
        check("non-finite geometry never sends a stop",
              st["status"] == "bad_geometry" and not mt5.sends, str(st))

    # ------------------------------------------------------- BE ratchet
    print("breakeven ratchet")
    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    tl = Tick(bid=4011.0, ask=4011.2)      # +11 on 8 risk = 1.375R < 1.5R
    br.tick = tl
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="be_below.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        res = g.manage(list(mt5.positions.values()), tl)
        check("the ratchet does not fire below the trigger",
              not res["armed"] and mt5.positions[TICKET].sl == 3992.0)
        check("nothing is armed in state", g.tracked[str(TICKET)]["be_armed"] is False)

        br.tick = Tick(bid=4012.0, ask=4012.2)   # exactly 1.5R
        res = g.manage(list(mt5.positions.values()), br.tick)
        check("the ratchet fires at exactly the trigger", res["armed"] == [TICKET], str(res))
        check("SL moved to breakeven", mt5.positions[TICKET].sl == 4000.0)
        check("the ratchet preserves the take-profit", mt5.positions[TICKET].tp == 4020.0)
        check("state records be_armed", g.tracked[str(TICKET)]["be_armed"] is True)

        n = len(mt5.sends)
        g.manage(list(mt5.positions.values()), Tick(bid=4030.0, ask=4030.2))
        check("the ratchet fires only once", len(mt5.sends) == n)

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="be_reject.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        mt5.modify_fails = 99
        res = g.manage(list(mt5.positions.values()), Tick(bid=4020.0, ask=4020.2))
        check("a rejected ratchet is not recorded as armed",
              not res["armed"] and g.tracked[str(TICKET)]["be_armed"] is False)
        check("the rejection is logged",
              any("BE modify rejected" in m for lv, m in logs))

    mt5 = FakeMT5()
    br = FakeBridge(mt5, sym=Sym(stops_level=2000))   # 2000 pts = 20.00
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="be_stops.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        sent_before = len(mt5.sends)
        res = g.manage(list(mt5.positions.values()), Tick(bid=4012.0, ask=4012.2))
        check("a BE target inside stops_level is not sent",
              len(mt5.sends) == sent_before and not res["armed"])
        check("the stops_level skip is logged",
              any("stops_level" in m for lv, m in logs))

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="be_sell.json")
        mt5.positions[TICKET] = Pos(side="SELL", entry=4000.0, sl=4008.0, tp=3980.0)
        g.on_fill(Resp(10009, order=TICKET), "SELL", 8.0, 20.0, 0.01)
        tl = Tick(bid=3987.9, ask=3988.1)     # entry - ask = 11.9 < 12
        g.manage(list(mt5.positions.values()), tl)
        check("SELL ratchet waits below the trigger", mt5.positions[TICKET].sl == 4008.0)
        tl = Tick(bid=3987.7, ask=3988.0)     # entry - ask = 12.0
        res = g.manage(list(mt5.positions.values()), tl)
        check("SELL ratchet fires at the trigger",
              res["armed"] == [TICKET] and mt5.positions[TICKET].sl == 4000.0, str(res))

    # --------------------------------------------------- restart safety
    print("restart / state recovery")
    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, _ = guard_for(tmp, br, name="re_restart.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        g.manage(list(mt5.positions.values()), Tick(bid=4012.0, ask=4012.2))
        check("first guard armed the ratchet", mt5.positions[TICKET].sl == 4000.0)

        g2, logs2 = guard_for(tmp, br, name="re_restart.json")   # "restart"
        check("a restart restores the tracked position", str(TICKET) in g2.tracked)
        check("a restart remembers be_armed", g2.tracked[str(TICKET)]["be_armed"] is True)
        n = len(mt5.sends)
        g2.manage(list(mt5.positions.values()), Tick(bid=4040.0, ask=4040.2))
        check("a restart does not re-fire the ratchet", len(mt5.sends) == n)

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        # Deployed onto an already-open position: no state for the ticket.
        g, logs = guard_for(tmp, br, name="re_orphan.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        g.manage(list(mt5.positions.values()), Tick(bid=4020.0, ask=4020.2))
        check("an untracked position is not modified",
              not any(s.get("action") == FakeMT5.TRADE_ACTION_SLTP for s in mt5.sends))

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="re_recover.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        g.tracked[str(TICKET)] = {"side": "BUY", "entry": 4000.0, "sl_dist": 0.0,
                                  "tp_dist": 20.0, "be_armed": False}
        res = g.manage(list(mt5.positions.values()), Tick(bid=4012.0, ask=4012.2))
        check("a lost sl_dist is recovered from the broker stop",
              res["armed"] == [TICKET] and mt5.positions[TICKET].sl == 4000.0, str(res))
        check("the recovery is logged",
              any("recovered from the broker stop" in m for lv, m in logs))

        mt5.positions[TICKET] = Pos(entry=4000.0, sl=4000.0, tp=4020.0)
        g.tracked[str(TICKET)]["be_armed"] = False
        res = g.manage(list(mt5.positions.values()), Tick(bid=4020.0, ask=4020.2))
        check("an already-breakeven stop is not re-derived", not res["armed"])

    # ---------------------------------------------------- housekeeping
    print("housekeeping")
    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="hk_prune.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        mt5.positions.clear()
        g.manage([], Tick())
        check("a closed ticket is pruned from state", str(TICKET) not in g.tracked)
        check("the prune is persisted",
              str(TICKET) not in json.loads((tmp / "hk_prune.json").read_text())["positions"])
        check("the prune is logged", any("no longer open" in m for lv, m in logs))

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="hk_vanish.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        mt5.positions[TICKET].sl = 0.0          # broker dropped the stop mid-trade
        res = g.manage(list(mt5.positions.values()), Tick())
        check("a mid-trade lost stop is restored from state",
              res["repaired"] == [TICKET] and mt5.positions[TICKET].sl == 3992.0, str(res))

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="hk_vanish_be.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=3992.0, tp=4020.0)
        g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        g.manage(list(mt5.positions.values()), Tick(bid=4012.0, ask=4012.2))  # arms BE
        check("setup: the stop is at breakeven", mt5.positions[TICKET].sl == 4000.0)
        mt5.positions[TICKET].sl = 0.0       # broker drops the armed stop
        res = g.manage(list(mt5.positions.values()), Tick())
        check("a lost stop is restored to BREAKEVEN, not to the original risk",
              res["repaired"] == [TICKET] and mt5.positions[TICKET].sl == 4000.0,
              f"sl={mt5.positions[TICKET].sl}")

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="hk_magic.json")
        mt5.positions[1] = Pos(ticket=1, magic=424242, entry=4000.0, sl=0.0)
        g.manage(list(mt5.positions.values()), Tick())
        check("another instance's position is ignored", not mt5.sends)

    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="hk_nobridge.json")
        g.bridge = None
        check("no bridge is a no-op, not a crash", g.manage([], Tick()) == {"armed": [], "repaired": []})

    # ------------------------------------------------- retcode handling
    print("retcode handling")
    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="rc_nochange.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=0.0, tp=4020.0)
        mt5.modify_retcode = FakeMT5.TRADE_RETCODE_NO_CHANGES
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("NO_CHANGES is success, not a failure", st["status"] == "repaired", str(st))

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="rc_hintmismatch.json")
        mt5.positions[77] = Pos(ticket=77, entry=4000.0, sl=3992.0, tp=4020.0)
        st = g.on_fill(Resp(10009, order=TICKET), "BUY", 8.0, 20.0, 0.01)
        check("a position ticket that differs from the order ticket is still verified",
              st["status"] == "ok" and st["ticket"] == 77, str(st))
        check("the ticket mismatch is reported",
              any("not present among positions" in m for lv, m in logs))

    mt5 = FakeMT5()
    br = FakeBridge(mt5)
    with cfg(**BASE_CFG):
        g, logs = guard_for(tmp, br, name="rc_noticket.json")
        mt5.positions[TICKET] = Pos(entry=4000.0, sl=0.0, tp=4020.0)
        st = g.on_fill(Resp(10009, order=0), "BUY", 8.0, 20.0, 0.01)
        check("a fill with no ticket hint still finds the newest position",
              st["status"] == "repaired" and st["ticket"] == TICKET, str(st))

    # --------------------------------------------------- intent sanity
    print("geometry helpers")
    sl, tp = live_position.intended_stops("BUY", 4000.0, 8.0, 20.0, 2)
    check("BUY intent", (sl, tp) == (3992.0, 4020.0), f"{sl},{tp}")
    sl, tp = live_position.intended_stops("SELL", 4000.0, 8.0, 20.0, 2)
    check("SELL intent", (sl, tp) == (4008.0, 3980.0), f"{sl},{tp}")
    sl, tp = live_position.intended_stops("BUY", 4000.0, 8.0, 0.0, 2)
    check("no-TP intent is 0.0 (MT5's none)", tp == 0.0)
    sl, tp = live_position.intended_stops("BUY", 0.0, 8.0, 20.0, 2)
    check("zero entry has no intent", (sl, tp) == (None, None))

    # ------------------------------------------------------------- wiring
    # The guard is only safe because run.py constructs it in the LIVE branch
    # alone. That is a property of run.py's structure, so assert on the AST
    # rather than trusting the diff.
    print("wiring")
    tree = ast.parse((ROOT / "run.py").read_text())
    paper_body, live_body = None, None
    # The mode branch is the one that builds the PaperAccount: `new_strategy`
    # also tests FORWARD_TEST (for the donchian guard) and has no LIVE half.
    for node in ast.walk(tree):
        if not isinstance(node, ast.If) or "FORWARD_TEST" not in ast.dump(node.test):
            continue
        body = "".join(ast.dump(n) for n in node.body)
        if "PaperAccount" not in body:
            continue
        paper_body = body
        live_body = "".join(ast.dump(n) for n in node.orelse)
        break
    check("run.py has a FORWARD_TEST branch", paper_body is not None)
    check("the paper branch never constructs the guard",
          paper_body is not None and "LivePositionGuard" not in paper_body)
    check("the LIVE branch constructs the guard",
          live_body is not None and "LivePositionGuard" in live_body)
    src = (ROOT / "run.py").read_text()
    check("the guard is guarded by `is not None` at every call site",
          src.count("if guard is not None:") == 3, str(src.count("if guard is not None:")))

    failed = [i for i, ok in enumerate(RESULTS) if not ok]
    print(f"\n{'ALL PASS' if not failed else 'FAILURES'}: "
          f"{len(RESULTS) - len(failed)}/{len(RESULTS)} live-position checks")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
