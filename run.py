import time
import config
from mt5_bridge import MT5Bridge
from strategy import ScalpStrategy

def main():
    print("=== Scalper Engine Started ===")
    bridge = MT5Bridge()
    strategy = ScalpStrategy()

    try:
        while True:
            try:
                acc = bridge.get_account_info()
                tick = bridge.get_live_tick()
                sym = bridge.get_symbol_info()

                if not tick or not sym:
                    print("[ERROR] Cannot connect to market stream. Retrying in 10s...")
                    time.sleep(10)
                    continue

                # 1. Spread Check
                spread_points = round((tick.ask - tick.bid) / sym.point)
                print(f"\n[{time.strftime('%H:%M:%S')}] Account: {acc.login} | Balance: ${acc.balance:.2f}")
                print(f"Price: {tick.bid}/{tick.ask} | Spread: {spread_points} points")

                if spread_points > config.MAX_SPREAD_POINTS:
                    print(f"[SKIP] Spread ({spread_points}) > limit ({config.MAX_SPREAD_POINTS})")
                    time.sleep(30)
                    continue

                # 2. Already in a trade?
                if bridge.has_open_position():
                    print("[INFO] Active position exists – waiting...")
                    time.sleep(30)
                    continue

                # 3. Strategy (need ≥200 bars for EMA200)
                rates = bridge.get_rates(count=250)
                signal, sl_dist, tp_dist = strategy.check_signal(rates)

                print(f"Strategy Signal: {signal} | SL dist: {sl_dist:.2f} | TP dist: {tp_dist:.2f}")

                # 4. Execute
                if signal in ("BUY", "SELL"):
                    print(f"[EXECUTE] Sending {signal} order ({config.LOT_SIZE} lots)...")
                    res = bridge.open_trade(signal, sl_dist, tp_dist)

                    if res and res.retcode == bridge.mt5.TRADE_RETCODE_DONE:
                        print(f"[SUCCESS] Order placed! Ticket: {res.order}")
                    else:
                        comment = res.comment if res else "No response"
                        print(f"[FAILED] {comment}")

                # Sleep between checks (adjust as needed)
                time.sleep(15)

            except Exception as e:
                print(f"[LOOP ERROR] {e}")
                time.sleep(15)

    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        bridge.close()

if __name__ == "__main__":
    main()
