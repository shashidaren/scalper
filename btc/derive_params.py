"""Turn a real BTCUSD bar file into the config values that are placeholders.

`btc/config.py` ships with every instrument-shaped number flagged PLACEHOLDER
(`ATR_MIN`, `MAX_SPREAD_POINTS`, `SPREAD_COST_PRICE`, `PRICE_DIGITS`, the risk
gates). This script is the honest way to replace them: it reads the CSV that
`btc/recon.py` writes (the broker's own bars, including its `spread` column)
and derives each one from the measured distribution, printing a ready-to-paste
config block plus the economics that decide whether the instrument is even
scalpable at 0.01 lots.

It does **not** write anything and it does **not** pick a strategy. Parameter
*adoption* still has to go through Phase 1 (train-select -> cold-OOS,
`btc/HANDOFF.md` §5); these are the starting values that sweep should explore
around, not a result.

Usage (on the server, once data/BTCUSD_M5.csv exists):
    mt5env/bin/python btc/tool.py btc/derive_params.py
    mt5env/bin/python btc/tool.py btc/derive_params.py --csv data/BTCUSD_M5.csv

Run it on gold to sanity-check the maths against a known instrument:
    python btc/derive_params.py --csv data/GOLD_M5.csv --config-dir .
"""
from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def _load_config(config_dir: str | None):
    """Activate an instance config (default: this BTC instance)."""
    sys.path.insert(0, HERE)
    import _instance  # noqa: E402

    target = os.path.abspath(config_dir) if config_dir else HERE
    _instance.activate(target)
    _instance.add_engine_path(ROOT)
    import config  # noqa: E402

    return config


def _fmt(x, nd=2):
    return "n/a" if x is None else f"{x:,.{nd}f}"


def analyse(df, config):
    import numpy as np
    import pandas as pd

    digits = int(getattr(config, "PRICE_DIGITS", 2))
    point = 10.0 ** -digits
    lot = float(getattr(config, "LOT_SIZE", 0.01))
    contract = float(getattr(config, "CONTRACT_SIZE", 1.0))
    atr_period = int(getattr(config, "ATR_PERIOD", 14))
    sl_mult = float(getattr(config, "SL_ATR_MULT", 2.0))
    tp_mult = float(getattr(config, "TP_ATR_MULT", 5.0))

    out = {"digits": digits, "point": point, "lot": lot, "contract": contract}

    # --- coverage -------------------------------------------------------
    t = pd.to_datetime(df["time"])
    out["bars"] = len(df)
    out["first"], out["last"] = str(t.iloc[0]), str(t.iloc[-1])
    out["days"] = (t.iloc[-1] - t.iloc[0]).total_seconds() / 86400.0
    by_dow = t.dt.dayofweek.value_counts().sort_index()
    out["bars_by_dow"] = {int(k): int(v) for k, v in by_dow.items()}
    out["weekend_bars"] = int(by_dow.get(5, 0) + by_dow.get(6, 0))
    hours = sorted(set(t.dt.hour.tolist()))
    out["hours_covered"] = len(hours)

    # --- price digits sanity -------------------------------------------
    close = df["close"].to_numpy(float)
    frac = np.abs(close - np.round(close, digits))
    out["digits_consistent"] = bool(np.nanmax(frac) < point / 100)
    out["price_median"] = float(np.median(close))

    # --- ATR (same definition as strategy.py) ---------------------------
    high, low = df["high"].to_numpy(float), df["low"].to_numpy(float)
    prev_close = np.concatenate(([np.nan], close[:-1]))
    tr = np.nanmax(np.vstack([
        high - low, np.abs(high - prev_close), np.abs(low - prev_close)
    ]), axis=0)
    atr = pd.Series(tr).rolling(atr_period).mean().dropna().to_numpy()
    q = lambda p: float(np.quantile(atr, p))  # noqa: E731
    out["atr"] = {"p05": q(.05), "p10": q(.10), "p25": q(.25), "p50": q(.50),
                  "p75": q(.75), "p90": q(.90), "min": float(atr.min()),
                  "max": float(atr.max())}

    # --- spread ---------------------------------------------------------
    if "spread" in df.columns:
        sp = pd.to_numeric(df["spread"], errors="coerce").dropna().to_numpy(float)
        out["spread_pts"] = {"mean": float(sp.mean()), "p50": float(np.median(sp)),
                             "p90": float(np.quantile(sp, .90)),
                             "p99": float(np.quantile(sp, .99)),
                             "max": float(sp.max())}
        out["spread_price_mean"] = float(sp.mean()) * point
        out["spread_price_p90"] = float(np.quantile(sp, .90)) * point
    else:
        out["spread_pts"] = None
        out["spread_price_mean"] = float(getattr(config, "SPREAD_COST_PRICE", 0.45))
        out["spread_price_p90"] = out["spread_price_mean"]

    # --- economics ------------------------------------------------------
    usd = lot * contract                       # $ per 1.00 of price movement
    atr_med = out["atr"]["p50"]
    out["usd_per_price_unit"] = usd
    out["sl_price"] = atr_med * sl_mult
    out["tp_price"] = atr_med * tp_mult
    out["risk_usd"] = out["sl_price"] * usd
    out["reward_usd"] = out["tp_price"] * usd
    out["spread_usd"] = out["spread_price_mean"] * usd
    out["spread_over_atr"] = out["spread_price_mean"] / atr_med if atr_med else None
    out["spread_over_risk"] = out["spread_usd"] / out["risk_usd"] if out["risk_usd"] else None
    rr = tp_mult / sl_mult
    out["rr"] = rr
    out["breakeven_wr"] = 100.0 / (1.0 + rr)

    # --- suggestions -----------------------------------------------------
    def round_up(x, step):
        import math
        return float(step * math.ceil(x / step)) if x else 0.0

    sp_p90_pts = out["spread_pts"]["p90"] if out["spread_pts"] else None
    out["suggest"] = {
        "PRICE_DIGITS": digits,
        "ATR_MIN": round(out["atr"]["p10"], max(0, digits - 1)),
        "MAX_SPREAD_POINTS": (round_up(sp_p90_pts * 1.25, 10) if sp_p90_pts else None),
        "SPREAD_COST_PRICE": round(out["spread_price_mean"], digits),
        # ~3.5 full stop-outs: the same shape as gold's gate (-$30 vs ~$6-9 risk)
        "MAX_DAILY_LOSS": round(3.5 * out["risk_usd"], 1),
    }
    return out


def report(a) -> str:
    L = []
    A = L.append
    A("=" * 72)
    A("DERIVED INSTRUMENT PARAMETERS  (measured, not adopted)")
    A("=" * 72)
    A(f"bars            {a['bars']:,}  {a['first']} .. {a['last']}  (~{a['days']:.0f} days)")
    A(f"weekend bars    {a['weekend_bars']:,}  ({'24/7 instrument' if a['weekend_bars'] else 'weekday-only data'})"
      f"   hours covered {a['hours_covered']}/24")
    A(f"price           median {_fmt(a['price_median'])}   digits {a['digits']} "
      f"({'consistent with the data' if a['digits_consistent'] else 'MISMATCH - check symbol_info.digits'})")
    A(f"$ per 1.00 move {_fmt(a['usd_per_price_unit'], 4)}  "
      f"(lot {a['lot']} x contract {a['contract']})")
    A("")
    atr = a["atr"]
    A("ATR distribution (price units)")
    A(f"  p05 {_fmt(atr['p05'])}  p10 {_fmt(atr['p10'])}  p25 {_fmt(atr['p25'])}  "
      f"p50 {_fmt(atr['p50'])}  p75 {_fmt(atr['p75'])}  p90 {_fmt(atr['p90'])}  max {_fmt(atr['max'])}")
    if a["spread_pts"]:
        s = a["spread_pts"]
        A("Spread (broker column)")
        A(f"  points: mean {_fmt(s['mean'],0)}  p50 {_fmt(s['p50'],0)}  p90 {_fmt(s['p90'],0)}  "
          f"p99 {_fmt(s['p99'],0)}  max {_fmt(s['max'],0)}")
        A(f"  price : mean {_fmt(a['spread_price_mean'])}  p90 {_fmt(a['spread_price_p90'])}"
          f"   = ${_fmt(a['spread_usd'], 4)} round trip at this size")
    else:
        A("Spread: no `spread` column in the CSV - falling back to config.SPREAD_COST_PRICE")
    A("")
    A("Economics at the current geometry")
    A(f"  SL {_fmt(a['sl_price'])} px = ${_fmt(a['risk_usd'])} risk    "
      f"TP {_fmt(a['tp_price'])} px = ${_fmt(a['reward_usd'])} target   RR 1:{a['rr']:.2g}")
    A(f"  spread / median ATR = {100 * a['spread_over_atr']:.1f}%   "
      f"spread / risk = {100 * a['spread_over_risk']:.1f}%")
    A(f"  structural break-even win rate = {a['breakeven_wr']:.1f}% "
      f"(before spread; the spread adds ~{100 * a['spread_over_risk'] / (1 + a['rr']):.1f} pts)")
    A("")
    A("Suggested starting values for the instance config (Phase 1 must still")
    A("earn them through train-select -> cold-OOS; these are priors, not results):")
    s = a["suggest"]
    A(f"  PRICE_DIGITS      = {s['PRICE_DIGITS']}")
    A(f"  ATR_MIN           = {s['ATR_MIN']}        # ATR p10 - bottom decile of volatility")
    if s["MAX_SPREAD_POINTS"]:
        A(f"  MAX_SPREAD_POINTS = {int(s['MAX_SPREAD_POINTS'])}      # 1.25x measured spread p90")
    A(f"  SPREAD_COST_PRICE = {s['SPREAD_COST_PRICE']}     # mean measured spread, price units")
    A(f"  MAX_DAILY_LOSS    = {s['MAX_DAILY_LOSS']}      # ~3.5 full stop-outs at this size")
    A("=" * 72)
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config-dir", default=None,
                    help="instance dir whose config.py to use (default: btc/)")
    ap.add_argument("--csv", default=None,
                    help="bar file (default: data/<SYMBOL>_<TIMEFRAME>.csv)")
    args = ap.parse_args(argv)

    config = _load_config(args.config_dir)
    import pandas as pd

    csv = args.csv or os.path.join(ROOT, "data", f"{config.SYMBOL}_{config.TIMEFRAME}.csv")
    if not os.path.exists(csv):
        print(f"ERROR: {csv} not found.\n"
              f"Pull it first on the server:  mt5env/bin/python btc/recon.py --bars 20000")
        return 2
    df = pd.read_csv(csv, parse_dates=["time"])
    print(f"symbol {config.SYMBOL} {config.TIMEFRAME}   csv {csv}")
    print(report(analyse(df, config)))
    print("\nNOTE: measured facts only. Nothing here is adopted until the Phase 1")
    print("train-select -> cold-OOS gate in btc/HANDOFF.md §5 says so.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
