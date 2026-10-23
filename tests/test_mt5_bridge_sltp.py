#!/usr/bin/env python3
"""Unit tests for the SLTP primitives `live_position` depends on.

`tests/test_live_position_guards.py` drives the guard with a *fake* bridge, so
a bug in the real `MT5Bridge` methods would slip through it. These tests cover
the other half:

  * `positions_get()` returns **None** on a failed read (never `[]`, which the
    guard would read as "the position is gone");
  * `modify_position_stops()` sends TRADE_ACTION_SLTP with the position ticket
    and the position's **current** tp (a zero tp would strip the target);
  * NO_CHANGES counts as success, so re-asserting a stop is idempotent;
  * `close_position()` sends the *opposite* deal with `position=<ticket>` and
    the exit-side price (bid to close a BUY, ask to close a SELL).

`rpyc` is stubbed before import: none of these methods touch it, and the suite
must run on a research box that has no MT5 stack installed. No network, no
files.
Run:  python3 tests/test_mt5_bridge_sltp.py      # exit 0 = PASS
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# --- stub rpyc so mt5_bridge imports on a box without the MT5 stack --------
if "rpyc" not in sys.modules:
    rpyc = types.ModuleType("rpyc")
    core = types.ModuleType("rpyc.core")
    service = types.ModuleType("rpyc.core.service")
    factory = types.ModuleType("rpyc.utils.factory")
    classic = types.ModuleType("rpyc.classic")

    class MasterService:  # noqa: D401 - stand-in for the real base class
        pass

    service.MasterService = MasterService
    factory.connect = lambda *a, **k: None
    classic.obtain = lambda x: x
    core.service = service
    rpyc.core = core
    rpyc.classic = classic
    sys.modules["rpyc"] = rpyc
    sys.modules["rpyc.core"] = core
    sys.modules["rpyc.core.service"] = service
    sys.modules["rpyc.utils"] = types.ModuleType("rpyc.utils")
    sys.modules["rpyc.utils.factory"] = factory
    sys.modules["rpyc.classic"] = classic

import config  # noqa: E402
import mt5_bridge  # noqa: E402

RESULTS = []
MAGIC = config.MAGIC_NUMBER


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append(bool(ok))


class Sym:
    point = 0.01
    digits = 2
    filling_mode = 2          # IOC allowed
    volume_min = 0.01
    volume_max = 50.0


class Tick:
    def __init__(self, bid=4000.0, ask=4000.2):
        self.bid = bid
        self.ask = ask


class Pos:
    def __init__(self, ticket=123, side="BUY", volume=0.01, entry=4000.0):
        self.ticket = ticket
        self.type = 0 if side == "BUY" else 1
        self.volume = volume
        self.price_open = entry
        self.sl = 0.0
        self.tp = 0.0


class Resp:
    def __init__(self, retcode, comment=""):
        self.retcode = retcode
        self.comment = comment


class FakeMT5:
    TRADE_ACTION_SLTP = 6
    TRADE_ACTION_DEAL = 1
    TRADE_RETCODE_DONE = 10009
    TRADE_RETCODE_NO_CHANGES = 10025
    ORDER_TYPE_BUY = 0
    ORDER_TYPE_SELL = 1
    ORDER_TIME_GTC = 0
    ORDER_FILLING_RETURN = 2
    ORDER_FILLING_FOK = 0
    ORDER_FILLING_IOC = 1

    def __init__(self):
        self.sends = []
        self.positions = {}
        self.read_raises = False
        self.retcode = self.TRADE_RETCODE_DONE
        self.result_none = False

    def symbol_info(self, symbol):
        return Sym()

    def symbol_info_tick(self, symbol):
        return Tick()

    def positions_get(self, **kw):
        if self.read_raises:
            raise RuntimeError("rpc closed")
        ticket = kw.get("ticket")
        if ticket is not None:
            return [self.positions[ticket]] if int(ticket) in self.positions else None
        # MT5's real contract: None means "flat" OR "unreadable", and only
        # last_error() tells them apart.
        return list(self.positions.values()) or None

    def last_error(self):
        if getattr(self, "unreadable", False):
            return (-10004, "No IPC connection")
        return (1, "Success")

    def account_info(self):
        return types.SimpleNamespace(balance=1000.0, equity=1000.0, margin_free=1000.0)

    def order_send(self, request):
        self.sends.append(dict(request))
        if self.result_none:
            return None
        return Resp(self.retcode, "ok")


def make_bridge(mt5=None):
    """A real MT5Bridge with the connection half stubbed out."""
    b = object.__new__(mt5_bridge.MT5Bridge)
    b.conn = None
    b.mt5 = mt5 or FakeMT5()
    b._closed = False
    b._shared = False
    b._cached_rates = None
    b._cached_count = None
    return b


def main() -> int:
    # ------------------------------------------------------- positions_get
    print("positions_get: None is not []")
    mt5 = FakeMT5()
    b = make_bridge(mt5)
    mt5.positions[1] = Pos(ticket=1)
    got = b.positions_get()
    check("a readable feed returns the list", got is not None and len(got) == 1)
    mt5.positions.clear()
    check("flat (API None + last_error Success) returns []",
          b.positions_get() == [])
    mt5.read_raises = True
    check("a raised read returns None, never []", b.positions_get() is None)
    mt5.read_raises = False
    mt5.unreadable = True
    check("API None with a real error returns None, not []", b.positions_get() is None)

    # ----------------------------------------------- modify_position_stops
    print("modify_position_stops")
    mt5 = FakeMT5()
    b = make_bridge(mt5)
    ok, rc, comment = b.modify_position_stops(123, 3992.0, 4020.0)
    req = mt5.sends[-1]
    check("a DONE modify reports success", ok is True and rc == 10009)
    check("it sends TRADE_ACTION_SLTP", req["action"] == FakeMT5.TRADE_ACTION_SLTP)
    check("it targets the position ticket", req["position"] == 123)
    check("it carries the requested SL", req["sl"] == 3992.0)
    check("it carries the position's current TP", req["tp"] == 4020.0)
    check("it carries the magic number", req["magic"] == MAGIC)
    check("it sends no price (SLTP has none)", "price" not in req)
    check("the comment fits MT5's 31-char limit", len(req["comment"]) <= 31)

    mt5.retcode = FakeMT5.TRADE_RETCODE_NO_CHANGES
    ok, rc, comment = b.modify_position_stops(123, 3992.0, 4020.0)
    check("NO_CHANGES counts as success (idempotent re-assert)",
          ok is True and rc == FakeMT5.TRADE_RETCODE_NO_CHANGES)

    mt5.retcode = 10013
    ok, rc, comment = b.modify_position_stops(123, 3992.0, 4020.0)
    check("a rejection is reported with its retcode", ok is False and rc == 10013)

    mt5.result_none = True
    ok, rc, comment = b.modify_position_stops(123, 3992.0, 4020.0)
    check("a null result is a failure, not a crash", ok is False and comment == "no_result")

    def boom(request):
        raise RuntimeError("bridge died")

    mt5.result_none = False
    mt5.order_send = boom
    ok, rc, comment = b.modify_position_stops(123, 3992.0, 4020.0)
    check("an exception is reported, not raised", ok is False and "exception" in comment)

    # ------------------------------------------------------- close_position
    print("close_position (emergency path)")
    mt5 = FakeMT5()
    b = make_bridge(mt5)
    mt5.positions[555] = Pos(ticket=555, side="BUY", volume=0.02)
    ok, detail = b.close_position(555)
    req = mt5.sends[-1]
    check("a BUY is closed with a SELL deal", req["type"] == FakeMT5.ORDER_TYPE_SELL)
    check("the close targets the position ticket", req["position"] == 555)
    check("the close uses the bid", req["price"] == 4000.0)
    check("the close uses the position volume", req["volume"] == 0.02)
    check("the close reports success", ok is True, detail)

    mt5 = FakeMT5()
    b = make_bridge(mt5)
    mt5.positions[556] = Pos(ticket=556, side="SELL", volume=0.01)
    ok, detail = b.close_position(556)
    req = mt5.sends[-1]
    check("a SELL is closed with a BUY deal", req["type"] == FakeMT5.ORDER_TYPE_BUY)
    check("the close uses the ask", req["price"] == 4000.2)

    mt5 = FakeMT5()
    b = make_bridge(mt5)
    ok, detail = b.close_position(999)
    check("closing a vanished position is a reported failure",
          ok is False and "not found" in detail and not mt5.sends)

    # ------------------------------------------------------- retcode set
    print("retcode handling")
    mt5 = FakeMT5()
    b = make_bridge(mt5)
    check("DONE and NO_CHANGES are both success",
          {10009, 10025}.issubset(b._ok_retcodes()))
    class BareMT5:
        pass
    b2 = make_bridge(BareMT5())
    check("a terminal without the constants falls back to 10009",
          b2._ok_retcodes() == {10009})

    failed = [i for i, ok in enumerate(RESULTS) if not ok]
    print(f"\n{'ALL PASS' if not failed else 'FAILURES'}: "
          f"{len(RESULTS) - len(failed)}/{len(RESULTS)} bridge SLTP checks")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
