#!/usr/bin/env python3
"""Parity + equivalence tests for the Phase-1c donchian strategy.

What is proven here (all on synthetic bars - plumbing evidence, not edge):

  1. REPLAY == PROTOTYPE: research/strategy_sweep.py family="donchian"
     reproduces btc/breakout_screen.py's (v2, engine-aligned) backtest
     trade-for-trade at zero cost (sides, exit bars, R and PnL), with and
     without the time stop and with the EMA trend filter on or off.
  2. LIVE == REPLAY: btc/strategy_btc.DonchianBreakoutStrategy.check_signal
     agrees with replay signal_at_donchian bar-for-bar (zero mismatches),
     including entry-blackout suppression, the EMA200 trend filter and the
     INDICATOR_FETCH_MARGIN slice (poisoned-margin check).
  3. EXITS == REPLAY: check_exit (CHANNEL / TIME) picks the same exit bar,
     price and reason the replay produced for every non-SL trade, and stays
     silent one bar early.
  4. ENGINE WIRING: run.new_strategy() honours BTC_STRATEGY (scalp default,
     donchian opt-in, LIVE refused); PaperAccount supports tp_dist=0 (no TP)
     and the strategy BE override - all in a temp dir, real logs untouched.

Run under the BTC instance:
    mt5env/bin/python btc/tool.py btc/strategy_btc_test.py
or in the sandbox venv:  /tmp/v1/bin/python btc/strategy_btc_test.py
Exit code 0 = all checks pass.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import _instance  # noqa: E402

config = sys.modules.get("config")
expected = (HERE / "config.py").resolve()
if config is None or Path(getattr(config, "__file__", "")).resolve() != expected:
    config = _instance.activate(str(HERE))
_instance.add_engine_path(str(ROOT))

import breakout_screen as bs  # noqa: E402  (btc/ is on sys.path)
import research.strategy_sweep as sweep  # noqa: E402
import strategy as strategy_mod  # noqa: E402
from strategy_btc import DonchianBreakoutStrategy  # noqa: E402

RESULTS = []
WARMUP = 400                       # test window; config is restored afterwards


def check(name: str, ok: bool, detail: str = "") -> bool:
    RESULTS.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


# --------------------------------------------------------------------------
# synthetic H1-ish bars: regime-switching random walk so breakouts happen
# --------------------------------------------------------------------------
def synth(n: int = 2600, seed: int = 20261006) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    drift = np.zeros(n)
    i = 0
    while i < n:                                   # trending regimes both ways
        ln = min(int(rng.integers(80, 240)), n - i)
        drift[i:i + ln] = rng.choice([-3.0e-4, -1.0e-4, 1.0e-4, 3.0e-4])
        i += ln
    ret = rng.normal(0, 0.006, n) + drift
    close = 60000.0 * np.exp(np.cumsum(ret))
    open_ = np.r_[close[0], close[:-1]]
    wick = np.abs(rng.normal(0, 0.0025, n)) * close
    high = np.maximum(open_, close) + wick
    low = np.minimum(open_, close) - wick
    t = pd.date_range("2024-01-01", periods=n, freq="1h")
    return pd.DataFrame({"time": t, "open": open_, "high": high, "low": low,
                         "close": close, "tick_volume": rng.integers(10, 900, n)})


def window_rates(df: pd.DataFrame, loop_bar: int, window: int, margin: int = 0,
                 poison: bool = False):
    """Live-shaped rates: `window` (+margin) rows ending at the forming bar,
    so the last CLOSED bar (index -2) is the replay signal bar loop_bar - 1.
    Returned as list-of-dicts, the exact shape the bridge hands the engine."""
    end = loop_bar + 1
    start = end - window - margin
    assert start >= 0, f"loop bar {loop_bar} too early for window {window}+{margin}"
    w = df.iloc[start:end]
    recs = w.to_dict("records")
    if poison:                       # margin bars must be ignored by the slice
        for r in recs[:margin]:
            for k in ("open", "high", "low", "close"):
                r[k] = float(r[k]) * 1000.0
    return recs


# --------------------------------------------------------------------------
# 1. replay == breakout_screen prototype (zero cost, EMA off)
# --------------------------------------------------------------------------
def test_replay_vs_prototype(df) -> bool:
    ok = True
    for ts, sl, ema in ((None, 2.0, 0), (37, 2.5, 0), (None, 1.5, 0),
                        (None, 2.0, 200), (37, 2.0, 200)):
        W = 300                                     # breakout_screen warmup
        ref = bs.backtest(df, entry_n=30, exit_n=15, sl_mult=sl,
                          trend_ema=ema or None, time_stop=ts,
                          spread_bp=0.0, warmup=W, lot=0.01, contract=1.0)
        p = sweep.Params(family="donchian", don_entry=30, don_exit=15,
                         ema_period=ema, sl_atr_mult=sl, be_trigger_r=None,
                         max_bars_in_trade=ts, session_enabled=False,
                         atr_min=0.0, warmup_bars=W + 2,   # first signal bar = W
                         spread_price=0.0, label="parity")
        rep = sweep.run("", p, df=df)
        same = ref["n"] == rep["trades"] and ref["n"] > 20
        if same:
            for a, b in zip(ref["trades"], rep["trades_list"]):
                if (a["side"] != b["type"] or abs(a["r"] - b["r"]) > 1e-12
                        or abs(a["pnl"] - b["pnl"]) > 1e-9
                        or pd.Timestamp(a["time"]) != pd.Timestamp(b["time"])):
                    same = False
                    break
        ok &= check(f"replay == breakout_screen (ema={ema or 'off'} ts={ts} "
                    f"sl={sl}) n={ref['n']}",
                    same, f"replay n={rep['trades']} net={rep['net']:.2f} "
                          f"vs {ref['net']:.2f}")
    return ok


# --------------------------------------------------------------------------
# 2. live check_signal == replay signal_at_donchian, bar-for-bar
# --------------------------------------------------------------------------
def live_replay_parity(df, blackouts_on: bool) -> tuple[bool, int, int, int]:
    if blackouts_on:
        config.ENTRY_BLACKOUTS_ENABLED = True
        config.ENTRY_BLACKOUT_WINDOWS = [{"name": "test_blackout",
                                          "start": "03:00", "minutes": 240}]
    try:
        p = sweep.Params(family="donchian", don_entry=30, don_exit=15,
                         ema_period=200, sl_atr_mult=2.0, be_trigger_r=None,
                         session_enabled=False, atr_min=0.0, warmup_bars=WARMUP,
                         spread_price=0.0,
                         blackouts=strategy_mod.config_blackouts())
        dind = sweep.compute_donchian(df, p)
        hours = df["time"].dt.hour.to_numpy()
        blocked = sweep.blackout_mask(df["time"], p.blackouts)

        replay_all = {i: sweep.signal_at_donchian(p, dind, hours, i, blocked)
                      for i in range(WARMUP - 1, len(df))}
        baseline = {i: sweep.signal_at_donchian(p, dind, hours, i, None)
                    for i in replay_all} if blackouts_on else {}
        suppressed = [i for i in baseline if baseline[i] and not replay_all[i]]
        firing = [i for i, s in replay_all.items() if s]

        mismatches, margin_bad, checked = [], [], 0
        margin = int(getattr(config, "INDICATOR_FETCH_MARGIN", 0))
        for i in sorted(set(firing) | set(range(WARMUP - 1, len(df), 37))):
            when = df["time"].iloc[i].to_pydatetime()
            # fresh instance per bar so the one-shot guard cannot interfere
            live, sl_d, tp_d = DonchianBreakoutStrategy().check_signal(
                window_rates(df, i, WARMUP), when=when)
            checked += 1
            if live != replay_all[i]:
                mismatches.append((i, str(df["time"].iloc[i]), live, replay_all[i]))
            elif live and (abs(sl_d - dind["atr"][i - 1] * 2.0) > 1e-9 or tp_d != 0.0):
                mismatches.append((i, "sl/tp", sl_d, tp_d))
            if margin > 0 and i >= WARMUP + margin:
                got, _, _ = DonchianBreakoutStrategy().check_signal(
                    window_rates(df, i, WARMUP, margin), when=when)
                got_p, _, _ = DonchianBreakoutStrategy().check_signal(
                    window_rates(df, i, WARMUP, margin, poison=True), when=when)
                if got != replay_all[i] or got_p != replay_all[i]:
                    margin_bad.append((i, got, got_p, replay_all[i]))

        ok = (not mismatches and not margin_bad and len(firing) > 10
              and (not blackouts_on or bool(suppressed)))
        return ok, len(firing), len(suppressed), checked
    finally:
        # the caller restores the true originals; this just ends the override
        config.ENTRY_BLACKOUTS_ENABLED = False


def test_live_replay(df) -> bool:
    saved_window = config.INDICATOR_WINDOW_BARS
    saved_bl = (getattr(config, "ENTRY_BLACKOUTS_ENABLED", False),
                list(getattr(config, "ENTRY_BLACKOUT_WINDOWS", []) or []))
    config.INDICATOR_WINDOW_BARS = WARMUP
    config.DONCHIAN_ENTRY_BARS, config.DONCHIAN_EXIT_BARS = 30, 15
    config.DONCHIAN_TREND_EMA, config.DONCHIAN_TIME_STOP_BARS = 200, 0
    try:
        ok, sig, supp, n = live_replay_parity(df, False)
        r1 = check("live check_signal == replay signal (EMA200, 0 mismatches)",
                   ok, f"{sig} replay signals, {n} bars compared")
        ok2, sig2, supp2, n2 = live_replay_parity(df, True)
        r2 = check("live == replay under entry-blackout windows", ok2,
                   f"{sig2} signals, {supp2} suppressed, {n2} bars compared")
        return r1 and r2
    finally:
        config.INDICATOR_WINDOW_BARS = saved_window
        config.ENTRY_BLACKOUTS_ENABLED, config.ENTRY_BLACKOUT_WINDOWS = saved_bl


# --------------------------------------------------------------------------
# 3. check_exit == replay exits (CHANNEL / TIME)
# --------------------------------------------------------------------------
def test_check_exit(df) -> bool:
    saved_window = config.INDICATOR_WINDOW_BARS
    saved = (config.DONCHIAN_ENTRY_BARS, config.DONCHIAN_EXIT_BARS,
             config.DONCHIAN_TREND_EMA, config.DONCHIAN_TIME_STOP_BARS)
    config.INDICATOR_WINDOW_BARS = WARMUP
    config.DONCHIAN_ENTRY_BARS, config.DONCHIAN_EXIT_BARS = 30, 15
    config.DONCHIAN_TREND_EMA, config.DONCHIAN_TIME_STOP_BARS = 200, 25
    try:
        p = sweep.Params(family="donchian", don_entry=30, don_exit=15,
                         ema_period=200, sl_atr_mult=2.0, be_trigger_r=None,
                         max_bars_in_trade=25, session_enabled=False,
                         atr_min=0.0, warmup_bars=WARMUP, spread_price=0.0)
        rep = sweep.run("", p, df=df)
        times = df["time"].to_numpy()
        strat = DonchianBreakoutStrategy()
        ok, checked = True, 0
        for t in rep["trades_list"]:
            if t["result"] not in ("CHANNEL", "TIME"):
                continue                       # SL exits are tick-resolved live
            exit_bar = int(np.searchsorted(times, t["time"]))
            entry_bar = int(np.searchsorted(times, t["entry_time"]))
            bars_in_trade = exit_bar - entry_bar
            w = window_rates(df, exit_bar + 1, WARMUP)  # closed bar = exit bar
            ex = strat.check_exit(w, {"side": t["type"]}, bars_in_trade)
            exp_px = float(df["close"].iloc[exit_bar])
            checked += 1
            if not (ex is not None and ex["reason"] == t["result"]
                    and abs(ex["price"] - exp_px) < 1e-9):
                ok = False
                print(f"    EXIT MISMATCH bar {exit_bar}: replay={t['result']} "
                      f"live={ex}")
        ok &= check(f"check_exit == replay for every CHANNEL/TIME exit",
                    ok and checked > 5, f"n={checked}")

        # silent one bar before the replay's exit bar
        t = next((t for t in rep["trades_list"]
                  if t["result"] in ("CHANNEL", "TIME")), None)
        if t:
            exit_bar = int(np.searchsorted(times, t["time"]))
            entry_bar = int(np.searchsorted(times, t["entry_time"]))
            if exit_bar - 1 > entry_bar and exit_bar >= WARMUP:
                w = window_rates(df, exit_bar, WARMUP)
                ex = strat.check_exit(w, {"side": t["type"]},
                                      exit_bar - 1 - entry_bar)
                ok &= check("check_exit is silent one bar before the replay exit",
                            ex is None)
        return ok
    finally:
        config.INDICATOR_WINDOW_BARS = saved_window
        (config.DONCHIAN_ENTRY_BARS, config.DONCHIAN_EXIT_BARS,
         config.DONCHIAN_TREND_EMA, config.DONCHIAN_TIME_STOP_BARS) = saved


# --------------------------------------------------------------------------
# 4. engine wiring: factory + paper semantics (real logs untouched)
# --------------------------------------------------------------------------
def test_wiring() -> bool:
    import logger  # noqa: E402
    import paper as paper_mod  # noqa: E402
    run = _instance.import_engine("run", str(ROOT))

    ok = True
    saved = {k: getattr(config, k) for k in ("BTC_STRATEGY", "TRADING_MODE")}
    try:
        config.BTC_STRATEGY = "scalp"
        from strategy import ScalpStrategy
        ok &= check("new_strategy() default (BTC_STRATEGY=scalp) -> ScalpStrategy",
                    isinstance(run.new_strategy(), ScalpStrategy))

        config.BTC_STRATEGY = "donchian"
        s = run.new_strategy()
        ok &= check("BTC_STRATEGY=donchian -> DonchianBreakoutStrategy "
                    "(BAR_CLOSE_EXITS, BE off)",
                    isinstance(s, DonchianBreakoutStrategy)
                    and s.BAR_CLOSE_EXITS is True and s.BE_OVERRIDE is None)

        config.TRADING_MODE = "LIVE"
        try:
            run.new_strategy()
            ok &= check("donchian + LIVE is refused", False)
        except SystemExit:
            ok &= check("donchian + LIVE is refused", True)

        config.TRADING_MODE = saved["TRADING_MODE"]
        config.BTC_STRATEGY = "bogus"
        try:
            run.new_strategy()
            ok &= check("unknown BTC_STRATEGY is refused", False)
        except SystemExit:
            ok &= check("unknown BTC_STRATEGY is refused", True)
    finally:
        for k, v in saved.items():
            setattr(config, k, v)

    # paper semantics in a temp dir (never the real btc/logs)
    logs_before = sorted(str(p) for p in (HERE / "logs").glob("*")) \
        if (HERE / "logs").exists() else []
    tmp = Path(tempfile.mkdtemp(prefix="btc_strat_test_"))
    saved_files = dict(state=paper_mod.STATE_FILE, trades=logger.TRADES_FILE,
                       sys=logger.SYSTEM_FILE, daily=logger.DAILY_STATS_FILE)
    try:
        paper_mod.STATE_FILE = tmp / "paper_account.json"
        logger.TRADES_FILE = tmp / "trades.jsonl"
        logger.SYSTEM_FILE = tmp / "system.jsonl"
        logger.DAILY_STATS_FILE = tmp / "daily_stats.json"

        acc = paper_mod.PaperAccount(be_trigger_r=None)     # donchian: BE off
        pos = acc.open("BUY", 60000.0, 500.0, 0.0)          # tp_dist=0 -> no TP
        ok &= check("paper open with tp_dist=0 stores tp=None (no TP)",
                    pos is not None and pos["tp"] is None and pos["sl"] == 59500.0)
        closed = acc.on_tick(60400.0, 60440.0)              # +0.8R, no BE arm
        ok &= check("no-TP position ignores favourable ticks (BE forced off)",
                    closed is None and acc.position["be_armed"] is False
                    and acc.position["sl"] == 59500.0)
        snap = acc.snapshot_position()[0]
        ok &= check("dashboard snapshot renders no-TP as 0.0", snap["tp"] == 0.0)
        closed = acc.on_tick(59400.0, 59440.0)              # through the SL
        ok &= check("no-TP position still exits on SL",
                    closed is not None and closed["reason"] == "SL")

        acc2 = paper_mod.PaperAccount()                     # config BE (=1.5 BTC)
        acc2.open("BUY", 60000.0, 500.0, 0.0)
        acc2.on_tick(60800.0, 60840.0)                      # +1.6R -> BE arms
        ok &= check("default PaperAccount keeps the config BE ratchet",
                    acc2.position is not None and acc2.position["be_armed"] is True
                    and acc2.position["sl"] == 60000.0)
    finally:
        paper_mod.STATE_FILE = saved_files["state"]
        logger.TRADES_FILE = saved_files["trades"]
        logger.SYSTEM_FILE = saved_files["sys"]
        logger.DAILY_STATS_FILE = saved_files["daily"]

    logs_after = sorted(str(p) for p in (HERE / "logs").glob("*")) \
        if (HERE / "logs").exists() else []
    ok &= check("real btc/logs untouched by the test", logs_before == logs_after)
    return ok


# --------------------------------------------------------------------------
# 4b. engine bar-close state machine (run.maybe_bar_close_exit)
# --------------------------------------------------------------------------
def test_engine_bar_close_helper(df) -> bool:
    """Drive the extracted engine helper bar-by-bar over real replay trades:
    it must stay silent until the replay's exit bar, then return the same
    reason/price, with the right bars-in-trade count."""
    run = _instance.import_engine("run", str(ROOT))
    saved_window = config.INDICATOR_WINDOW_BARS
    saved = (config.DONCHIAN_ENTRY_BARS, config.DONCHIAN_EXIT_BARS,
             config.DONCHIAN_TREND_EMA, config.DONCHIAN_TIME_STOP_BARS)
    config.INDICATOR_WINDOW_BARS = WARMUP
    config.DONCHIAN_ENTRY_BARS, config.DONCHIAN_EXIT_BARS = 30, 15
    config.DONCHIAN_TREND_EMA = 200
    ok = True
    try:
        for ts_stop in (0, 25):                       # CHANNEL-heavy + TIME case
            config.DONCHIAN_TIME_STOP_BARS = ts_stop
            p = sweep.Params(family="donchian", don_entry=30, don_exit=15,
                             ema_period=200, sl_atr_mult=2.0, be_trigger_r=None,
                             max_bars_in_trade=(ts_stop or None),
                             session_enabled=False, atr_min=0.0,
                             warmup_bars=WARMUP, spread_price=0.0)
            rep = sweep.run("", p, df=df)
            times = df["time"].to_numpy()                 # datetime64 (searchsorted)
            ts_sec = (df["time"].astype("datetime64[s]").astype("int64")
                      .to_numpy())                        # epoch s (matches rates)
            strat = DonchianBreakoutStrategy()
            tested = 0
            for t in rep["trades_list"]:
                if t["result"] not in ("CHANNEL", "TIME"):
                    continue
                entry_bar = int(np.searchsorted(times, t["entry_time"]))
                exit_bar = int(np.searchsorted(times, t["time"]))
                if exit_bar - entry_bar < 2 or exit_bar >= len(df) - 1:
                    continue
                tested += 1
                last_ts, bars = int(ts_sec[entry_bar]), 0   # set at SIM_ENTRY
                early, fire = None, None
                for b in range(entry_bar + 1, exit_bar + 1):
                    rates = window_rates(df, b + 1, WARMUP)   # rates[-2] == b
                    ex, last_ts, bars = run.maybe_bar_close_exit(
                        strat, rates, {"side": t["type"]}, last_ts, bars)
                    if ex is not None:
                        if b != exit_bar:
                            early = (b, ex)
                        fire = (b, ex, bars)
                        break
                exp_px = float(df["close"].iloc[exit_bar])
                good = (fire is not None and early is None
                        and fire[0] == exit_bar and bars == exit_bar - entry_bar
                        and fire[1]["reason"] == t["result"]
                        and abs(fire[1]["price"] - exp_px) < 1e-9)
                if not good:
                    ok = False
                    print(f"    helper mismatch: {t['result']} entry={entry_bar} "
                          f"exit={exit_bar} early={early} fire={fire}")
                if tested >= 12:
                    break
            ok &= check(f"maybe_bar_close_exit reproduces replay exits "
                        f"(time-stop={ts_stop or 'off'})", ok and tested > 3,
                        f"{tested} positions driven")
        return ok
    finally:
        config.INDICATOR_WINDOW_BARS = saved_window
        (config.DONCHIAN_ENTRY_BARS, config.DONCHIAN_EXIT_BARS,
         config.DONCHIAN_TREND_EMA, config.DONCHIAN_TIME_STOP_BARS) = saved


# --------------------------------------------------------------------------
# 5. one-shot per closed bar
# --------------------------------------------------------------------------
def test_one_shot(df) -> bool:
    saved_window = config.INDICATOR_WINDOW_BARS
    saved = (config.DONCHIAN_ENTRY_BARS, config.DONCHIAN_EXIT_BARS,
             config.DONCHIAN_TREND_EMA, config.DONCHIAN_TIME_STOP_BARS)
    config.INDICATOR_WINDOW_BARS = WARMUP
    config.DONCHIAN_ENTRY_BARS, config.DONCHIAN_EXIT_BARS = 30, 15
    config.DONCHIAN_TREND_EMA, config.DONCHIAN_TIME_STOP_BARS = 200, 0
    try:
        p = sweep.Params(family="donchian", don_entry=30, don_exit=15,
                         ema_period=200, sl_atr_mult=2.0, be_trigger_r=None,
                         session_enabled=False, atr_min=0.0,
                         warmup_bars=WARMUP, spread_price=0.0)
        dind = sweep.compute_donchian(df, p)
        hours = df["time"].dt.hour.to_numpy()
        fired = next((i for i in range(WARMUP - 1, len(df))
                      if sweep.signal_at_donchian(p, dind, hours, i, None)), None)
        if fired is None:
            return check("one-shot per closed bar", False, "no signal on fixture")
        strat = DonchianBreakoutStrategy()
        w = window_rates(df, fired, WARMUP)
        when = df["time"].iloc[fired].to_pydatetime()
        s1, _, tp1 = strat.check_signal(w, when=when)
        s2, _, _ = strat.check_signal(w, when=when)
        return check("signal fires once per closed bar (duplicate suppressed)",
                     s1 in ("BUY", "SELL") and tp1 == 0.0 and s2 is None
                     and strat.last_skip_reason == "duplicate_bar")
    finally:
        config.INDICATOR_WINDOW_BARS = saved_window
        (config.DONCHIAN_ENTRY_BARS, config.DONCHIAN_EXIT_BARS,
         config.DONCHIAN_TREND_EMA, config.DONCHIAN_TIME_STOP_BARS) = saved


def main() -> int:
    print("=" * 88)
    print("BTC Phase-1c donchian strategy: parity & wiring tests (synthetic bars)")
    print("=" * 88)
    df = synth()
    ok = True
    ok &= test_replay_vs_prototype(df)
    ok &= test_live_replay(df)
    ok &= test_check_exit(df)
    ok &= test_engine_bar_close_helper(df)
    ok &= test_wiring()
    ok &= test_one_shot(df)
    n_pass = sum(1 for _, o in RESULTS if o)
    print("=" * 88)
    print(f"{n_pass}/{len(RESULTS)} checks passed" + ("" if ok else "  -- FAILURES ABOVE"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
