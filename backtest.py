import os
from datetime import datetime
import pandas as pd
import config
from strategy import ScalpStrategy

def _parse_bar_time(val):
    """Best-effort parse of the CSV time column into a datetime (assumed UTC)."""
    if isinstance(val, datetime):
        return val
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y.%m.%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(val), fmt)
        except Exception:
            continue
    return None

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
    peak = balance
    max_dd = 0.0
    active_trade = None
    trades_history = []
    spread_cost = 0.30  # approximate GOLD spread in price units

    # Strategy requires len(rates) >= 202; live uses get_rates(250).
    # Window must be at least that wide or every bar early-returns None.
    lookback = 250

    for i in range(lookback, len(df)):
        current_bar = df.iloc[i]
        bar_time = _parse_bar_time(current_bar.get("time"))

        # 1. Manage Active Trade (with rough BE ratchet)
        if active_trade is not None:
            direction = active_trade['type']
            entry_price = active_trade['entry_price']
            sl = active_trade['sl']
            tp = active_trade['tp']
            sl_dist = active_trade['sl_dist']

            # Breakeven ratchet once +BE_TRIGGER_R
            be_r = getattr(config, "BE_TRIGGER_R", 0.75)
            if not active_trade.get("be_armed") and sl_dist > 0:
                if direction == "BUY":
                    fav = current_bar['high'] - entry_price
                else:
                    fav = entry_price - current_bar['low']
                if fav >= be_r * sl_dist:
                    active_trade['sl'] = entry_price
                    active_trade['be_armed'] = True
                    sl = entry_price

            closed = False
            pnl = 0.0
            result = None

            if direction == "BUY":
                # Pessimistic: SL first if both touched
                if current_bar['low'] <= sl:
                    pnl = (sl - entry_price) - spread_cost
                    closed = True
                    result = "BE" if active_trade.get("be_armed") and sl == entry_price else "SL"
                elif current_bar['high'] >= tp:
                    pnl = (tp - entry_price) - spread_cost
                    closed = True
                    result = "TP"

            elif direction == "SELL":
                if current_bar['high'] >= sl:
                    pnl = (entry_price - sl) - spread_cost
                    closed = True
                    result = "BE" if active_trade.get("be_armed") and sl == entry_price else "SL"
                elif current_bar['low'] <= tp:
                    pnl = (entry_price - tp) - spread_cost
                    closed = True
                    result = "TP"

            if closed:
                dollar_pnl = pnl * (config.LOT_SIZE * 100)
                balance += dollar_pnl
                peak = max(peak, balance)
                dd = peak - balance
                max_dd = max(max_dd, dd)
                trades_history.append({
                    'type': direction,
                    'result': result,
                    'pnl': dollar_pnl,
                    'balance': balance,
                    'time': current_bar.get('time'),
                    'r': (pnl / sl_dist) if sl_dist else 0.0,
                })
                active_trade = None

        # 2. Check for New Signal
        if active_trade is None:
            window = df.iloc[i - lookback + 1:i + 1].to_dict('records')
            signal, sl_dist, tp_dist = strategy.check_signal(window, when=bar_time)

            if signal == "BUY":
                entry = current_bar['close']
                active_trade = {
                    'type': "BUY",
                    'entry_price': entry,
                    'sl': entry - sl_dist,
                    'tp': entry + tp_dist,
                    'sl_dist': sl_dist,
                    'be_armed': False,
                }
            elif signal == "SELL":
                entry = current_bar['close']
                active_trade = {
                    'type': "SELL",
                    'entry_price': entry,
                    'sl': entry + sl_dist,
                    'tp': entry - tp_dist,
                    'sl_dist': sl_dist,
                    'be_armed': False,
                }

    print("\n================ BACKTEST RESULTS ================")
    print(f"Initial Balance:  ${initial_balance:.2f}")
    print(f"Final Balance:    ${balance:.2f}")
    print(f"Net Profit/Loss:  ${balance - initial_balance:.2f}")
    print(f"Max Drawdown:     ${max_dd:.2f}")

    total_trades = len(trades_history)
    print(f"Total Trades:     {total_trades}")

    if total_trades > 0:
        wins = [t for t in trades_history if t['pnl'] > 0]
        losses = [t for t in trades_history if t['pnl'] <= 0]
        win_rate = (len(wins) / total_trades) * 100
        gross_profit = sum(t['pnl'] for t in wins) if wins else 0.0
        gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')
        avg_r = sum(t.get('r', 0) for t in trades_history) / total_trades

        print(f"Winning Trades:   {len(wins)}")
        print(f"Losing Trades:    {len(losses)}")
        print(f"Win Rate:         {win_rate:.1f}%")
        print(f"Profit Factor:    {profit_factor:.2f}")
        print(f"Average R:        {avg_r:.2f}")
    print("==================================================")

if __name__ == "__main__":
    csv_file = f"data/{config.SYMBOL}_{config.TIMEFRAME}.csv"
    run_backtest(csv_file)
