#!/usr/bin/env python3
"""Offline tests for btc/preflight.py (no bridge, no MT5, no network).

Three things are asserted:
  1. the bar-file economics match the documented gold facts (spread/1R ~5.7%,
     break-even WR 28.6%) - i.e. the maths that tells you whether a shape can
     pay for the spread is right;
  2. the BTC failure mode is reproduced: quotes far above the CONFIGURED
     MAX_SPREAD_POINTS grade INFEASIBLE with exit code 2. Asserted relative
     to the config value, not the old 1500 placeholder - the gate moved to
     6250 on 2026-10-08 and a hard-coded number goes red for no reason;
  3. exit codes are meaningful (0 OK / 2 INFEASIBLE / 3 unknown) so a runbook
     can gate on the command.

    python3 btc/preflight_test.py        # exit 0 = PASS
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT))      # spread_gate.py lives at the repo root

import _instance  # noqa: E402

RESULTS = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    RESULTS.append(bool(ok))


def btc_shaped_csv(path: Path, bars: int = 3000, spread_pts: int = 4242) -> Path:
    """A synthetic XM-BTCUSD-shaped file: $77.3k, ATR(14) ~81 px, 4,242-pt spread."""
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(5)
    close = 77304.55 + np.cumsum(rng.normal(0, 30, bars))
    high = close + np.abs(rng.normal(0, 60, bars))
    low = close - np.abs(rng.normal(0, 60, bars))
    pd.DataFrame({
        "time": pd.date_range("2026-09-01", periods=bars, freq="5min").strftime("%Y-%m-%d %H:%M:%S"),
        "open": close, "high": high, "low": low, "close": close + rng.normal(0, 10, bars),
        "tick_volume": 500, "spread": spread_pts,
    }).to_csv(path, index=False)
    return path


def main() -> int:
    print("btc/preflight.py offline")

    # --- 1. gold economics (btc config vs gold config) --------------------
    import pandas as pd

    gold_csv = ROOT / "data" / "GOLD_M5.csv"
    if gold_csv.exists():
        import importlib.util
        spec = importlib.util.spec_from_file_location("_gold_config", ROOT / "config.py")
        gold_cfg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(gold_cfg)
        import preflight
        rep = preflight.csv_cost_report(pd.read_csv(gold_csv, parse_dates=["time"]), gold_cfg)
        check("gold spread/1R reproduces the documented ~5.3-5.7%",
              0.05 < rep["cost_per_r"] < 0.06, f"{100 * rep['cost_per_r']:.2f}%")
        check("gold break-even WR reproduces 28.6% (RR 1:2.5)",
              abs(rep["breakeven_wr_pct"] - 28.6) < 0.1, f"{rep['breakeven_wr_pct']:.1f}%")
        check("gold's required WR with cost is ~30%",
              29.5 < rep["required_wr_pct"] < 31.0, f"{rep['required_wr_pct']:.1f}%")
    else:
        print("  (skipping gold economics: data/GOLD_M5.csv not present)")

    # --- 2. the BTC failure mode grades INFEASIBLE ------------------------
    # The subprocess reads btc/config.py, so derive the synthetic spreads from
    # the configured gate instead of hard-coding the retired 1500 placeholder.
    # Read btc/config.py directly: `sys.modules["config"]` is whichever instance
    # this test process activated, not necessarily the BTC one.
    import importlib.util
    _spec = importlib.util.spec_from_file_location("_btc_gate_config", HERE / "config.py")
    btc_config = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(btc_config)
    gate = float(getattr(btc_config, "MAX_SPREAD_POINTS", 0) or 0)
    infeasible_pts = int(gate * 3) if gate > 0 else 4242
    ok_pts = max(1, int(gate / 10)) if gate > 0 else 200
    with tempfile.TemporaryDirectory() as td:
        btc_csv = btc_shaped_csv(Path(td) / "BTCUSD_synth_M5.csv", spread_pts=infeasible_pts)
        proc = subprocess.run(
            [sys.executable, str(HERE / "preflight.py"), "--offline", "--csv", str(btc_csv)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        out = proc.stdout
        check(f"{infeasible_pts}-pt quotes vs the {gate:g}-pt gate -> INFEASIBLE",
              proc.returncode == 2 and "INFEASIBLE" in out,
              f"exit={proc.returncode}")
        check("the verdict explains that 0 trades is a config problem",
              "Do NOT read 0 trades" in out)
        check("the cost-per-1R is printed for the operator",
              "spread / 1R" in out and "just to break even" in out)

        # --- 3. exit code 0 when the gate clears the file ------------------
        ok_csv = btc_shaped_csv(Path(td) / "BTCUSD_ok_M5.csv", spread_pts=ok_pts)
        proc2 = subprocess.run(
            [sys.executable, str(HERE / "preflight.py"), "--offline", "--csv", str(ok_csv)],
            capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        check(f"a {ok_pts}-pt quote file against the {gate:g}-pt gate -> OK, exit 0",
              proc2.returncode == 0 and "VERDICT: OK" in proc2.stdout,
              f"exit={proc2.returncode}")

        # --- 4. no data -> UNKNOWN (never a silent OK) ---------------------
        proc3 = subprocess.run(
            [sys.executable, str(HERE / "preflight.py"), "--offline",
             "--csv", str(Path(td) / "missing.csv")],
            capture_output=True, text=True, cwd=str(ROOT), timeout=300)
        check("no quotes to grade -> UNKNOWN, exit 3",
              proc3.returncode == 3 and "UNKNOWN" in proc3.stdout,
              f"exit={proc3.returncode}")

    # --- 5. starved band is reported as starved, not infeasible -----------
    import preflight
    from spread_gate import summarise
    st = summarise(1500, [4242] * 99 + [1000])
    check("99/100 vetoes -> starved (a pass exists, so entries are possible)",
          st["state"] == "starved" and st["veto_pct"] == 99.0, st["state"])

    print(f"\n{'ALL PASS' if all(RESULTS) else 'SOME CHECKS FAILED'}  "
          f"({sum(RESULTS)}/{len(RESULTS)})")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
