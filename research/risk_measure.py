#!/usr/bin/env python3
"""Measure the two tail-risk rules before anyone turns them on.

`docs/live_readiness_review_2026-10-23.md` §4.3 (weekend flat / hold cap) and
§4.4 (equity floor) are *risk* decisions, not signal decisions, but they still
have a P&L cost and that cost has to be priced, not guessed. This tool prices
them on the same two datasets the rest of the repo uses:

  1. **Weekend flat** - replay the adopted config, then ask of every trade
     "what if it had been closed at the Friday 20:00 UTC boundary instead?".
  2. **Weekend gap profile** - what the M5 file actually does across the
     Friday->Monday break (the risk the backtester cannot model: it fills the
     SL at the stop price, never through it).
  3. **Time stop** - the same counterfactual at 4/6/8/12 hours.
  4. **Equity floor** - stop trading at -X% from start / from peak, replayed
     over the backtest and over the live paper book.

**Limitation, stated up front.** (1) and (3) are a post-hoc swap on a fixed
trade sequence: closing a trade early also frees the slot for a trade the
engine never took, so these numbers price the *rule*, not a full counterfactual
replay. That is the same convention `docs/loss_analysis_2026-10-02.md` used for
the daily gate ("blocks 5 trades -> net $438.48, i.e. -$18.10"). They are
sufficient to answer "is this rule free, cheap, or expensive?".

Run:  python research/risk_rules.py
      python research/risk_rules.py --csv data/GOLD_M5.csv --paper logs/ledger.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

import config  # noqa: E402
import strategy_sweep as sweep  # noqa: E402

POINT = 10.0 ** -int(getattr(config, "PRICE_DIGITS", 2))
LOT = float(getattr(config, "LOT_SIZE", 0.01))
CONTRACT = float(getattr(config, "CONTRACT_SIZE", 100.0))
WEEKEND_FLAT_HOUR = 20          # UTC, Friday


# ----------------------------------------------------------------- helpers
def _load(csv_file):
    df = pd.read_csv(csv_file, parse_dates=["time"])
    df = df.sort_values("time").reset_index(drop=True)
    return df


def _bar_at_or_after(df, when):
    """Index of the first bar at/after `when`, or None."""
    i = int(df["time"].searchsorted(pd.Timestamp(when), side="left"))
    return i if i < len(df) else None


def _spread_at(df, i):
    if "spread" in df.columns and pd.notna(df["spread"].iloc[i]):
        return float(df["spread"].iloc[i]) * POINT
    return float(getattr(config, "SPREAD_COST_PRICE", 0.45))


def _first_friday_cutoff(entry_t, exit_t):
    """First Friday-20:00-UTC instant strictly inside (entry_t, exit_t]."""
    t = pd.Timestamp(entry_t)
    # advance to the next Friday
    days = (4 - t.weekday()) % 7
    cut = (t + timedelta(days=days)).replace(hour=WEEKEND_FLAT_HOUR, minute=0,
                                             second=0, microsecond=0)
    if cut <= t:
        cut += timedelta(days=7)
    return cut if cut <= pd.Timestamp(exit_t) else None


def _counterfactual(df, trade, when):
    """Close `trade` at the first bar at/after `when`. Returns (pnl$, reason)."""
    entry_t = pd.Timestamp(trade["entry_time"])
    exit_t = pd.Timestamp(trade["time"])
    if when is None or when <= entry_t or when > exit_t:
        return None
    i = _bar_at_or_after(df, when)
    if i is None:
        return None
    px = float(df["close"].iloc[i])
    spread = _spread_at(df, i)
    side = trade["type"]
    diff = (px - trade["entry"]) if side == "BUY" else (trade["entry"] - px)
    return (diff - spread) * LOT * CONTRACT


def _entry_prices(df, trades):
    """The replay fills at the signal bar's close; recover it by timestamp."""
    lookup = {pd.Timestamp(t): float(c) for t, c in zip(df["time"], df["close"])}
    out = []
    for t in trades:
        t = dict(t)
        t["entry"] = lookup.get(pd.Timestamp(t["entry_time"]), float("nan"))
        out.append(t)
    return out


def _pf(pnls):
    gp = sum(p for p in pnls if p > 0)
    gl = abs(sum(p for p in pnls if p <= 0))
    return (gp / gl) if gl > 0 else float("inf")


# ----------------------------------------------------------------- sections
def report_weekend(df, trades, label):
    print(f"\n=== 1. weekend flat @ Friday {WEEKEND_FLAT_HOUR:02d}:00 UTC — {label} ===")
    affected, deltas, winners_lost, losers_saved = [], [], [], []
    for t in trades:
        cut = _first_friday_cutoff(t["entry_time"], t["time"])
        if cut is None:
            continue
        cf = _counterfactual(df, t, cut)
        if cf is None:
            continue
        affected.append((t, cut, cf))
        deltas.append(cf - t["pnl"])
        if t["pnl"] > 0:
            winners_lost.append(t["pnl"] - cf)
        else:
            losers_saved.append(cf - t["pnl"])

    print(f"  trades held over a Friday cut-off : {len(affected)} of {len(trades)} "
          f"({100.0 * len(affected) / max(len(trades), 1):.1f}%)")
    if not affected:
        print("  no exposure in this window")
        return
    base = sum(t["pnl"] for t in trades)
    adj = base + sum(deltas)
    print(f"  net $   : actual {base:+8.2f} -> with the rule {adj:+8.2f} "
          f"(delta {sum(deltas):+.2f})")
    print(f"  PF      : actual {_pf([t['pnl'] for t in trades]):.2f} -> with the rule "
          f"{_pf([t['pnl'] for t in trades if t not in [a[0] for a in affected]] + [a[2] for a in affected]):.2f}")
    print(f"  of those trades: {len(winners_lost)} would have closed a winner early "
          f"(forgone ${sum(winners_lost):+.2f}), {len(losers_saved)} avoided a weekend hold "
          f"(${sum(losers_saved):+.2f} better)")
    worst = sorted(deltas)[:3]
    print(f"  worst three deltas: {', '.join(f'{d:+.2f}' for d in worst)}")
    for t, cut, cf in sorted(affected, key=lambda a: a[2] - a[0]["pnl"])[:5]:
        print(f"    {t['type']:4s} {str(t['entry_time'])[:16]} -> {str(t['time'])[:16]} "
              f"({t['result']:2s}) actual {t['pnl']:+7.2f}  weekend-close {cf:+7.2f} "
              f"  [{cut}]")


def report_gaps(df):
    print("\n=== 2. weekend gap profile (what the backtest cannot model) ===")
    dt = df["time"].diff().dt.total_seconds()
    gaps = df.index[dt > 2 * 3600]
    rows = []
    for i in gaps:
        prev_close = float(df["close"].iloc[i - 1])
        nxt_open = float(df["open"].iloc[i])
        move = nxt_open - prev_close
        rows.append((df["time"].iloc[i], move, 100.0 * move / prev_close))
    if not rows:
        print("  no gaps > 2h in this file")
        return
    moves = [r[1] for r in rows]
    print(f"  gaps > 2h: {len(rows)} | |move| median ${statistics.median([abs(m) for m in moves]):.2f}, "
          f"p90 ${sorted(abs(m) for m in moves)[int(0.9 * (len(moves) - 1))]:.2f}, "
          f"max ${max(abs(m) for m in moves):.2f}")
    atr = (df["high"] - df["low"]).rolling(14).mean()
    med_atr = float(atr.median())
    print(f"  median ATR14 ${med_atr:.2f} -> the largest gap is "
          f"{max(abs(m) for m in moves) / med_atr:.1f}x ATR")
    worst = sorted(rows, key=lambda r: -abs(r[1]))[:3]
    for when, move, pct in worst:
        print(f"    {str(when)[:16]}  gap {move:+.2f} ({pct:+.2f}%)")
    print("  NOTE: a stop filled through a gap costs more than 1R. The backtest "
          "fills at the stop price, so this tail is invisible in every P&L "
          "number in this repo.")


def report_time_stop(df, trades, label):
    print(f"\n=== 3. time stop — {label} ===")
    print(f"  {'cap':>6}  {'affected':>8}  {'delta$':>9}  {'net$':>9}  {'PF':>5}")
    base = sum(t["pnl"] for t in trades)
    for hours in (4, 6, 8, 12, 24):
        deltas, pnls = [], []
        for t in trades:
            when = pd.Timestamp(t["entry_time"]) + timedelta(hours=hours)
            cf = _counterfactual(df, t, when)
            if cf is None:
                pnls.append(t["pnl"])
            else:
                pnls.append(cf)
                deltas.append(cf - t["pnl"])
        print(f"  {hours:>4}h  {len(deltas):>8}  {sum(deltas):>+9.2f}  "
              f"{base + sum(deltas):>+9.2f}  {_pf(pnls):>5.2f}")


def report_equity_floor(pnls, start, label):
    print(f"\n=== 4. equity floor — {label} (start ${start:.0f}, 0.01 lots) ===")
    print(f"  {'mode':>6} {'floor':>6}  {'stopped at':>11}  {'final$':>8}  {'kept %':>7}  note")
    for mode in ("start", "peak"):
        for pct in (10, 15, 20, 25, 30, 40, 50):
            bal, peak, stop_at = float(start), float(start), None
            for i, p in enumerate(pnls, 1):
                bal += p
                peak = max(peak, bal)
                ref = start if mode == "start" else peak
                if bal <= ref * (1.0 - pct / 100.0):
                    stop_at = i
                    break
            if stop_at is None:
                note = "never binds"
            else:
                note = f"halted {len(pnls) - stop_at} trades early"
            print(f"  {mode:>6} {pct:>5}%  {('trade ' + str(stop_at)) if stop_at else '-':>11}  "
                  f"{bal:>8.2f}  {100.0 * bal / start:>6.1f}%  {note}")


def paper_sequence(path):
    rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    exits = [r for r in rows if r.get("event") == "SIM_EXIT" and r.get("time", "") >= "2026-10-04"]
    return [float(r["profit"]) for r in exits], len([r for r in rows if r.get("event") == "SIM_ENTRY"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", default=str(ROOT / "data" / f"{config.SYMBOL}_{config.TIMEFRAME}.csv"))
    ap.add_argument("--paper", default=str(ROOT / "logs" / "ledger.jsonl"))
    ap.add_argument("--warmup", type=int, default=1000)
    args = ap.parse_args(argv)

    df = _load(args.csv)
    p = sweep.params_from_config()
    if args.warmup != p.warmup_bars:
        from dataclasses import replace
        p = replace(p, warmup_bars=args.warmup)
    res = sweep.run(args.csv, p, df=df)
    trades = _entry_prices(df, res["trades_list"])
    label = (f"adopted config, {len(trades)} trades, "
             f"{str(df['time'].iloc[0])[:10]}..{str(df['time'].iloc[-1])[:10]}")
    print(f"=== baseline — {label} ===")
    print(sweep.fmt(res))

    report_weekend(df, trades, "full file")
    report_gaps(df)
    report_time_stop(df, trades, "full file")

    report_equity_floor([t["pnl"] for t in trades], 300.0, "backtest, $300 account")
    report_equity_floor([t["pnl"] for t in trades], 1000.0, "backtest, $1000 account")

    if Path(args.paper).exists():
        pnls, n_entries = paper_sequence(args.paper)
        if pnls:
            print(f"\n=== 5. live paper book ({len(pnls)} closed since 2026-10-04) ===")
            print(f"  net ${sum(pnls):+.2f} on a $300 start, PF {_pf(pnls):.2f}")
            report_equity_floor(pnls, 300.0, "paper book")
    return 0


if __name__ == "__main__":
    sys.exit(main())
