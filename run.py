import time
from datetime import datetime
import config
from mt5_bridge import MT5Bridge
from strategy import ScalpStrategy
from paper import PaperAccount
from logger import (
    log_system, log_trade, get_today_stats,
    update_connection_status, update_live_status
)


def backoff_delay(failures):
    """Exponential backoff for repeated connection failures, capped."""
    max_delay = getattr(config, "RECONNECT_MAX_DELAY_SECONDS", 60)
    delay = config.RETRY_SLEEP_SECONDS * (2 ** min(max(failures - 1, 0), 6))
    return int(min(delay, max_delay))


def main():
    log_system("INFO", "=== Scalper Engine Started ===")
    bridge = None
    strategy = ScalpStrategy()

    paper = None
    if config.TRADING_MODE == "FORWARD_TEST":
        paper = PaperAccount()
        log_system("INFO",
            f"TRADING MODE: FORWARD_TEST (paper) - simulated balance ${paper.balance:.2f}, "
            f"NO real orders will be sent")
    else:
        log_system("INFO", "TRADING MODE: LIVE - real orders WILL be sent")

    consecutive_errors = 0
    connect_failures = 0
    reconnect_count = 0
    connected_since = None
    last_tick_time = None
    missing_data_count = 0
    stale_tick_cycles = 0
    last_tick_msc = None

    try:
        while True:
            try:
                # --- Connection recovery (with backoff + actionable errors) ---
                if bridge is None:
                    if connect_failures == 0:
                        log_system("INFO", f"Connecting to MT5 bridge at {config.HOST}:{config.PORT} ...")
                    try:
                        bridge = MT5Bridge()
                    except Exception as e:
                        connect_failures += 1
                        delay = backoff_delay(connect_failures)
                        log_system("ERROR", f"MT5 bridge unreachable (attempt {connect_failures}): {e}")
                        if connect_failures in (1, 5) or connect_failures % 10 == 0:
                            log_system("WARNING",
                                f"Hint: check the MT5 Docker container / RPyC server on "
                                f"{config.HOST}:{config.PORT} (e.g. 'docker ps', "
                                f"'ss -tlnp | grep {config.PORT}'). The bot will keep retrying "
                                f"and recover automatically.")
                        update_connection_status(
                            connected=False,
                            reconnect_count=reconnect_count,
                            connected_since=None,
                            last_tick_time=last_tick_time,
                            last_error=str(e),
                            uptime_seconds=0
                        )
                        update_live_status(connected=False, error=str(e))
                        log_system("INFO", f"Retrying MT5 connection in {delay}s ...")
                        time.sleep(delay)
                        continue

                    # Connected successfully
                    consecutive_errors = 0
                    connect_failures = 0
                    missing_data_count = 0
                    stale_tick_cycles = 0
                    last_tick_msc = None
                    reconnect_count += 1
                    connected_since = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log_system("INFO", f"Connected to MT5 (reconnect #{reconnect_count})")
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
                    update_live_status(connected=False, error="Market data temporarily unavailable")

                    if missing_data_count >= 5:
                        raise ConnectionError("Market data unavailable for too long")

                    time.sleep(config.RETRY_SLEEP_SECONDS)
                    continue

                # Data is good
                missing_data_count = 0
                last_tick_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # --- Stale tick detection ---
                # If the feed/terminal is frozen, ticks stop advancing. Warn
                # early, force a reconnect if it stays frozen for a long time.
                try:
                    tick_msc = tick.time_msc
                except Exception:
                    tick_msc = None
                if tick_msc is not None:
                    if last_tick_msc is not None and tick_msc == last_tick_msc:
                        stale_tick_cycles += 1
                        warn_at = getattr(config, "STALE_TICK_WARN_CYCLES", 20)
                        reconnect_at = getattr(config, "STALE_TICK_RECONNECT_CYCLES", 120)
                        if stale_tick_cycles == warn_at:
                            log_system("WARNING",
                                f"Tick data unchanged for {stale_tick_cycles} cycles - "
                                f"possible stale feed (market closed or terminal frozen)")
                        if stale_tick_cycles >= reconnect_at:
                            raise ConnectionError(
                                f"Tick data frozen for {stale_tick_cycles} cycles - forcing reconnect")
                    else:
                        stale_tick_cycles = 0
                    last_tick_msc = tick_msc

                # --- Paper exit resolution (real ticks, simulated fills) ---
                if paper is not None:
                    paper.on_tick(tick.bid, tick.ask)

                uptime = 0
                if connected_since:
                    try:
                        start = datetime.strptime(connected_since, "%Y-%m-%d %H:%M:%S")
                        uptime = int((datetime.now() - start).total_seconds())
                    except Exception:
                        uptime = 0

                # Collect open positions
                positions = []
                try:
                    raw_positions = bridge.mt5.positions_get(symbol=config.SYMBOL)
                    if raw_positions:
                        for p in raw_positions:
                            if p.magic == config.MAGIC_NUMBER:
                                positions.append({
                                    "ticket": p.ticket,
                                    "type": "BUY" if p.type == 0 else "SELL",
                                    "volume": float(p.volume),
                                    "price_open": float(p.price_open),
                                    "sl": float(p.sl),
                                    "tp": float(p.tp),
                                    "profit": float(p.profit),
                                    "time": datetime.fromtimestamp(p.time).strftime("%Y-%m-%d %H:%M:%S")
                                })
                except Exception:
                    positions = []

                spread_points = round((tick.ask - tick.bid) / sym.point)

                # In FORWARD_TEST the dashboard shows the simulated account
                if paper is not None:
                    disp_balance = paper.balance
                    disp_equity = paper.equity(tick.bid, tick.ask)
                    disp_margin = max(paper.balance, 0.0)
                    positions += paper.snapshot_position()
                else:
                    disp_balance = float(acc.balance)
                    disp_equity = float(acc.equity)
                    disp_margin = float(getattr(acc, "margin_free", 0) or 0)

                # Write full live status for dashboard (no concurrent MT5 needed)
                update_live_status(
                    balance=disp_balance,
                    equity=disp_equity,
                    margin_free=disp_margin,
                    bid=float(tick.bid),
                    ask=float(tick.ask),
                    spread=spread_points,
                    positions=positions,
                    connected=True,
                    error=None,
                    mode=config.TRADING_MODE
                )

                update_connection_status(
                    connected=True,
                    reconnect_count=reconnect_count,
                    connected_since=connected_since,
                    last_tick_time=last_tick_time,
                    last_error=None,
                    uptime_seconds=uptime
                )

                if paper is not None:
                    acct_str = f"SIM: ${disp_balance:.2f} | SimEquity: ${disp_equity:.2f}"
                else:
                    acct_str = f"Balance: ${acc.balance:.2f} | Equity: ${acc.equity:.2f}"
                log_system("INFO",
                    f"{acct_str} | "
                    f"Price: {tick.bid}/{tick.ask} | Spread: {spread_points} | "
                    f"Today PnL: ${stats['pnl']:.2f} | Trades: {stats['trades']} | "
                    f"Uptime: {uptime}s | Reconnects: {reconnect_count}"
                )

                # Spread filter
                if spread_points > config.MAX_SPREAD_POINTS:
                    log_trade("SKIP", {"reason": "high_spread", "spread": spread_points})
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                # Already in a trade? (real or simulated)
                if bridge.has_open_position() or (paper is not None and paper.has_position()):
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
                    if paper is not None:
                        # FORWARD_TEST: simulated fill at the live price
                        entry_price = tick.ask if signal == "BUY" else tick.bid
                        log_system("INFO",
                            f"[PAPER] Simulating {signal} @ {entry_price:.2f} "
                            f"(SL {sl_dist:.2f} / TP {tp_dist:.2f})")
                        pos = paper.open(signal, entry_price, sl_dist, tp_dist)
                        if pos:
                            log_trade("SIM_ENTRY", {
                                "side": signal,
                                "entry": pos["entry"],
                                "sl": pos["sl"],
                                "tp": pos["tp"],
                                "volume": pos["volume"],
                                "sl_dist": round(sl_dist, 2),
                                "tp_dist": round(tp_dist, 2)
                            })
                        else:
                            log_trade("SIM_ENTRY_FAILED", {"reason": "paper position already open"})
                    else:
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
                update_live_status(connected=False, error=str(e))

                if consecutive_errors >= 3:
                    if bridge is not None:
                        log_system("WARNING", "Multiple hard errors – forcing reconnect")
                        try:
                            bridge.close()
                        except Exception:
                            pass
                        bridge = None
                    connected_since = None
                    missing_data_count = 0
                    stale_tick_cycles = 0
                    last_tick_msc = None

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
        update_live_status(connected=False, error="Engine stopped")
        log_system("INFO", "Engine stopped")

if __name__ == "__main__":
    main()
