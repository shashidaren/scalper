HOST = "localhost"
PORT = 18812

SYMBOL = "GOLD"
MAGIC_NUMBER = 999111
TIMEFRAME = "M5"

# --- Trading mode ---
# "FORWARD_TEST" = paper trading on real MT5 ticks: balance/positions are
#                  simulated, NO orders are sent (port of the
#                  gold-trading-bot FORWARD_TEST approach)
# "LIVE"         = real orders through the MT5 bridge
TRADING_MODE = "FORWARD_TEST"

# Paper account (FORWARD_TEST only)
SIM_START_BALANCE = 200.0   # dummy balance to emulate with
BE_TRIGGER_R = 0.75         # move SL to breakeven once +0.75R (like gold-trading-bot)

# Position sizing (testing size)
LOT_SIZE = 0.01

# Spread protection (raised for current broker conditions)
MAX_SPREAD_POINTS = 80

# --- Risk Controls ---
MAX_DAILY_LOSS = 30.0          # Stop trading for the day if daily PnL <= -$30
MAX_TRADES_PER_DAY = 15        # Hard cap on number of trades per day
# Pause *new* entries for the rest of the calendar day after this many
# consecutive closed losses (paper or live). 0 disables. Open trades still
# manage to SL/TP/BE. Streak resets on a win or a new day.
# v12: tightened 4→2 after paper 0/13 wipe so a bad cluster stops faster.
MAX_CONSECUTIVE_LOSSES = 2

# Loop timing
CHECK_INTERVAL_SECONDS = 15    # How often the live loop checks for signals
RETRY_SLEEP_SECONDS = 10       # Sleep when connection problems occur

# --- MT5 / RPyC connection robustness ---
CONNECT_TIMEOUT_SECONDS = 10   # TCP probe timeout when reaching the RPyC bridge
RPC_TIMEOUT_SECONDS = 30       # Max seconds to wait for any single RPyC/MT5 call
RECONNECT_MAX_DELAY_SECONDS = 60  # Cap for exponential reconnect backoff
STALE_TICK_WARN_CYCLES = 20    # Warn after N loops with an unchanged tick
STALE_TICK_RECONNECT_CYCLES = 120  # Force reconnect after N loops with an unchanged tick

# --- Strategy filters (v12) ---
# Session filter: only take signals during higher-liquidity hours (UTC).
# v12: 08–16 UTC (was 07–17). Drops London-open noise and late-NY fade.
SESSION_FILTER_ENABLED = True
SESSION_START_HOUR_UTC = 8
SESSION_END_HOUR_UTC = 16

# Friday early-close: gold thins into the weekend; skip *new* entries after
# this UTC hour on Friday. Open trades still manage to SL/TP/BE.
FRIDAY_CUTOFF_ENABLED = True
FRIDAY_CUTOFF_HOUR_UTC = 16

# Weekend flat: session hours alone would still allow Sat/Sun session hours.
# Skip *new* entries on Saturday and Sunday (weekend gap / thin quotes).
WEEKEND_FLAT_ENABLED = True

# RSI extremes (softer than original 28/72 for more quality pullbacks)
RSI_BUY_LEVEL = 30
RSI_SELL_LEVEL = 70
# v12.1 recovery band: reject late RSI crosses that already ran far from the
# extreme (chase entries). 0 disables the cap/floor.
# Widened 40/60 → 45/55 after v12 produced 0 paper fills (gold M5 often
# jumps >10 RSI points on the cross bar). Still rejects mid-range chases.
RSI_BUY_MAX = 45    # BUY only if rsi_curr <= this after crossing BUY_LEVEL
RSI_SELL_MIN = 55   # SELL only if rsi_curr >= this after crossing SELL_LEVEL

# v12: signal bar body must agree with direction (bullish candle for BUY).
REQUIRE_SIGNAL_CANDLE = True

# Evaluate EMA/RSI/ATR on the last *completed* M5 bar (not the forming one).
# Combined with one-shot-per-bar in ScalpStrategy so the 15s live loop cannot
# re-fire the same RSI cross after a quick scratch/BE exit.
SIGNAL_ON_CLOSED_BAR = True

# Minimum M5 ATR in price units. $0.50 was too low vs typical GOLD spread
# (30–80 points ≈ $0.30–$0.80), so SL/TP were mostly the bid/ask.
MIN_ATR = 0.80

# Live/paper only: require sl_dist >= this multiple of (ask-bid).
# 0 disables. 3.0 means R must be at least 3 spreads before we take the trade.
MIN_SL_SPREAD_MULT = 3.0
