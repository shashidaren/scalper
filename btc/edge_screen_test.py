#!/usr/bin/env python3
"""Offline tests for btc/edge_screen.py and the cost-vs-edge maths.

No bridge, no MT5, no network. Synthetic bars with known spread and a known
stop distance let us assert the decomposition exactly:

    net_R == gross_R - cost_R          (per trade, and in the mean)

and the gold cross-check (when data/GOLD_M5.csv is present) asserts the screen
still reproduces `backtest.py`'s canonical 255 / +$456.58 / PF 1.32 baseline -
i.e. the tool does not invent its own accounting.

    python3 btc/edge_screen_test.py            # exit 0 = PASS
"""
from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import _instance  # noqa: E402

config = _instance.activate(str(HERE))
_instance.add_engine_path(str(ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import research.strategy_sweep as sweep  # noqa: E402
import edge_screen  # noqa: E402


def synth_bars(n=4000, price0=100.0, spread_pts=20, digits=2, seed=11):
    """Bars with a drifting random walk; spread fixed in points."""
    rng = np.random.default_rng(seed)
    close = price0 + np.cumsum(rng.normal(0, 0.35, n))
    high = close + np.abs(rng.normal(0, 0.8, n))
    low = close - np.abs(rng.normal(0, 0.8, n))
    return pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=n, freq="5min"),
        "open": close + rng.normal(0, 0.1, n), "high": high, "low": low,
        "close": close, "tick_volume": 1000, "spread": spread_pts,
    })


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    return bool(ok)


def main() -> int:
    results = []
    point = 10.0 ** -int(getattr(config, "PRICE_DIGITS", 2))
    df = synth_bars()
    base = replace(sweep.params_from_config(), warmup_bars=300, spread_price=None,
                   max_spread_points=None, session_enabled=False, label="t")

    # 1. gross run really charges nothing, net run charges the file's spread
    gross = sweep.run("", replace(base, spread_price=0.0), df=df)
    net = sweep.run("", base, df=df)
    results.append(check("gross and net runs trade the same bars",
                         gross["trades"] == net["trades"],
                         f"{gross['trades']} vs {net['trades']}"))
    if gross["trades"]:
        g_r = np.array([t["r"] for t in gross["trades_list"]])
        n_r = np.array([t["r"] for t in net["trades_list"]])
        c_r = g_r - n_r
        results.append(check("cost is strictly positive per trade",
                             (c_r > 0).all(), f"c mean {c_r.mean():.3f}R"))
        results.append(check("cost < 1R per trade in this fixture",
                             (c_r < 1.0).all(), f"c max {c_r.max():.3f}R"))
        row = edge_screen.screen_one(df, sweep, base, "t")
        results.append(check("screen_one nets to gross - cost",
                             abs(row["net_r"] - (row["raw_r"] - row["cost_r"])) < 1e-9,
                             f"{row['raw_r']:.4f} - {row['cost_r']:.4f} = {row['net_r']:.4f}"))
        results.append(check("verdict flag follows g > c",
                             row["pays"] == (row["raw_r"] > row["cost_r"])))

    # 2. cost models: 'file' keeps the column, 'bp' rebuilds it, 'price' drops it
    d_file, pt, note = edge_screen.apply_cost_model(df, "file", None, config)
    results.append(check("--cost file keeps the CSV spread column",
                         "spread" in d_file.columns
                         and float(d_file["spread"].iloc[0]) == float(df["spread"].iloc[0]),
                         note))
    d_bp, _, note = edge_screen.apply_cost_model(df, "bp", 5.0, config)
    want_pts = round(float(df["close"].iloc[0]) * 5.0 / 10000.0 / pt)
    results.append(check("--cost bp rebuilds the spread in points",
                         abs(float(d_bp["spread"].iloc[0]) - want_pts) <= 1, note))
    d_price, _, note = edge_screen.apply_cost_model(df, "price", None, config)
    results.append(check("--cost price leaves no column (uses the config fallback)",
                         "spread" not in d_price.columns, note))

    # 3. 'bp' converts the cost proportionally to price (regime-normalised)
    df2 = df.copy()
    df2[["open", "high", "low", "close"]] *= 10.0       # 10x price level
    d_bp2, _, _ = edge_screen.apply_cost_model(df2, "bp", 5.0, config)
    results.append(check("a 10x price level costs 10x the points at the same bp",
                         abs(float(d_bp2["spread"].iloc[0]) - 10 * float(d_bp["spread"].iloc[0])) <= 10,
                         f"{d_bp['spread'].iloc[0]} -> {d_bp2['spread'].iloc[0]} pts"))

    # 4. gold cross-check via the real CLI (subprocess, gold config):
    #    the screen must reproduce backtest.py's canonical baseline
    gold_csv = ROOT / "data" / "GOLD_M5.csv"
    if gold_csv.exists():
        import json as _json
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out_json = os.path.join(td, "rows.json")
            proc = subprocess.run(
                [sys.executable, str(HERE / "edge_screen.py"), "--config-dir", str(ROOT),
                 "--csv", str(gold_csv), "--json", out_json],
                capture_output=True, text=True, cwd=str(ROOT), timeout=900)
            if proc.returncode != 0:
                results.append(check("gold CLI run succeeds", False, proc.stderr[-200:]))
            else:
                rows = _json.load(open(out_json))["rows"]
                base_row = next(r for r in rows if r["label"].startswith("baseline"))
                results.append(check(
                    "gold baseline reproduces backtest.py (255 tr / +$456.58 / PF 1.32)",
                    base_row["trades"] == 255 and abs(base_row["net_net"] - 456.58) < 0.01
                    and abs(base_row["net_pf"] - 1.32) < 0.005,
                    f"n={base_row['trades']} net=${base_row['net_net']:.2f} "
                    f"PF={base_row['net_pf']:.2f} grossR={base_row['raw_r']:+.3f} "
                    f"costR={base_row['cost_r']:.3f}"))
                results.append(check("gold's gross edge clears its cost (g > c)",
                                     base_row["pays"] and base_row["raw_r"] > 0.1,
                                     f"g={base_row['raw_r']:+.3f} c={base_row['cost_r']:.3f}"))
    else:
        print("  (skipping gold cross-check: data/GOLD_M5.csv not present)")

    print(f"\n{'ALL PASS' if all(results) else 'SOME CHECKS FAILED'}  "
          f"({sum(results)}/{len(results)})")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
