#!/usr/bin/env python3
"""Breakout-family screen (hypothesis C prototype) - screening only.

Why this exists
---------------
`btc/edge_screen.py` measures the *shipped* shape (EMA200 + RSI pullback +
ATR SL/TP + BE). On BTC that shape is a coin flip: its gross edge (~+0.02R on
XM M5, +0.03..+0.09R on proxy H1) is smaller than the XM spread cost
(0.03..0.26R of 1R depending on timeframe). Tuning it does not change that.

This script screens a *different* family against the same cost model, so a
hypothesis is only pre-registered for a real data pull if it first shows a
gross edge that can plausibly pay for the spread on proxy data:

    entry: close breaks the highest high / lowest low of the last N bars
           (Donchian, signal on the closed bar, fill at that bar's close)
    filter: optional close > EMA(span) for longs (mirror for shorts)
    stop:  entry -/+ sl_mult x ATR(14), fixed
    exit:  opposite Donchian channel (N/2) on close, or a time stop
    cost:  one round-trip spread per trade, charged in *basis points of price*
           (`--spread-bp`, default the measured XM Standard 5.486 bp) so bars
           from a different price regime are charged this instrument's real
           cost. `--spread-bp 0` gives the gross edge.

Output: gross vs net PF / R / $, plus era buckets from a single run (bucketing
trades by entry time avoids the warm-up and open-position artefacts of
re-running each era separately).

THIS IS NOT THE ENGINE AND NOT EVIDENCE
---------------------------------------
* Proxy bars are exchange spot klines (see docs/btc_spread_edge_analysis_2026-10-06.md
  for the sources); XM CFD bars can differ. Do not quote these numbers as XM
  results and do not treat a variant that screens well as an adopted parameter.
* If this family is pursued, it must be implemented in the engine
  (`btc/strategy_btc.py` + a parity-tested replay path) and then go through
  `btc/train_select.py` on **untouched** XM bars, exactly like Phase 1b.
  Nothing here may replace that gate.

Usage
-----
    python3 btc/breakout_screen.py --csv /tmp/proxy/btc_1h_2017_2025.csv --eras
    python3 btc/breakout_screen.py --csv data/BTCUSD_H1.csv --spread-bp 5.486
    python3 btc/breakout_screen.py --csv f.csv --entry 150 --exit 75 --sl 2.0
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

XM_SPREAD_BP = 5.486          # measured on the real XM BTCUSD M5 file (2026-10-03 run)


def atr_series(df, period: int = 14) -> np.ndarray:
    h, l, c = (df[x].to_numpy(float) for x in ("high", "low", "close"))
    pc = np.concatenate(([np.nan], c[:-1]))
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    return pd.Series(tr).rolling(period).mean().to_numpy()


def ema_series(x, span: int) -> np.ndarray:
    return pd.Series(x).ewm(span=span, adjust=False).mean().to_numpy()


def donchian(high, low, n: int):
    hh = pd.Series(high).rolling(n).max().shift(1).to_numpy()
    ll = pd.Series(low).rolling(n).min().shift(1).to_numpy()
    return hh, ll


def backtest(df, entry_n: int = 100, exit_n: int | None = None, sl_mult: float = 2.0,
             trend_ema: int | None = 200, time_stop: int | None = None,
             spread_bp: float = XM_SPREAD_BP, warmup: int = 1000,
             lot: float = 0.01, contract: float = 1.0) -> dict:
    """Bar-close Donchian breakout replay. Pessimistic SL-first, spread on close."""
    exit_n = exit_n or max(1, entry_n // 2)
    h, l, c = (df[x].to_numpy(float) for x in ("high", "low", "close"))
    atr = atr_series(df)
    ema = ema_series(c, trend_ema) if trend_ema else None
    hh, ll = donchian(h, l, entry_n)
    hhx, llx = donchian(h, l, exit_n)

    trades, pos = [], None
    for i in range(warmup, len(df)):
        if pos is None:
            up = c[i] > hh[i] and not np.isnan(hh[i])
            dn = c[i] < ll[i] and not np.isnan(ll[i])
            if ema is not None and not np.isnan(ema[i]):
                up, dn = up and c[i] > ema[i], dn and c[i] < ema[i]
            if not (up or dn) or np.isnan(atr[i]) or atr[i] <= 0:
                continue
            side = "BUY" if up else "SELL"
            entry = c[i]
            sl_dist = atr[i] * sl_mult
            pos = {"side": side, "entry": entry, "sl_dist": sl_dist,
                   "sl": entry - sl_dist if side == "BUY" else entry + sl_dist,
                   "cost": spread_bp / 10000.0 * entry, "bar": i}
            continue

        raw = None
        if pos["side"] == "BUY":
            if l[i] <= pos["sl"]:
                raw = pos["sl"] - pos["entry"]
            elif c[i] < llx[i]:
                raw = c[i] - pos["entry"]
        else:
            if h[i] >= pos["sl"]:
                raw = pos["entry"] - pos["sl"]
            elif c[i] > hhx[i]:
                raw = pos["entry"] - c[i]
        if raw is None and time_stop is not None and i - pos["bar"] >= time_stop:
            raw = (c[i] - pos["entry"]) if pos["side"] == "BUY" else (pos["entry"] - c[i])
        if raw is not None:
            r = (raw - pos["cost"]) / pos["sl_dist"]
            trades.append({"r": r, "pnl": r * pos["sl_dist"] * lot * contract,
                           "time": df["time"].iloc[i], "sl_dist": pos["sl_dist"],
                           "side": pos["side"]})
            pos = None

    if not trades:
        return {"n": 0, "trades": []}
    r = np.array([t["r"] for t in trades])
    pnl = np.array([t["pnl"] for t in trades])
    w, ls = pnl[pnl > 0], pnl[pnl <= 0]
    return {"n": len(r), "trades": trades, "avg_r": r.mean(), "net": pnl.sum(),
            "wr": 100 * len(w) / len(pnl),
            "pf": (w.sum() / abs(ls.sum())) if len(ls) and ls.sum() else float("inf")}


def summarize(tag: str, df, spread_bp: float = XM_SPREAD_BP, **kw) -> dict:
    gross = backtest(df, spread_bp=0.0, **kw)
    net = backtest(df, spread_bp=spread_bp, **kw)
    if not net["n"]:
        print(f"  {tag:<46} no trades")
        return net
    print(f"  {tag:<46} n={net['n']:>4}  gross PF{gross['pf']:>5.2f} R{gross['avg_r']:+.3f} "
          f"${gross['net']:>8.2f} | net PF{net['pf']:>5.2f} R{net['avg_r']:+.3f} "
          f"${net['net']:>8.2f} WR{net['wr']:>5.1f}%")
    return net


def eras(df, tag: str, **kw) -> list[tuple[str, dict]]:
    """Per-era PF/net from ONE full run (no slice/warm-up artefacts)."""
    res = backtest(df, **kw)
    if not res["n"]:
        print(f"  {tag}: no trades")
        return []
    t = pd.DataFrame(res["trades"])
    t["time"] = pd.to_datetime(t["time"])
    out = []
    # half-open windows: a trade on 31 Dec must land in ITS bucket (an inclusive
    # "<= 2024-12-31" compares against midnight and silently drops that day)
    for name, a, b in [("2017-2018", "2017-01-01", "2019-01-01"),
                       ("2019-2020", "2019-01-01", "2021-01-01"),
                       ("2021-2022", "2021-01-01", "2023-01-01"),
                       ("2023-2024", "2023-01-01", "2025-01-01"),
                       ("2025+", "2025-01-01", "2031-01-01")]:
        sub = t[(t["time"] >= a) & (t["time"] < b)]["pnl"].to_numpy(float)
        if not len(sub):
            out.append((name, {"n": 0}))
            continue
        w, l = sub[sub > 0], sub[sub <= 0]
        out.append((name, {"n": len(sub),
                           "pf": (w.sum() / abs(l.sum())) if len(l) and l.sum() else float("inf"),
                           "net": sub.sum(), "wr": 100 * len(w) / len(sub)}))
    print(f"\n  era buckets - {tag}")
    print(f"    {'era':<12}{'n':>6}{'PF':>7}{'net$':>10}{'WR%':>7}")
    for name, s in out:
        if s.get("n"):
            print(f"    {name:<12}{s['n']:>6}{s['pf']:>7.2f}{s['net']:>10.2f}{s['wr']:>7.1f}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", required=True, help="bar file (time,open,high,low,close[,tick_volume])")
    ap.add_argument("--entry", type=int, default=100, help="Donchian entry lookback (default 100)")
    ap.add_argument("--exit", type=int, default=None, help="exit channel (default entry/2)")
    ap.add_argument("--sl", type=float, default=2.0, help="stop = N x ATR(14) (default 2.0)")
    ap.add_argument("--ema", type=int, default=200, help="trend filter EMA span (0 = off)")
    ap.add_argument("--time-stop", type=int, default=None, help="bars (0 = off)")
    ap.add_argument("--spread-bp", type=float, default=XM_SPREAD_BP,
                    help=f"round-trip spread in bp of price (default {XM_SPREAD_BP}; 0 = gross)")
    ap.add_argument("--warmup", type=int, default=1000)
    ap.add_argument("--scan", action="store_true", help="scan a small lookback grid")
    ap.add_argument("--eras", action="store_true", help="also print per-era buckets")
    args = ap.parse_args(argv)

    df = pd.read_csv(args.csv, parse_dates=["time"])
    print("=" * 118)
    print(f"BREAKOUT SCREEN (prototype, not the engine)  {args.csv}  {len(df):,} bars "
          f"{df['time'].iloc[0]} .. {df['time'].iloc[-1]}")
    print(f"cost model: {args.spread_bp:g} bp of price per round trip "
          f"(0.01 lot x 1 BTC; XM measured Standard = {XM_SPREAD_BP})")
    print("=" * 118)
    kw = dict(trend_ema=args.ema or None, time_stop=args.time_stop or None,
              warmup=args.warmup, spread_bp=args.spread_bp)
    if args.scan:
        for ne, nx in ((20, 10), (50, 25), (100, 50), (150, 75), (200, 100)):
            for sl in (2.0, 3.0):
                summarize(f"donchian{ne} exit{nx} sl{sl}xATR ema{args.ema}", df,
                          entry_n=ne, exit_n=nx, sl_mult=sl, **kw)
    else:
        summarize(f"donchian{args.entry} exit{args.exit or args.entry // 2} "
                  f"sl{args.sl}xATR ema{args.ema}", df, entry_n=args.entry,
                  exit_n=args.exit, sl_mult=args.sl, **kw)
        if args.eras:
            eras(df, f"don{args.entry}/exit{args.exit or args.entry // 2} sl{args.sl}",
                 entry_n=args.entry, exit_n=args.exit, sl_mult=args.sl, **kw)
    print("\nScreening only: a variant that screens well is a candidate for a PRE-REGISTERED\n"
          "train-select -> cold-OOS run on untouched XM bars, never an adopted parameter.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
