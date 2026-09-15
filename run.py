import time
from datetime import datetime
import config
from mt5_bridge import MT5Bridge
from strategy import ScalpStrategy
from logger import (
    log_system, log_trade, get_today_stats,
    update_connection_status
)

def main():
    log_system("INFO", "=== Scalper Engine Started ===")
    bridge = None
    strategy = ScalpStrategy()

    consecutive_errors = 0
    reconnect_count = 0
    connected_since = None
    last_tick_time = None
    missing_data_count = 0

    try:
        while True:
            try:
                # --- Connection recovery ---
                if bridge is None:
                    log_system("INFO", "Connecting to MT5...")
                    bridge = MT5Bridge()
                    consecutive_errors = 0
                    missing_data_count = 0
                    reconnect_count += 1
                    connected_since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log_system("INFO", f"Connected successfully (reconnect #{reconnect_count})")
                    update_connection_status(
                        connected=True,
                        reconnect_count=reconnect_count,
                        connected_since=connected_since,
                        last_tick_time=None,
                        last_error=None,
                        uptime_seconds=0
                    )

                # --- Daily risk checks ---
                stats = get_today_stats()
                if stats["pnl"] <= -config.MAX_DAILY_LOSS:
                    log_system("WARNING", f"Daily loss limit reached (${stats['pnl']:.2f}). Sleeping until tomorrow.")
                    time.sleep(300)
                    continue

                if stats["trades"] >= config.MAX_TRADES_PER_DAY:
                    log_system("WARNING", f"Max trades per day reached ({stats['trades']}). Sleeping.")
                    time.sleep(300)
                    continue

                # --- Market data (tolerant) ---
                acc = bridge.get_account_info()
                tick = bridge.get_live_tick()
                sym = bridge.get_symbol_info()

                if not tick or not sym or not acc:
                    missing_data_count += 1
                    log_system("WARNING", f"Market data temporarily unavailable (count={missing_data_count})")

                    # Only treat as hard error after several consecutive misses
                    if missing_data_count >= 5:
                        raise ConnectionError("Market data unavailable for too long")

                    time.sleep(config.RETRY_SLEEP_SECONDS)
                    continue

                # Data is good → reset missing counter
                missing_data_count = 0
                last_tick_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                uptime = 0
                if connected_since:
                    try:
                        start = datetime.strptime(connected_since, "%Y-%m-%d %H:%M:%S")
                        uptime = int((datetime.now() - start).total_seconds())
                    except Exception:
                        uptime = 0

                update_connection_status(
                    connected=True,
                    reconnect_count=reconnect_count,
                    connected_since=connected_since,
                    last_tick_time=last_tick_time,
                    last_error=None,
                    uptime_seconds=uptime
                )

                spread_points = round((tick.ask - tick.bid) / sym.point)

                log_system("INFO",
                    f"Balance: ${acc.balance:.2f} | Equity: ${acc.equity:.2f} | "
                    f"Price: {tick.bid}/{tick.ask} | Spread: {spread_points} | "
                    f"Today PnL: ${stats['pnl']:.2f} | Trades: {stats['trades']} | "
                    f"Uptime: {uptime}s | Reconnects: {reconnect_count}"
                )

                # Spread filter
                if spread_points > config.MAX_SPREAD_POINTS:
                    log_trade("SKIP", {"reason": "high_spread", "spread": spread_points})
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                # Already in a trade?
                if bridge.has_open_position():
                    log_system("INFO", "Active position exists – waiting...")
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                # Strategy evaluation
                rates = bridge.get_rates(count=250)
                signal, sl_dist, tp_dist = strategy.check_signal(rates)

                log_trade("SIGNAL", {
                    "signal": signal,
                    "sl_dist": round(sl_dist, 2),
                    "tp_dist": round(tp_dist, 2)
                })

                if signal in ("BUY", "SELL"):
                    log_system("INFO", f"Executing {signal} order...")
                    res = bridge.open_trade(signal, sl_dist, tp_dist)

                    if res and res.retcode == bridge.mt5.TRADE_RETCODE_DONE:
                        log_trade("ENTRY", {
                            "side": signal,
                            "ticket": res.order,
                            "volume": config.LOT_SIZE,
                            "sl_dist": round(sl_dist, 2),
                            "tp_dist": round(tp_dist, 2)
                        })
                    else:
                        comment = res.comment if res else "No response"
                        log_trade("ENTRY_FAILED", {"reason": comment})

                consecutive_errors = 0
                time.sleep(config.CHECK_INTERVAL_SECONDS)

            except Exception as e:
                consecutive_errors += 1
                log_system("ERROR", f"Loop error ({consecutive_errors}): {e}")

                update_connection_status(
                    connected=False,
                    reconnect_count=reconnect_count,
                    connected_since=connected_since,
                    last_tick_time=last_tick_time,
                    last_error=str(e),
                    uptime_seconds=0
                )

                # Force reconnect after repeated hard failures
                if consecutive_errors >= 3:
                    log_system("WARNING", "Multiple hard errors – forcing reconnect")
                    try:
                        if bridge:
                            bridge.close()
                    except Exception:
                        pass
                    bridge = None
                    connected_since = None
                    missing_data_count = 0

                time.sleep(config.RETRY_SLEEP_SECONDS)

    except KeyboardInterrupt:
        log_system("INFO", "Shutting down by user request")
    finally:
        if bridge:
            try:
                bridge.close()
            except Exception:
                pass
        update_connection_status(
            connected=False,
            reconnect_count=reconnect_count,
            connected_since=None,
            last_tick_time=last_tick_time,
            last_error="Engine stopped",
            uptime_seconds=0
        )
        log_system("INFO", "Engine stopped")

if __name__ == "__main__":
    main()
