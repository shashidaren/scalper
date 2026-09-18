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
MAX_CONSECUTIVE_LOSSES = 4     # Optional pause after X losses in a row

# Loop timing
CHECK_INTERVAL_SECONDS = 15    # How often the live loop checks for signals
RETRY_SLEEP_SECONDS = 10       # Sleep when connection problems occur

# --- MT5 / RPyC connection robustness ---
CONNECT_TIMEOUT_SECONDS = 10   # TCP probe timeout when reaching the RPyC bridge
RPC_TIMEOUT_SECONDS = 30       # Max seconds to wait for any single RPyC/MT5 call
RECONNECT_MAX_DELAY_SECONDS = 60  # Cap for exponential reconnect backoff
STALE_TICK_WARN_CYCLES = 20    # Warn after N loops with an unchanged tick
STALE_TICK_RECONNECT_CYCLES = 120  # Force reconnect after N loops with an unchanged tick

# --- Strategy filters (v7) ---
# Session filter: only take signals during higher-liquidity hours (UTC).
# London open ~07:00, NY open ~13:00; we allow 07:00–17:00 UTC to cover
# London + London-NY overlap and early NY. Asian session is skipped.
SESSION_FILTER_ENABLED = True
SESSION_START_HOUR_UTC = 7
SESSION_END_HOUR_UTC = 17

# RSI extremes (softer than original 28/72 for more quality pullbacks)
RSI_BUY_LEVEL = 30
RSI_SELL_LEVEL = 70

# Evaluate EMA/RSI/ATR on the last *completed* M5 bar (not the forming one).
# Combined with one-shot-per-bar in ScalpStrategy so the 15s live loop cannot
# re-fire the same RSI cross after a quick scratch/BE exit.
SIGNAL_ON_CLOSED_BAR = True
