#!/usr/bin/env python3
"""BTC-only, chronological train-select -> cold-OOS research screen.

Run through `btc/tool.py` so the shared replay engine uses btc/config.py:
    mt5env/bin/python btc/tool.py btc/train_select.py --csv data/BTCUSD_M5.csv

The pre-registered 5 x 3 x 4 grid varies only ATR floor, SL multiple, and BE
trigger (duplicate ATR quantiles are deduplicated, so the grid can be smaller
than 60). ATR floors and the spread-veto threshold are derived from TRAIN bars
only.
Candidates are ranked by TRAIN net (minimum trade count first; PF and count
break ties). Only the frozen winner and the pre-registered current-geometry
baseline are then evaluated on the cold second half. No OOS result is used to
rank or choose a candidate.

This is a research screen, not parameter adoption. It does not model slippage,
swap P&L, daily account gates, or weekend gaps. The spread entry veto is modeled
from the CSV's spread points; costs are charged per bar by strategy_sweep.py.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import replace
from itertools import product
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def _config_and_sweep():
    """Use the already selected instance config, or activate BTC when standalone."""
    sys.path.insert(0, str(HERE))
    import _instance

    config = sys.modules.get("config")
    expected = (HERE / "config.py").resolve()
    if config is None or Path(getattr(config, "__file__", "")).resolve() != expected:
        config = _instance.activate(str(HERE))
    _instance.add_engine_path(str(ROOT))

    import research.strategy_sweep as sweep
    return config, sweep


def train_split(n_bars: int, warmup_bars: int) -> tuple[int, int]:
    """Return first playable index and 50/50 split, leaving warmup in TRAIN."""
    start = max(0, int(warmup_bars) - 1)
    if n_bars - start < 200:
        raise ValueError(
            f"need at least 200 playable bars after warmup; got {n_bars - start}"
        )
    mid = start + (n_bars - start) // 2
    if mid <= start or n_bars - mid < 100:
        raise ValueError("not enough bars on both sides of the chronological split")
    return start, mid


def train_atr_floors(df, base, mid: int, sweep) -> list[tuple[str, float]]:
    """Build 0 / p10 / p25 / p50 / p75 floors from TRAIN-only ATR values."""
    import numpy as np

    start = max(0, base.warmup_bars - 1)
    train = df.iloc[:mid].reset_index(drop=True)
    atr = sweep.compute_indicators(train, base)["atr"][start:]
    atr = atr[np.isfinite(atr)]
    if atr.size < 100:
        raise ValueError(f"only {atr.size} valid TRAIN ATR observations")

    levels: list[tuple[str, float]] = [("zero", 0.0)]
    for name, q in (("p10", .10), ("p25", .25), ("p50", .50), ("p75", .75)):
        levels.append((name, float(np.quantile(atr, q))))

    # Avoid duplicate candidates on flat/rounded datasets without looking at OOS.
    unique: list[tuple[str, float]] = []
    for name, value in levels:
        if not any(math.isclose(value, old, rel_tol=1e-12, abs_tol=1e-12)
                   for _, old in unique):
            unique.append((name, value))
    return unique


def train_spread_gate(df, start: int, mid: int) -> tuple[float, float, float]:
    """Set a fixed 1.25x TRAIN-p90 spread veto; return (threshold, p90, vetoed%)."""
    import numpy as np
    import pandas as pd

    if "spread" not in df.columns:
        raise ValueError(
            "BTC Phase 1b requires the broker 'spread' column; refusing to use "
            "the placeholder SPREAD_COST_PRICE as evidence"
        )
    values = pd.to_numeric(df["spread"].iloc[start:mid], errors="coerce").to_numpy(float)
    values = values[np.isfinite(values)]
    if values.size < 100:
        raise ValueError(f"only {values.size} valid TRAIN spread observations")
    if np.any(values < 0):
        raise ValueError("spread points must be non-negative")
    p90 = float(np.quantile(values, .90))
    threshold = float(math.ceil((p90 * 1.25) / 10.0) * 10.0)
    vetoed_pct = 100.0 * float(np.mean(values > threshold))
    return threshold, p90, vetoed_pct


def candidate_grid(base, floor_levels, spread_threshold: float):
    """The pre-registered 5 x 3 x 4 grid; BE off is None, never 0."""
    for (floor_name, floor), sl, be in product(
        floor_levels, (2.0, 2.5, 3.0), (None, 1.0, 1.5, 2.0)
    ):
        be_label = "off" if be is None else f"{be:g}R"
        label = f"ATR {floor_name}={floor:.2f} SL={sl:g} BE={be_label}"
        params = replace(
            base,
            label=label,
            atr_min=float(floor),
            sl_atr_mult=float(sl),
            be_trigger_r=be,
            max_spread_points=float(spread_threshold),
        )
        yield params


def donchian_grid(base, spread_threshold: float):
    """Phase-1c hypothesis C grid, pre-registered 2026-10-04/10-06.

    The geometry (don100/exit50/EMA200, no TP, BE off) comes from the instance
    config and is FIXED here; only the two pre-registered levers vary:
    SL multiple (2.0-2.5) and the time-stop robustness variant (off / 100
    bars). No ATR floor was pre-registered for this family.
    """
    for sl in (2.0, 2.5):
        for ts, ts_label in ((None, "off"), (100, "100")):
            label = (f"don{base.don_entry}/exit{base.don_exit} "
                     f"SL={sl:g} ts={ts_label}")
            yield replace(
                base,
                label=label,
                sl_atr_mult=float(sl),
                max_bars_in_trade=ts,
                max_spread_points=float(spread_threshold),
            )


def rank_train_results(rows, min_train_trades: int):
    """Rank using TRAIN fields only; OOS is intentionally not an input."""
    qualified = [r for r in rows if r["train"]["trades"] >= min_train_trades]
    pool = qualified or list(rows)
    ranked = sorted(
        pool,
        key=lambda r: (
            float(r["train"]["net"]),
            float(r["train"].get("pf", 0.0)),
            int(r["train"]["trades"]),
        ),
        reverse=True,
    )
    return ranked, bool(qualified)


def bootstrap_net(trades: list[dict], n: int, seed: int = 7) -> tuple[float, float, float]:
    """Trade-level iid bootstrap CI and P(net>0), in bounded-memory batches."""
    import numpy as np

    pnl = np.asarray([t["pnl"] for t in trades], dtype=float)
    if pnl.size == 0 or n <= 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    nets = np.empty(n, dtype=float)
    batch = max(1, min(256, n))
    for offset in range(0, n, batch):
        count = min(batch, n - offset)
        idx = rng.integers(0, pnl.size, size=(count, pnl.size))
        nets[offset:offset + count] = pnl[idx].sum(axis=1)
    lo, hi = np.percentile(nets, [2.5, 97.5])
    return float(lo), float(hi), float(np.mean(nets > 0))


def _metric_line(label: str, result: dict, ci: tuple[float, float, float] | None = None) -> str:
    pf = result.get("pf", 0.0)
    pf_s = "inf" if math.isinf(pf) else f"{pf:.2f}"
    line = (f"{label:<34} n={result['trades']:>4}  net=${result['net']:>9.2f}  "
            f"PF={pf_s:>5}  maxDD=${result['max_dd']:.2f}")
    if ci is not None:
        line += f"  iid 95% CI=[${ci[0]:.2f}, ${ci[1]:.2f}]  P(net>0)={ci[2]:.3f}"
    return line


def main(argv=None) -> int:
    config, sweep = _config_and_sweep()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=None,
                    help="broker CSV with spread column (default: "
                         "data/<SYMBOL>_<TIMEFRAME>.csv, or <SYMBOL>_H1.csv "
                         "for --family donchian)")
    ap.add_argument("--family", default="scalp", choices=("scalp", "donchian"),
                    help="strategy family to select over. 'scalp' is the "
                         "Phase-1b pullback grid (ATR floor x SL x BE); "
                         "'donchian' is the pre-registered Phase-1c hypothesis C "
                         "grid (don entry/exit/EMA from config, SL 2.0-2.5, "
                         "time-stop off/100) for untouched H1 bars")
    ap.add_argument("--min-train-trades", type=int, default=20,
                    help="minimum TRAIN sample before a candidate is eligible (default 20)")
    ap.add_argument("--min-oos-trades", type=int, default=None,
                    help="minimum cold-OOS sample for the screen "
                         "(default 20 for scalp; 60 for donchian per the "
                         "pre-registered Phase-1c gate)")
    ap.add_argument("--bootstrap", type=int, default=10000,
                    help="iid trade bootstrap samples for the frozen OOS result (default 10000)")
    ap.add_argument("--top", type=int, default=10, help="TRAIN-ranked rows to print")
    args = ap.parse_args(argv)

    if args.min_oos_trades is None:
        # The Phase-1c amendment (docs/btc_spread_edge_analysis_2026-10-06.md
        # §6.3) pre-registers n >= 60 on cold OOS for the donchian family;
        # the Phase-1b scalp gate used 20.
        args.min_oos_trades = 60 if args.family == "donchian" else 20
    if args.min_train_trades < 0 or args.min_oos_trades < 0 or args.bootstrap < 0 or args.top < 1:
        ap.error("trade counts/bootstrap must be non-negative and --top must be positive")

    if args.csv is None:
        tf = "H1" if args.family == "donchian" else config.TIMEFRAME
        args.csv = str(ROOT / "data" / f"{config.SYMBOL}_{tf}.csv")
    csv_path = Path(args.csv)
    if not csv_path.is_absolute() and not csv_path.exists():
        csv_path = ROOT / csv_path
    if not csv_path.is_file():
        print(f"ERROR: BTC bar file not found: {csv_path}", file=sys.stderr)
        if args.family == "donchian":
            print("       donchian needs untouched H1 bars; pull them first on the server:\n"
                  "       mt5env/bin/python btc/recon.py --timeframe H1 --bars 20000",
                  file=sys.stderr)
        return 2

    import pandas as pd

    df = pd.read_csv(csv_path, parse_dates=["time"])
    required = {"time", "open", "high", "low", "close", "spread"}
    missing = sorted(required - set(df.columns))
    if missing:
        print(f"ERROR: BTC Phase 1b CSV missing required columns: {', '.join(missing)}",
              file=sys.stderr)
        return 2
    if df.empty or not df["time"].is_monotonic_increasing:
        print("ERROR: CSV must be non-empty and time-sorted oldest to newest", file=sys.stderr)
        return 2
    if df["time"].duplicated().any():
        print("ERROR: duplicate bar timestamps; refusing a leaky/ambiguous split", file=sys.stderr)
        return 2

    if args.family == "donchian":
        base = sweep.donchian_from_config()
    else:
        base = sweep.params_from_config()
    start, mid = train_split(len(df), base.warmup_bars)
    spread_threshold, spread_p90, vetoed_pct = train_spread_gate(df, start, mid)
    floors = None
    if args.family == "scalp":
        floors = train_atr_floors(df, base, mid, sweep)

    print("=" * 88)
    phase = "1c hypothesis C (donchian)" if args.family == "donchian" else "1b"
    print(f"BTC Phase {phase}: TRAIN-only selection, then one frozen cold-OOS read")
    print(f"symbol={config.SYMBOL}  timeframe={config.TIMEFRAME}  "
          f"family={args.family}  file={csv_path}")
    print(f"bars={len(df):,}  {df['time'].iloc[0]} .. {df['time'].iloc[-1]}")
    print(f"TRAIN={df['time'].iloc[start]} .. {df['time'].iloc[mid - 1]} ({mid - start:,} bars)")
    print(f"OOS  ={df['time'].iloc[mid]} .. {df['time'].iloc[-1]} ({len(df) - mid:,} bars)")
    if args.family == "donchian":
        ts = base.max_bars_in_trade
        print(f"warmup={base.warmup_bars}  entry=don{base.don_entry} exit=don{base.don_exit} "
              f"trendEMA={base.ema_period or 'off'}  SL={base.sl_atr_mult:g}xATR  "
              f"time-stop={ts if ts else 'off'}  BE=off  TP=none(channel exit)")
    else:
        print(f"warmup={base.warmup_bars}  RSI={base.rsi_buy:g}/{base.rsi_sell:g}  "
              f"TP={base.tp_atr_mult:g}x ATR  session_filter={base.session_enabled}")
    print("spread costs: per-bar CSV spread; entry veto: fixed 1.25x TRAIN p90")
    print(f"TRAIN spread p90={spread_p90:.1f} points -> replay MAX_SPREAD_POINTS="
          f"{spread_threshold:.0f}; {vetoed_pct:.2f}% of TRAIN quotes exceed it")
    current_gate = float(getattr(config, "MAX_SPREAD_POINTS", float("nan")))
    if math.isfinite(current_gate):
        all_train_spreads = pd.to_numeric(df["spread"].iloc[start:mid], errors="coerce").dropna()
        current_veto = 100.0 * float((all_train_spreads > current_gate).mean())
        print(f"current config MAX_SPREAD_POINTS={current_gate:g} would veto "
              f"{current_veto:.2f}% of valid TRAIN spread quotes")
    if floors is not None:
        print("ATR floors (TRAIN-only): " + ", ".join(f"{k}={v:.2f}" for k, v in floors))
    print("Research limitations: no slippage, swap P&L, daily risk gates, or weekend-gap model.")
    print("No config is changed by this script. A pass is not authorization to start a service.")
    print("=" * 88)

    rows = []
    grid = (donchian_grid(base, spread_threshold) if args.family == "donchian"
            else candidate_grid(base, floors, spread_threshold))
    for params in grid:
        train_result = sweep.run_slice(df, params, start, mid, params.label)
        rows.append({"params": params, "train": train_result})

    ranked, enough_train = rank_train_results(rows, args.min_train_trades)
    if not ranked:
        print("ERROR: no candidates were generated", file=sys.stderr)
        return 2
    print(f"\nTRAIN ranking only (eligible candidates have >= {args.min_train_trades} trades; "
          f"grid size {len(rows)}; eligible pool {'available' if enough_train else 'empty'})")
    print(f"{'rank':>4}  {'config':<34} {'trades':>7} {'net$':>10} {'PF':>7} {'maxDD$':>10}")
    for i, row in enumerate(ranked[:args.top], 1):
        r = row["train"]
        pf = r.get("pf", 0.0)
        pf_s = "inf" if math.isinf(pf) else f"{pf:.2f}"
        print(f"{i:>4}  {r['label']:<34} {r['trades']:>7} {r['net']:>10.2f} "
              f"{pf_s:>7} {r['max_dd']:>10.2f}")

    winner = ranked[0]
    frozen = winner["params"]
    print("\nFROZEN before OOS read:")
    if args.family == "donchian":
        print(f"  {frozen.label}; entry=don{frozen.don_entry} exit=don{frozen.don_exit} "
              f"trendEMA={frozen.ema_period or 'off'}; "
              f"MAX_SPREAD_POINTS={frozen.max_spread_points:.0f}")
    else:
        print(f"  {frozen.label}; RSI={frozen.rsi_buy:g}/{frozen.rsi_sell:g}; "
              f"TP={frozen.tp_atr_mult:g}; MAX_SPREAD_POINTS={frozen.max_spread_points:.0f}")

    # Only now read OOS for the frozen winner and a pre-registered baseline.
    baseline = replace(
        base,
        label="configured geometry + TRAIN spread gate",
        max_spread_points=spread_threshold,
    )
    baseline_oos = sweep.run_slice(df, baseline, mid, len(df), baseline.label)
    if frozen == baseline:
        winner_oos = baseline_oos
    else:
        winner_oos = sweep.run_slice(df, frozen, mid, len(df), frozen.label)
    base_ci = bootstrap_net(baseline_oos["trades_list"], args.bootstrap)
    win_ci = bootstrap_net(winner_oos["trades_list"], args.bootstrap)
    print("\nCOLD OOS (no candidate rankings or changes based on this read):")
    print(_metric_line("pre-registered baseline", baseline_oos, base_ci))
    print(_metric_line("TRAIN-selected candidate", winner_oos, win_ci))
    if winner_oos["trades"]:
        print(f"  winner exits: SL={winner_oos.get('sl', 0)} "
              f"BE={winner_oos.get('be', 0)} TP={winner_oos.get('tp', 0)} "
              f"CHANNEL={winner_oos.get('channel', 0)} TIME={winner_oos.get('time_exits', 0)}")

    # g > c precondition (Phase-1c amendment item 4): a shape whose gross edge
    # is smaller than the instrument's cost ratio cannot pass, whatever the
    # net. Entry logic is cost-independent, so the zero-cost rerun must produce
    # the identical trade list; otherwise something is wrong and we refuse.
    gross_ok = True
    gross_r = cost_r = None
    if args.family == "donchian" and winner_oos["trades"]:
        gross_oos = sweep.run_slice(
            df, replace(frozen, label=frozen.label + " [zero cost]", spread_price=0.0),
            mid, len(df))
        if gross_oos["trades"] != winner_oos["trades"]:
            print("ERROR: zero-cost rerun changed the trade list; refusing to gate")
            return 2
        gross_r = sum(t["r"] for t in gross_oos["trades_list"]) / gross_oos["trades"]
        net_r = sum(t["r"] for t in winner_oos["trades_list"]) / winner_oos["trades"]
        cost_r = gross_r - net_r
        gross_ok = gross_r > cost_r
        print(f"  gross vs cost (OOS, R/trade): g={gross_r:+.3f}  c={cost_r:.3f}  "
              f"-> {'g > c' if gross_ok else 'g <= c: the shape cannot pay for the spread'}")

    passes = (
        enough_train
        and winner_oos["trades"] >= args.min_oos_trades
        and winner_oos["net"] > 0
        and winner_oos.get("pf", 0.0) >= 1.2
        and gross_ok
    )
    gate_desc = ("positive cold-OOS net, PF >= 1.2, sufficient OOS trades"
                 + (", g > c" if args.family == "donchian" else ""))
    print(f"\nScreen gate ({gate_desc}): "
          + ("PASS — review costs/risk and fresh data; do not auto-adopt" if passes
             else "FAIL — negative result is acceptable; do not tune until it looks positive"))
    if win_ci[0] <= 0:
        print("Bootstrap note: the iid 95% net CI includes zero; this is not strong evidence of edge.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
