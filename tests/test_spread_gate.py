#!/usr/bin/env python3
"""Unit tests for spread_gate.SpreadGateMonitor (shared by both instances).

Pure standard library - no pandas, no MT5, no bridge. Run:

    python3 tests/test_spread_gate.py      # exit 0 = PASS
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from spread_gate import SpreadGateMonitor, summarise  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append(bool(ok))


def main() -> int:
    print("spread_gate monitor")

    # --- a feasible gate -------------------------------------------------
    m = SpreadGateMonitor(1500)
    passes = [m.observe(sp) for sp in (900, 1200, 1500, 4000, 1400)]
    check("gate passes/defers exactly as the engine rule does",
          passes == [True, True, True, False, True], str(passes))
    check("counters add up", (m.samples, m.passed, m.vetoed) == (5, 4, 1))
    check("not infeasible, not starved", not m.infeasible and not m.starved)
    check("no warning for a feasible gate", not m.warn_now())

    # --- an impossible gate (the BTC M5 case: gate 1500 vs ~4200 quotes) --
    m2 = SpreadGateMonitor(1500, warn_after=8)
    for _ in range(20):
        m2.observe(4242)
    check("20/20 vetoes -> infeasible", m2.infeasible and m2.vetoed == 20)
    check("reports its veto share", abs(m2.veto_pct - 100.0) < 1e-9)
    check("spread stats come from observed quotes",
          m2.spread_stats() == {"min": 4242, "median": 4242, "max": 4242, "window": 20})
    check("warns once, then rate-limits",
          m2.warn_now() and not m2.warn_now())
    msg = m2.warning_message("BTCUSD")
    check("warning names the gate, the quotes and the consequence",
          "INFEASIBLE" in msg and "1500" in msg and "4242" in msg
          and "0 trades" in msg, msg[:80] + "...")
    for _ in range(m2.rewarn_every):
        m2.observe(4242)
    check("re-warns after rewarn_every cycles", m2.warn_now())

    # --- starved (95% < veto rate < 100%) --------------------------------
    m3 = SpreadGateMonitor(100, warn_after=4, starve_pct=90.0)
    for sp in (200, 200, 200, 50, 200, 200, 200, 200):   # 7/8 = 87.5% < 90
        m3.observe(sp)
    check("87.5% veto is not flagged starved", not m3.starved and not m3.infeasible)
    m3.observe(200)                                      # 8/9 = 88.9%
    m3.observe(200)                                      # 9/10 = 90%
    check("90% veto is starved", m3.starved and not m3.infeasible, f"{m3.veto_pct}%")
    check("starved warning text differs", "STARVED" in m3.warning_message())

    # --- a pass downgrades the verdict but keeps the history -------------
    m4 = SpreadGateMonitor(100, warn_after=3)
    for _ in range(5):
        m4.observe(300)
    first = m4.warn_now()
    check("5/5 vetoes warn as infeasible", first and m4.infeasible)
    m4.observe(50)
    check("a pass clears consecutive_vetoes and downgrades the verdict",
          m4.consecutive_vetoes == 0 and not m4.infeasible and m4.ever_bad)
    check("the recovery is announced exactly once",
          m4.recovered_now() and not m4.recovered_now())
    for _ in range(200):          # 210/211 vetoes -> starved again (>= starve_pct)
        m4.observe(300)
    check("drifting back to a bad state warns again",
          m4.state == "starved" and m4.warn_now() is True, m4.state)

    # --- status is JSON-serialisable and preflight-friendly --------------
    st = m4.status()
    json.dumps(st)
    check("status() is JSON-serialisable with the fields the dashboard reads",
          set(st) >= {"gate", "samples", "vetoed", "veto_pct", "median",
                      "infeasible", "starved", "last_pass_at"}, str(sorted(st))[:80])

    st2 = summarise(1500, [4242] * 6 + [4242])
    check("summarise() grades a list of quotes", st2["infeasible"] and st2["veto_pct"] == 100.0)
    check("summarise() handles an empty sample", summarise(1500, [])["samples"] == 0)

    # --- garbage in does not crash the engine ----------------------------
    m5 = SpreadGateMonitor(100)
    check("None/NaN quotes are vetoed, not counted as passes",
          m5.observe(None) is False and m5.observe(float("nan")) is False)

    print(f"\n{'ALL PASS' if all(RESULTS) else 'SOME CHECKS FAILED'}  "
          f"({sum(RESULTS)}/{len(RESULTS)})")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
