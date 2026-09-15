import os
import pandas as pd
import config
from strategy import ScalpStrategy

def run_backtest(csv_file):
    if not os.path.exists(csv_file):
        print(f"Error: {csv_file} not found!")
        return

    print(f"Loading data from {csv_file}...")
    df = pd.read_csv(csv_file)
    print(f"Loaded {len(df)} candles.")

    strategy = ScalpStrategy()

    balance = 1000.0
    initial_balance = balance
    active_trade = None
    trades_history = []
    spread_cost = 0.30

    for i in range(200, len(df)):
        current_bar = df.iloc[i]
        
        # 1. Manage Active Trade
        if active_trade is not None:
            direction = active_trade['type']
            entry_price = active_trade['entry_price']
            sl = active_trade['sl']
            tp = active_trade['tp']

            closed = False
            pnl = 0.0

            if direction == "BUY":
                if current_bar['low'] <= sl:
                    pnl = (sl - entry_price) - spread_cost
                    closed = True
                    result = "SL"
                elif current_bar['high'] >= tp:
                    pnl = (tp - entry_price) - spread_cost
                    closed = True
                    result = "TP"

            elif direction == "SELL":
                if current_bar['high'] >= sl:
                    pnl = (entry_price - sl) - spread_cost
                    closed = True
                    result = "SL"
                elif current_bar['low'] <= tp:
                    pnl = (entry_price - tp) - spread_cost
                    closed = True
                    result = "TP"

            if closed:
                dollar_pnl = pnl * (config.LOT_SIZE * 100)
                balance += dollar_pnl
                trades_history.append({
                    'type': direction,
                    'result': result,
                    'pnl': dollar_pnl,
                    'balance': balance,
                    'time': current_bar['time']
                })
                active_trade = None

        # 2. Check for New Signal with Dynamic SL/TP
        if active_trade is None:
            window = df.iloc[i-200:i+1].to_dict('records')
            signal, sl_dist, tp_dist = strategy.check_signal(window)

            if signal == "BUY":
                entry = current_bar['close']
                active_trade = {
                    'type': "BUY",
                    'entry_price': entry,
                    'sl': entry - sl_dist,
                    'tp': entry + tp_dist,
                }
            elif signal == "SELL":
                entry = current_bar['close']
                active_trade = {
                    'type': "SELL",
                    'entry_price': entry,
                    'sl': entry + sl_dist,
                    'tp': entry - tp_dist,
                }

    print("\n================ BACKTEST RESULTS ================")
    print(f"Initial Balance:  ${initial_balance:.2f}")
    print(f"Final Balance:    ${balance:.2f}")
    print(f"Net Profit/Loss:  ${balance - initial_balance:.2f}")
    
    total_trades = len(trades_history)
    print(f"Total Trades:     {total_trades}")

    if total_trades > 0:
        wins = [t for t in trades_history if t['pnl'] > 0]
        win_rate = (len(wins) / total_trades) * 100
        print(f"Winning Trades:   {len(wins)}")
        print(f"Losing Trades:    {total_trades - len(wins)}")
        print(f"Win Rate:         {win_rate:.1f}%")
    print("==================================================")

if __name__ == "__main__":
    csv_file = f"data/{config.SYMBOL}_{config.TIMEFRAME}.csv"
    run_backtest(csv_file)
