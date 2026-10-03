#!/usr/bin/env python3
"""Small deterministic checks for the BTC train-select helpers (no market data)."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from btc.train_select import candidate_grid, rank_train_results, train_split
from research.strategy_sweep import Params, run, spread_gate_mask


def main() -> int:
    start, mid = train_split(20_000, 1_000)
    assert start == 999 and mid == 10_499, (start, mid)

    base = Params(atr_min=0.0, sl_atr_mult=2.0, be_trigger_r=1.5)
    floors = [("zero", 0.0), ("p10", 1.0), ("p25", 2.0), ("p50", 3.0), ("p75", 4.0)]
    grid = list(candidate_grid(base, floors, 5_000.0))
    assert len(grid) == 60, len(grid)
    assert any(p.be_trigger_r is None for p in grid)
    assert all(p.be_trigger_r != 0 for p in grid)
    assert all(p.max_spread_points == 5_000.0 for p in grid)

    # Only TRAIN metrics determine rank; a bogus OOS score is not accepted as input.
    rows = [
        {"train": {"trades": 30, "net": 12.0, "pf": 1.1}},
        {"train": {"trades": 25, "net": 9.0, "pf": 2.0}},
        {"train": {"trades": 8, "net": 999.0, "pf": 99.0}},
    ]
    ranked, eligible = rank_train_results(rows, min_train_trades=20)
    assert eligible and ranked[0] is rows[0]
    ranked, eligible = rank_train_results(rows, min_train_trades=40)
    assert not eligible and ranked[0] is rows[2]

    quotes = pd.DataFrame({"spread": [100, 200, 201, float("nan")]})
    mask = spread_gate_mask(quotes, 200)
    assert mask.tolist() == [False, False, True, True], mask
    assert spread_gate_mask(quotes, None) is None

    # Integration: when every quote exceeds the explicit replay gate, no entry
    # can be opened. This tests the mask is consumed by `run()`, not just built.
    close = 100.0 + np.sin(np.arange(1_200, dtype=float) / 9.0)
    bars = pd.DataFrame({
        "time": pd.date_range("2026-01-01", periods=len(close), freq="5min"),
        "open": close,
        "high": close + 0.2,
        "low": close - 0.2,
        "close": close,
        "spread": np.full(len(close), 5.0),
    })
    replay = run("", replace(Params(warmup_bars=202), max_spread_points=4.0), df=bars)
    assert replay["trades"] == 0, replay["trades"]

    try:
        spread_gate_mask(pd.DataFrame({"close": [1.0]}), 200)
    except ValueError:
        pass
    else:
        raise AssertionError("spread gate must fail closed without a spread column")

    print("BTC train-select helper tests: PASS (60 configs, train-only rank, spread veto, split)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
