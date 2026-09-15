import os
import pandas as pd
import rpyc
import config

def download_data(symbol=config.SYMBOL, timeframe=config.TIMEFRAME, bars_count=20000):
    print("Connecting to MT5 Docker container...")
    conn = rpyc.classic.connect(config.HOST, config.PORT)
    mt5 = conn.modules.MetaTrader5

    if not mt5.initialize():
        print(f"Failed to initialize MT5: {mt5.last_error()}")
        conn.close()
        return

    tf_map = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "H1": mt5.TIMEFRAME_H1
    }
    tf = tf_map.get(timeframe, mt5.TIMEFRAME_M1)

    print(f"Downloading {bars_count} candles for {symbol} ({timeframe})...")
    mt5.symbol_select(symbol, True)
    
    raw_rates = mt5.copy_rates_from_pos(symbol, tf, 0, bars_count)
    rates = rpyc.classic.obtain(raw_rates)

    mt5.shutdown()
    conn.close()

    if rates is None or len(rates) == 0:
        print("Failed to fetch rates from MT5.")
        return

    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df = df[['time', 'open', 'high', 'low', 'close', 'tick_volume', 'spread']]

    os.makedirs("data", exist_ok=True)
    filename = f"data/{symbol}_{timeframe}.csv"
    df.to_csv(filename, index=False)

    print(f"\n[SUCCESS] Saved {len(df)} candles to {filename}")

if __name__ == "__main__":
    download_data(symbol=config.SYMBOL, timeframe=config.TIMEFRAME, bars_count=20000)
