# Python MT5 Gold Scalper & Backtester Framework

An experimental algorithmic trading and backtesting framework for GOLD / XAUUSD using MetaTrader 5 inside a Docker container (Wine) bridged to a host Python environment via RPyC.

Trading logic, risk controls, and failure handling have been thoroughly tested and validated through historical simulation.

---

## System Architecture Overview

The system strictly separates trading logic from the MetaTrader 5 execution environment:

1. Host Python Environment (mt5env):
   Runs strategy analysis, data processing, backtesting engine, and live execution loop on Linux.

2. Docker Container (lprett/mt5linux:latest):
   Provides the Windows-compatible MT5 terminal via Wine (XM Global Broker).

3. RPyC Bridge (Port 18812):
   Enables real-time remote function calls between host Python and the Wine MT5 library.

4. Separation of Concerns:
   MT5 handles broker connectivity; host Python handles signals, risk management, and order parameter calculations.

---

## File Structure & Responsibilities

- config.py: Global parameters (Symbol: GOLD, Magic: 999111, Timeframe: M5, Lot Size: 0.01, Spread Limits).
- mt5_bridge.py: RPyC wrapper for connection handling, tick/candle streams, active order queries, and live order execution.
- strategy.py: Core Strategy v5 (200 EMA trend filter + RSI(14) pullback signals + ATR(14) volatility filter + dynamic SL/TP).
- fetch_data.py: High-speed historical candle downloader using rpyc.classic.obtain() to store local CSV data.
- backtest.py: Bar-by-bar simulator accounting for $0.30/oz spread cost, dynamic SL/TP checks, and net PnL tracking.
- run.py: Live trading execution engine with pre-trade safety checks and position guards.

---

## Risk Controls & Failure Safeguards

1. Spread Filter Guard: Checks live market spread prior to trade execution (MAX_SPREAD_POINTS = 50). Skips entry if spread spikes.
2. Active Position Guard: Checks open positions via MAGIC_NUMBER before placing orders, preventing duplicate re-entries.
3. Volatility Guard (ATR): Skips trade entries when market volatility drops below $0.50/min (prevents choppy range-bound losses).
4. Dynamic Risk-to-Reward Ratio (1 : 2.5):
   - Stop Loss (SL): Entry +/- (2.0 x ATR)
   - Take Profit (TP): Entry -/+ (5.0 x ATR)
5. Fixed Position Sizing: Controlled lot sizing (0.01 lots for testing) to prevent over-leveraging.
6. RPyC Stream EOF Prevention: Solved socket disconnects when pulling large arrays by using rpyc.classic.obtain().
7. Strict Crossover Logic: Replaced continuous directional conditions with single-bar state triggers to eliminate duplicate trade loops.

---

## Strategy Evolution & Backtest History

- Stage 1 (Baseline - M1, 5k bars): Raw 5/20 EMA Crossover | Trades: 1644 | Win Rate: 34.8% | Net PnL: -$385.20 (Heavy overtrading)
- Stage 2 (M1, 5k bars): + 200 EMA Trend Filter | Trades: 1155 | Win Rate: 33.7% | Net PnL: -$328.50 (Cut counter-trend trades)
- Stage 3 (M1, 5k bars): + Strict Crossover Trigger | Trades: 147 | Win Rate: 35.4% | Net PnL: -$30.60 (Cut 90% of re-entry losses)
- Stage 4 (M1, 5k bars): + RSI(14) Pullback (35/65) | Trades: 111 | Win Rate: 42.3% | Net PnL: -$20.30 (Mean-reversion entry)
- Stage 5 (M1, 5k bars): + Fixed 1:2.75 R:R & ATR filter | Trades: 65 | Win Rate: 33.8% | Net PnL: +$15.50 (Profitable on small sample)
- Stage 6 (M1, 20k bars): Fixed 1:2.75 R:R on larger dataset | Trades: 207 | Win Rate: 29.0% | Net PnL: -$17.41 (M1 spread ate profit)
- FINAL STAGE (M5, 20k bars): Dynamic ATR SL/TP (1:2.5 R:R) | Trades: 187 | Win Rate: 29.4% | Net PnL: +$43.68 (PROFITABLE - Beats broker spread)

---

## Active Strategy Rules (v5)

1. Timeframe: 5-Minute Chart (M5).
2. Trend Filter: 200-period Exponential Moving Average (EMA).
   - Only BUY if Price > 200 EMA.
   - Only SELL if Price < 200 EMA.
3. Entry Trigger (RSI 14 Pullback):
   - BUY Signal: RSI dips <= 28 (oversold) and crosses back above 28.
   - SELL Signal: RSI spikes >= 72 (overbought) and crosses back below 72.
4. Volatility Guard (ATR 14):
   - Skip entry if current ATR < $0.50 per candle.
5. Dynamic SL / TP Levels:
   - Stop Loss: Entry +/- (2.0 x ATR)
   - Take Profit: Entry -/+ (5.0 x ATR)

---

## Execution Guide

1. Download Historical Data (20,000 M5 Candles):
   python3 fetch_data.py

2. Run Strategy Backtest:
   python3 backtest.py

3. Run Live Pre-Trade Pipeline:
   python3 run.py
