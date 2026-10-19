#!/usr/bin/env python3
"""Unit tests for risk_sizer.size_lots (LIVE %-risk sizing).

Pure standard library. Run:  python3 tests/test_risk_sizer.py   # exit 0 = PASS

The load-bearing properties:
  * RISK_PCT=0 is inert (the engine keeps fixed LOT_SIZE)
  * an unavailable balance refuses the trade instead of guessing
  * a stop too wide for the budget SKIPS instead of sending an oversized lot
  * rounding is DOWN, never up, so the cap is a cap
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from risk_sizer import size_lots  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append(bool(ok))


def main() -> int:
    print("disabled / unavailable inputs")
    s = size_lots(1000, 10, 100, 0)
    check("RISK_PCT=0 is inert", s.lots is None and s.reason == "risk_pct_disabled")
    for bal in (0, -5, float("nan"), float("inf"), None):
        s = size_lots(bal, 10, 100, 1)
        check(f"balance {bal!r} refuses", s.lots is None and s.reason == "balance_unavailable")
    check("zero stop refused",
          size_lots(1000, 0, 100, 1).reason == "stop_distance_invalid")
    check("NaN stop refused",
          size_lots(1000, float("nan"), 100, 1).reason == "stop_distance_invalid")
    check("zero contract refused",
          size_lots(1000, 10, 0, 1).reason == "contract_size_invalid")

    print("XAUUSD arithmetic (contract 100, 1% of $1,000 = $10 budget)")
    s = size_lots(1000, 10, 100, 1, volume_step=0.01, volume_min=0.01)
    check("$10 stop -> 0.01 lots", s.lots == 0.01, str(s))
    check("actual risk equals the budget", s.actual_risk_usd == 10.0)
    s = size_lots(1000, 5, 100, 1, volume_step=0.01, volume_min=0.01)
    check("$5 stop -> 0.02 lots", s.lots == 0.02, str(s))
    check("still inside the budget", s.actual_risk_usd <= s.risk_usd)

    print("floors, never rounds up")
    # 699 * 1% = $6.99 budget / ($1 * 100) = 0.0699 lots.
    # round() would give 0.07 (risking $7.00 > $6.99).
    s = size_lots(699, 1, 100, 1, volume_step=0.01, volume_min=0.01)
    check("0.0699 floors to 0.06", s.lots == 0.06, str(s))
    check("never exceeds the budget", s.actual_risk_usd <= s.risk_usd + 1e-9)
    s = size_lots(700, 1, 100, 1, volume_step=0.01, volume_min=0.01)
    check("0.07 survives float truncation", s.lots == 0.07, str(s))

    print("skips instead of over-risking")
    s = size_lots(100, 10, 100, 1, volume_step=0.01, volume_min=0.01)
    check("$1 budget vs $1000/lot -> below volume_min",
          s.lots is None and s.reason == "below_volume_min", str(s))
    s = size_lots(1000, 10, 100, 1, volume_step=0.1, volume_min=0.1)
    check("broker minimum 0.1 lot also skips", s.lots is None)

    print("caps")
    s = size_lots(10_000_000, 10, 100, 1, volume_step=0.01,
                  volume_min=0.01, volume_max=5.0)
    check("volume_max caps the lot", s.lots == 5.0, str(s))

    print("BTC-shaped contract (contract 1, 1% of $1,000 = $10)")
    s = size_lots(1000, 500, 1, 1, volume_step=0.01, volume_min=0.01)
    check("$500 stop -> 0.02 lots", s.lots == 0.02, str(s))

    print("fallback step when the broker gives none")
    s = size_lots(1000, 10, 100, 1, volume_step=0, volume_min=None)
    check("degenerate step still sizes sanely", s.lots == 0.01, str(s))

    failed = RESULTS.count(False)
    print(f"\n{'ALL PASS' if failed == 0 else str(failed) + ' FAILED'}: "
          f"{RESULTS.count(True)}/{len(RESULTS)} risk-sizer checks")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
