import time
import config
from mt5_bridge import MT5Bridge
from strategy import ScalpStrategy

def main():
    print("=== Scalper Engine Started ===")
    bridge = MT5Bridge()
    strategy = ScalpStrategy()

    try:
        acc = bridge.get_account_info()
        tick = bridge.get_live_tick()
        sym = bridge.get_symbol_info()

        if not tick or not sym:
            print("[ERROR] Cannot connect to market stream.")
            return

        # 1. Spread Check Filter
        spread_points = round((tick.ask - tick.bid) / sym.point)
        print(f"Account: {acc.login} | Balance: ${acc.balance}")
        print(f"Price: {tick.bid}/{tick.ask} | Current Spread: {spread_points} points")

        if spread_points > config.MAX_SPREAD_POINTS:
            print(f"[SKIP] Spread ({spread_points}) is higher than limit ({config.MAX_SPREAD_POINTS}).")
            return

        # 2. Check if trade is already running
        if bridge.has_open_position():
            print("[INFO] Bot already has an active trade running. Skipping entry.")
            return

        # 3. Strategy Evaluation
        rates = bridge.get_rates(count=50)
        signal = strategy.check_signal(rates)
        print(f"Strategy Signal: {signal}")

        # 4. Order Execution
        if signal in ["BUY", "SELL"]:
            print(f"[EXECUTE] Sending {signal} order for {config.LOT_SIZE} lots...")
            res = bridge.open_trade(signal)

            if res and res.retcode == bridge.mt5.TRADE_RETCODE_DONE:
                print(f"[SUCCESS] Order Placed! Ticket: {res.order}")
            else:
                comment = res.comment if res else "No response"
                print(f"[FAILED] Trade failed to execute: {comment}")

    except Exception as e:
        print(f"Execution Error: {e}")
    finally:
        bridge.close()

if __name__ == "__main__":
    main()
