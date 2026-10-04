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

# Paper account (FORWARD_TEST only) — reset 2026-10-04: $200 → $300
SIM_START_BALANCE = 300.0   # dummy balance to emulate with
# Move SL to breakeven once +X R. Offline sweep (2026-09-30, 20k M5 bars,
# docs/strategy_iteration_2026-09-30.md) shows the old 0.75R was actively
# harmful: it scratched 94 of 189 trades at entry (each paying a full spread)
# while the 5R targets rarely survived a 0.75R pullback. Monotone improvement
# 0.5R < 0.75R < 1.0R < 1.25R < 1.5R ~ off; 1.5R is the conservative end of
# the plateau (some protection, no reliable loss). Re-tune after more data.
BE_TRIGGER_R = 1.5

# Position sizing (testing size)
LOT_SIZE = 0.01

# Spread protection (raised for current broker conditions)
MAX_SPREAD_POINTS = 80

# Assumed round-trip spread in *price* units for the backtester when the data
# has no `spread` column. The M5 CSV's own spread column (mean ~47, median ~51
# points = $0.47/$0.51 at 2-digit gold pricing) is preferred when present; the
# old hard-coded 0.30 was ~40% too optimistic.
SPREAD_COST_PRICE = 0.45

# --- Risk Controls ---
MAX_DAILY_LOSS = 30.0          # Stop trading for the day if daily PnL <= -$30
MAX_TRADES_PER_DAY = 15        # Hard cap on number of trades per day
MAX_CONSECUTIVE_LOSSES = 4     # Optional pause after X losses in a row

# Loop timing
CHECK_INTERVAL_SECONDS = 15    # How often the live loop checks for signals while flat
POSITION_CHECK_INTERVAL_SECONDS = 1  # Faster tick poll (seconds) while a paper position is open
RETRY_SLEEP_SECONDS = 10       # Sleep when connection problems occur

# --- MT5 / RPyC connection robustness ---
CONNECT_TIMEOUT_SECONDS = 10   # TCP probe timeout when reaching the RPyC bridge
RPC_TIMEOUT_SECONDS = 30       # Max seconds to wait for any single RPyC/MT5 call
RECONNECT_MAX_DELAY_SECONDS = 60  # Cap for exponential reconnect backoff
STALE_TICK_WARN_CYCLES = 20    # Warn after N loops with an unchanged tick
STALE_TICK_RECONNECT_CYCLES = 120  # Force reconnect after N loops with an unchanged tick

# --- Strategy filters (v7) ---
# Session filter: only take signals during higher-liquidity hours (UTC).
# London open ~07:00, NY open ~13:00. Widened 17:00 -> 20:00 on 2026-10-01
# (research/strategy_sweep.py --sweep session, 20k M5 bars) after the paper
# book was found to be taking very few trades: 07-17 alone gave 174 trades
# over ~101 days (~2.5/day); 07-20 keeps the full NY afternoon in play and
# gives 216 trades (+24%) with a *better* PF (1.14 vs 1.06) and lower max DD.
# Still skips the 21:00-22:00 UTC daily rollover break and the Asian session.
SESSION_FILTER_ENABLED = True
SESSION_START_HOUR_UTC = 7
SESSION_END_HOUR_UTC = 20

# Widened 35/65 -> 40/60 on 2026-10-01 for the same reason (too few trades).
# Offline sweep (research/strategy_sweep.py --sweep rsi, 20k M5 bars) found a
# stable hump around 40/60 (36..44 all positive/PF>1.1, not a knife-edge):
# combined with the 07-20 session this is 255 trades over ~101 days (was 174,
# +47%), net +$456.58 (was +$52.80), PF 1.32 (was 1.06), max DD $108.65 (was
# $99.62), positive in every calendar month and both halves of the data, and
# a 10k-resample bootstrap P(net>0)=0.96 (was 0.60 — the old config's CI
# spanned zero). See docs/strategy_iteration_2026-10-01.md.
RSI_BUY_LEVEL = 40
RSI_SELL_LEVEL = 60

# Evaluate EMA/RSI/ATR on the last *completed* M5 bar (not the forming one).
# Combined with one-shot-per-bar in ScalpStrategy so the 15s live loop cannot
# re-fire the same RSI cross after a quick scratch/BE exit.
SIGNAL_ON_CLOSED_BAR = True

# --- Indicator periods & ATR risk geometry ---
# These used to be literals inside strategy.py (200 / 14 / 14, ATR floor 0.50,
# SL 2.0xATR, TP 5.0xATR). They are config keys now so a second symbol instance
# (see btc/config.py) can carry its own values without forking the engine.
# The values here are exactly the old literals: gold behaves identically.
# Consumers: strategy.check_signal, research/strategy_sweep.py
# (params_from_config), research/parity_test.py (parity guard).
EMA_PERIOD = 200
RSI_PERIOD = 14
ATR_PERIOD = 14

# Minimum ATR to trade at all. NOTE: 0.50 never binds on the current gold data
# (file ATR min ~1.22 — see docs/loss_analysis_2026-10-02.md §4), so for gold
# this is documentation, not a live filter; keep it explicit rather than
# silently mis-tuning it.
ATR_MIN = 0.50

# Exit geometry in ATR multiples (backtest and live read the same keys).
SL_ATR_MULT = 2.0
TP_ATR_MULT = 5.0

# --- Instrument economics (symbol-agnostic engine) ---
# XAU/USD on XM Standard: 1.00 lot = 100 oz, so $PnL = price_diff * lots * 100.
# A BTC instance overrides both of these (1 lot = 1 BTC, same 2 digits).
CONTRACT_SIZE = 100.0
PRICE_DIGITS = 2      # quoted decimals; spread points -> price = 10^-digits

# --- Indicator window (single source of truth) ---
# How many M5 bars the signal window must contain. The 200-EMA only has
# (window - 1) bars of recursion, and with adjust=False the seed keeps weight
# (1 - 2/(200+1))^(window-1): at the old 250-bar live fetch that was ~8%, at the
# backtester's 202 bars ~13.5% — i.e. the "EMA200" was really a much shorter,
# wildly warm-up-dependent average, and live and backtest disagreed with each
# other. At 1000 bars the seed weight is ~5e-5 (converged), so this is a real
# EMA200 and the live path matches the backtester.
# Consumers: strategy.check_signal (guard), MT5Bridge.get_rates (fetch count),
# backtest.run_backtest (window).
INDICATOR_WINDOW_BARS = 1000

# Extra bars MT5Bridge.get_rates requests on top of INDICATOR_WINDOW_BARS.
# strategy.check_signal requires >= INDICATOR_WINDOW_BARS bars and then slices
# to exactly that many, so the margin gives headroom (one missing/partial bar
# from the broker would otherwise silence every signal) without changing the
# indicator values.
INDICATOR_FETCH_MARGIN = 50
