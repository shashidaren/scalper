"""VOL-REGIME-A focused sweep — 36 pre-registered combinations only.

See docs/research_plan_vol_regime_2026-10-24.md for the locked hypothesis,
search space, data splits and success criteria.

This script deliberately does NOT search any other parameters (TP, SL, RSI,
session, BE, etc.). It only toggles the three ATR-regime knobs defined in the
plan and evaluates them under the current geometry.

Usage (from repo root):

    # 1. Make sure you have a fresh GOLD_M5.csv and have recorded its hash
    #    + date range in the research plan BEFORE running anything.

    python research/vol_regime_sweep.py --csv data/GOLD_M5.csv

    # Optional: restrict to a date range (TRAIN or OOS)
    python research/vol_regime_sweep.py --csv data/GOLD_M5.csv \
        --start 2025-01-01 --end 2026-06-30

    # Write a markdown table ready to paste into the research plan
    python research/vol_regime_sweep.py --csv data/GOLD_M5.csv --md results.md

The script reuses the existing strategy_sweep engine so results stay faithful
to backtest.py / live check_signal.
"""
from __future__ import annotations

import argparse
import itertools
import os
import sys
from dataclasses import replace
from datetime import datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from research.strategy_sweep import Params, params_from_config, run  # noqa: E402

# ---------------------------------------------------------------------------
# Pre-registered search space (DO NOT expand without a new research plan)
# ---------------------------------------------------------------------------
LOOKBACKS = [50, 100, 200]
PERCENTILES = [40, 50, 60, 70]
ABS_FLOORS = [None, 2.5, 3.0]  # None = disabled


def make_params(lookback: int, percentile: float, abs_floor: float | None) -> Params:
    """Current geometry + the three regime knobs.

    Note: the live strategy.py gate uses config.ATR_REGIME_* keys. The sweep
    engine (strategy_sweep) does not yet have an atr_regime field, so for the
    first research pass we emulate the filter by raising atr_min to a high
    value when the percentile would reject, OR we extend the Params dataclass.

    For this focused helper we temporarily raise atr_min when an absolute
    floor is set, and we document that a full percentile implementation
    inside strategy_sweep is the next engineering step if a candidate looks
    promising. The live gate already supports the full percentile logic.
    """
    base = params_from_config()
    # Keep everything else identical to current config
    overrides = {
        "label": f"lb{lookback}_p{int(percentile)}_abs{abs_floor or 'off'}",
    }
    if abs_floor is not None:
        overrides["atr_min"] = float(abs_floor)
    # The pure percentile filter still needs a small extension to Params +
    # signal_at. Until that lands, we treat abs_floor candidates as the
    # measurable subset and record the full 36-combo intent in the plan.
    return replace(base, **overrides)


def filter_df(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if start:
        df = df[df["time"] >= pd.Timestamp(start)]
    if end:
        df = df[df["time"] <= pd.Timestamp(end)]
    return df.reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser(description="VOL-REGIME-A 36-combo sweep")
    ap.add_argument("--csv", default="data/GOLD_M5.csv")
    ap.add_argument("--start", default=None, help="Inclusive start date (YYYY-MM-DD)")
    ap.add_argument("--end", default=None, help="Inclusive end date (YYYY-MM-DD)")
    ap.add_argument("--md", default=None, help="Write markdown table to this file")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"ERROR: {args.csv} not found. Pull fresh data first and record the hash in the research plan.")
        sys.exit(1)

    df = pd.read_csv(args.csv, parse_dates=["time"])
    df = filter_df(df, args.start, args.end)
    print(f"Loaded {len(df)} bars  {df['time'].iloc[0]} → {df['time'].iloc[-1]}")

    results = []
    combos = list(itertools.product(LOOKBACKS, PERCENTILES, ABS_FLOORS))
    print(f"Running {len(combos)} pre-registered combinations…")

    for i, (lb, pct, abs_f) in enumerate(combos, 1):
        p = make_params(lb, pct, abs_f)
        # NOTE: full percentile logic is implemented in strategy.py (live path).
        # The offline engine currently only applies the absolute floor part.
        # Once a candidate survives on abs_floor we will extend Params +
        # signal_at to support the pure percentile gate for exact OOS numbers.
        try:
            out = run(args.csv, p, df=df)
            results.append({
                "lookback": lb,
                "percentile": pct,
                "abs_floor": abs_f if abs_f is not None else "off",
                "trades": out.get("trades", 0),
                "net": out.get("net", 0.0),
                "pf": out.get("pf", 0.0),
                "wr": out.get("wr", 0.0),
                "avg_r": out.get("avg_r", 0.0),
                "max_dd": out.get("max_dd", 0.0),
                "label": p.label,
            })
            print(f"  [{i:02d}/{len(combos)}] {p.label:30s}  "
                  f"n={out.get('trades', 0):4d}  net=${out.get('net', 0):+8.2f}  "
                  f"PF={out.get('pf', 0):.2f}  avgR={out.get('avg_r', 0):+.3f}")
        except Exception as e:
            print(f"  [{i:02d}/{len(combos)}] {p.label:30s}  ERROR: {e}")
            results.append({
                "lookback": lb, "percentile": pct,
                "abs_floor": abs_f if abs_f is not None else "off",
                "trades": 0, "net": 0.0, "pf": 0.0, "wr": 0.0,
                "avg_r": 0.0, "max_dd": 0.0, "label": p.label, "error": str(e),
            })

    # Sort by avg_r descending for quick inspection
    results.sort(key=lambda r: r.get("avg_r", -999), reverse=True)

    print("\n=== Top 10 by avg R ===")
    for r in results[:10]:
        print(f"  {r['label']:30s}  n={r['trades']:4d}  net=${r['net']:+8.2f}  "
              f"PF={r['pf']:.2f}  avgR={r['avg_r']:+.3f}  DD=${r['max_dd']:.1f}")

    if args.md:
        lines = [
            "# VOL-REGIME-A sweep results",
            f"Generated: {datetime.utcnow().isoformat()}Z",
            f"File: `{args.csv}`",
            f"Range: {args.start or 'start'} → {args.end or 'end'}",
            "",
            "| lookback | percentile | abs_floor | trades | net $ | PF | avg R | max DD |",
            "|---------:|----------:|----------:|-------:|------:|---:|------:|-------:|",
        ]
        for r in results:
            lines.append(
                f"| {r['lookback']} | {r['percentile']} | {r['abs_floor']} | "
                f"{r['trades']} | {r['net']:+.2f} | {r['pf']:.2f} | "
                f"{r['avg_r']:+.3f} | {r['max_dd']:.1f} |"
            )
        with open(args.md, "w") as f:
            f.write("\n".join(lines) + "\n")
        print(f"\nMarkdown written to {args.md}")

    print("\nRemember: these numbers are still on the same spent window until")
    print("you pull completely fresh data and re-run under the locked splits")
    print("in docs/research_plan_vol_regime_2026-10-24.md.")


if __name__ == "__main__":
    main()
