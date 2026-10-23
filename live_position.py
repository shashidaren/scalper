"""LIVE-only position protection: post-fill stop verification + BE ratchet.

Two gaps closed here (write-up: `docs/live_readiness_review_2026-10-23.md`
§4.1, §4.2, §4.5). Both are **LIVE only**; `enabled` refuses to act in
`FORWARD_TEST`, so the paper book cannot be touched even if this module is
wired wrongly.

1. **Post-fill stop verification.** `run.py` used to trust
   `TRADE_RETCODE_DONE` and never look at the position again. A stop the
   broker silently drops (invalid stops, partial attach, a server-side edit)
   leaves the book open with no SL - the one failure mode here that is not
   self-limiting. After every fill this module re-reads the position and
   proves a stop is attached at 2xATR from the **actual fill price**, so the
   realized R matches the modelled R even when the fill slipped away from the
   pre-trade tick. Missing/drifted stops are re-sent via `TRADE_ACTION_SLTP`;
   a stop that still cannot be attached is closed (default) or alerted.

2. **Breakeven ratchet.** The validated 255-trade shape takes 43 of its exits
   (16.9%) from BE at 1.5R, but the ratchet only ever existed in `paper.py` -
   a LIVE book without it runs an exit engine that was never forward tested.
   This applies the same rule through `TRADE_ACTION_SLTP`.

Design notes that matter if you change anything here:

* **`None` is not `[]`.** `positions_get` returning None means the read failed;
  the guard then retries and never concludes "the position is gone". Closing a
  position on a failed read would be worse than the disease.
* **Every modify carries the current TP.** MT5 treats a missing `tp` in a
  SLTP request as "remove the TP" (0.0), so a BE ratchet that forgot it would
  silently strip every target off the book.
* **State is persisted** (`<LOG_DIR>/live_positions.json`, atomic write) so a
  restart mid-trade neither re-arms an armed ratchet nor loses the original
  `sl_dist` the ratchet is measured against. When the state is missing (feature
  first deployed on an open position) the stop distance is recovered from the
  broker's own stop, which is the same number while the SL is still original.
* **Fail safe, never fail silent.** Every refusal path logs at ERROR/WARNING
  with the ticket number, because the alternative - an unprotected position
  nobody was told about - is the whole reason this file exists.

Pure standard library + `config`, `logger`. No MT5 import: `tests/
test_live_position_guards.py` drives it with a fake bridge.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import config
import logger

STATE_NAME = "live_positions.json"


def _finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _positive(x):
    return _finite(x) and float(x) > 0.0


def _norm_position(p):
    """Normalise an MT5 position object or run.py's position dict.

    run.py's dicts are already filtered by magic (`run.py` collects only
    `magic == config.MAGIC_NUMBER`), so a dict without a magic key is treated
    as ours; a raw MT5 object always carries one and is filtered on it.
    """
    if isinstance(p, dict):
        return {
            "ticket": int(p.get("ticket") or 0),
            "side": str(p.get("type") or p.get("side") or "").upper(),
            "volume": float(p.get("volume") or 0.0),
            "entry": float(p.get("price_open", p.get("entry")) or 0.0),
            "sl": float(p.get("sl") or 0.0),
            "tp": float(p.get("tp") or 0.0),
            "profit": float(p.get("profit") or 0.0),
            "magic": int(p.get("magic", config.MAGIC_NUMBER)),
        }
    try:
        ptype = int(getattr(p, "type", 1))
    except Exception:
        ptype = 1
    return {
        "ticket": int(getattr(p, "ticket", 0) or 0),
        "side": "BUY" if ptype == 0 else "SELL",
        "volume": float(getattr(p, "volume", 0.0) or 0.0),
        "entry": float(getattr(p, "price_open", 0.0) or 0.0),
        "sl": float(getattr(p, "sl", 0.0) or 0.0),
        "tp": float(getattr(p, "tp", 0.0) or 0.0),
        "profit": float(getattr(p, "profit", 0.0) or 0.0),
        "magic": int(getattr(p, "magic", config.MAGIC_NUMBER) or 0),
    }


def intended_stops(side, entry, sl_dist, tp_dist, digits):
    """SL/TP a position should carry, anchored on the ACTUAL fill price.

    Anchoring on the fill (not on the pre-trade tick the order was built from)
    is what removes the slippage drift in realized R: a stop sent as
    `ask - 2xATR` while the fill landed 0.30 higher would otherwise risk
    `2xATR + 0.30`. `tp_dist <= 0` means "no take-profit" -> 0.0, MT5's
    sentinel for none.
    """
    if not _positive(entry) or not _finite(sl_dist):
        return None, None
    sl_dist = float(sl_dist)
    tp_dist = float(tp_dist or 0.0)
    has_tp = tp_dist > 0
    if str(side).upper() == "BUY":
        sl = round(entry - sl_dist, digits)
        tp = round(entry + tp_dist, digits) if has_tp else 0.0
    else:
        sl = round(entry + sl_dist, digits)
        tp = round(entry - tp_dist, digits) if has_tp else 0.0
    return sl, tp


class LivePositionGuard:
    """Verifies, repairs and ratchets stops on LIVE positions.

    `bridge` is the shared `MT5Bridge`; `run.py` re-assigns it after a
    reconnect (the object is rebuilt by the connection-recovery branch), so it
    is read at call time, never captured at construction.
    """

    def __init__(self, bridge=None, state_file=None, log=None, sleep_fn=None):
        self.bridge = bridge
        self.state_file = Path(state_file) if state_file is not None else (
            Path(getattr(config, "LOG_DIR", logger.LOG_DIR)) / STATE_NAME)
        self._log = log or logger.log_system
        self._sleep = sleep_fn or (lambda s: None)
        self.tracked = {}          # str(ticket) -> state dict
        self._warned = set()       # tickets already warned about (log once)
        self._load()

    # ------------------------------------------------------------ config
    @property
    def enabled(self):
        """LIVE only, and behind its own switch.

        Defence in depth: `run.py` only constructs this in the LIVE branch, but
        the FORWARD_TEST clause means a mis-wired caller still cannot modify a
        paper position or send a SLTP request against the shared terminal.
        """
        if str(getattr(config, "TRADING_MODE", "FORWARD_TEST")).upper() != "LIVE":
            return False
        return bool(getattr(config, "LIVE_PROTECT_ENABLED", True))

    @property
    def be_trigger_r(self):
        """Ratchet trigger in R for log lines (0 = ratchet off)."""
        return self._be_trigger()

    def _digits(self):
        return int(getattr(config, "PRICE_DIGITS", 2))

    def _tolerance(self, sym=None):
        """Broker may store the stop a few points away without it being wrong."""
        return float(getattr(config, "LIVE_STOP_TOLERANCE_POINTS", 5)) * self._point(sym)

    def _point(self, sym=None):
        sym = sym if sym is not None else self._symbol_info()
        try:
            return float(sym.point)
        except (TypeError, ValueError, AttributeError):
            return 10.0 ** -self._digits()

    def _stops_level(self, sym=None):
        """Broker's minimum stop distance in points (0 = no restriction)."""
        sym = sym if sym is not None else self._symbol_info()
        for attr in ("trade_stops_level", "stops_level"):
            try:
                v = getattr(sym, attr, None)
                if v is not None:
                    return float(v)
            except Exception:
                continue
        return 0.0

    def _symbol_info(self):
        try:
            return self.bridge.get_symbol_info() if self.bridge is not None else None
        except Exception:
            return None

    def _attempts(self):
        return max(1, int(getattr(config, "LIVE_STOP_VERIFY_ATTEMPTS", 3)))

    def _sleep_between(self):
        self._sleep(float(getattr(config, "LIVE_STOP_VERIFY_SLEEP_SECONDS", 1.0)))

    def _be_trigger(self):
        """Ratchet trigger in R. `LIVE_BE_TRIGGER_R=None` inherits BE_TRIGGER_R.

        `LIVE_BE_ENABLED=False` or a falsy trigger disables the ratchet without
        disabling stop verification.
        """
        if not getattr(config, "LIVE_BE_ENABLED", True):
            return 0.0
        trigger = getattr(config, "LIVE_BE_TRIGGER_R", None)
        if trigger is None:
            trigger = getattr(config, "BE_TRIGGER_R", None)
        try:
            trigger = float(trigger) if trigger else 0.0
        except (TypeError, ValueError):
            trigger = 0.0
        return trigger if trigger > 0 else 0.0

    # ------------------------------------------------------- persistence
    def _load(self):
        try:
            if not self.state_file.exists():
                return
            data = json.loads(self.state_file.read_text())
            positions = data.get("positions") if isinstance(data, dict) else None
            if isinstance(positions, dict):
                self.tracked = {str(k): v for k, v in positions.items()
                                if isinstance(v, dict)}
        except Exception as e:
            self._log("WARNING", f"[LIVE-GUARD] unreadable {self.state_file} ({e}) - "
                                  f"starting empty; BE state will be re-derived")
            self.tracked = {}

    def _save(self):
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_name(self.state_file.name + ".tmp")
            with open(tmp, "w") as f:
                json.dump({"positions": self.tracked,
                           "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
                          f, indent=2)
            tmp.replace(self.state_file)
        except Exception as e:
            self._log("WARNING", f"[LIVE-GUARD] could not persist {self.state_file}: {e}")

    # ------------------------------------------------------------ reading
    def _positions(self):
        """Symbol positions, or None when the read itself failed."""
        if self.bridge is None:
            return None
        try:
            fn = getattr(self.bridge, "positions_get", None)
            if fn is not None:
                return fn()
            return self.bridge.mt5.positions_get(symbol=config.SYMBOL)
        except Exception as e:
            self._log("WARNING", f"[LIVE-GUARD] positions_get failed: {e}")
            return None

    def _ours(self, listing):
        out = []
        for p in listing or []:
            n = _norm_position(p)
            if n["magic"] == int(getattr(config, "MAGIC_NUMBER", n["magic"])):
                out.append(n)
        return out

    def _find(self, positions, prefer_ticket=None):
        """The position this guard means: the hinted ticket, else the newest."""
        if not positions:
            return None
        if prefer_ticket:
            for p in positions:
                if p["ticket"] == int(prefer_ticket):
                    return p
        return max(positions, key=lambda p: p["ticket"])

    def _find_ticket(self, ticket, attempts=1):
        for i in range(max(1, attempts)):
            listing = self._positions()
            if listing is not None:
                pos = self._find(self._ours(listing), ticket)
                if pos is not None and pos["ticket"] == int(ticket):
                    return pos
            if i + 1 < attempts:
                self._sleep_between()
        return None

    # ------------------------------------------------------------ writing
    def _modify(self, ticket, sl, tp):
        """Send a SLTP request. Returns (ok, detail)."""
        if self.bridge is None:
            return False, "no_bridge"
        fn = getattr(self.bridge, "modify_position_stops", None)
        if fn is None:
            return False, "bridge_has_no_modify_position_stops"
        try:
            res = fn(int(ticket), sl, tp)
        except Exception as e:
            return False, f"exception:{e}"
        if isinstance(res, tuple):
            ok = bool(res[0])
            detail = " ".join(str(x) for x in res[1:] if x is not None)
            return ok, detail or ("ok" if ok else "modify_failed")
        return bool(res), ("ok" if res else "modify_failed")

    def _emergency_close(self, pos):
        if self.bridge is None:
            return False, "no_bridge"
        fn = getattr(self.bridge, "close_position", None)
        if fn is None:
            return False, "bridge_has_no_close_position"
        try:
            res = fn(int(pos["ticket"]))
        except Exception as e:
            return False, f"exception:{e}"
        if isinstance(res, tuple):
            ok = bool(res[0])
            return ok, " ".join(str(x) for x in res[1:] if x is not None) or ("ok" if ok else "failed")
        return bool(res), ("ok" if res else "failed")

    def _naked_response(self, pos, why):
        """A position exists with no stop and the repair failed: bounded choice."""
        action = str(getattr(config, "LIVE_NAKED_POSITION_ACTION", "close")).lower()
        if action == "close":
            ok, detail = self._emergency_close(pos)
            if ok:
                self._log("ERROR",
                          f"[LIVE-GUARD] CRITICAL ticket {pos['ticket']}: {why} - position "
                          f"EMERGENCY-CLOSED to avoid unbounded risk ({detail})")
            else:
                self._log("ERROR",
                          f"[LIVE-GUARD] CRITICAL ticket {pos['ticket']}: {why} - emergency "
                          f"close FAILED ({detail}). UNPROTECTED POSITION - act manually in MT5 now.")
        else:
            self._log("ERROR",
                      f"[LIVE-GUARD] CRITICAL ticket {pos['ticket']}: {why} - alert only "
                      f"(LIVE_NAKED_POSITION_ACTION=alert). UNPROTECTED POSITION - act manually now.")

    def _ensure_stops(self, pos, want_sl, want_tp, sym=None):
        """Make the position carry `want_sl`/`want_tp`. Returns (pos, status).

        Closing a position is only ever allowed on **positive evidence**: a
        read of the position itself showing `sl == 0`, with the repairs having
        failed. A read that fails is not evidence of anything, so it can never
        escalate to a close - otherwise one RPC hiccup would flatten a healthy
        trade.
        """
        tol = self._tolerance(sym)
        current = pos
        if _positive(current["sl"]) and abs(current["sl"] - want_sl) <= tol:
            return current, "ok"

        why = ("no stop attached" if not _positive(current["sl"])
               else f"stop drift {current['sl']:.2f} != {want_sl:.2f}")
        # Never send tp=0 for a position that has a target: MT5 reads a zero tp
        # in a SLTP request as "remove it". Keep the broker's own tp when the
        # caller passed none.
        target_tp = want_tp if _finite(want_tp) and float(want_tp or 0) != 0 else current["tp"]
        last = "not_attempted"
        last_seen = current          # most recent positive reading
        accepted = False             # a modify the broker acknowledged
        unconfirmed = False          # ...that we could not read back
        for attempt in range(1, self._attempts() + 1):
            ok, detail = self._modify(current["ticket"], want_sl, target_tp)
            last = detail
            accepted = accepted or ok
            if ok:
                confirmed = self._find_ticket(current["ticket"])
                if confirmed is None:
                    unconfirmed = True
                    last = "accepted, but the position could not be re-read"
                else:
                    last_seen = confirmed
                    if _positive(confirmed["sl"]) and abs(confirmed["sl"] - want_sl) <= tol:
                        self._log("INFO" if attempt == 1 else "WARNING",
                                  f"[LIVE-GUARD] ticket {current['ticket']}: {why} -> SL set to "
                                  f"{want_sl:.2f} (attempt {attempt})")
                        return confirmed, "repaired"
                    last = f"accepted, but the position now shows sl={confirmed['sl']:.2f}"
            if attempt < self._attempts():
                self._sleep_between()

        if not _positive(last_seen["sl"]):
            if accepted and unconfirmed:
                self._log("ERROR",
                          f"[LIVE-GUARD] ticket {current['ticket']}: stop repair was accepted "
                          f"but never confirmed ({last}). NOT closing on unconfirmed data - "
                          f"verify this position in MT5 now.")
                return last_seen, "unconfirmed"
            self._naked_response(last_seen,
                                 f"{why} and repair failed after {self._attempts()} "
                                 f"attempts: {last}")
            return last_seen, "naked_unrepaired"

        if unconfirmed:
            self._log("ERROR",
                      f"[LIVE-GUARD] ticket {current['ticket']}: {why}; {last}. The position "
                      f"still has a stop (sl={last_seen['sl']:.2f}) but the intended one is "
                      f"unverified.")
            return last_seen, "unconfirmed"
        self._log("ERROR",
                  f"[LIVE-GUARD] ticket {current['ticket']}: {why}; repair failed after "
                  f"{self._attempts()} attempts ({last}). The position still has its "
                  f"original stop but not the intended one.")
        return last_seen, "drift_unrepaired"

    # ------------------------------------------------------------- public
    def on_fill(self, result, side, sl_dist, tp_dist, volume, sym=None):
        """Verify (and repair) the stop on a position we just opened.

        The position's own `price_open` is the real fill after slippage, so it
        is what the intended stop is anchored on. Returns a small status dict
        for the caller's log line; never raises.
        """
        if not self.enabled:
            return {"status": "disabled"}
        ticket_hint = None
        for attr in ("order", "deal"):
            try:
                v = int(getattr(result, attr, 0) or 0)
            except Exception:
                v = 0
            if v:
                ticket_hint = v
                break

        pos = None
        for attempt in range(1, self._attempts() + 1):
            listing = self._positions()
            if listing is not None:
                positions = self._ours(listing)
                if ticket_hint is not None:
                    for candidate in positions:
                        if candidate["ticket"] == ticket_hint:
                            pos = candidate
                            break
                elif positions:
                    pos = max(positions, key=lambda p: p["ticket"])
                if pos is not None:
                    break
                if positions and attempt == self._attempts():
                    # Some brokers issue a position ticket that differs from
                    # the order ticket. Only one position per magic can be open
                    # (run.py checks before entering), so the newest one is
                    # this fill - verifying it beats verifying nothing.
                    pos = max(positions, key=lambda p: p["ticket"])
                    self._log("WARNING",
                              f"[LIVE-GUARD] order ticket {ticket_hint} not present among "
                              f"positions; verifying position {pos['ticket']} instead")
                    break
            if attempt < self._attempts():
                self._sleep_between()
        if pos is None:
            self._log("ERROR",
                      f"[LIVE-GUARD] could not locate the position for the fill "
                      f"(order hint {ticket_hint}) after {self._attempts()} reads - "
                      f"stop NOT verified. Check the MT5 terminal now.")
            return {"status": "not_found", "ticket": ticket_hint}

        digits = self._digits()
        want_sl, want_tp = intended_stops(side, pos["entry"], sl_dist, tp_dist, digits)
        if want_sl is None:
            self._log("ERROR", f"[LIVE-GUARD] ticket {pos['ticket']}: cannot compute intended "
                               f"stops (entry={pos['entry']!r} sl_dist={sl_dist!r}) - "
                               f"stop NOT verified.")
            return {"status": "bad_geometry", "ticket": pos["ticket"]}

        pos, status = self._ensure_stops(pos, want_sl, want_tp, sym)
        if status in ("naked_unrepaired",):
            self.tracked.pop(str(pos["ticket"]), None)
            self._save()
            return {"status": status, "ticket": pos["ticket"]}

        self.tracked[str(pos["ticket"])] = {
            "side": pos["side"],
            "entry": pos["entry"],
            "sl_dist": float(sl_dist),
            "tp_dist": float(tp_dist or 0.0),
            "volume": float(volume or pos["volume"]),
            "be_armed": False,
            "opened_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        self._save()
        return {"status": status, "ticket": pos["ticket"], "sl": pos["sl"], "tp": pos["tp"]}

    def manage(self, positions, tick, sym=None):
        """Per-loop housekeeping on open positions: prunes, stop re-checks, BE.

        Safe to call when flat (it just prunes), and safe to call with the
        bridge's raw objects or run.py's dicts.
        """
        if not self.enabled or self.bridge is None:
            return {"armed": [], "repaired": []}

        live = {p["ticket"]: p for p in self._ours(positions)}
        armed, repaired = [], []
        dirty = False

        for ticket in list(self.tracked):
            if int(ticket) not in live:
                self.tracked.pop(ticket, None)
                self._warned.discard(int(ticket))
                dirty = True
                self._log("INFO", f"[LIVE-GUARD] ticket {ticket} no longer open - stop tracking")

        for ticket, pos in live.items():
            state = self.tracked.get(str(ticket))

            # A stop can also disappear mid-trade (broker edit, margin event).
            if not _positive(pos["sl"]):
                want_sl = None
                if state:
                    want_sl, _ = intended_stops(state["side"], state["entry"],
                                                state["sl_dist"], state["tp_dist"],
                                                self._digits())
                if want_sl is None:
                    if int(ticket) not in self._warned:
                        self._warned.add(int(ticket))
                        self._log("ERROR",
                                  f"[LIVE-GUARD] ticket {ticket} has no stop and no recorded "
                                  f"geometry to restore it (not opened by this build?) - "
                                  f"MONITOR MANUALLY.")
                    continue
                if state.get("be_armed"):
                    # Restore the RATCHETED stop, not the original one: putting
                    # the stop back at entry-sl_dist would silently un-breakeven
                    # a trade that had already reached 1.5R.
                    want_sl = round(float(state["entry"]), self._digits())
                pos, status = self._ensure_stops(pos, want_sl, pos["tp"], sym)
                if status == "repaired":
                    repaired.append(int(ticket))
                continue

            if not state:
                continue

            trigger = self._be_trigger()
            if not trigger or state.get("be_armed"):
                continue

            sl_dist = float(state.get("sl_dist") or 0.0)
            if not _positive(sl_dist):
                # State survived a deploy but not the original sl_dist. While
                # the SL is still the original one it IS the distance.
                entry = float(state.get("entry") or pos["entry"])
                if _positive(pos["sl"]) and abs(pos["sl"] - entry) > 1e-9:
                    sl_dist = abs(entry - pos["sl"])
                    state["sl_dist"] = sl_dist
                    dirty = True
                    self._log("WARNING",
                              f"[LIVE-GUARD] ticket {ticket}: sl_dist recovered from the "
                              f"broker stop ({sl_dist:.2f})")
                else:
                    continue

            entry = float(state.get("entry") or pos["entry"])
            exit_side_price = tick.bid if pos["side"] == "BUY" else tick.ask
            try:
                fav = ((exit_side_price - entry) if pos["side"] == "BUY"
                       else (entry - exit_side_price))
            except (TypeError, AttributeError):
                continue
            if not _finite(fav) or float(fav) < trigger * sl_dist:
                continue

            target = round(entry, self._digits())
            tol = self._tolerance(sym)
            if abs(pos["sl"] - target) <= tol:
                state["be_armed"] = True
                state["be_armed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                dirty = True
                continue

            # A stop inside the broker's minimum distance is rejected, and a
            # rejected ratchet must not be recorded as armed.
            point = self._point(sym)
            stops_level = self._stops_level(sym)
            if stops_level > 0 and point > 0 and abs(exit_side_price - target) < stops_level * point:
                if int(ticket) not in self._warned:
                    self._warned.add(int(ticket))
                    self._log("WARNING",
                              f"[LIVE-GUARD] ticket {ticket}: BE target {target:.2f} is inside "
                              f"the broker stops_level ({stops_level:.0f} pts) - ratchet not sent")
                continue

            ok, detail = self._modify(ticket, target, pos["tp"])
            if not ok:
                self._log("WARNING", f"[LIVE-GUARD] ticket {ticket}: BE modify rejected ({detail})")
                continue
            confirmed = self._find_ticket(ticket)
            if confirmed is not None and abs(confirmed["sl"] - target) <= tol:
                state["be_armed"] = True
                state["be_armed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                dirty = True
                armed.append(int(ticket))
                self._log("INFO",
                          f"[LIVE-GUARD] ticket {ticket}: +{trigger:g}R reached "
                          f"({fav:.2f} on {sl_dist:.2f} risk) -> SL moved to breakeven {target:.2f}")
            else:
                self._log("WARNING",
                          f"[LIVE-GUARD] ticket {ticket}: BE modify accepted but the position "
                          f"shows sl={confirmed['sl'] if confirmed else 'gone'}")

        if dirty:
            self._save()
        return {"armed": armed, "repaired": repaired}
