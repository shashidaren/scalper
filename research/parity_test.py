"""Live vs backtest signal parity check.

The 2026-09-30 iteration found that the live path (`get_rates(count=250)`) and
the backtester (202-bar window) were evaluating *different* EMA200s, because
`ewm(span=200, adjust=False)` keeps `(1-alpha)^(n-1)` weight on the first bar of
whatever window it is handed. The fix was to pin both to
`config.INDICATOR_WINDOW_BARS`.

This script is the regression guard: for a sample of bars it feeds the *live*
code path (`ScalpStrategy.check_signal` on a trailing window of exactly
`INDICATOR_WINDOW_BARS` bars) and the replay engine
(`research.strategy_sweep.signal_at` on full-history indicators) the same data
and asserts they agree.

Run:  python research/parity_test.py
Exit: 0 = parity holds, 1 = mismatch (do not trust a sweep until this passes).
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
from strategy import ScalpStrategy  # noqa: E402
import strategy_sweep as sweep  # noqa: E402


def main(csv_file: str | None = None, step: int = 137) -> int:
    csv_file = csv_file or f"data/{config.SYMBOL}_{config.TIMEFRAME}.csv"
    window = int(getattr(config, "INDICATOR_WINDOW_BARS", 202))
    df = pd.read_csv(csv_file, parse_dates=["time"])

    p = sweep.params_from_config(label="parity")
    ind = sweep.compute_indicators(df, p)
    hours = df["time"].dt.hour.to_numpy()

    cols = ["time", "open", "high", "low", "close", "tick_volume", "spread"]
    cols = [c for c in cols if c in df.columns]

    # Replay every bar once (cheap) so we can sample *all* firing bars as well
    # as a periodic stride: signal bars are exactly where a mismatch would
    # change trades, and they are far too rare to hit by stride alone.
    replay_all = {i: sweep.signal_at(p, ind, hours, None, i)
                  for i in range(window - 1, len(df))}
    firing = [i for i, s in replay_all.items() if s]
    sampled = sorted(set(firing) | set(range(window - 1, len(df), step)))
    print(f"replay signals across the file: {len(firing)}")

    mismatches, checked, signals = [], 0, 0
    for i in sampled:
        rates = df.iloc[i - window + 1:i + 1][cols].to_dict("records")
        # fresh instance per bar so the one-shot-per-bar guard cannot interfere
        live, _, _ = ScalpStrategy().check_signal(rates, when=df["time"].iloc[i])
        replay = replay_all[i]
        checked += 1
        signals += int(replay is not None)
        if live != replay:
            mismatches.append((i, str(df["time"].iloc[i]), live, replay))

    print(f"window={window} bars, checked={checked} bars, replay signals={signals}")
    if mismatches:
        print(f"FAIL: {len(mismatches)} mismatches, first few:")
        for m in mismatches[:10]:
            print("   bar %d %s: live=%s replay=%s" % m)
        return 1
    print("PASS: live check_signal and sweep replay agree on every sampled bar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
