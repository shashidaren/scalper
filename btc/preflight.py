#!/usr/bin/env python3
"""Pre-start check: would this instance's spread gate actually let it trade?

The engine refuses to enter while the live spread exceeds
`config.MAX_SPREAD_POINTS`. If that gate sits below the instrument's normal
spread, the bot runs forever without a single entry and the only symptom is a
`SKIP high_spread` line per cycle - which is how the BTC instance spent its
whole life at 0 trades (btc/HANDOFF.md §9: ~4,000-point quotes against the
`MAX_SPREAD_POINTS=1500` placeholder).

Run this **before** starting/enabling a bot and after any change to
`MAX_SPREAD_POINTS` or a switch of account tier. It answers, with numbers:

  1. what the live spread distribution actually is (sampled, in points);
  2. what share of those quotes the configured gate would veto;
  3. what the round-trip spread costs as a fraction of one stop (1R) - the
     number that decides whether a shape can pay for the spread at all;
  4. a verdict: OK / STARVED / INFEASIBLE (see `spread_gate.py`).

Read-only: it never sends orders and never calls `mt5.shutdown()` (the gold bot
shares the terminal through the same RPyC bridge). Exit codes: 0 OK, 1 starved,
2 infeasible, 3 could not measure - so a runbook can gate on it.

Usage (on the server, from the repo root):
    mt5env/bin/python btc/preflight.py                    # live sample, btc/ config
    mt5env/bin/python btc/preflight.py --seconds 120
    mt5env/bin/python btc/preflight.py --offline --csv data/BTCUSD_M5.csv
    python3 btc/preflight.py --config-dir . --offline --csv data/GOLD_M5.csv   # gold sanity

Offline/`--csv` mode is bridge-free: it grades the gate against the spread
column of a bar file plus its measured ATR (the same maths as
`btc/edge_screen.py` and `btc/derive_params.py`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

EXIT_OK, EXIT_STARVED, EXIT_INFEASIBLE, EXIT_UNKNOWN = 0, 1, 2, 3


def _load_config(config_dir: str | None):
    sys.path.insert(0, HERE)
    import _instance  # noqa: E402

    target = os.path.abspath(config_dir) if config_dir else HERE
    _instance.activate(target)
    _instance.add_engine_path(ROOT)
    import config  # noqa: E402

    return config


# --------------------------------------------------------------------------
# pure helpers (tested offline by btc/preflight_test.py)
# --------------------------------------------------------------------------
def csv_cost_report(df, config) -> dict:
    """Spread / ATR / cost-per-R from a bar file, in the instance's units."""
    import numpy as np
    import pandas as pd

    digits = int(getattr(config, "PRICE_DIGITS", 2))
    point = 10.0 ** -digits
    sl_mult = float(getattr(config, "SL_ATR_MULT", 2.0))
    tp_mult = float(getattr(config, "TP_ATR_MULT", 5.0))
    atr_period = int(getattr(config, "ATR_PERIOD", 14))
    lot = float(getattr(config, "LOT_SIZE", 0.01))
    contract = float(getattr(config, "CONTRACT_SIZE", 100.0))

    close = df["close"].to_numpy(float)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    prev = np.concatenate(([np.nan], close[:-1]))
    tr = np.nanmax(np.vstack([high - low, np.abs(high - prev), np.abs(low - prev)]), axis=0)
    atr = pd.Series(tr).rolling(atr_period).mean().dropna().to_numpy()

    out = {"bars": int(len(df)), "atr_p50": float(np.median(atr)) if len(atr) else None}
    if "spread" in df.columns:
        sp = pd.to_numeric(df["spread"], errors="coerce").dropna().to_numpy(float)
        out["spread_pts"] = {"p10": float(np.quantile(sp, .10)), "p50": float(np.median(sp)),
                             "p90": float(np.quantile(sp, .90)), "max": float(sp.max())}
    else:
        out["spread_pts"] = None

    spread_px = (out["spread_pts"]["p50"] * point) if out["spread_pts"] else \
        float(getattr(config, "SPREAD_COST_PRICE", 0.45))
    sl_px = out["atr_p50"] * sl_mult if out["atr_p50"] else None
    out["sl_px"] = sl_px
    out["spread_px"] = spread_px
    out["cost_per_r"] = (spread_px / sl_px) if sl_px else None
    out["risk_usd"] = sl_px * lot * contract if sl_px else None
    out["spread_usd"] = spread_px * lot * contract
    rr = tp_mult / sl_mult
    out["required_wr_pct"] = (100.0 * (1.0 + (out["cost_per_r"] or 0)) / (1.0 + rr))
    out["breakeven_wr_pct"] = 100.0 / (1.0 + rr)
    return out


def render(config, gate_status, cost, symbol, source, live_spec=None) -> tuple[list[str], int]:
    L, A = [], None
    A = L.append
    A("=" * 78)
    A(f"PREFLIGHT  {symbol}   ({source})")
    A("=" * 78)
    A(f"TRADING_MODE            {getattr(config, 'TRADING_MODE', '?')}")
    A(f"MAX_SPREAD_POINTS       {gate_status.get('gate')}")
    if live_spec:
        A(f"symbol spec             digits {live_spec.get('digits')} "
          f"point {live_spec.get('point')} contract {live_spec.get('contract')} "
          f"min lot {live_spec.get('volume_min')} stops_level {live_spec.get('stops_level')}")
    A("")
    A(f"observed quotes         {gate_status.get('samples')}  "
      f"pass {gate_status.get('passed')}  veto {gate_status.get('vetoed')} "
      f"({gate_status.get('veto_pct')}%)")
    if gate_status.get("samples"):
        A(f"spread min/median/max   {gate_status.get('min'):g} / "
          f"{gate_status.get('median'):g} / {gate_status.get('max'):g} points")
    if cost:
        sp = cost.get("spread_pts")
        A("")
        A("bar-file economics (defines what the gate must be above)")
        if sp:
            A(f"  spread column p10/p50/p90  {sp['p10']:.0f} / {sp['p50']:.0f} / {sp['p90']:.0f} points")
        A(f"  median ATR({getattr(config, 'ATR_PERIOD', 14)})            "
          f"{cost['atr_p50']:.2f} px  -> stop {cost['sl_px']:.2f} px "
          f"= ${cost['risk_usd']:.2f} risk at {getattr(config, 'LOT_SIZE', 0.01)} lots")
        A(f"  round-trip spread        {cost['spread_px']:.2f} px = ${cost['spread_usd']:.4f}")
        A(f"  spread / 1R              {100 * cost['cost_per_r']:.1f}%  ->  a shape needs "
          f"gross edge > {cost['cost_per_r']:.3f}R just to break even")
        A(f"  break-even WR            {cost['breakeven_wr_pct']:.1f}% before cost, "
          f"{cost['required_wr_pct']:.1f}% after")
    A("")
    if not gate_status.get("samples"):
        code = EXIT_UNKNOWN
        A("VERDICT: UNKNOWN - no quotes sampled, so the gate could not be graded.")
        A("  Pass --csv <bar file> for the offline economics, or run without --offline")
        A("  while the RPyC bridge is up to sample live quotes.")
    elif gate_status.get("infeasible"):
        code = EXIT_INFEASIBLE
        A("VERDICT: INFEASIBLE - every sampled quote exceeds MAX_SPREAD_POINTS.")
        A("  This instance cannot enter a trade as configured. Do NOT read 0 trades")
        A("  as 'no signal': the gate is below the instrument's spread. Either raise")
        A("  the gate to a measured value (btc/derive_params.py: 1.25x spread p90) -")
        A("  which is a research decision, not a fix - or leave the bot stopped.")
    elif gate_status.get("starved"):
        code = EXIT_STARVED
        A(f"VERDICT: STARVED - {gate_status.get('veto_pct')}% of quotes vetoed; entries are")
        A("  technically possible but effectively never happen. Treat any '0 trades'")
        A("  reading from this instance as a configuration statement first.")
    else:
        code = EXIT_OK
        A(f"VERDICT: OK - the gate passes {100 - (gate_status.get('veto_pct') or 0):.1f}% of quotes.")
        A("  Feasibility only: this says nothing about whether the strategy has an edge;")
        A("  that is the Phase 1 train-select -> cold-OOS gate (btc/HANDOFF.md §5).")
    A("=" * 78)
    return L, code


# --------------------------------------------------------------------------
# live sampling
# --------------------------------------------------------------------------
def sample_live(config, seconds: float, interval: float, host=None, port=None):
    """Sample real ticks through the RPyC bridge. Read-only, no shutdown()."""
    import rpyc
    from spread_gate import SpreadGateMonitor

    host = host or getattr(config, "HOST", "localhost")
    port = port or getattr(config, "PORT", 18812)
    symbol = getattr(config, "SYMBOL", "BTCUSD")
    gate = float(getattr(config, "MAX_SPREAD_POINTS", 0))

    conn = rpyc.classic.connect(host, int(port))
    mt5 = conn.modules.MetaTrader5
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
    mt5.symbol_select(symbol, True)
    si = mt5.symbol_info(symbol)
    if si is None:
        raise RuntimeError(f"symbol {symbol!r} not found in this terminal")
    point = float(si.point)

    spec = {
        "digits": int(si.digits), "point": point,
        "contract": float(getattr(si, "trade_contract_size", 1.0)),
        "volume_min": float(si.volume_min), "stops_level": int(getattr(si, "trade_stops_level", 0)),
        "spread_current": int(getattr(si, "spread", 0)),
        "swap_long": float(getattr(si, "swap_long", 0.0)),
        "swap_short": float(getattr(si, "swap_short", 0.0)),
        "swap_rollover3days": int(getattr(si, "swap_rollover3days", 0)),
    }

    mon = SpreadGateMonitor(gate, window=100000, warn_after=1, symbol=symbol)
    t_end = time.time() + float(seconds)
    last = None
    while time.time() < t_end:
        tick = rpyc.classic.obtain(mt5.symbol_info_tick(symbol))
        if tick is not None:
            sp = round((tick.ask - tick.bid) / point)
            mon.observe(sp)
            last = (tick.bid, tick.ask, sp)
        time.sleep(max(0.05, float(interval)))
    # deliberately no mt5.shutdown() - the gold bot may share this session
    return mon.status(), spec, last


# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config-dir", default=None,
                    help="instance dir whose config.py to use (default: btc/)")
    ap.add_argument("--seconds", type=float, default=60.0,
                    help="live sampling window (default 60s)")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="seconds between live samples (default 1s)")
    ap.add_argument("--host", default=None, help="bridge host (default: config.HOST)")
    ap.add_argument("--port", type=int, default=None, help="bridge port (default: config.PORT)")
    ap.add_argument("--offline", action="store_true",
                    help="do not touch the bridge; grade the gate from --csv only")
    ap.add_argument("--csv", default=None, help="bar file for the economics block")
    ap.add_argument("--json", default=None, help="also write the result here")
    args = ap.parse_args(argv)

    config = _load_config(args.config_dir)
    symbol = getattr(config, "SYMBOL", "?")
    gate = float(getattr(config, "MAX_SPREAD_POINTS", 0))

    cost = None
    csv_path = args.csv or os.path.join(ROOT, "data", f"{symbol}_{getattr(config, 'TIMEFRAME', 'M5')}.csv")
    if os.path.exists(csv_path):
        import pandas as pd
        try:
            cost = csv_cost_report(pd.read_csv(csv_path, parse_dates=["time"]), config)
            cost["csv"] = csv_path
        except Exception as e:
            print(f"[preflight] could not read {csv_path}: {e}", file=sys.stderr)

    live_spec = None
    if args.offline:
        spreads = []
        if cost and cost.get("spread_pts"):
            sp = cost["spread_pts"]
            spreads = [sp["p10"]] * 1 + [sp["p50"]] * 8 + [sp["p90"]] * 1
        from spread_gate import summarise
        gate_status = summarise(gate, spreads, symbol) if spreads else \
            {"gate": gate, "samples": 0, "passed": 0, "vetoed": 0, "veto_pct": 0.0,
             "infeasible": False, "starved": False}
        source = f"offline - {cost['csv'] if cost else 'no bar file'}"
        code_hint = None
    else:
        try:
            gate_status, live_spec, last = sample_live(config, args.seconds, args.interval,
                                                       args.host, args.port)
            source = (f"live sample {args.seconds:g}s @{args.interval:g}s via "
                      f"{args.host or getattr(config, 'HOST', 'localhost')}:"
                      f"{args.port or getattr(config, 'PORT', 18812)}"
                      + (f"  last bid/ask {last[0]}/{last[1]}" if last else ""))
        except Exception as e:
            print(f"[preflight] live sampling failed: {e}\n"
                  f"            (is the RPyC bridge running? try --offline --csv <file>)",
                  file=sys.stderr)
            return EXIT_UNKNOWN

    lines, code = render(config, gate_status, cost, symbol, source, live_spec)
    print("\n".join(lines))
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"symbol": symbol, "gate": gate_status, "csv_cost": cost,
                       "spec": live_spec, "exit_code": code}, f, indent=2)
        print(f"wrote {args.json}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
