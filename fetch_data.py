import argparse
import os
import sys
import pandas as pd
import rpyc
import config
from mt5_bridge import probe_bridge


def download_data(symbol=config.SYMBOL, timeframe=config.TIMEFRAME,
                  bars_count=20000, start_pos=0, out_file=None):
    print(f"Connecting to MT5 Docker container at {config.HOST}:{config.PORT}...")
    ok, err = probe_bridge(config.HOST, config.PORT,
                           timeout=getattr(config, "CONNECT_TIMEOUT_SECONDS", 10))
    if not ok:
        print(f"[ERROR] Cannot reach MT5 bridge: {err}", file=sys.stderr)
        return None

    conn = rpyc.classic.connect(config.HOST, config.PORT)
    mt5 = conn.modules.MetaTrader5

    if not mt5.initialize():
        print(f"Failed to initialize MT5: {mt5.last_error()}", file=sys.stderr)
        conn.close()
        return None

    tf_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1,
    }
    tf = tf_map.get(timeframe, mt5.TIMEFRAME_M1)

    print(f"Downloading {bars_count} candles (start_pos={start_pos}) "
          f"for {symbol} ({timeframe})...")
    mt5.symbol_select(symbol, True)

    raw_rates = mt5.copy_rates_from_pos(symbol, tf, int(start_pos), int(bars_count))
    rates = rpyc.classic.obtain(raw_rates)

    mt5.shutdown()
    conn.close()

    if rates is None or len(rates) == 0:
        print("Failed to fetch rates from MT5.", file=sys.stderr)
        return None

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df = df[["time", "open", "high", "low", "close", "tick_volume", "spread"]]

    filename = out_file or f"data/{symbol}_{timeframe}.csv"
    os.makedirs(os.path.dirname(filename) or ".", exist_ok=True)
    df.to_csv(filename, index=False)

    print(f"\n[SUCCESS] Saved {len(df)} candles "
          f"({df['time'].min()} -> {df['time'].max()}) to {filename}")
    return filename


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Download OHLCV+spread history from the MT5 RPyC bridge."
    )
    ap.add_argument("--symbol", default=config.SYMBOL)
    ap.add_argument("--timeframe", default=config.TIMEFRAME,
                    choices=["M1", "M5", "M15", "H1"])
    ap.add_argument("--bars", type=int, default=20000,
                    help="number of bars to request (e.g. 60000 for ~300 days of M5)")
    ap.add_argument("--start-pos", type=int, default=0,
                    help="bar offset from current bar 0 (e.g. 20000 for an earlier non-overlapping window)")
    ap.add_argument("--out", default=None,
                    help="output CSV path (default: data/<SYMBOL>_<TIMEFRAME>.csv)")
    args = ap.parse_args(argv)
    res = download_data(
        symbol=args.symbol,
        timeframe=args.timeframe,
        bars_count=args.bars,
        start_pos=args.start_pos,
        out_file=args.out,
    )
    return 0 if res else 1


if __name__ == "__main__":
    raise SystemExit(main())
