"""Fast, faithful replay of backtest.py for offline parameter sweeps.

Why this exists
---------------
`backtest.py` rebuilds a 202-row DataFrame per bar (~28 s for 20k M5 bars), which
is too slow to iterate on strategy parameters. This module replays the *same*
logic with vectorised indicators and a lightweight per-bar loop (~1 s), so we
can change one variable at a time and still trust the numbers.

It is deliberately faithful to `backtest.py`'s semantics:
  * signal evaluated on the last *completed* bar (window index -2),
  * entry filled at the signal bar's close, management starts on the next bar,
  * pessimistic exit order (SL before TP when a bar touches both),
  * breakeven ratchet armed on the bar's favourable extreme before the
    adverse extreme is tested (same as backtest.py),
  * $PnL = price_diff * LOT_SIZE * 100, spread subtracted once per trade.

Only the EMA200 depends on how far back the window reaches (with
`adjust=False` the seed keeps weight (1-alpha)^(n-1)); everything else is a
plain rolling mean and is unaffected by the window start. `warmup_bars`
therefore parameterises the EMA warm-up, which is the one place where live
(`get_rates(count=250)`) and backtest (202) disagreed.

`--verify` cross-checks this engine against `backtest.py` on the default config
and prints both results side by side.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, replace, asdict
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config  # noqa: E402

CONTRACT_SIZE = 100.0  # XAU/USD: 1.00 lot = 100 oz


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Params:
    # indicator / warm-up
    warmup_bars: int = 202          # bars fed to the signal check (see module docstring)
    ema_period: int = 200
    rsi_period: int = 14
    atr_period: int = 14

    # entry filters
    rsi_buy: float = 35.0
    rsi_sell: float = 65.0
    atr_min: float = 0.50
    session_enabled: bool = True
    session_start: int = 7
    session_end: int = 17
    h1_trend: bool = False
    h1_ema_period: int = 50

    # exits / risk
    sl_atr_mult: float = 2.0
    tp_atr_mult: float = 5.0
    be_trigger_r: float | None = 0.75
    max_bars_in_trade: int | None = None

    # costs
    spread_price: float | None = 0.30   # None -> use the CSV's per-bar spread column
    lot_size: float = 0.01

    # bookkeeping
    label: str = "baseline"


def params_from_config(**overrides) -> Params:
    """Defaults mirroring config.py, then apply overrides."""
    base = Params(
        warmup_bars=int(getattr(config, "INDICATOR_WINDOW_BARS", 202)),
        rsi_buy=float(getattr(config, "RSI_BUY_LEVEL", 35)),
        rsi_sell=float(getattr(config, "RSI_SELL_LEVEL", 65)),
        session_enabled=bool(getattr(config, "SESSION_FILTER_ENABLED", True)),
        session_start=int(getattr(config, "SESSION_START_HOUR_UTC", 7)),
        session_end=int(getattr(config, "SESSION_END_HOUR_UTC", 17)),
        be_trigger_r=getattr(config, "BE_TRIGGER_R", 0.75),
        lot_size=float(getattr(config, "LOT_SIZE", 0.01)),
        spread_price=None,  # per-bar from the CSV, like backtest.py
    )
    return replace(base, **overrides)


# --------------------------------------------------------------------------
# Indicators
# --------------------------------------------------------------------------
def _windowed_ema_last(close: np.ndarray, span: int, n: int) -> np.ndarray:
    """EMA(span, adjust=False) evaluated at the last bar of each `n`-bar sliding
    window — exactly what pandas produces inside strategy.check_signal.

    Returns an array aligned to `close`: out[i] is the EMA over close[i-n+1:i+1]
    (NaN for i < n-1).

    Callers must pass n = (bars in the rate window) - 1: `check_signal` reads
    window index -2 (the last *completed* bar), so the recursion spans one bar
    fewer than the window.
    """
    n = min(n, len(close))
    alpha = 2.0 / (span + 1.0)
    kernel = alpha * (1.0 - alpha) ** np.arange(n - 1, -1, -1)
    kernel[0] = (1.0 - alpha) ** (n - 1)  # the seed bar gets no alpha factor
    out = np.full(len(close), np.nan)
    if len(close) >= n:
        out[n - 1:] = np.convolve(close, kernel[::-1], mode="valid")
    return out


def _rolling_mean(x: np.ndarray, period: int) -> np.ndarray:
    # Plain cumsum-based rolling mean accumulates floating-point error over a
    # long series (tens of thousands of bars) and can disagree with
    # strategy.py's freshly-windowed `pandas.Series.rolling(period).mean()`
    # by ~1e-11 at a given bar - usually invisible, but on 2026-10-01 it
    # flipped a signal at a bar where RSI was an exact tie with the new
    # RSI_SELL_LEVEL=60 threshold (research/parity_test.py caught it). Use
    # pandas' rolling mean (not cumsum) so this replay is bit-identical to
    # the live/backtest path at window boundaries, not just "close enough".
    if len(x) < period:
        return np.full(len(x), np.nan)
    return pd.Series(x).rolling(period).mean().to_numpy()


def compute_indicators(df: pd.DataFrame, p: Params):
    close = df["close"].to_numpy(float)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)

    ema = _windowed_ema_last(close, p.ema_period, p.warmup_bars - 1)

    delta = np.diff(close, prepend=np.nan)
    gain = _rolling_mean(np.where(delta > 0, delta, 0.0), p.rsi_period)
    loss = _rolling_mean(np.where(delta < 0, -delta, 0.0), p.rsi_period)
    with np.errstate(divide="ignore", invalid="ignore"):
        rs = gain / loss
        rsi = 100.0 - (100.0 / (1.0 + rs))
    rsi = np.where(loss == 0, 100.0, rsi)

    prev_close = np.concatenate([[np.nan], close[:-1]])
    tr = np.nanmax(
        np.vstack([high - low, np.abs(high - prev_close), np.abs(low - prev_close)]),
        axis=0,
    )
    atr = _rolling_mean(tr, p.atr_period)

    return {"close": close, "high": high, "low": low,
            "ema": ema, "rsi": rsi, "atr": atr}


def h1_trend_series(df: pd.DataFrame, p: Params) -> np.ndarray:
    """Boolean per M5 bar: last *completed* H1 close above its EMA.

    Uses only H1 buckets that finished strictly before the M5 bar's own hour, so
    there is no look-ahead.
    """
    h1 = (df.set_index("time")
            .resample("1h", label="left", closed="left")
            .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
            .dropna())
    if h1.empty:
        return np.zeros(len(df), bool)
    h1_ema = h1["close"].ewm(span=p.h1_ema_period, adjust=False).mean()
    h1_up = (h1["close"] > h1_ema).to_numpy()
    h1_labels = h1.index.to_numpy()

    h2 = df["time"].dt.floor("1h").to_numpy()
    # last completed H1 bar = the one labelled one hour before this M5 bar's hour
    cut = h2 - np.timedelta64(1, "h")
    idx = np.searchsorted(h1_labels, cut, side="right") - 1
    out = np.zeros(len(df), bool)
    ok = (idx >= 0) & (h1_labels[np.clip(idx, 0, None)] <= cut)
    out[ok] = h1_up[idx[ok]]
    return out


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------
def signal_at(p: Params, ind: dict, hours: np.ndarray, h1_up, i: int):
    """Signal decision at loop bar `i` — a direct transcription of
    ScalpStrategy.check_signal's closed-bar branch.

    Exposed separately so `research/parity_test.py` can assert that the live
    code path (strategy.check_signal on a trailing window) and this replay
    agree bar-for-bar; that equivalence is the thing the warm-up fix restored.
    """
    si = i - 1                          # signal bar (window index -2)
    if si < 1:
        return None
    close, ema, rsi, atr = ind["close"], ind["ema"], ind["rsi"], ind["atr"]
    in_session = (not p.session_enabled) or (p.session_start <= hours[i] < p.session_end)
    if not (in_session and close[si] > 0 and atr[si] >= p.atr_min and not np.isnan(ema[si])):
        return None
    rsi_curr, rsi_prev = rsi[si], rsi[si - 1]
    signal = None
    if close[si] > ema[si] and rsi_prev <= p.rsi_buy and rsi_curr > p.rsi_buy:
        signal = "BUY"
    elif close[si] < ema[si] and rsi_prev >= p.rsi_sell and rsi_curr < p.rsi_sell:
        signal = "SELL"
    if signal and h1_up is not None and (signal == "BUY") != bool(h1_up[si]):
        signal = None
    return signal


def run(csv_file: str, p: Params, df: pd.DataFrame | None = None) -> dict:
    if df is None:
        df = pd.read_csv(csv_file, parse_dates=["time"])
    ind = compute_indicators(df, p)
    close, high, low = ind["close"], ind["high"], ind["low"]
    ema, rsi, atr = ind["ema"], ind["rsi"], ind["atr"]
    hours = df["time"].dt.hour.to_numpy()
    times = df["time"].to_numpy()
    if p.spread_price is None and "spread" in df.columns:
        spread_col = df["spread"].to_numpy(float) * 0.01
        spread_col = np.nan_to_num(spread_col, nan=float(getattr(config, "SPREAD_COST_PRICE", 0.45)))
    else:
        spread_col = None
        if p.spread_price is None:  # no column and no explicit value
            p = replace(p, spread_price=float(getattr(config, "SPREAD_COST_PRICE", 0.45)))
    h1_up = h1_trend_series(df, p) if p.h1_trend else None

    balance = 1000.0
    initial = balance
    peak = balance
    max_dd = 0.0
    trade = None
    trades = []
    n = len(df)
    start = p.warmup_bars - 1

    for i in range(start, n):
        # --- signal (mirrors check_signal: index -2 is the last completed bar)
        if trade is None and i >= start:
            signal = signal_at(p, ind, hours, h1_up, i)
            if signal:
                si = i - 1                  # signal bar
                entry = close[si]
                sl_dist = atr[si] * p.sl_atr_mult
                tp_dist = atr[si] * p.tp_atr_mult
                trade = {
                    "type": signal, "entry": entry, "sl_dist": sl_dist,
                    "sl": entry - sl_dist if signal == "BUY" else entry + sl_dist,
                    "tp": entry + tp_dist if signal == "BUY" else entry - tp_dist,
                    "be_armed": False, "opened_bar": i,
                }

        # --- manage
        if trade is not None:
            side = trade["type"]
            entry, sl, tp, sl_dist = trade["entry"], trade["sl"], trade["tp"], trade["sl_dist"]
            be_r = p.be_trigger_r

            if (be_r is not None and not trade["be_armed"] and sl_dist > 0):
                fav = (high[i] - entry) if side == "BUY" else (entry - low[i])
                if fav >= be_r * sl_dist:
                    trade["sl"] = entry
                    trade["be_armed"] = True
                    sl = entry

            spread = float(spread_col[i]) if spread_col is not None else float(p.spread_price)

            closed = None
            if side == "BUY":
                if low[i] <= sl:
                    pnl = (sl - entry) - spread
                    closed = "BE" if (trade["be_armed"] and sl == entry) else "SL"
                elif high[i] >= tp:
                    pnl = (tp - entry) - spread
                    closed = "TP"
            else:
                if high[i] >= sl:
                    pnl = (entry - sl) - spread
                    closed = "BE" if (trade["be_armed"] and sl == entry) else "SL"
                elif low[i] <= tp:
                    pnl = (entry - tp) - spread
                    closed = "TP"

            if closed is None and p.max_bars_in_trade is not None:
                if i - trade["opened_bar"] >= p.max_bars_in_trade:
                    px = close[i]
                    pnl = ((px - entry) if side == "BUY" else (entry - px)) - spread
                    closed = "TIME"

            if closed:
                dollar = pnl * (p.lot_size * CONTRACT_SIZE)
                balance += dollar
                peak = max(peak, balance)
                max_dd = max(max_dd, peak - balance)
                trades.append({
                    "type": side, "result": closed, "pnl": dollar, "balance": balance,
                    "time": times[i], "entry_time": times[max(trade["opened_bar"] - 1, 0)],
                    "r": (pnl / sl_dist) if sl_dist else 0.0,
                    "bars": i - trade["opened_bar"],
                })
                trade = None

    total = len(trades)
    res = {"label": p.label, "trades": total, "net": balance - initial,
           "max_dd": max_dd, "final": balance}
    if total:
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        gp = sum(t["pnl"] for t in wins)
        gl = abs(sum(t["pnl"] for t in losses))
        res.update({
            "win_rate": 100.0 * len(wins) / total,
            "pf": (gp / gl) if gl > 0 else float("inf"),
            "avg_r": sum(t["r"] for t in trades) / total,
            "expectancy": (balance - initial) / total,
            "tp": sum(1 for t in trades if t["result"] == "TP"),
            "be": sum(1 for t in trades if t["result"] == "BE"),
            "sl": sum(1 for t in trades if t["result"] == "SL"),
            "time_exits": sum(1 for t in trades if t["result"] == "TIME"),
            "avg_bars": sum(t["bars"] for t in trades) / total,
        })
    res["trades_list"] = trades
    res["params"] = asdict(p)
    return res


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
HEAD = ("config", "trades", "net$", "PF", "WR%", "avgR", "maxDD$", "TP", "BE", "SL", "exp$")


def fmt(r: dict) -> str:
    return ("{:<28}{:>7}{:>9.2f}{:>7.2f}{:>7.1f}{:>7.2f}{:>9.2f}"
            "{:>6}{:>6}{:>6}{:>8.2f}").format(
        r["label"][:28], r["trades"], r["net"], r.get("pf", 0), r.get("win_rate", 0),
        r.get("avg_r", 0), r["max_dd"], r.get("tp", 0), r.get("be", 0), r.get("sl", 0),
        r.get("expectancy", 0))


def header() -> str:
    return ("{:<28}{:>7}{:>9}{:>7}{:>7}{:>7}{:>9}{:>6}{:>6}{:>6}{:>8}").format(*HEAD)


def bootstrap(csv_file: str, df: pd.DataFrame, p: Params, n: int = 2000,
              seed: int = 7) -> list[str]:
    """Resample the per-trade PnL with replacement to see whether the observed
    net is distinguishable from zero, or just a handful of lucky trades."""
    r = run(csv_file, replace(p, label=p.label), df=df)
    pnl = np.array([t["pnl"] for t in r["trades_list"]], float)
    if pnl.size == 0:
        return ["bootstrap: no trades"]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, pnl.size, size=(n, pnl.size))
    nets = pnl[idx].sum(axis=1)
    lo, hi = np.percentile(nets, [2.5, 97.5])
    ppos = float((nets > 0).mean())
    return [
        f"=== bootstrap: {p.label} (n={pnl.size} trades, {n} resamples) ===",
        f"  observed net      ${pnl.sum():.2f}",
        f"  95% CI of net     [${lo:.2f}, ${hi:.2f}]",
        f"  P(net > 0)        {ppos:.3f}",
        f"  median trade      ${np.median(pnl):.2f}   mean ${pnl.mean():.2f}",
        f"  best/worst trade  ${pnl.max():.2f} / ${pnl.min():.2f}",
    ]


def _coerce(v: str):
    """Parse a --set value into None/bool/int/float/str."""
    vl = v.strip().lower()
    if vl in ("none", "off", "null"):
        return None
    if vl in ("true", "false"):
        return vl == "true"
    for cast in (int, float):
        try:
            return cast(v)
        except ValueError:
            pass
    return v


def breakdown(csv_file: str, df: pd.DataFrame, p: Params) -> list[str]:
    """Side / month / half-split stability of one parameter set."""
    base = run(csv_file, replace(p, label=p.label + " [all]"), df=df)
    out = [f"=== {p.label} ===", header(), fmt(base)]

    tl = base["trades_list"]
    if not tl:
        return out

    def line(label, trades):
        net = sum(t["pnl"] for t in trades)
        wins = [t for t in trades if t["pnl"] > 0]
        gl = abs(sum(t["pnl"] for t in trades if t["pnl"] <= 0))
        gp = sum(t["pnl"] for t in wins)
        pf = (gp / gl) if gl > 0 else float("inf")
        top5 = sum(t["pnl"] for t in sorted(trades, key=lambda t: -t["pnl"])[:5])
        return ("  {:<14}{:>6}{:>10.2f}{:>7.2f}{:>7.1f}{:>14.2f}").format(
            label, len(trades), net, pf, 100.0 * len(wins) / len(trades) if trades else 0, top5)

    out.append("  {:<14}{:>6}{:>10}{:>7}{:>7}{:>14}".format("slice", "n", "net$", "PF", "WR%", "top5 pnl$"))
    for side in ("BUY", "SELL"):
        out.append(line(f"{side}", [t for t in tl if t["type"] == side]))

    tdf = pd.DataFrame({"t": [t["time"] for t in tl], "pnl": [t["pnl"] for t in tl]})
    tdf["t"] = pd.to_datetime(tdf["t"])
    for month, g in tdf.groupby(tdf["t"].dt.to_period("M")):
        out.append(line(str(month), [tl[i] for i in g.index.tolist()]))

    mid = df["time"].iloc[len(df) // 2]
    for lbl, sel in (("first half", tdf["t"] < mid), ("second half", tdf["t"] >= mid)):
        out.append(line(lbl, [tl[i] for i in tdf.index[sel].tolist()]))

    top5 = sorted(tl, key=lambda t: -t["pnl"])[:5]
    out.append("  top-5 winners: " + ", ".join(f"{t['pnl']:.1f}({t['type']})" for t in top5))
    worst5 = sorted(tl, key=lambda t: t["pnl"])[:5]
    out.append("  worst-5:       " + ", ".join(f"{t['pnl']:.1f}({t['type']})" for t in worst5))
    return out


def sweep_ema(df, base):
    """Is the trend filter doing real work, or is the 202-bar window just acting
    like a shorter EMA? Run converged EMAs of several lengths (needs a warm-up
    >= ~10x the longest span, so pair this with --warmup 2000+)."""
    return _rows(df, base, [
        (f"EMA {n} (converged)", dict(ema_period=n)) for n in (30, 50, 75, 100, 150, 200, 300)
    ], f"trend-filter length (warm-up {base.warmup_bars})")


def sweep_honest(df, base):
    """The table that matters: candidates re-priced with the real spread."""
    return _rows(df, base, [
        ("live cfg: BE.75 sp.30", dict(be_trigger_r=0.75, spread_price=0.30)),
        ("live cfg + real spread", dict(be_trigger_r=0.75, spread_price=0.47)),
        ("BE 1.0R + real spread", dict(be_trigger_r=1.00, spread_price=0.47)),
        ("BE 1.25R + real spread", dict(be_trigger_r=1.25, spread_price=0.47)),
        ("BE 1.5R + real spread", dict(be_trigger_r=1.50, spread_price=0.47)),
        ("BE off + real spread", dict(be_trigger_r=None, spread_price=0.47)),
    ], f"honest re-pricing (warm-up {base.warmup_bars})")


def sweep_combo(df, base):
    """After one-at-a-time, test combinations of the survivors."""
    variants = []
    for be in (None, 1.0, 1.25):
        for sl in (2.0, 2.5, 3.0):
            for tp in (2.5, 5.0, 6.0):
                variants.append((f"BE={be} SL={sl} TP={tp}",
                                 dict(be_trigger_r=be, sl_atr_mult=sl, tp_atr_mult=tp)))
    return _rows(df, base, variants, "combined grid")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", default=f"data/{config.SYMBOL}_{config.TIMEFRAME}.csv")
    ap.add_argument("--verify", action="store_true",
                    help="compare against backtest.py on the default config")
    ap.add_argument("--sweep", default=None,
                    help="name of a predefined sweep (be, sl, tp, session, warmup, rsi, h1, spread, combo)")
    ap.add_argument("--warmup", type=int, default=None,
                    help="warm-up bars for every config in a sweep "
                         "(default: config.INDICATOR_WINDOW_BARS)")
    ap.add_argument("--bootstrap", type=int, default=0, metavar="N",
                    help="bootstrap N resamples of the --set config's trade PnL")
    ap.add_argument("--detail", action="store_true",
                    help="print side/month/half breakdown for the --set config")
    ap.add_argument("--set", action="append", default=[], metavar="K=V",
                    help="override a Params field for --detail (repeatable)")
    args = ap.parse_args(argv)

    df = pd.read_csv(args.csv, parse_dates=["time"])
    if args.warmup is None:
        args.warmup = int(getattr(config, "INDICATOR_WINDOW_BARS", 202))
    print(f"Loaded {len(df)} bars: {df.time.min()} -> {df.time.max()} "
          f"(warm-up {args.warmup})\n")

    if args.verify:
        import backtest
        base = params_from_config()
        ref = None
        print(header())
        ours = run(args.csv, replace(base, label="sweep engine (default)"), df=df)
        print(fmt(ours))
        print("\nreference backtest.py (same config, slow path):")
        os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        backtest.run_backtest(args.csv)
        return

    if args.detail or args.bootstrap:
        kw = {"warmup_bars": args.warmup}
        for kv in args.set:
            k, v = kv.split("=", 1)
            kw[k] = _coerce(v)
        p = replace(params_from_config(), **kw)
        if args.bootstrap:
            for line in bootstrap(args.csv, df, p, args.bootstrap):
                print(line)
        if args.detail:
            for line in breakdown(args.csv, df, p):
                print(line)
        return

    if args.sweep:
        base = replace(params_from_config(), warmup_bars=args.warmup,
                       label=f"base warmup={args.warmup}")
        for line in SWEEPS[args.sweep](df, base):
            print(line)
        return

    print(header())
    print(fmt(run(args.csv, params_from_config(label="baseline (as configured)"), df=df)))


def _rows(df, base: Params, variants, name: str):
    out = [f"--- {name} ---", header()]
    for label, kw in variants:
        p = replace(base, label=label, **kw)
        out.append(fmt(run("", p, df=df)))
    return out


def sweep_warmup(df, base):
    return _rows(df, base, [
        ("warmup 202 (current)", dict(warmup_bars=202)),
        ("warmup 300", dict(warmup_bars=300)),
        ("warmup 500", dict(warmup_bars=500)),
        ("warmup 1000 (converged)", dict(warmup_bars=1000)),
        ("warmup 2000", dict(warmup_bars=2000)),
        ("warmup 5000", dict(warmup_bars=5000)),
    ], "warm-up length")


def sweep_be(df, base):
    return _rows(df, base, [
        ("BE 0.75R (current)", dict(be_trigger_r=0.75)),
        ("BE 0.50R", dict(be_trigger_r=0.50)),
        ("BE 1.00R", dict(be_trigger_r=1.00)),
        ("BE 1.25R", dict(be_trigger_r=1.25)),
        ("BE 1.50R", dict(be_trigger_r=1.50)),
        ("BE off", dict(be_trigger_r=None)),
    ], "breakeven trigger")


def sweep_sl(df, base):
    return _rows(df, base, [
        (f"SL {m}x ATR", dict(sl_atr_mult=m)) for m in (1.0, 1.5, 2.0, 2.5, 3.0)
    ], "SL multiple (TP fixed 5.0)")


def sweep_tp(df, base):
    return _rows(df, base, [
        (f"TP {m}x ATR", dict(tp_atr_mult=m)) for m in (2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0)
    ], "TP multiple (SL fixed 2.0)")


def sweep_session(df, base):
    return _rows(df, base, [
        ("session 07-17 (current)", dict(session_start=7, session_end=17)),
        ("session 08-16", dict(session_start=8, session_end=16)),
        ("session 08-17", dict(session_start=8, session_end=17)),
        ("session 07-16", dict(session_start=7, session_end=16)),
        ("session 09-16", dict(session_start=9, session_end=16)),
        ("session 13-17 (NY)", dict(session_start=13, session_end=17)),
        ("session 07-20", dict(session_start=7, session_end=20)),
        ("session off", dict(session_enabled=False)),
    ], "session window (UTC)")


def sweep_rsi(df, base):
    return _rows(df, base, [
        (f"RSI {lo:.0f}/{hi:.0f}", dict(rsi_buy=lo, rsi_sell=hi))
        for lo, hi in ((30, 70), (35, 65), (40, 60), (45, 55))
    ], "RSI thresholds")


def sweep_h1(df, base):
    return _rows(df, base, [
        ("H1 trend off (current)", dict(h1_trend=False)),
        ("H1 trend EMA50", dict(h1_trend=True, h1_ema_period=50)),
        ("H1 trend EMA100", dict(h1_trend=True, h1_ema_period=100)),
    ], "H1 trend confirmation")


def sweep_spread(df, base):
    return _rows(df, base, [
        ("spread 0.30 (current)", dict(spread_price=0.30)),
        ("spread 0.40", dict(spread_price=0.40)),
        ("spread 0.47 (CSV mean)", dict(spread_price=0.47)),
        ("spread 0.51 (CSV median)", dict(spread_price=0.51)),
        ("spread per-bar (CSV)", dict(spread_price=None)),
    ], "spread assumption")


SWEEPS = {
    "warmup": sweep_warmup,
    "ema": sweep_ema,
    "honest": sweep_honest,
    "be": sweep_be,
    "sl": sweep_sl,
    "tp": sweep_tp,
    "session": sweep_session,
    "rsi": sweep_rsi,
    "h1": sweep_h1,
    "spread": sweep_spread,
}


if __name__ == "__main__":
    main()
