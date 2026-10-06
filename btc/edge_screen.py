#!/usr/bin/env python3
"""Edge screen: does a shape's GROSS edge beat what the spread costs?

Why this exists
---------------
Phase 1b showed why BTC M5 lost: the *price* of the trade is the spread. The
replay (`research/strategy_sweep.py`) charges the spread inside each trade, so
it answers "did this configuration make money?". It does not answer the more
useful question when a run fails:

    was the loss the signal's fault, or the cost's?

This tool splits one configuration into its two halves, in R units (1R = the
stop distance), so the answer has a scale:

    gross edge   g = average R per trade with the spread charged at ZERO
    cost ratio   c = average (spread / stop distance) per trade
    net edge       = g - c

A shape can only pay for the spread when **g > c**. For gold (validated below)
g = +0.21R and c = 0.054R, so it clears. For XM BTCUSD M5, Phase 1b measured
g = +0.02R against c = 0.26R, i.e. the shape was ~13x short - and no amount of
stop/target tuning moves c by anything like that factor.

The screen is instrument-generic and works on any CSV in the repo format
(`time,open,high,low,close,tick_volume[,spread]`); `--cost bp` charges a
*relative* spread so price-level-different data (a $9,000 BTC proxy vs a
$77,000 quote) can be compared honestly.

What it is NOT
--------------
Diagnostic only. It reports economics of a fixed geometry; it does not select
parameters, does not write config, and does not replace the Phase 1 gate
(train-select -> cold-OOS in `btc/HANDOFF.md` §5). Never adopt a parameter
because this table likes it - re-run it through the gate on untouched data.

Usage
-----
    # on the real BTC file (cost from the file's own spread column)
    mt5env/bin/python btc/tool.py btc/edge_screen.py --csv data/BTCUSD_M5.csv

    # charge a relative spread instead (e.g. the XM measured 5.49 bp of price)
    mt5env/bin/python btc/tool.py btc/edge_screen.py --csv data/BTCUSD_M15.csv --cost bp --spread-bp 5.49

    # sanity-check the maths on gold, where g > c is known to hold
    python btc/edge_screen.py --config-dir . --csv data/GOLD_M5.csv

    # more/other geometries, exported rows for pasting into a report
    python btc/edge_screen.py --csv data/BTCUSD_H1.csv --detail --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import replace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

BANNER = ("DIAGNOSTIC ONLY - the numbers below do NOT adopt a parameter. "
          "Selection still requires btc/train_select.py on untouched data.")


def _load_config(config_dir: str | None):
    sys.path.insert(0, HERE)
    import _instance  # noqa: E402

    target = os.path.abspath(config_dir) if config_dir else HERE
    _instance.activate(target)
    _instance.add_engine_path(ROOT)
    import config  # noqa: E402

    return config


# --------------------------------------------------------------------------
# cost models
# --------------------------------------------------------------------------
def apply_cost_model(df, mode: str, spread_bp: float | None, config):
    """Return (df, point, cost_note).  The replay reads the CSV's `spread`
    column when `Params.spread_price is None`, and falls back to
    `config.SPREAD_COST_PRICE` when the column is absent - so each mode returns
    exactly the frame that encodes that cost.

    mode "file": keep the CSV's own `spread` column (points) - same cost basis
                 as `backtest.py`.
    mode "bp":   replace it with a RELATIVE spread of `spread_bp` basis points
                 of price (round to whole points), so data from a different
                 price regime can be charged this instrument's real spread.
    mode "price": no column - let the replay charge config.SPREAD_COST_PRICE.
    """
    import numpy as np

    digits = int(getattr(config, "PRICE_DIGITS", 2))
    point = 10.0 ** -digits

    if mode == "file":
        if "spread" not in df.columns:
            raise SystemExit("--cost file needs a `spread` column in the CSV; "
                             "use --cost bp or --cost price instead")
        return df, point, f"per-bar CSV spread column (points x {point:g})"

    if mode == "price":
        out = df.drop(columns=["spread"], errors="ignore")
        return out, point, (f"constant config.SPREAD_COST_PRICE="
                            f"{getattr(config, 'SPREAD_COST_PRICE', 0.45)} px")

    if not spread_bp or spread_bp <= 0:
        raise SystemExit("--cost bp needs a positive --spread-bp")

    out = df.copy()
    close = out["close"].to_numpy(float)
    pts = np.round(close * spread_bp / 10000.0 / point)
    out["spread"] = pts
    return out, point, (f"relative {spread_bp:g} bp of price = "
                        f"{pts.min():.0f}-{pts.max():.0f} points across the file")


# --------------------------------------------------------------------------
# one configuration: gross vs net
# --------------------------------------------------------------------------
def screen_one(df, sweep, base, label: str, **overrides) -> dict:
    """Run one geometry twice (spread at zero / spread at the modelled cost)."""
    p_gross = replace(base, label=label, spread_price=0.0, **overrides)
    gross = sweep.run("", p_gross, df=df)
    if not gross["trades"]:
        return {"label": label, "trades": 0}

    p_net = replace(base, label=label, **overrides)   # spread_price from base
    net = sweep.run("", p_net, df=df)

    g_r = [t["r"] for t in gross["trades_list"]]
    n_r = [t["r"] for t in net["trades_list"]]
    if len(g_r) != len(n_r):
        # entry logic is cost-independent, so this means the CSV/params moved
        raise RuntimeError(f"{label}: gross/nets trade counts differ "
                           f"({len(g_r)} vs {len(n_r)}) - refusing to report")
    cost_r = [a - b for a, b in zip(g_r, n_r)]
    n = len(g_r)

    return {
        "label": label, "trades": n,
        "raw_r": sum(g_r) / n, "cost_r": sum(cost_r) / n,
        "net_r": sum(n_r) / n,
        "net_net": net["net"], "net_pf": net.get("pf", float("nan")),
        "gross_pf": gross.get("pf", float("nan")),
        "win_rate": net.get("win_rate", 0.0),
        "tp": net.get("tp", 0), "be": net.get("be", 0), "sl": net.get("sl", 0),
        "time_exits": net.get("time_exits", 0), "channel": net.get("channel", 0),
        "pays": (sum(g_r) / n) > (sum(cost_r) / n),
    }


def donchian_variants(config) -> list[tuple[str, dict]]:
    """Diagnostic variants around the pre-registered hypothesis-C geometry.

    The base geometry (entry/exit/EMA/time-stop) comes from the instance
    config; only the pre-registered levers (SL multiple, time stop, trend
    filter, channel lookbacks) are varied, one at a time. Screening only —
    selection still goes through btc/train_select.py --family donchian on
    untouched bars.
    """
    entry_n = int(getattr(config, "DONCHIAN_ENTRY_BARS", 20))
    exit_n = int(getattr(config, "DONCHIAN_EXIT_BARS", max(1, entry_n // 2)))
    v = [(f"baseline don{entry_n}/exit{exit_n} (as configured)", {})]
    for sl in (1.5, 2.0, 2.5, 3.0):
        v.append((f"sl {sl}xATR", {"sl_atr_mult": sl}))
    for ts in (50, 100, 200):
        v.append((f"time stop {ts} bars", {"max_bars_in_trade": ts}))
    v.append(("trend EMA off", {"ema_period": 0}))
    for ne, nx in ((50, 25), (150, 75), (200, 100)):
        v.append((f"don{ne}/exit{nx}", {"don_entry": ne, "don_exit": nx}))
    return v


def default_variants(config) -> list[tuple[str, dict]]:
    """One-variable-at-a-time variants around the instance's own geometry."""
    v = [("baseline (as configured)", {})]
    for lo, hi in ((30, 70), (35, 65), (45, 55)):
        v.append((f"rsi {lo}/{hi}", {"rsi_buy": lo, "rsi_sell": hi}))
    for sl in (1.5, 2.5, 3.0):
        v.append((f"sl {sl}xATR", {"sl_atr_mult": sl}))
    for tp in (3.0, 4.0, 6.0, 10.0):
        v.append((f"tp {tp}xATR", {"tp_atr_mult": tp}))
    v.append(("be off", {"be_trigger_r": None}))
    v.append(("be 1.0R", {"be_trigger_r": 1.0}))
    v.append(("be 2.0R", {"be_trigger_r": 2.0}))
    for bars in (12, 24, 48):
        v.append((f"time stop {bars} bars", {"max_bars_in_trade": bars}))
    v.append(("session on 07-20 UTC", {"session_enabled": True,
                                       "session_start": 7, "session_end": 20}))
    v.append(("h1 trend filter", {"h1_trend": True}))
    return v


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------
HEAD = (f"{'geometry':<28}{'tr':>7}{'grossR':>9}{'costR':>8}{'netR':>8}"
        f"{'PFnet':>7}{'net$':>10}{'WR%':>7}{'TP/BE/SL':>11}{'  verdict'}")


def fmt_row(r: dict) -> str:
    if not r.get("trades"):
        return f"{r['label']:<28}{0:>7}   (no trades)"
    verdict = "g > c" if r["pays"] else "g < c (cannot pay)"
    star = "  POSITIVE" if r["net_r"] > 0 else ""
    exits = f"{r.get('tp', 0)}/{r.get('be', 0)}/{r.get('sl', 0)}"
    if r.get("channel") or r.get("time_exits"):   # donchian: SL/CHANNEL/TIME
        exits = f"{r.get('sl', 0)}/{r.get('channel', 0)}/{r.get('time_exits', 0)}*"
    return (f"{r['label']:<28}{r['trades']:>7}{r['raw_r']:>9.3f}{r['cost_r']:>8.3f}"
            f"{r['net_r']:>8.3f}{r['net_pf']:>7.2f}{r['net_net']:>10.2f}"
            f"{r['win_rate']:>7.1f}{exits:>11}  {verdict}{star}")


def report(df, sweep, base, config, variants, cost_note, csv_path, detail=False) -> tuple[list[str], list[dict]]:
    import numpy as np

    lines = ["=" * 118,
             f"EDGE SCREEN  {config.SYMBOL} {config.TIMEFRAME}   {csv_path}",
             f"cost model: {cost_note}",
             f"lot {base.lot_size} x contract {getattr(config, 'CONTRACT_SIZE', 100.0)}"
             f" | warm-up {base.warmup_bars} bars | {len(df):,} bars"
             f" {df['time'].iloc[0]} .. {df['time'].iloc[-1]}",
             "=" * 118]
    if detail:
        atr = sweep.compute_indicators(df, base)["atr"]
        med = float(np.nanmedian(atr))
        price = float(df["close"].median())
        lines.append(f"median ATR14 {med:,.2f} px = {10000*med/price:.2f} bp of price "
                     f"(median price {price:,.2f})")
    lines += [HEAD, "-" * 118]
    if getattr(base, "family", "scalp") == "donchian":
        lines.append(f"  (family=donchian: exits column is SL/CHANNEL/TIME; "
                     f"shape {getattr(base, 'don_entry', '?')}/"
                     f"{getattr(base, 'don_exit', '?')} EMA{base.ema_period or ' off'}, "
                     f"no TP, no BE)")

    rows = []
    for label, over in variants:
        r = screen_one(df, sweep, base, label, **over)
        rows.append(r)
        lines.append(fmt_row(r))

    done = [r for r in rows if r.get("trades")]
    if done:
        best = max(done, key=lambda r: r["net_r"])
        lines += ["-" * 118,
                  f"trades {min(r['trades'] for r in done)}-{max(r['trades'] for r in done)}"
                  f" | best net edge: {best['label']} {best['net_r']:+.3f}R/trade"
                  f" (gross {best['raw_r']:+.3f} vs cost {best['cost_r']:.3f})",
                  f"a shape needs grossR > costR to break even; costR is set by the "
                  f"instrument, grossR by the signal."]
    lines += ["=" * 118, BANNER, "=" * 118]
    return lines, rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config-dir", default=None,
                    help="instance dir whose config.py to use (default: btc/)")
    ap.add_argument("--csv", default=None,
                    help="bar file (default: data/<SYMBOL>_<TIMEFRAME>.csv)")
    ap.add_argument("--cost", default="file", choices=("file", "bp", "price"),
                    help="file = the CSV's spread column (default), "
                         "bp = relative spread of --spread-bp of price, "
                         "price = constant config.SPREAD_COST_PRICE")
    ap.add_argument("--spread-bp", type=float, default=None,
                    help="spread in basis points of price for --cost bp")
    ap.add_argument("--warmup", type=int, default=None,
                    help="warm-up bars (default: config.INDICATOR_WINDOW_BARS)")
    ap.add_argument("--family", default="scalp", choices=("scalp", "donchian"),
                    help="shape to screen: 'scalp' = the shipped EMA+RSI "
                         "pullback (default), 'donchian' = the pre-registered "
                         "Phase-1c breakout geometry from the instance config")
    ap.add_argument("--detail", action="store_true", help="print ATR context")
    ap.add_argument("--json", default=None, help="also write the rows to this file")
    args = ap.parse_args(argv)

    config = _load_config(args.config_dir)
    import pandas as pd

    default_tf = "H1" if args.family == "donchian" else config.TIMEFRAME
    csv = args.csv or os.path.join(ROOT, "data", f"{config.SYMBOL}_{default_tf}.csv")
    if not os.path.exists(csv):
        pull_tf = f" --timeframe {default_tf}" if args.family == "donchian" else ""
        print(f"ERROR: {csv} not found.\n"
              f"Pull it first on the server: mt5env/bin/python btc/recon.py{pull_tf} --bars 20000")
        return 2
    df = pd.read_csv(csv, parse_dates=["time"])
    df, _point, cost_note = apply_cost_model(df, args.cost, args.spread_bp, config)

    sys.path.insert(0, ROOT)
    import research.strategy_sweep as sweep  # noqa: E402

    warmup = args.warmup if args.warmup is not None else int(
        getattr(config, "INDICATOR_WINDOW_BARS", 202))
    if args.family == "donchian":
        base = replace(sweep.donchian_from_config(), warmup_bars=warmup,
                       spread_price=None, max_spread_points=None)
        variants = donchian_variants(config)
    else:
        base = replace(sweep.params_from_config(), warmup_bars=warmup,
                       spread_price=None, max_spread_points=None)
        variants = default_variants(config)

    lines, rows = report(df, sweep, base, config, variants,
                         cost_note, csv, detail=args.detail)
    print("\n".join(lines))
    if args.json:
        def _plain(o):
            if hasattr(o, "item"):
                return o.item()
            if isinstance(o, (str, int, float, bool)) or o is None:
                return o
            return str(o)

        with open(args.json, "w") as f:
            json.dump({"csv": csv, "cost": cost_note, "rows": rows},
                      f, indent=2, default=_plain)
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
