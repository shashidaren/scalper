"""Anatomy of the losing trades — where the strategy bleeds and whether it is fixable.

Why this exists
---------------
`backtest.py` reports aggregates (255 trades / PF 1.32 / 72 TP / 43 BE / 140 SL)
but not *which* trades lose, *when*, or *why*. Before deciding whether to keep
or change the adopted config (`BE_TRIGGER_R=1.5`, RSI 40/60, session 07-20 UTC)
we need the loss distribution decomposed by exit type, side, hour, weekday,
month, volatility, time-in-trade, and excursion path.

This tool does not re-implement the strategy. It replays through
`research/strategy_sweep.py`'s `run()` (verified bit-for-bit against
`backtest.py` by `--verify`) and re-derives each trade's entry price / SL
distance with the same `compute_indicators()` the sweep and the live strategy
share, then joins per-bar path data (MFE/MAE in R units) to every trade.

Outputs
-------
  * exit-type anatomy (count, $ and R per exit, share of gross loss)
  * cost decomposition (spread paid vs realised edge)
  * loss clustering: streaks, worst days, and what the live daily-loss gate
    (config.MAX_DAILY_LOSS) would have done to the backtest's PnL
  * conditional loss rate by hour / weekday / side / month / ATR bucket
  * excursion analysis: how close full-SL losers came to the BE trigger
    (i.e. is 1.5R the right ratchet under the *current* config?)

Usage
-----
    python research/loss_analysis.py                 # full report
    python research/loss_analysis.py --csv data/GOLD_M5.csv --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import replace

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402
from research.strategy_sweep import (  # noqa: E402
    CONTRACT_SIZE,
    compute_indicators,
    params_from_config,
    run,
)


def build_trades(csv_file: str, df: pd.DataFrame | None = None, p=None):
    """Replay the current config and enrich every trade with path/context data."""
    if df is None:
        df = pd.read_csv(csv_file, parse_dates=["time"])
    p = p or params_from_config()
    res = run(csv_file, replace(p, label="current config"), df=df)
    ind = compute_indicators(df, p)
    close, high, low, atr = ind["close"], ind["high"], ind["low"], ind["atr"]

    times = pd.to_datetime(df["time"])
    idx_of = {t: i for i, t in enumerate(times)}

    spread_col = None
    if "spread" in df.columns:
        spread_col = np.nan_to_num(df["spread"].to_numpy(float) * 0.01,
                                   nan=float(getattr(config, "SPREAD_COST_PRICE", 0.45)))

    out = []
    for t in res["trades_list"]:
        exit_i = idx_of[pd.Timestamp(t["time"])]
        entry_i = exit_i - int(t["bars"])          # bar where management began
        sig_i = entry_i - 1                        # signal bar (window index -2)
        entry = float(close[sig_i])
        sl_dist = float(atr[sig_i]) * p.sl_atr_mult
        side = t["type"]

        seg_h = high[entry_i:exit_i + 1]
        seg_l = low[entry_i:exit_i + 1]
        if side == "BUY":
            mfe = (float(seg_h.max()) - entry) / sl_dist if sl_dist else 0.0
            mae = (entry - float(seg_l.min())) / sl_dist if sl_dist else 0.0
        else:
            mfe = (entry - float(seg_l.min())) / sl_dist if sl_dist else 0.0
            mae = (float(seg_h.max()) - entry) / sl_dist if sl_dist else 0.0

        et = pd.Timestamp(t["time"])
        out.append({
            **{k: v for k, v in t.items() if k != "trades_list"},
            "entry": entry,
            "sl_dist": sl_dist,
            "atr": float(atr[sig_i]),
            "mfe_r": mfe,
            "mae_r": mae,
            "hour": int(times.iloc[entry_i].hour),
            "weekday": int(times.iloc[entry_i].dayofweek),
            "month": str(times.iloc[entry_i].to_period("M")),
            "day": str(times.iloc[entry_i].date()),
            "spread_paid": float(spread_col[exit_i]) if spread_col is not None else float(p.spread_price),
            "exit_time": et,
        })
    return res, out, df, p


def _stats(trades):
    n = len(trades)
    if not n:
        return {"n": 0, "net": 0.0, "pf": 0.0, "wr": 0.0, "avg_r": 0.0, "loss_rate": 0.0}
    pnl = np.array([t["pnl"] for t in trades])
    gp = float(pnl[pnl > 0].sum())
    gl = float(abs(pnl[pnl <= 0].sum()))
    return {
        "n": n,
        "net": float(pnl.sum()),
        "pf": (gp / gl) if gl > 0 else float("inf"),
        "wr": 100.0 * float((pnl > 0).sum()) / n,
        "loss_rate": 100.0 * float((pnl <= 0).sum()) / n,
        "avg_r": float(np.mean([t["r"] for t in trades])),
    }


def report(csv_file: str, json_out: str | None = None) -> list[str]:
    res, trades, df, p = build_trades(csv_file)
    out = []
    w = out.append
    pnl = np.array([t["pnl"] for t in trades])
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    w("=" * 78)
    w("LOSS ANATOMY — current config (replayed via research/strategy_sweep.py)")
    w(f"  {csv_file}: {len(df)} bars, {df['time'].min()} -> {df['time'].max()}")
    w(f"  params: BE={p.be_trigger_r}R SL={p.sl_atr_mult}xATR TP={p.tp_atr_mult}xATR "
      f"RSI={p.rsi_buy}/{p.rsi_sell} session={p.session_start}-{p.session_end}UTC")
    w("=" * 78)
    w(f"trades {res['trades']}  net ${res['net']:.2f}  PF {res['pf']:.2f}  "
      f"WR {res['win_rate']:.1f}%  avgR {res['avg_r']:.2f}  maxDD ${res['max_dd']:.2f}")
    w(f"gross profit ${wins.sum():.2f} over {len(wins)} wins | "
      f"gross loss ${abs(losses.sum()):.2f} over {len(losses)} non-wins")

    # --- 1. exit-type anatomy -------------------------------------------
    w("")
    w("--- 1. Exit anatomy: which exits pay, which bleed ---")
    w("  {:<6}{:>6}{:>11}{:>10}{:>9}{:>12}{:>14}".format(
        "exit", "n", "net$", "avg$", "avgR", "% of trades", "% of gross loss"))
    gl_total = abs(losses.sum())
    for kind in ("TP", "BE", "SL", "TIME"):
        sub = [t for t in trades if t["result"] == kind]
        if not sub:
            continue
        s = _stats(sub)
        share = 100.0 * abs(min(s["net"], 0.0)) / gl_total if gl_total else 0.0
        w("  {:<6}{:>6}{:>11.2f}{:>10.2f}{:>9.2f}{:>11.1f}%{:>13.1f}%".format(
            kind, s["n"], s["net"], s["net"] / s["n"], s["avg_r"],
            100.0 * s["n"] / len(trades), share))
    # BE exits are scratches: quantify their true cost (spread only)
    be = [t for t in trades if t["result"] == "BE"]
    if be:
        w(f"  BE exits are spread-only scratches: they cost "
          f"${abs(sum(t['pnl'] for t in be)):.2f} total "
          f"(avg ${abs(sum(t['pnl'] for t in be)) / len(be):.2f}/trade) vs "
          f"${abs(sum(t['pnl'] for t in trades if t['result'] == 'SL')):.2f} "
          f"for full stop-outs.")

    # --- 2. cost decomposition ------------------------------------------
    w("")
    w("--- 2. Cost decomposition (spread is charged once per trade) ---")
    total_spread = sum(t["spread_paid"] for t in trades) * (p.lot_size * CONTRACT_SIZE)
    w(f"  spread paid:        ${total_spread:.2f}  "
      f"({100.0 * total_spread / (wins.sum() + total_spread):.0f}% of gross profit)")
    w(f"  net before spread:  ${res['net'] + total_spread:.2f}")
    w(f"  net after spread:   ${res['net']:.2f}")
    w(f"  avg spread/trade:   ${total_spread / len(trades):.2f}  "
      f"(1R = avg ${np.mean([t['sl_dist'] for t in trades]) * p.lot_size * CONTRACT_SIZE:.2f})")
    w("  -> a +1R winner nets ~"
      f"${np.mean([t['sl_dist'] for t in trades]) * p.lot_size * CONTRACT_SIZE - total_spread / len(trades):.2f} "
      "after spread; break-even WR at 2R SL / 5R TP is 28.6% before costs.")

    # --- 3. loss clustering / streaks / daily gate ----------------------
    w("")
    w("--- 3. Loss clustering ---")
    seq = pnl <= 0
    runs, cur = [], 0
    for is_loss in seq:
        if is_loss:
            cur += 1
        else:
            if cur:
                runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    runs_arr = np.array(runs) if runs else np.array([0])
    w(f"  losing streaks: {len(runs)} runs, max {runs_arr.max()} in a row, "
      f"mean {runs_arr.mean():.2f}")
    hist = defaultdict(int)
    for r in runs:
        hist[r] += 1
    w("  streak length -> count: " +
      ", ".join(f"{k}x:{hist[k]}" for k in sorted(hist)))
    cfg_max = int(getattr(config, "MAX_CONSECUTIVE_LOSSES", 4))
    w(f"  config.MAX_CONSECUTIVE_LOSSES={cfg_max} is defined but UNUSED in "
      f"run.py; {sum(v for k, v in hist.items() if k > cfg_max)} streak(s) "
      f"exceeded it.")

    daily = defaultdict(float)
    daily_n = defaultdict(int)
    for t in trades:
        daily[t["day"]] += t["pnl"]
        daily_n[t["day"]] += 1
    days = pd.Series(daily)
    gate = float(getattr(config, "MAX_DAILY_LOSS", 30.0))
    breached = days[days <= -gate]
    w(f"  trading days: {len(days)}; worst day ${days.min():.2f} "
      f"({daily_n[days.idxmin()]} trades), best day ${days.max():.2f}")
    w(f"  days <= config.MAX_DAILY_LOSS (-${gate:.0f}): {len(breached)} "
      f"totalling ${breached.sum():.2f} ({100.0 * abs(breached.sum()) / abs(losses.sum()):.0f}% of gross loss)")
    w("  NOTE: backtest.py does not model the daily-loss gate, so the live path "
      "would stop early on those days — backtest and live PnL diverge there.")

    # --- 3b. what the live gates would actually have done ---------------
    gate_pnl, gate_days, d_pnl, d_n, blocked = 0.0, set(), 0.0, 0, 0
    max_cap = int(getattr(config, "MAX_TRADES_PER_DAY", 15))
    cur_day = None
    for t in trades:
        if t["day"] != cur_day:
            cur_day, d_pnl, d_n = t["day"], 0.0, 0
        if d_pnl <= -gate or d_n >= max_cap:      # run.py checks before entry
            blocked += 1
            continue
        gate_pnl += t["pnl"]
        d_pnl += t["pnl"]
        d_n += 1
        gate_days.add(cur_day)
    w(f"  re-running the same trades through the LIVE gates "
      f"(MAX_DAILY_LOSS=-${gate:.0f}, MAX_TRADES_PER_DAY={max_cap}, "
      f"run.py:151-159) blocks {blocked} trades -> net ${gate_pnl:.2f} "
      f"({'+' if gate_pnl > res['net'] else ''}{gate_pnl - res['net']:.2f} vs the "
      f"ungated backtest). Max trades in any one day: {max(daily_n.values())} "
      f"(cap {max_cap} {'never binds' if max(daily_n.values()) < max_cap else 'BINDS'}).")

    # --- 3c. what wiring MAX_CONSECUTIVE_LOSSES would do ----------------
    for n_consec in (3, int(cfg_max), 5, 6):
        c_pnl, c_blocked, cur_day2 = 0.0, 0, None
        day_streak, halted = 0, False
        for t in trades:
            if t["day"] != cur_day2:
                cur_day2, day_streak, halted = t["day"], 0, False
            if halted:
                c_blocked += 1
                continue
            c_pnl += t["pnl"]
            day_streak = day_streak + 1 if t["pnl"] <= 0 else 0
            if day_streak >= n_consec:
                halted = True
        w(f"  if MAX_CONSECUTIVE_LOSSES={n_consec} were wired (pause for the rest "
          f"of the day): blocks {c_blocked:>2} trades -> net ${c_pnl:.2f} "
          f"({'+' if c_pnl > res['net'] else ''}{c_pnl - res['net']:.2f} vs ungated)")

    # --- 4. conditional loss rates --------------------------------------
    w("")
    w("--- 4. Where the losses concentrate (conditional expectancy) ---")

    def group(label, keyfn, order=None):
        w(f"  by {label}:")
        w("    {:<12}{:>6}{:>8}{:>10}{:>8}{:>8}{:>9}".format(
            label, "n", "net$", "PF", "WR%", "avgR", "loss%"))
        buckets = defaultdict(list)
        for t in trades:
            buckets[keyfn(t)].append(t)
        keys = order if order else sorted(buckets, key=lambda k: sum(x["pnl"] for x in buckets[k]))
        for k in keys:
            if k not in buckets:
                continue
            s = _stats(buckets[k])
            w("    {:<12}{:>6}{:>8.2f}{:>10.2f}{:>8.1f}{:>8.2f}{:>8.1f}%".format(
                str(k)[:12], s["n"], s["net"], s["pf"], s["wr"], s["avg_r"], s["loss_rate"]))

    group("side", lambda t: t["type"], order=["BUY", "SELL"])
    group("hour(UTC)", lambda t: t["hour"])
    group("weekday", lambda t: ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][t["weekday"]],
          order=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])
    group("month", lambda t: t["month"])
    atrs = np.array([t["atr"] for t in trades])
    qs = np.quantile(atrs, [0.25, 0.5, 0.75])

    def atr_bucket(t):
        a = t["atr"]
        if a <= qs[0]:
            return f"ATR q1(<={qs[0]:.2f})"
        if a <= qs[1]:
            return "ATR q2"
        if a <= qs[2]:
            return "ATR q3"
        return f"ATR q4(>{qs[2]:.2f})"

    group("ATR quartile", atr_bucket,
          order=[f"ATR q1(<={qs[0]:.2f})", "ATR q2", "ATR q3", f"ATR q4(>{qs[2]:.2f})"])

    # --- 5. excursion analysis: is 1.5R the right BE ratchet? -----------
    w("")
    w("--- 5. Excursion analysis (MFE in R) — the BE-trigger question ---")
    sl = [t for t in trades if t["result"] == "SL"]
    w(f"  full stop-outs: {len(sl)} trades, ${sum(t['pnl'] for t in sl):.2f}")
    w("  (R here = the SL distance, so a full stop-out is -1R and a TP is "
      f"+{p.tp_atr_mult / p.sl_atr_mult:.1f}R; BE_TRIGGER_R uses the same units)")
    for thr in (0.25, 0.5, 0.75, 1.0, 1.25):
        near = [t for t in sl if t["mfe_r"] >= thr]
        w(f"    reached +{thr:.2f}R before dying: {len(near):>3} "
          f"({100.0 * len(near) / len(sl):.0f}%) — a BE trigger at {thr}R would "
          f"have scratched these for spread instead of the full -1R")

    be_r = p.be_trigger_r
    w(f"  BE arms at +{be_r}R: {sum(1 for t in trades if t['mfe_r'] >= be_r)} trades "
      f"ever got that far ({100.0 * sum(1 for t in trades if t['mfe_r'] >= be_r) / len(trades):.0f}%)")
    tp = [t for t in trades if t["result"] == "TP"]
    w(f"  TP hits ({len(tp)}): avg {sum(t['bars'] for t in tp) / len(tp):.0f} bars in trade; "
      f"SL hits: avg {sum(t['bars'] for t in sl) / len(sl):.0f} bars; "
      f"BE: {sum(t['bars'] for t in be) / len(be):.0f} bars" if be else "")
    w("  -> losers resolve faster than winners: the market tells you a trade is "
      "wrong quickly, which is what makes a time-based exit testable.")

    # --- 6. tail risk / concentration -----------------------------------
    w("")
    w("--- 6. Concentration ---")
    srt = sorted(trades, key=lambda t: -t["pnl"])
    top5 = sum(t["pnl"] for t in srt[:5])
    top10 = sum(t["pnl"] for t in srt[:10])
    w(f"  top-5 winners: ${top5:.2f} ({100.0 * top5 / res['net']:.0f}% of net); "
      f"top-10: ${top10:.2f} ({100.0 * top10 / res['net']:.0f}%)")
    worst5_str = ", ".join("%.2f" % t["pnl"] for t in srt[-5:])
    w(f"  worst-5 losers: {worst5_str}")
    w(f"  worst single loss ${srt[-1]['pnl']:.2f} = "
      f"{abs(srt[-1]['r']):.2f}R ({srt[-1]['type']} {srt[-1]['time']})")
    net_wo5 = res["net"] - top5
    w(f"  net excluding top-5 winners: ${net_wo5:.2f} "
      f"({'still profitable' if net_wo5 > 0 else 'TURNED NEGATIVE'})")

    if json_out:
        payload = {
            "params": res["params"],
            "summary": {k: res[k] for k in ("trades", "net", "pf", "win_rate", "avg_r", "max_dd")},
            "gross_profit": float(wins.sum()),
            "gross_loss": float(abs(losses.sum())),
            "spread_paid": float(total_spread),
            "trades": [{k: (str(v) if isinstance(v, (pd.Timestamp,)) else v)
                        for k, v in t.items()} for t in trades],
        }
        with open(json_out, "w") as fh:
            json.dump(payload, fh, indent=1, default=str)
        w(f"\nper-trade JSON written to {json_out}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=f"data/{config.SYMBOL}_{config.TIMEFRAME}.csv")
    ap.add_argument("--json", default=None, help="also dump per-trade rows to this JSON file")
    args = ap.parse_args(argv)
    for line in report(args.csv, args.json):
        print(line)


if __name__ == "__main__":
    main()
