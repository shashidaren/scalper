HOST = "localhost"
PORT = 18812

SYMBOL = "GOLD"
MAGIC_NUMBER = 999111
TIMEFRAME = "M5"

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
