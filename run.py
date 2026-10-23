import time
from datetime import datetime
import config
from mt5_bridge import MT5Bridge
from strategy import ScalpStrategy
from paper import PaperAccount
from live_ledger import LiveLedger
from logger import (
    LOG_DIR, log_system, log_trade, get_today_stats,
    update_connection_status, update_live_status
)
from spread_gate import SpreadGateMonitor
from risk_sizer import size_lots
from live_position import LivePositionGuard
import risk_guard
try:
    from portfolio import portfolio_blocked
except Exception:
    portfolio_blocked = None  # portfolio gate optional (e.g. during unit tests)

# Emergency stop: create this file to disable NEW entries without killing the
# service (open positions keep their broker-side SL/TP). Remove it to resume.
KILL_SWITCH_FILE = LOG_DIR / "KILL_SWITCH"


def backoff_delay(failures):
    """Exponential backoff for repeated connection failures, capped."""
    max_delay = getattr(config, "RECONNECT_MAX_DELAY_SECONDS", 60)
    delay = config.RETRY_SLEEP_SECONDS * (2 ** min(max(failures - 1, 0), 6))
    return int(min(delay, max_delay))


def new_strategy():
    """Instance-config strategy factory.

    Gold's config has no BTC_STRATEGY key, so this returns ScalpStrategy there
    exactly as before. The BTC instance can opt into the pre-registered
    Phase-1c shape (btc/strategy_btc.DonchianBreakoutStrategy) via
    btc/config.py BTC_STRATEGY="donchian" - a deployment decision that
    btc/HANDOFF.md gates behind a passing train-select run, a derived
    MAX_SPREAD_POINTS and explicit user authorisation.
    """
    name = str(getattr(config, "BTC_STRATEGY", "scalp")).strip().lower()
    if name in ("", "scalp"):
        return ScalpStrategy()
    if name in ("donchian", "donchian_breakout"):
        if config.TRADING_MODE != "FORWARD_TEST":
            raise SystemExit(
                "BTC_STRATEGY=donchian is FORWARD_TEST-only: its bar-close "
                "channel/time exits are implemented for the paper book, not "
                "for broker order management. Flip TRADING_MODE back first.")
        from strategy_btc import DonchianBreakoutStrategy   # btc/ is on sys.path
        return DonchianBreakoutStrategy()
    raise SystemExit(f"unknown BTC_STRATEGY={name!r} (expected 'scalp' or 'donchian')")


def _bar_time(bar):
    """Timestamp of a rates row (numpy int or whatever the bridge returns)."""
    try:
        t = bar["time"]
        if hasattr(t, "item"):
            t = t.item()
        return t
    except Exception:
        return None


def maybe_bar_close_exit(strategy, rates, position, last_closed_ts, bars_in_trade):
    """Bar-close exit step for strategies with BAR_CLOSE_EXITS (donchian).

    Returns (exit_or_None, new_last_closed_ts, new_bars_in_trade). `exit` is
    the strategy.check_exit verdict ({"reason", "price"}) or None to stay
    open. State machine: the first sighted closed bar only baselines; each
    *new* closed bar advances bars_in_trade and asks the strategy whether the
    opposite channel crossed on that close or the time stop elapsed. After an
    engine restart mid-position a time stop can therefore only fire late,
    never early. Pure function - unit-tested in btc/strategy_btc_test.py.
    """
    if rates is None or len(rates) < 3:
        return None, last_closed_ts, bars_in_trade
    closed_ts = _bar_time(rates[-2])
    if closed_ts is None:
        return None, last_closed_ts, bars_in_trade
    if last_closed_ts is None:
        return None, closed_ts, bars_in_trade        # baseline only
    if closed_ts == last_closed_ts:
        return None, last_closed_ts, bars_in_trade   # same bar, no count
    bars_in_trade += 1
    ex = strategy.check_exit(rates, position, bars_in_trade) if position else None
    return ex, closed_ts, bars_in_trade


def poll_paper_position(bridge, paper, total_seconds=None, interval_seconds=None,
                        sleep_fn=time.sleep):
    """While a paper position is open, poll live ticks at a tighter cadence
    (`POSITION_CHECK_INTERVAL_SECONDS`, default 1s) instead of sleeping blindly
    for the full `CHECK_INTERVAL_SECONDS` (15s).

    When flat (`paper is None` or `not paper.has_position()`), this simply
    sleeps `total_seconds` once with zero extra MT5 bridge calls.
    Returns the close-info dict if the position closed during the window,
    else None.
    """
    if total_seconds is None:
        total_seconds = float(getattr(config, "CHECK_INTERVAL_SECONDS", 15))
    if interval_seconds is None:
        interval_seconds = float(getattr(config, "POSITION_CHECK_INTERVAL_SECONDS", 1))

    if (paper is None or not paper.has_position()
            or interval_seconds <= 0 or interval_seconds >= total_seconds):
        sleep_fn(total_seconds)
        return None

    remaining = float(total_seconds)
    last_msc = None
    while remaining > 0 and paper.has_position():
        step = min(float(interval_seconds), remaining)
        sleep_fn(step)
        remaining -= step
        if not paper.has_position():
            break
        try:
            tick = bridge.get_live_tick(retries=1)
        except Exception:
            tick = None
        if not tick:
            continue
        msc = getattr(tick, "time_msc", None)
        if msc is not None and last_msc is not None and msc == last_msc:
            continue
        last_msc = msc
        closed = paper.on_tick(tick.bid, tick.ask)
        if closed is not None:
            log_system("INFO",
                f"[PAPER] Fast-poll exit ({closed['reason']}): "
                f"PnL ${closed['profit']:+.2f} | Balance ${closed['balance']:.2f}")
            return closed
    return None


def main():
    # Feasibility telemetry for the entry spread gate. Purely descriptive: it
    # counts quotes/vetoes and warns loudly when the gate cannot be passed at
    # all (see spread_gate.py) - it never changes the gate.
    spread_monitor = SpreadGateMonitor(getattr(config, "MAX_SPREAD_POINTS", 0),
                                       symbol=config.SYMBOL)
    log_system("INFO", "=== Scalper Engine Started ===")
    bridge = None
    strategy = new_strategy()
    log_system("INFO", f"Strategy: {type(strategy).__name__}")
    if (config.TRADING_MODE != "FORWARD_TEST"
            and float(getattr(config, "MAX_HOLD_MINUTES", 0) or 0) > 0):
        log_system("WARNING",
            "MAX_HOLD_MINUTES is set, but the time stop is implemented for the "
            "paper book only - LIVE exits stay with the broker-side SL/TP.")

    # A strategy may force the breakeven ratchet for its book (the donchian
    # shape pre-registers BE off); absent the hook, config decides (gold path).
    paper_kwargs = {}
    if hasattr(strategy, "BE_OVERRIDE"):
        paper_kwargs["be_trigger_r"] = strategy.BE_OVERRIDE

    paper = None
    ledger = None
    # LIVE-only position protection (docs/live_readiness_review_2026-10-23.md
    # §4.1/§4.2): post-fill stop verification and the BE ratchet. Constructed
    # only in LIVE, and the guard refuses to act outside TRADING_MODE=LIVE, so
    # the paper path below is untouched. `bridge` is assigned after every
    # (re)connect because the object is rebuilt by the recovery branch.
    guard = None
    if config.TRADING_MODE == "FORWARD_TEST":
        paper = PaperAccount(**paper_kwargs)
        log_system("INFO",
            f"TRADING MODE: FORWARD_TEST (paper) - simulated balance ${paper.balance:.2f}, "
            f"NO real orders will be sent")
    else:
        ledger = LiveLedger()
        guard = LivePositionGuard()
        be_note = ("off" if not getattr(config, "LIVE_BE_ENABLED", True)
                   else f"{guard.be_trigger_r:g}R")
        log_system("INFO",
            "TRADING MODE: LIVE - real orders WILL be sent | "
            f"stop verification {'on' if guard.enabled else 'OFF'}, "
            f"BE ratchet {be_note}")

    # Account-level guards (risk_guard): a latched total-loss floor and the
    # Friday weekend flat. Both are inert in FORWARD_TEST only in the sense
    # that they never fire there in practice - the floor is far below the
    # observed drawdown and the paper book has no gaps to protect against -
    # so the paper book runs the same rules as LIVE would.
    equity_floor = risk_guard.EquityFloor()
    log_system("INFO",
        f"Equity floor: {'on' if equity_floor.enabled else 'OFF'} "
        f"({equity_floor.pct:g}% of {equity_floor.mode}"
        + (f", reference ${equity_floor.start:.2f}" if equity_floor.start else "")
        + ") | weekend flat: "
        + ("on" if risk_guard.weekend_flat_enabled() else "OFF")
        + f" (Fri {getattr(config, 'WEEKEND_FLAT_HOUR_UTC', 20):02d}:00 UTC)"
        + f" | hold cap: {risk_guard.hold_limit_minutes():g} min"
        + ("" if risk_guard.hold_limit_minutes() else " (off)"))

    consecutive_errors = 0
    connect_failures = 0
    reconnect_count = 0
    connected_since = None
    last_tick_time = None
    missing_data_count = 0
    stale_tick_cycles = 0
    last_tick_msc = None
    kill_switch_active = False
    floor_blocked_prev = None
    weekend_blocked_prev = None

    # Bar-close exit bookkeeping for strategies with BAR_CLOSE_EXITS (the
    # donchian shape's channel/time exits; gold's ScalpStrategy has none of
    # this). bars_in_trade counts bars closed since the fill bar, matching the
    # replay's `i - entry_bar >= time_stop` and btc/breakout_screen.py.
    bar_exit_last_closed_ts = None
    bar_exit_bars_in_trade = 0

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
                    if guard is not None:
                        # The bridge is rebuilt on every reconnect; the guard
                        # must talk to the live object, never a stale one.
                        guard.bridge = bridge
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

                # --- Portfolio-level gate (shared-account mode) ---
                # In ACCOUNT_MODE=shared one equity pool is at risk, so per-bot
                # gates alone can hide 2× loss. Both bots check this combined gate
                # every loop (file-based, <1ms when flat). Isolated mode returns False.
                if portfolio_blocked is not None:
                    try:
                        p_blocked, p_reason = portfolio_blocked()
                        if p_blocked:
                            log_system("WARNING", f"Portfolio gate blocked: {p_reason} - sleeping.")
                            time.sleep(300)
                            continue
                    except Exception as e:
                        log_system("WARNING", f"Portfolio gate check failed: {e}")

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
                elif ledger is not None:
                    # LIVE: detect broker-side closes so daily risk gates apply.
                    ledger.poll(bridge)

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

                # LIVE-only stop housekeeping (no-op in paper mode: guard is
                # None there, and the paper ratchet lives in paper.on_tick).
                # Re-verifies a stop that vanished mid-trade and ratchets to
                # breakeven at BE_TRIGGER_R. Never allowed to break the loop.
                if guard is not None:
                    try:
                        guard.manage(positions, tick, sym)
                    except Exception as e:
                        log_system("WARNING", f"[LIVE-GUARD] manage failed: {e}")

                # A missing/zero `point` used to raise ZeroDivisionError inside
                # the broad handler; fail the gate CLOSED instead of trading on
                # a spread we cannot measure.
                try:
                    point = float(sym.point)
                except (TypeError, ValueError):
                    point = 0.0
                if point > 0:
                    spread_points = round((tick.ask - tick.bid) / point)
                    gate_pass = spread_monitor.observe(spread_points)
                else:
                    spread_points = 0
                    gate_pass = False
                    log_system("WARNING",
                        "symbol_info.point missing/zero - spread gate fails closed this loop")
                if spread_monitor.warn_now():
                    log_system("WARNING", spread_monitor.warning_message())
                elif spread_monitor.recovered_now():
                    log_system("INFO",
                        f"Spread gate feasible again: spread {spread_points} <= "
                        f"MAX_SPREAD_POINTS={getattr(config, 'MAX_SPREAD_POINTS', 0)} "
                        f"(first pass after a starved/infeasible stretch)")

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
                    mode=config.TRADING_MODE,
                    spread_gate=spread_monitor.status()
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

                # Equity floor (latched). Measured on EQUITY - floating P&L
                # counts - and only ever blocks NEW entries: open positions
                # keep their broker-side stops and the LIVE guard.
                floor_blocked, floor_reason = False, ""
                if equity_floor is not None:
                    try:
                        floor_blocked, floor_reason = equity_floor.blocked(disp_equity)
                    except Exception as e:
                        log_system("WARNING", f"[RISK] equity floor check failed: {e}")

                # Kill switch: disable NEW entries without stopping the engine.
                # Open positions keep their broker-side SL/TP. Log once per
                # state change so the trades log isn't spammed every 15s.
                kill_active = KILL_SWITCH_FILE.exists()
                if kill_active != kill_switch_active:
                    kill_switch_active = kill_active
                    if kill_active:
                        log_system("WARNING",
                            f"KILL_SWITCH detected ({KILL_SWITCH_FILE}) - new entries disabled; "
                            f"open positions keep broker-side SL/TP. Remove the file to resume.")
                    else:
                        log_system("INFO", "KILL_SWITCH removed - new entries re-enabled.")

                # Already in a trade? (real or simulated)
                if bridge.has_open_position() or (paper is not None and paper.has_position()):
                    log_system("INFO", "Active position exists – waiting...")
                    # Bar-close exits (donchian family only; ScalpStrategy has
                    # no BAR_CLOSE_EXITS so gold never fetches rates here).
                    # The intra-bar SL was already resolved pessimistically by
                    # paper.on_tick earlier this loop - same order as replay.
                    if (paper is not None and paper.has_position()
                            and getattr(strategy, "BAR_CLOSE_EXITS", False)):
                        try:
                            ex_rates = bridge.get_rates(tick=tick)
                        except Exception:
                            ex_rates = None
                        ex, bar_exit_last_closed_ts, bar_exit_bars_in_trade = \
                            maybe_bar_close_exit(
                                strategy, ex_rates, paper.position,
                                bar_exit_last_closed_ts, bar_exit_bars_in_trade)
                        if ex:
                            closed_info = paper.close(ex["price"], ex["reason"])
                            log_system("INFO",
                                f"[PAPER] Bar-close exit ({ex['reason']} after "
                                f"{bar_exit_bars_in_trade} bars): "
                                f"PnL ${closed_info['profit']:+.2f} | "
                                f"Balance ${closed_info['balance']:.2f}")
                    poll_paper_position(bridge, paper)
                    continue

                if kill_active:
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                if floor_blocked:
                    if floor_blocked_prev is not True:
                        log_system("WARNING",
                            f"[RISK] new entries BLOCKED: {floor_reason}. Open positions keep "
                            f"their stops. Reset: python risk_guard.py --reset")
                    floor_blocked_prev = True
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue
                floor_blocked_prev = False

                # The session filter already ends at 20:00 UTC, so this is the
                # belt to that braces: no entry may be opened into the weekend.
                if risk_guard.weekend_flat_enabled() and risk_guard.in_weekend_window():
                    if weekend_blocked_prev is not True:
                        log_system("INFO",
                            "[RISK] weekend flat window - no new entries until Monday "
                            "00:00 UTC (open positions are closed at market)")
                    weekend_blocked_prev = True
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue
                weekend_blocked_prev = False

                # Spread filter (identical rule to before, but the decision is
                # recorded by the monitor so an impossible gate is visible)
                if not gate_pass:
                    log_trade("SKIP", {"reason": "high_spread", "spread": spread_points})
                    time.sleep(config.CHECK_INTERVAL_SECONDS)
                    continue

                # Strategy evaluation (rates cached per closed bar)
                rates = bridge.get_rates(tick=tick)  # -> window + fetch margin
                signal, sl_dist, tp_dist = strategy.check_signal(rates)

                log_trade("SIGNAL", {
                    "signal": signal,
                    "sl_dist": round(sl_dist, 2),
                    "tp_dist": round(tp_dist, 2),
                    "reason": strategy.last_skip_reason,
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
                            if getattr(strategy, "BAR_CLOSE_EXITS", False):
                                # The signal bar is the one that just closed;
                                # the next bar to close counts as bar 1.
                                bar_exit_bars_in_trade = 0
                                bar_exit_last_closed_ts = (
                                    _bar_time(rates[-2])
                                    if rates is not None and len(rates) >= 2 else None)
                        else:
                            log_trade("SIM_ENTRY_FAILED", {"reason": "paper position already open"})
                    else:
                        log_system("INFO", f"Executing {signal} order...")
                        # LIVE sizing: fixed LOT_SIZE unless RISK_PCT > 0, in
                        # which case the lot count is derived from the broker
                        # balance and a stop that is too wide for the budget is
                        # SKIPPED rather than sent oversized. The paper path
                        # above never comes here (gold 2026-10-17 correction).
                        volume = float(getattr(config, "LOT_SIZE", 0.01))
                        sizing = None
                        risk_pct = float(getattr(config, "RISK_PCT", 0.0) or 0.0)
                        if risk_pct > 0:
                            sym_step = (getattr(sym, "volume_step", None)
                                        or getattr(config, "VOLUME_STEP", 0.01))
                            sym_min = (getattr(config, "VOLUME_MIN", None)
                                       or getattr(sym, "volume_min", None) or sym_step)
                            sym_max = (getattr(config, "VOLUME_MAX", None)
                                       or getattr(sym, "volume_max", None))
                            sizing = size_lots(
                                balance=float(acc.balance),
                                stop_price_distance=sl_dist,
                                contract_size=float(getattr(config, "CONTRACT_SIZE", 100.0)),
                                risk_pct=risk_pct,
                                volume_step=sym_step,
                                volume_min=sym_min,
                                volume_max=sym_max,
                            )
                        if sizing is not None and sizing.lots is None:
                            log_trade("ENTRY_SKIPPED", {
                                "reason": f"risk_sizer:{sizing.reason}",
                                "risk_pct": risk_pct,
                                "stop_distance": round(sl_dist, 2),
                                "risk_per_lot": round(sizing.risk_per_lot_usd, 2),
                            })
                        else:
                            if sizing is not None:
                                volume = sizing.lots
                                log_system("INFO",
                                    f"[LIVE] Sized {volume} lots at RISK_PCT={risk_pct:g}% "
                                    f"(budget ${sizing.risk_usd:.2f}, "
                                    f"actual ${sizing.actual_risk_usd:.2f})")
                            res = bridge.open_trade(signal, sl_dist, tp_dist, volume=volume)

                            if res and res.retcode == bridge.mt5.TRADE_RETCODE_DONE:
                                log_trade("ENTRY", {
                                    "side": signal,
                                    "ticket": res.order,
                                    "volume": volume,
                                    "sl_dist": round(sl_dist, 2),
                                    "tp_dist": round(tp_dist, 2)
                                })
                                # A DONE retcode does not prove a stop is
                                # attached. Prove it, repair it, or close it -
                                # before the loop moves on (§4.2).
                                if guard is not None:
                                    try:
                                        v = guard.on_fill(res, signal, sl_dist,
                                                          tp_dist, volume, sym)
                                        if v.get("status") in ("ok", "repaired"):
                                            log_system("INFO",
                                                f"[LIVE] stop verified on ticket {v.get('ticket')} "
                                                f"(SL {v.get('sl')}, TP {v.get('tp')}) "
                                                f"[{v.get('status')}]")
                                        else:
                                            log_system("ERROR",
                                                f"[LIVE] stop NOT verified: {v.get('status')} - "
                                                f"check ticket {v.get('ticket')} in MT5 now")
                                    except Exception as e:
                                        log_system("ERROR",
                                            f"[LIVE-GUARD] verification raised ({e}) - the "
                                            f"position may have NO stop; check MT5 now")
                            else:
                                comment = res.comment if res else "No response"
                                log_trade("ENTRY_FAILED", {"reason": comment})

                consecutive_errors = 0
                poll_paper_position(bridge, paper)

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
