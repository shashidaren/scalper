"""BTC instance config — the ONLY thing that makes the shared engine a bitcoin bot.

How this file is used
---------------------
The engine modules at the repo root (`run.py`, `strategy.py`, `paper.py`,
`mt5_bridge.py`, `logger.py`, ...) all do a plain `import config`. The BTC entry
points (`btc/run.py`, `btc/dashboard.py`, `btc/tool.py`) pre-load THIS file into
`sys.modules["config"]` before anything else imports it, so the whole engine
runs as a BTC instance with no fork of the engine code. The gold bot keeps
importing the root `config.py` and is untouched.

**Everything marked PLACEHOLDER below is a starting hypothesis, not a tuned
value.** Gold's adopted parameters (RSI 40/60, session 07-20, BE 1.5R, the
2.0/5.0xATR geometry, MAX_SPREAD_POINTS=80, the $ risk gates) were fitted to
100 days of gold M5 data and transfer to BTC with zero evidence behind them.
Derive each one from BTC data first: `btc/HANDOFF.md` §5 (Phase 0 recon →
Phase 1 train-select/cold-OOS sweep). Until then:
`TRADING_MODE` stays `"FORWARD_TEST"`.

Nothing here has been validated against a live BTCUSD feed yet — see
`btc/HANDOFF.md` §3 for the broker specs still to confirm with `btc/recon.py`.
"""
from pathlib import Path

# --- connection (same MT5 terminal/container as gold; one bridge, two bots) ---
HOST = "localhost"
PORT = 18812

# --- instrument ---
SYMBOL = "BTCUSD"          # PLACEHOLDER: confirm the exact broker name (btc/recon.py)
TIMEFRAME = "M5"

# Must differ from gold's 999111: positions/deals/ledger are magic-matched, so a
# shared magic would let the two books see each other's fills in LIVE mode.
MAGIC_NUMBER = 999112

# Separate log dir per instance — trades.jsonl, daily_stats.json,
# paper_account.json and KILL_SWITCH all hang off this. Without it both bots
# would append to the same gold book.
LOG_DIR = Path(__file__).resolve().parent / "logs"

DASHBOARD_TITLE = "Bitcoin Scalper Dashboard"
DASHBOARD_PORT = 8089

# --- trading mode ---
# Non-negotiable until BTC has its own paper track record: no real orders.
TRADING_MODE = "FORWARD_TEST"

# Paper account (FORWARD_TEST only). Same $200 start as gold for comparability,
# but note the per-trade $ are ~10x smaller at 0.01 lots (see CONTRACT_SIZE),
# so this book will look quieter and its %% returns are not comparable to gold.
SIM_START_BALANCE = 200.0

# --- instrument economics ---
# XM BTCUSD: 1.00 lot = 1 BTC, 2 decimals (digits/point come from symbol_info at
# runtime for live orders; these keys drive the backtester/paper P&L maths).
# 0.01 lot = 0.01 BTC, i.e. $0.01 of P&L per $1 of price movement.
CONTRACT_SIZE = 1.0
PRICE_DIGITS = 2           # PLACEHOLDER: confirm symbol_info.digits
LOT_SIZE = 0.01            # broker minimum, same as gold

# --- strategy: entry filters ---
# 24/7 market. Gold's session filter exists partly to dodge the 21:00-22:00 UTC
# gold rollover break, which does not apply to BTC — and gold's end value (20)
# was fitted to gold data, so it is not inherited. Start with NO session filter
# and let Phase 1 earn one back (crypto liquidity still varies by hour/weekend,
# and weekend spreads are usually wider).
SESSION_FILTER_ENABLED = False
SESSION_START_HOUR_UTC = 7     # inert while the filter is off; documents intent
SESSION_END_HOUR_UTC = 20

# PLACEHOLDER: gold's adopted levels, unvalidated on BTC. Sweep 36/64…44/56 and
# the 30/70 baseline before adopting anything.
RSI_BUY_LEVEL = 40
RSI_SELL_LEVEL = 60

# --- strategy: indicators & ATR geometry ---
EMA_PERIOD = 200
RSI_PERIOD = 14
ATR_PERIOD = 14              # PLACEHOLDER: BTC is 24/7 and noisier than gold M5

# Gold's adopted 0.50 floor never binds on gold data (ATR min ~1.22). On BTC the
# ATR is ~$50-150 in price units, so 0.50 would be pure decoration: this MUST be
# derived from the recon ATR distribution (e.g. a 10-20th percentile) or left at
# 0.0 to disable the filter honestly rather than pretend it does something.
ATR_MIN = 0.0                # PLACEHOLDER: derive from btc/recon.py ATR quantiles

SL_ATR_MULT = 2.0            # PLACEHOLDER: gold's geometry, untested on BTC
TP_ATR_MULT = 5.0            # PLACEHOLDER: same; 2.0/5.0 = 1:2.5 RR

# Move SL to breakeven once +X R. Gold measured 0.75R as actively harmful and
# 1.5R as the conservative end of a monotone plateau — on gold data. On BTC this
# is unmeasured; sweep before trusting it.
BE_TRIGGER_R = 1.5           # PLACEHOLDER

# --- spread protection ---
# Gold uses 80 points (~$0.80); XM Standard BTCUSD typically quotes ~500 points
# (~$5.00), so copying 80 here would silently skip every trade. Start generous
# and tighten to the measured p90 from btc/recon.py + the BTC CSV.
MAX_SPREAD_POINTS = 1500     # PLACEHOLDER: derive from recon spread p90

# Fallback round-trip spread in price units when the CSV has no `spread` column
# (the MT5 pull does include it, so this rarely applies).
SPREAD_COST_PRICE = 5.0      # PLACEHOLDER

# --- risk gates ---
# CROSS-CHECK THESE AGAINST MEASURED BTC P&L BEFORE PAPER COUNTS FOR ANYTHING.
# At 0.01 lots a 2xATR stop on BTC risks roughly $1-3 (vs ~$6 median on gold),
# so gold's -$30 daily loss would need ~10-15 straight stop-outs and would be
# effectively dead next to MAX_TRADES_PER_DAY. These are deliberately scaled
# down; re-derive both from the Phase 1 trade distribution.
MAX_DAILY_LOSS = 8.0         # PLACEHOLDER: ~3-4 BTC stop-outs at 0.01 lots
MAX_TRADES_PER_DAY = 15      # PLACEHOLDER: 24/7 market may justify more/less
MAX_CONSECUTIVE_LOSSES = 4   # unused on gold too - measured as harmful there

# --- loop timing (same as gold; proven on the shared bridge) ---
CHECK_INTERVAL_SECONDS = 15
POSITION_CHECK_INTERVAL_SECONDS = 1
RETRY_SLEEP_SECONDS = 10

# --- MT5 / RPyC robustness ---
CONNECT_TIMEOUT_SECONDS = 10
RPC_TIMEOUT_SECONDS = 30
RECONNECT_MAX_DELAY_SECONDS = 60
# Crypto is 24/7 so "market closed" staleness is rarer than gold's daily break,
# but the broker does have crypto maintenance windows; keep the same watchdogs.
STALE_TICK_WARN_CYCLES = 20
STALE_TICK_RECONNECT_CYCLES = 120

# --- signal evaluation ---
SIGNAL_ON_CLOSED_BAR = True

# Same window everywhere (strategy guard, bridge fetch, backtester). 1000 bars
# converges the EMA200 seed weight to ~5e-5 on gold and is symbol-agnostic.
INDICATOR_WINDOW_BARS = 1000
INDICATOR_FETCH_MARGIN = 50
