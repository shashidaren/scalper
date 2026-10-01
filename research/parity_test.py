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
from mt5_bridge import MT5Bridge  # noqa: E402
from strategy import ScalpStrategy  # noqa: E402
import strategy_sweep as sweep  # noqa: E402


class _FakeTick:
    def __init__(self, time_sec: int, bid: float = 4000.0, ask: float = 4000.45):
        self.time = int(time_sec)
        self.time_msc = int(time_sec) * 1000
        self.bid = float(bid)
        self.ask = float(ask)


class _FakeMT5ForRates:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_H1 = 60

    def __init__(self, struct_rates):
        self._all_rates = struct_rates
        self.end_idx = len(struct_rates)
        self.calls = []  # list of requested counts

    def copy_rates_from_pos(self, symbol, tf, start_pos, count):
        self.calls.append(int(count))
        end = self.end_idx - int(start_pos)
        start = max(0, end - int(count))
        return self._all_rates[start:end].copy()


def _check_bridge_cache_parity(df: pd.DataFrame, replay_all: dict,
                               window: int, margin: int) -> int:
    """Verify MT5Bridge.get_rates() closed-bar caching across 15s loop cycles:
      1) reacts on the very first 15s tick after a new bar closes (0 mismatches),
      2) cuts full 1050-bar RPyC fetches by ~20x (1 per 5m bar instead of 20),
      3) works both when `tick` is passed (0 RPyC calls mid-bar) and when
         `tick` is omitted (2-bar probe mid-bar).
    """
    import numpy as np

    full_count = window + margin
    # Pick a 60-bar slice that includes several real firing signals
    firing_indices = [i for i, s in replay_all.items() if s and i >= full_count + 10]
    start_bar = firing_indices[0] - 5 if firing_indices else full_count
    end_bar = min(len(df), start_bar + 60)
    n_bars = end_bar - start_bar

    dtype = [
        ("time", "i8"), ("open", "f8"), ("high", "f8"),
        ("low", "f8"), ("close", "f8"), ("tick_volume", "i8"), ("spread", "i8"),
    ]
    struct_rates = np.zeros(len(df), dtype=dtype)
    struct_rates["time"] = df["time"].astype("datetime64[s]").astype("int64").to_numpy()
    for col in ("open", "high", "low", "close"):
        struct_rates[col] = df[col].to_numpy(float)
    if "tick_volume" in df.columns:
        struct_rates["tick_volume"] = df["tick_volume"].to_numpy(int)
    if "spread" in df.columns:
        struct_rates["spread"] = df["spread"].to_numpy(int)

    for mode in ("with_tick", "probe_only"):
        fake_mt5 = _FakeMT5ForRates(struct_rates)
        bridge = MT5Bridge.__new__(MT5Bridge)
        bridge.mt5 = fake_mt5
        bridge.conn = None
        bridge._closed = False
        bridge.invalidate_rates_cache()
        bridge.rates_full_fetches = 0
        bridge.rates_cache_hits = 0

        strat = ScalpStrategy()
        cycles_per_bar = 20  # 20 x 15s = 300s (one M5 bar)

        for bar_i in range(start_bar, end_bar):
            fake_mt5.end_idx = bar_i + 1
            forming_ts = int(struct_rates[bar_i]["time"])
            bar_dt = df["time"].iloc[bar_i]
            expected_sig = replay_all[bar_i]

            for cycle in range(cycles_per_bar):
                tick = _FakeTick(forming_ts + cycle * 15) if mode == "with_tick" else None
                rates = bridge.get_rates(tick=tick)
                sig, sl_d, tp_d = strat.check_signal(rates, when=bar_dt)

                if cycle == 0:
                    # Must react on the very first 15s cycle after the bar closes
                    if sig != expected_sig:
                        print(f"FAIL ({mode}): bar {bar_i} cycle 0 sig={sig} != expected={expected_sig}")
                        return 1
                else:
                    # Subsequent cycles inside the same 5m bar must not re-fire
                    if sig is not None:
                        print(f"FAIL ({mode}): bar {bar_i} cycle {cycle} duplicate fire {sig}")
                        return 1
                    if expected_sig is not None and strat.last_skip_reason != "duplicate_bar":
                        print(f"FAIL ({mode}): bar {bar_i} cycle {cycle} expected duplicate_bar, got {strat.last_skip_reason}")
                        return 1

        full_calls = sum(1 for c in fake_mt5.calls if c == full_count)
        if full_calls != n_bars:
            print(f"FAIL ({mode}): expected {n_bars} full fetches ({full_count} bars), got {full_calls}")
            return 1
        if mode == "with_tick" and len(fake_mt5.calls) != n_bars:
            print(f"FAIL (with_tick): expected {n_bars} total RPyC calls, got {len(fake_mt5.calls)}")
            return 1

    print(f"bridge cache check: {n_bars} M5 bars x 20 (15s) cycles = {n_bars * 20} loops -> "
          f"{n_bars} full ({full_count}-bar) fetches (20x reduction), 0 signal/timing mismatches")
    return 0


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

    # Margin invariance: the bridge fetches window + INDICATOR_FETCH_MARGIN
    # bars and check_signal must slice back to `window`, so the extra bars
    # cannot shift the signal (live stays identical to the backtest).
    margin = int(getattr(config, "INDICATOR_FETCH_MARGIN", 0))
    margin_bad = []
    if margin > 0:
        for i in sampled:
            if i - window - margin + 1 < 0:
                continue
            wide = df.iloc[i - window - margin + 1:i + 1][cols].to_dict("records")
            got, _, _ = ScalpStrategy().check_signal(wide, when=df["time"].iloc[i])
            if got != replay_all[i]:
                margin_bad.append((i, str(df["time"].iloc[i]), got, replay_all[i]))
            # Real extra bars barely move a converged EMA, so the check above
            # alone cannot prove the slice exists. Poison the margin bars: if
            # check_signal really ignores everything before the last `window`
            # bars, the result is unchanged; a missing slice would flip it.
            poisoned = [dict(r) for r in wide]
            for r in poisoned[:margin]:
                for k in ("open", "high", "low", "close"):
                    r[k] = float(r[k]) * 1000.0
            got, _, _ = ScalpStrategy().check_signal(poisoned, when=df["time"].iloc[i])
            if got != replay_all[i]:
                margin_bad.append((i, str(df["time"].iloc[i]), got, replay_all[i]))
        print(f"margin check: window+{margin} bars (real and poisoned) vs window alone, "
              f"{len(margin_bad)} mismatches")
        if margin_bad:
            print("FAIL: INDICATOR_FETCH_MARGIN shifts signals:")
            for m in margin_bad[:10]:
                print("   bar %d %s: wide=%s replay=%s" % m)
            return 1
    if mismatches:
        print(f"FAIL: {len(mismatches)} mismatches, first few:")
        for m in mismatches[:10]:
            print("   bar %d %s: live=%s replay=%s" % m)
        return 1

    if _check_bridge_cache_parity(df, replay_all, window, margin) != 0:
        return 1

    print("PASS: live check_signal and sweep replay agree on every sampled bar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
