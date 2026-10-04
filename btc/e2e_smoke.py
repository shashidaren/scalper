#!/usr/bin/env python3
"""End-to-end smoke test for a symbol instance — no real broker, no real orders.

Proves the whole instance wiring on synthetic bars, in-process:

    btc/config.py -> _instance.activate -> engine run.py -> MT5Bridge (real RPyC
    over a fake MetaTrader5) -> strategy -> PaperAccount -> instance log dir

and then asserts a full round trip (SIM_ENTRY -> SL exit) with the instrument's
own contract maths. It is the only test that exercises the *instance* wiring end
to end (research/parity_test.py covers signals, research/paper_exit_test.py the
exit logic, backtest.py the accounting).

    mt5env/bin/python btc/e2e_smoke.py                       # test btc/ instance
    mt5env/bin/python btc/e2e_smoke.py --config-dir btc --bars 20000 --keep
    mt5env/bin/python btc/e2e_smoke.py --csv data/BTCUSD_M5.csv

Safety notes
------------
* Refuses to run if the instance config is not FORWARD_TEST (no orders are ever
  sent anyway — the fake MT5's order_send does not exist — but the guard makes
  that explicit).
* Uses its OWN storage: a temp instance dir, temp synthetic CSV and temp log
  dir. The real btc/logs (or gold logs/) is never touched.
* Binds a free ephemeral port, never 18812, so a live MT5 container on the
  server cannot be disturbed.

Exit code 0 = all checks pass.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import _instance  # noqa: E402


# --------------------------------------------------------------------------
# synthetic bars (pipeline fixture only - never evidence about any edge)
# --------------------------------------------------------------------------
def synth_bars(n: int, seed: int = 20261003, price0: float = 65000.0,
               spread_points: int = 520, digits: int = 2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    t = pd.date_range("2026-06-01", periods=n, freq="5min")   # 24/7, no gaps
    sigma = 0.0012
    vol = np.empty(n)
    v = sigma
    for i in range(n):
        v = float(np.clip(0.92 * v + 0.08 * sigma * (0.6 + 0.9 * rng.random()),
                          0.0004, 0.0045))
        vol[i] = v
    drift = np.concatenate([np.full(n // 4, 2e-5),
                            np.full(n // 4, -3e-5),
                            np.full(n - 2 * (n // 4), 1e-5)])
    close = price0 * np.exp(np.cumsum(rng.normal(0, 1, n) * vol + drift))
    open_ = np.r_[close[0], close[:-1]]
    wick = np.abs(rng.normal(0, 1, n)) * vol * close * 0.8
    spread = np.clip(rng.lognormal(np.log(spread_points), 0.45, n), 150, 4000).astype(int)
    spike = rng.random(n) < 0.05
    spread[spike] = rng.integers(1500, 4000, spike.sum())
    return pd.DataFrame({
        "time": t.strftime("%Y-%m-%d %H:%M:%S"),
        "open": open_, "high": np.maximum(open_, close) + wick,
        "low": np.minimum(open_, close) - wick, "close": close,
        "tick_volume": rng.integers(50, 3000, n), "spread": spread})


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# --------------------------------------------------------------------------
# fake MT5 + RPyC server (HANDOFF §8 pattern, as an actual socket server)
# --------------------------------------------------------------------------
def build_fake_mt5(arr: np.ndarray, state: dict, digits: int, point: float,
                   contract_size: float):
    class FakeTick:
        def __init__(self):
            self.bid = state["bid"]
            self.ask = state["ask"]
            self.last = state["bid"]
            self.time = int(state["t0"]) + int(time.time()) % 1000
            self.time_msc = int(state["t0"]) * 1000 + int(time.time() * 1000) % 200000

    class FakeMT5:
        TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_H1 = 1, 5, 15, 60
        DEAL_ENTRY_OUT = 1
        TRADE_RETCODE_DONE = 10009

        def initialize(self, *a, **k):
            return True

        def shutdown(self, *a, **k):
            return True

        def last_error(self):
            return (0, "fake ok")

        def symbol_select(self, s, e=True):
            return True

        def symbol_info(self, s):
            return SimpleNamespace(
                name=s, digits=digits, point=point, spread=520, filling_mode=2,
                visible=True, trade_contract_size=contract_size,
                volume_min=0.01, volume_step=0.01, volume_max=80.0,
                trade_stops_level=0, trade_tick_value=point * contract_size)

        def symbol_info_tick(self, s):
            return FakeTick()

        def account_info(self):
            return SimpleNamespace(login=1, server="FAKE", currency="USD",
                                   leverage=500, balance=300.0, equity=300.0,
                                   margin_free=300.0, margin_mode=0,
                                   trade_allowed=True)

        def copy_rates_from_pos(self, s, tf, start_pos, count):
            end = state["end_idx"] - int(start_pos)
            start = max(0, end - int(count))
            return arr[start:end].copy()

        def positions_get(self, symbol=None):
            return ()

    return FakeMT5()


def make_array(df: pd.DataFrame) -> np.ndarray:
    arr = np.zeros(len(df), dtype=[
        ("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"),
        ("close", "f8"), ("tick_volume", "i8"), ("spread", "i8")])
    arr["time"] = pd.to_datetime(df["time"]).astype("datetime64[s]").astype("int64").to_numpy()
    for c in ("open", "high", "low", "close"):
        arr[c] = df[c].to_numpy(float)
    arr["tick_volume"] = df["tick_volume"].to_numpy(int)
    arr["spread"] = df["spread"].to_numpy(int)
    return arr


def write_temp_instance(src_dir: Path, dst_dir: Path, symbol: str, port: int) -> Path:
    """Instance config = the real one, with a test symbol + temp logs + fake port."""
    src = (src_dir / "config.py").resolve()
    dst_dir.mkdir(parents=True, exist_ok=True)
    (dst_dir / "config.py").write_text(
        "import importlib.util\n"
        f"_spec = importlib.util.spec_from_file_location('_src_config', {str(src)!r})\n"
        "_m = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_m)\n"
        "for _k, _v in list(vars(_m).items()):\n"
        "    if not _k.startswith('_'):\n"
        "        globals()[_k] = _v\n"
        f"SYMBOL = {symbol!r}\n"
        "HOST = '127.0.0.1'\n"
        f"PORT = {port}\n"
        f"LOG_DIR = r'{dst_dir / 'logs'}'\n")
    return dst_dir


def read_jsonl(p: Path) -> list:
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config-dir", default=str(HERE),
                    help="instance dir whose config.py to test (default: btc/)")
    ap.add_argument("--csv", default=None, help="bars CSV (default: generated synthetic)")
    ap.add_argument("--bars", type=int, default=20000)
    ap.add_argument("--keep", action="store_true", help="keep the temp dir for inspection")
    args = ap.parse_args(argv)

    src_dir = Path(args.config_dir).resolve()
    if not (src_dir / "config.py").is_file():
        print(f"[ERROR] no config.py in {src_dir}")
        return 2

    import rpyc  # noqa: F401  (fail early with a clear message if missing)
    from rpyc.core.service import SlaveService
    from rpyc.utils.server import ThreadedServer

    tmp = Path(tempfile.mkdtemp(prefix="inst_e2e_"))
    port = free_port()
    inst_dir = write_temp_instance(src_dir, tmp / "instance", "SMOKETEST", port)
    logs = inst_dir / "logs"

    # --- activate the instance first: the synthetic spread must clear the
    #     instance's own spread gate, and gold's 80-point gate is 6x tighter
    #     than BTC's 1500 (with a 520-point fixture no trade would ever fire) ---
    config = _instance.activate(str(inst_dir))
    _instance.add_engine_path(str(ROOT))
    import config as cfg_check  # noqa: E402
    assert Path(cfg_check.__file__).resolve() == (inst_dir / "config.py").resolve()
    if str(getattr(config, "TRADING_MODE", "")) != "FORWARD_TEST":
        print(f"[ERROR] refusing to run: TRADING_MODE={config.TRADING_MODE!r} (expected FORWARD_TEST)")
        return 2
    max_spread = int(getattr(config, "MAX_SPREAD_POINTS", 80))
    fixture_spread = max(1, min(520, int(max_spread * 0.4)))

    # --- bars ---
    if args.csv:
        df = pd.read_csv(args.csv)
        print(f"bars: {args.csv} ({len(df)} rows)")
    else:
        df = synth_bars(args.bars, spread_points=fixture_spread)
        csv_path = tmp / "SMOKETEST_M5.csv"
        df.to_csv(csv_path, index=False)
        print(f"bars: generated synthetic {len(df)} rows (spread ~{fixture_spread} pts "
              f"< MAX_SPREAD_POINTS={max_spread}) -> {csv_path}")

    digits = int(getattr(config, "PRICE_DIGITS", 2))
    point = 10.0 ** -digits
    arr = make_array(df)

    sys.path.insert(0, str(ROOT))          # for `research.*` imports
    import research.strategy_sweep as sweep
    p = sweep.params_from_config()
    ind = sweep.compute_indicators(df, p)
    hours = pd.to_datetime(df["time"]).dt.hour.to_numpy()
    warm = int(p.warmup_bars)
    firing = [i for i in range(warm, len(df)) if sweep.signal_at(p, ind, hours, None, i)]
    if not firing:
        print("[ERROR] no signal fires in this data - cannot test the round trip")
        return 2
    sig_idx = firing[0]
    print(f"instance: {inst_dir}  symbol={config.SYMBOL}  contract={config.CONTRACT_SIZE} "
          f"lot={config.LOT_SIZE}  port={port}")
    print(f"first signal bar: idx={sig_idx} {df['time'].iloc[sig_idx]}")

    # --- fake MT5 over RPyC on the ephemeral port ---
    # The tick spread must match the fixture: the live loop reads it for the
    # MAX_SPREAD_POINTS gate (the CSV's spread column only drives the backtest).
    spread_price = fixture_spread * point
    state = {"end_idx": sig_idx + 1,
             "bid": float(df["close"].iloc[sig_idx]),
             "ask": float(df["close"].iloc[sig_idx]) + spread_price,
             "t0": int(arr["time"][sig_idx]) + 300}
    fake = build_fake_mt5(arr, state, digits, point, float(config.CONTRACT_SIZE))
    sys.modules["MetaTrader5"] = fake
    server = ThreadedServer(
        SlaveService, hostname="127.0.0.1", port=port,
        protocol_config={"allow_pickle": True, "allow_all_attrs": True,
                         "allow_getattr": True, "allow_setattr": True,
                         "import_custom_exceptions": True})
    threading.Thread(target=server.start, daemon=True).start()
    time.sleep(0.5)

    # --- engine (real run.py, loaded by path) ---
    engine = _instance.import_engine("run", str(ROOT))

    def wait_for(pred, timeout, label):
        t0 = time.time()
        while time.time() - t0 < timeout:
            if pred():
                print(f"  [{time.time() - t0:5.1f}s] OK   {label}")
                return True
            time.sleep(0.5)
        print(f"  [{time.time() - t0:5.1f}s] FAIL {label}")
        return False

    print("\n--- phase 1: signal -> paper entry (no orders) ---")
    engine_thread = threading.Thread(target=engine.main, daemon=True)
    engine_thread.start()
    ok_entry = wait_for(
        lambda: any(t.get("event") == "SIM_ENTRY" for t in read_jsonl(logs / "trades.jsonl")),
        45, "SIM_ENTRY logged into the instance log dir")

    state_file = logs / "paper_account.json"
    acct = json.loads(state_file.read_text()) if state_file.exists() else {}
    pos = acct.get("position") or {}
    if not pos:
        # No entry: show why (the engine logs SKIP/SIGNAL reasons) and fail clearly
        # instead of crashing on a missing file.
        recent = [t for t in read_jsonl(logs / "trades.jsonl")][-4:]
        print(f"  no paper position opened; recent engine events: {recent}")
        print("  (a SKIP/high_spread or session reason here means the fixture and the "
              "instance gates disagree, not that the wiring is broken)")
        sys.stdout.flush()
        os._exit(1)
    print(f"  position: {pos.get('side')} entry={pos.get('entry')} sl={pos.get('sl')} "
          f"tp={pos.get('tp')}")

    print("\n--- phase 2: drive the quote through SL -> paper exit ---")
    adverse = float(pos.get("sl", 0.0))
    if pos.get("side") == "BUY":
        state["bid"], state["ask"] = adverse - 1.0, adverse - 1.0 + spread_price
    else:
        state["bid"], state["ask"] = adverse + 1.0, adverse + 1.0 + spread_price
    ok_exit = wait_for(
        lambda: any(t.get("event") == "SIM_EXIT" for t in read_jsonl(logs / "trades.jsonl")),
        45, "SIM_EXIT logged")

    exits = [t for t in read_jsonl(logs / "trades.jsonl") if t.get("event") == "SIM_EXIT"]
    last = exits[-1] if exits else {}
    profit, reason = last.get("profit"), last.get("reason")
    sl_dist = float(pos.get("sl_dist") or 0.0)
    expected = -sl_dist * float(config.LOT_SIZE) * float(config.CONTRACT_SIZE)
    plausible = profit is not None and abs(profit - expected) <= max(0.05, abs(expected) * 0.05)
    print(f"  exit reason={reason} profit=${profit} (expected ~${expected:.2f} = "
          f"{sl_dist:.1f} px x {config.LOT_SIZE} lots x {config.CONTRACT_SIZE})")

    gold_logs = ROOT / "logs" / "trades.jsonl"
    checks = [
        ("engine connected to the fake bridge", ok_entry),
        ("SIM_ENTRY + SIM_EXIT in the instance log dir", ok_entry and ok_exit),
        ("exit reason == SL (pessimistic fill)", reason == "SL"),
        (f"P&L in instrument scale (not x100)", bool(plausible)),
        ("real logs/ untouched", (not gold_logs.exists())
         or "SMOKETEST" not in gold_logs.read_text()),
        ("no ENTRY (real order) logged",
         not any(t.get("event") == "ENTRY" for t in read_jsonl(logs / "trades.jsonl"))),
        ("open position cleared after exit", (json.loads((logs / "paper_account.json").read_text())
                                              .get("position") is None)),
    ]
    print("\n--- verdict ---")
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    passed = all(o for _, o in checks)

    if args.keep:
        print(f"\ntemp dir kept: {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\nALL PASS" if passed else "\nSOME CHECKS FAILED")
    sys.stdout.flush()
    os._exit(0 if passed else 1)   # daemon engine thread + RPyC server are non-joinable


if __name__ == "__main__":
    raise SystemExit(main())
