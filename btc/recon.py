#!/usr/bin/env python3
"""Phase 0 recon for the BTCUSD scalper (see btc/HANDOFF.md §5, §7).

READ-ONLY. Never sends an order, never changes config, and deliberately does
NOT call mt5.shutdown() — the gold bot shares the same MT5 terminal session
through the RPyC bridge, and shutting it down could disturb a running bot.
(For the same reason this script is preferred over fetch_data.py for BTC pulls
while the gold bot is live.)

What it does, in one pass:
  1. probes/connects to the RPyC bridge (--host/--port; defaults match config.py)
  2. finds the exact BTC symbol name (symbols_get("*BTC*")) and selects it
  3. dumps the contract spec that the strategy math depends on
     (digits/point/contract size/volume min/leverage/filling/spread/stops/swap)
  4. pulls --bars M5 (or M1) bars and reports coverage + gaps
     (confirms 24/7 vs a daily break like gold's 21:00-22:00 UTC)
  5. reports spread-vs-ATR economics in BTC terms (the number that decides
     whether a scalping edge is even geometrically possible)
  6. writes the bars as a CSV in the same format as data/GOLD_M5.csv, so the
     existing backtest/sweep tooling can read it unmodified

Usage (on the server):
    cd /root/scalper && mt5env/bin/python btc/recon.py --bars 20000
    cd /root/scalper && mt5env/bin/python btc/recon.py --timeframe M1 --bars 60000 --out data/BTCUSD_M1.csv
    python btc/recon.py --self-test        # offline sanity check of the maths, no bridge

Nothing here imports the repo's `config`, so it is immune to which config.py is
first on sys.path (gold vs btc) — the bridge address is explicit.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60}

SPEC_FIELDS = [
    "name", "digits", "point", "spread", "spread_float",
    "trade_contract_size", "trade_tick_value", "trade_tick_value_profit",
    "trade_tick_size", "volume_min", "volume_step", "volume_max",
    "currency_profit", "currency_margin", "margin_initial", "margin_hedged",
    "swap_long", "swap_short", "swap_rollover3days",
    "trade_stops_level", "trade_freeze_level", "filling_mode", "trade_mode",
    "trade_exemode", "session_deals", "visible", "select",
]


# --------------------------------------------------------------------------
# pure helpers (covered by --self-test)
# --------------------------------------------------------------------------
def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift()
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def coverage_report(df: pd.DataFrame, tf_minutes: int) -> dict:
    """Weekday/hour bar counts + gaps, to confirm whether the market is 24/7."""
    t = pd.to_datetime(df["time"])
    gaps = t.diff().dt.total_seconds().div(60)
    step = float(tf_minutes)
    big = gaps[gaps > step * 1.5]
    by_dow = t.dt.dayofweek.value_counts().sort_index()
    by_hour = t.dt.hour.value_counts().sort_index()
    return {
        "start": str(t.iloc[0]),
        "end": str(t.iloc[-1]),
        "span_days": round((t.iloc[-1] - t.iloc[0]).total_seconds() / 86400.0, 1),
        "bars_per_weekday": {int(k): int(v) for k, v in by_dow.items()},
        "bars_per_hour_utc": {int(k): int(v) for k, v in by_hour.items()},
        "gap_count": int(len(big)),
        "largest_gaps_minutes": [round(float(g), 1) for g in big.nlargest(5)],
        "expected_24_7_bars": int(round((t.iloc[-1] - t.iloc[0]).total_seconds() / 60.0 / step)) + 1,
    }


def economics(df: pd.DataFrame, point: float, contract_size: float, lot: float,
              tf_minutes: int) -> dict:
    """Spread-vs-ATR and per-trade dollar risk — the go/no-go geometry check."""
    a = atr(df).dropna()
    spread_pts = pd.to_numeric(df["spread"], errors="coerce").dropna()
    spread_px = spread_pts * point
    med_atr_px = float(a.median()) if len(a) else float("nan")
    med_spread_px = float(spread_px.median()) if len(spread_px) else float("nan")
    risk_per_trade = med_atr_px * 2.0 * contract_size * lot     # 2.0xATR stop, like gold
    return {
        "atr_points": round(med_atr_px / point, 1) if point else None,
        "atr_price": round(med_atr_px, 2),
        "atr_p10": round(float(a.quantile(0.10)), 2) if len(a) else None,
        "atr_p90": round(float(a.quantile(0.90)), 2) if len(a) else None,
        "spread_points_median": round(float(spread_pts.median()), 1) if len(spread_pts) else None,
        "spread_points_p90": round(float(spread_pts.quantile(0.90)), 1) if len(spread_pts) else None,
        "spread_price_median": round(med_spread_px, 2),
        "spread_price_p90": round(float(spread_px.quantile(0.90)), 2) if len(spread_px) else None,
        "round_trip_cost_usd_per_lot": round(med_spread_px * contract_size, 2),
        "round_trip_cost_usd_at_lot": round(med_spread_px * contract_size * lot, 4),
        "spread_pct_of_atr": round(100.0 * med_spread_px / med_atr_px, 2) if med_atr_px else None,
        "risk_usd_per_trade_2atr_at_lot": round(risk_per_trade, 2),
        "reward_usd_per_trade_5atr_at_lot": round(med_atr_px * 5.0 * contract_size * lot, 2),
        "bars": int(len(df)),
        "timeframe_minutes": int(tf_minutes),
    }


def make_csv(df: pd.DataFrame, out_file: str) -> str:
    cols = ["time", "open", "high", "low", "close", "tick_volume", "spread"]
    out = df.copy()
    out["time"] = pd.to_datetime(out["time"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    for c in cols:
        if c not in out.columns:
            out[c] = 0
    out[cols].to_csv(out_file, index=False)
    return out_file


# --------------------------------------------------------------------------
# bridge I/O
# --------------------------------------------------------------------------
def find_symbol(mt5, wanted: str) -> list:
    """Exact name first; otherwise any symbol containing the base name."""
    names = []
    try:
        info = mt5.symbol_info(wanted)
        if info is not None:
            names.append(info.name)
            return names
    except Exception:
        pass
    try:
        import rpyc
        got = rpyc.classic.obtain(mt5.symbols_get("*%s*" % wanted.upper().replace("USD", "")))
        for s in got or []:
            if s is not None:
                names.append(s.name)
    except Exception:
        pass
    return names


def fetch(args) -> int:
    import rpyc  # imported here so --self-test needs no rpyc

    try:
        with socket.create_connection((args.host, args.port), timeout=5):
            pass
    except Exception as e:
        print(f"[ERROR] cannot reach the RPyC bridge at {args.host}:{args.port}: {e}")
        print("        is the MT5 Docker container up? (docker ps | grep mt5)")
        return 1

    conn = rpyc.classic.connect(args.host, args.port)
    mt5 = conn.modules.MetaTrader5
    if not mt5.initialize():
        print(f"[ERROR] MT5 initialize() failed: {mt5.last_error()}")
        conn.close()
        return 1

    print("=" * 72)
    print(f"BTC recon — {datetime.now(timezone.utc):%Y-%m-%d %H:%M:%S} UTC")
    print("=" * 72)

    acc = mt5.account_info()
    if acc is not None:
        print("\n--- account ---")
        for f in ("login", "server", "currency", "leverage", "balance",
                  "equity", "margin_free", "margin_mode", "trade_allowed"):
            print(f"  {f:18s} {getattr(acc, f, '*n/a*')}")

    candidates = find_symbol(mt5, args.symbol)
    print(f"\n--- symbol lookup for '{args.symbol}' ---")
    print(f"  candidates: {candidates or 'NONE FOUND'}")
    if not candidates:
        print("[ERROR] no matching symbol — check the exact broker name (suffixes?)")
        conn.close()
        return 1
    symbol = candidates[0]
    if not mt5.symbol_select(symbol, True):
        print(f"[ERROR] symbol_select('{symbol}') failed")
        conn.close()
        return 1

    info = mt5.symbol_info(symbol)
    spec = {f: getattr(info, f, "*n/a*") for f in SPEC_FIELDS}
    print(f"\n--- contract spec: {symbol} ---")
    for k, v in spec.items():
        print(f"  {k:24s} {v}")

    tick = mt5.symbol_info_tick(symbol)
    if tick is not None:
        print(f"\n--- live tick ---\n  bid={getattr(tick, 'bid', None)} "
              f"ask={getattr(tick, 'ask', None)} time={getattr(tick, 'time', None)}")

    tf_map = {"M1": mt5.TIMEFRAME_M1, "M5": mt5.TIMEFRAME_M5,
              "M15": mt5.TIMEFRAME_M15, "M30": mt5.TIMEFRAME_M30,
              "H1": mt5.TIMEFRAME_H1}
    tf = tf_map[args.timeframe]
    print(f"\n--- fetching {args.bars} {args.timeframe} bars (start_pos={args.start_pos}) ---")
    raw = mt5.copy_rates_from_pos(symbol, tf, int(args.start_pos), int(args.bars))
    rates = rpyc.classic.obtain(raw)
    if rates is None or len(rates) == 0:
        print("[ERROR] copy_rates_from_pos returned nothing (symbol not subscribed in Market Watch?)")
        conn.close()
        return 1

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    print(f"  got {len(df)} bars")

    point = float(spec.get("point") or 0.01)
    contract = float(spec.get("trade_contract_size") or 1.0)
    lot = float(args.lot)

    cov = coverage_report(df, TF_MINUTES[args.timeframe])
    print("\n--- coverage (confirms 24/7 vs a daily/weekly break) ---")
    for k in ("start", "end", "span_days", "gap_count", "largest_gaps_minutes", "expected_24_7_bars"):
        print(f"  {k:24s} {cov[k]}")
    print(f"  bars_per_weekday         {cov['bars_per_weekday']}")
    hours = cov["bars_per_hour_utc"]
    thin = [h for h, n in hours.items() if n < 0.5 * (max(hours.values()) if hours else 1)]
    print(f"  hours with <50% of peak bars: {thin}")

    eco = economics(df, point, contract, lot, TF_MINUTES[args.timeframe])
    print(f"\n--- spread vs ATR economics (point={point}, contract={contract}, lot={lot}) ---")
    for k, v in eco.items():
        print(f"  {k:32s} {v}")
    print("  (gold reference: spread ~$0.47 = ~15-20% of M5 ATR; if BTC's "
          "spread_pct_of_atr is far worse, a 5xATR-target scalp is not viable)")

    out_file = args.out or f"data/{symbol}_{args.timeframe}.csv"
    make_csv(df, out_file)
    print(f"\n[OK] wrote {out_file}")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"symbol": symbol, "spec": {k: str(v) for k, v in spec.items()},
                       "coverage": cov, "economics": eco}, f, indent=2)
        print(f"[OK] wrote {args.json}")

    # Deliberately no mt5.shutdown(): the gold bot shares this terminal session.
    conn.close()
    print("\nDone. Paste this output into the session; nothing was changed.")
    return 0


# --------------------------------------------------------------------------
# offline self-test
# --------------------------------------------------------------------------
def self_test() -> int:
    rng = np.random.default_rng(7)
    n = 3000
    start = np.datetime64("2026-06-01T00:00:00")
    times = start + np.arange(n) * np.timedelta64(5, "m")
    close = 65000.0 + np.cumsum(rng.normal(0, 60, n))
    high = close + np.abs(rng.normal(0, 40, n))
    low = close - np.abs(rng.normal(0, 40, n))
    df = pd.DataFrame({
        "time": pd.to_datetime(times),
        "open": np.r_[close[0], close[:-1]],
        "high": high, "low": low, "close": close,
        "tick_volume": rng.integers(10, 500, n),
        "spread": rng.integers(200, 900, n),
    })
    a = atr(df)
    assert a.notna().sum() > n - 20 and a.dropna().gt(0).all(), "ATR broken"
    cov = coverage_report(df, 5)
    assert cov["gap_count"] == 0 and cov["span_days"] > 10, cov
    eco = economics(df, 0.01, 1.0, 0.01, 5)
    assert eco["spread_price_median"] > 0 and eco["risk_usd_per_trade_2atr_at_lot"] > 0, eco
    import tempfile, os
    p = os.path.join(tempfile.mkdtemp(), "BTCUSD_M5.csv")
    make_csv(df, p)
    back = pd.read_csv(p)
    assert len(back) == n and list(back.columns) == [
        "time", "open", "high", "low", "close", "tick_volume", "spread"], list(back.columns)
    print("self-test OK")
    for k, v in eco.items():
        print(f"  {k:32s} {v}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--symbol", default="BTCUSD")
    ap.add_argument("--timeframe", default="M5", choices=sorted(TF_MINUTES))
    ap.add_argument("--bars", type=int, default=20000)
    ap.add_argument("--start-pos", type=int, default=0)
    ap.add_argument("--out", default=None, help="default: data/<symbol>_<tf>.csv")
    ap.add_argument("--json", default=None, help="optional machine-readable dump")
    ap.add_argument("--lot", type=float, default=0.01,
                    help="lot size for the per-trade $ figures (config.LOT_SIZE is 0.01)")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=18812)
    ap.add_argument("--self-test", action="store_true",
                    help="run the pure-maths checks offline (no bridge needed)")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    return fetch(args)


if __name__ == "__main__":
    raise SystemExit(main())
