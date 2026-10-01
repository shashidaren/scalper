"""Fake-bridge & historical M1 verification for paper-mode exit fidelity.

Tests `run.poll_paper_position` + `paper.PaperAccount` against the fake-bridge
pattern (HANDOFF §8) and compares coarse 15s snapshot checking vs 1s fast
polling on synthetic intra-window wicks as well as on the overlapping
`data/GOLD_M5.csv` + `data/GOLD_M1.csv` historical window.

Run:  python research/paper_exit_test.py
Exit: 0 = all checks pass, 1 = failure.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import logger  # noqa: E402
import paper as paper_mod  # noqa: E402
import run as run_mod  # noqa: E402
import strategy_sweep as sweep  # noqa: E402


class FakeTick:
    def __init__(self, bid: float, ask: float, time_msc: int):
        self.bid = float(bid)
        self.ask = float(ask)
        self.time_msc = int(time_msc)
        self.time = int(time_msc) // 1000


class FakeBridge:
    """Lightweight in-process fake MT5Bridge (HANDOFF §8 pattern) that streams
    a pre-scripted 1-second tick sequence."""

    def __init__(self, ticks: list[FakeTick]):
        self._ticks = list(ticks)
        self.idx = 0
        self.tick_calls = 0

    def get_live_tick(self, retries: int = 5):
        self.tick_calls += 1
        if not self._ticks:
            return None
        t = self._ticks[min(self.idx, len(self._ticks) - 1)]
        self.idx += 1
        return t


def _run_unit_scenarios(tmp_dir: Path) -> int:
    state_file = tmp_dir / "paper_account.json"
    trades_file = tmp_dir / "trades.jsonl"
    sys_file = tmp_dir / "system.jsonl"
    daily_file = tmp_dir / "daily_stats.json"

    with patch.object(paper_mod, "STATE_FILE", state_file), \
         patch.object(logger, "TRADES_FILE", trades_file), \
         patch.object(logger, "SYSTEM_FILE", sys_file), \
         patch.object(logger, "DAILY_STATS_FILE", daily_file):

        # ------------------------------------------------------------------
        # Scenario 1: Fast SL wick inside a 15s window (reverses before 15s)
        # BUY @ 4000.00, sl_dist=2.00 -> SL=3998.00, TP=4005.00
        # At t=3s, bid dips to 3997.80 (touches SL), then recovers to 4000.20
        # by t=15s.
        #   - Old 15s snapshot check (only sees t=0 and t=15s): MISSES the SL
        #   - New poll_paper_position (1s poll while position open): CATCHES SL
        #     at t=3s (matching backtest.py's bar-low <= SL assumption) and
        #     stops polling immediately once flat.
        # ------------------------------------------------------------------
        ticks_sl_wick = [
            FakeTick(3999.50 - (1.70 if s == 3 else 0.0),
                     3999.95 - (1.70 if s == 3 else 0.0),
                     1_700_000_000_000 + s * 1000)
            for s in range(1, 16)
        ]

        # Old coarse 15s behaviour: only checks t=15s snapshot
        old_acct = paper_mod.PaperAccount()
        old_acct.reset()
        old_acct.open("BUY", 4000.00, sl_dist=2.00, tp_dist=5.00)
        old_close = old_acct.on_tick(ticks_sl_wick[-1].bid, ticks_sl_wick[-1].ask)
        assert old_close is None and old_acct.has_position(), (
            "Expected coarse 15s check to miss intra-window SL wick"
        )

        # New fast-poll behaviour while position is open
        new_acct = paper_mod.PaperAccount()
        new_acct.reset()
        new_acct.open("BUY", 4000.00, sl_dist=2.00, tp_dist=5.00)
        fb_sl = FakeBridge(ticks_sl_wick)
        slept = []
        res_sl = run_mod.poll_paper_position(
            fb_sl, new_acct, total_seconds=15, interval_seconds=1,
            sleep_fn=lambda dt: slept.append(dt),
        )
        assert res_sl is not None and res_sl["reason"] == "SL", f"Expected SL exit, got {res_sl}"
        assert not new_acct.has_position(), "Position must be closed after SL hit"
        assert fb_sl.tick_calls == 3, f"Expected exit on 3rd 1s poll (no extra calls after flat), got {fb_sl.tick_calls}"

        # ------------------------------------------------------------------
        # Scenario 2: Fast +1.5R spike arms BE, then pullback to entry within 15s
        # BUY @ 4000.00, sl_dist=2.00 (BE triggers at +1.5R = 4003.00), TP=4005.00
        # t=4s: bid hits 4003.10 -> arms BE (SL moves to 4000.00)
        # t=9s: bid pulls back to 3999.90 -> triggers BE exit at 4000.00
        # t=15s: bid is back at 4001.00
        # ------------------------------------------------------------------
        ticks_be_wick = []
        for s in range(1, 16):
            if s == 4:
                bid = 4003.10
            elif s == 9:
                bid = 3999.90
            else:
                bid = 4001.00
            ticks_be_wick.append(FakeTick(bid, bid + 0.45, 1_700_000_020_000 + s * 1000))

        be_acct = paper_mod.PaperAccount()
        be_acct.reset()
        be_acct.open("BUY", 4000.00, sl_dist=2.00, tp_dist=5.00)
        fb_be = FakeBridge(ticks_be_wick)
        res_be = run_mod.poll_paper_position(
            fb_be, be_acct, total_seconds=15, interval_seconds=1,
            sleep_fn=lambda _: None,
        )
        assert res_be is not None and res_be["reason"] == "BE", f"Expected BE exit, got {res_be}"
        assert res_be["profit"] == 0.0, f"Expected $0.00 BE profit, got {res_be['profit']}"
        assert fb_be.tick_calls == 9, f"Expected exit on 9th 1s poll, got {fb_be.tick_calls}"

        # ------------------------------------------------------------------
        # Scenario 3: Fast TP wick inside a 15s window
        # SELL @ 4000.00, sl_dist=2.00 (SL=4002.00), tp_dist=5.00 (TP=3995.00)
        # t=6s: ask drops to 3994.90 -> hits TP
        # ------------------------------------------------------------------
        ticks_tp_wick = [
            FakeTick(3998.00, 3994.90 if s == 6 else 3998.45, 1_700_000_040_000 + s * 1000)
            for s in range(1, 16)
        ]
        tp_acct = paper_mod.PaperAccount()
        tp_acct.reset()
        tp_acct.open("SELL", 4000.00, sl_dist=2.00, tp_dist=5.00)
        fb_tp = FakeBridge(ticks_tp_wick)
        res_tp = run_mod.poll_paper_position(
            fb_tp, tp_acct, total_seconds=15, interval_seconds=1,
            sleep_fn=lambda _: None,
        )
        assert res_tp is not None and res_tp["reason"] == "TP", f"Expected TP exit, got {res_tp}"
        assert res_tp["profit"] == 5.00, f"Expected +$5.00 TP profit, got {res_tp['profit']}"
        assert fb_tp.tick_calls == 6, f"Expected exit on 6th 1s poll, got {fb_tp.tick_calls}"

        # ------------------------------------------------------------------
        # Scenario 4: Flat account -> zero bridge tick calls, single 15s sleep
        # ------------------------------------------------------------------
        flat_acct = paper_mod.PaperAccount()
        flat_acct.reset()
        fb_flat = FakeBridge(ticks_sl_wick)
        flat_sleeps = []
        res_flat = run_mod.poll_paper_position(
            fb_flat, flat_acct, total_seconds=15, interval_seconds=1,
            sleep_fn=lambda dt: flat_sleeps.append(dt),
        )
        assert res_flat is None
        assert fb_flat.tick_calls == 0, f"Expected 0 bridge calls while flat, got {fb_flat.tick_calls}"
        assert flat_sleeps == [15], f"Expected single 15s sleep while flat, got {flat_sleeps}"

    print("PASS: fake-bridge unit scenarios (SL wick, BE arm+scratch wick, TP wick, zero-load when flat)")
    return 0


def _compare_m1_vs_m5_resolution() -> int:
    """Compare exit resolution on the overlapping window of GOLD_M5.csv and
    GOLD_M1.csv (2026-08-24 -> 2026-09-11, 4,003 M5 bars / 20,000 M1 bars):
      1) Coarse M5 close-only (300s snapshot, misses intra-bar wicks)
      2) Medium M1 close-only (60s snapshot, misses sub-minute wicks)
      3) Fine M1 OHLC wicks (sub-bar chronological M1 extremes)
      4) Reference backtest.py M5 OHLC resolution
    """
    import numpy as np

    m5_path = Path("data/GOLD_M5.csv")
    m1_path = Path("data/GOLD_M1.csv")
    if not (m5_path.exists() and m1_path.exists()):
        return 0

    m5 = pd.read_csv(m5_path, parse_dates=["time"])
    m1 = pd.read_csv(m1_path, parse_dates=["time"])
    start_idx = int(m5.index[m5["time"] >= m1["time"].min()][0])
    p = sweep.params_from_config(label="M5 OHLC (backtest.py)")
    w = p.warmup_bars
    sub_m5 = m5.iloc[start_idx - (w - 1):].reset_index(drop=True)

    # 1) Standard backtest M5 OHLC
    r_m5 = sweep.run("", p, df=sub_m5)

    # 2) Coarse M5 close-only exit evaluation (signals still use true OHLC/ATR)
    ind = sweep.compute_indicators(sub_m5, p)
    df_close_exits = sub_m5.copy()
    df_close_exits["high"] = df_close_exits["close"]
    df_close_exits["low"] = df_close_exits["close"]
    with patch.object(sweep, "compute_indicators", return_value={
        **ind,
        "high": df_close_exits["high"].to_numpy(float),
        "low": df_close_exits["low"].to_numpy(float),
    }):
        r_m5_close = sweep.run("", sweep.replace(p, label="M5 close-only (300s snap)"), df=df_close_exits)

    # 3) M1 sub-bar replay (close-only 60s snapshots vs M1 OHLC wicks)
    hours = sub_m5["time"].dt.hour.to_numpy()
    times = sub_m5["time"].to_numpy()
    close, atr = ind["close"], ind["atr"]
    spread_col = sub_m5["spread"].to_numpy(float) * 0.01
    m1_times = m1["time"].to_numpy()
    m1_high = m1["high"].to_numpy(float)
    m1_low = m1["low"].to_numpy(float)
    m1_close = m1["close"].to_numpy(float)

    def _replay_m1(use_wicks: bool, label: str) -> dict:
        balance, peak, max_dd = 1000.0, 1000.0, 0.0
        trade = None
        trades = []
        for i in range(w - 1, len(sub_m5)):
            if trade is None:
                sig = sweep.signal_at(p, ind, hours, None, i)
                if sig:
                    si = i - 1
                    entry = close[si]
                    sl_d = atr[si] * p.sl_atr_mult
                    tp_d = atr[si] * p.tp_atr_mult
                    trade = {
                        "type": sig, "entry": entry, "sl_dist": sl_d,
                        "sl": entry - sl_d if sig == "BUY" else entry + sl_d,
                        "tp": entry + tp_d if sig == "BUY" else entry - tp_d,
                        "be_armed": False,
                    }
            if trade is not None:
                t0 = times[i]
                t1 = t0 + np.timedelta64(5, "m")
                j0 = int(np.searchsorted(m1_times, t0, side="left"))
                j1 = int(np.searchsorted(m1_times, t1, side="left"))
                spread = float(spread_col[i])
                side = trade["type"]
                entry, sl_d = trade["entry"], trade["sl_dist"]
                closed = None
                for j in range(j0, j1):
                    hi_j = m1_high[j] if use_wicks else m1_close[j]
                    lo_j = m1_low[j] if use_wicks else m1_close[j]
                    if p.be_trigger_r is not None and not trade["be_armed"] and sl_d > 0:
                        fav = (hi_j - entry) if side == "BUY" else (entry - lo_j)
                        if fav >= p.be_trigger_r * sl_d:
                            trade["sl"] = entry
                            trade["be_armed"] = True
                    sl, tp = trade["sl"], trade["tp"]
                    if side == "BUY":
                        if lo_j <= sl:
                            pnl = (sl - entry) - spread
                            closed = "BE" if (trade["be_armed"] and sl == entry) else "SL"
                            break
                        elif hi_j >= tp:
                            pnl = (tp - entry) - spread
                            closed = "TP"
                            break
                    else:
                        if hi_j >= sl:
                            pnl = (entry - sl) - spread
                            closed = "BE" if (trade["be_armed"] and sl == entry) else "SL"
                            break
                        elif lo_j <= tp:
                            pnl = (entry - tp) - spread
                            closed = "TP"
                            break
                if closed:
                    dollar = pnl * (p.lot_size * sweep.CONTRACT_SIZE)
                    balance += dollar
                    peak = max(peak, balance)
                    max_dd = max(max_dd, peak - balance)
                    trades.append({"result": closed, "pnl": dollar, "r": pnl / sl_d if sl_d else 0.0})
                    trade = None
        total = len(trades)
        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        gp = sum(t["pnl"] for t in wins)
        gl = abs(sum(t["pnl"] for t in losses))
        return {
            "label": label, "trades": total, "net": balance - 1000.0, "max_dd": max_dd,
            "win_rate": 100.0 * len(wins) / total if total else 0.0,
            "pf": (gp / gl) if gl > 0 else 0.0,
            "avg_r": sum(t["r"] for t in trades) / total if total else 0.0,
            "expectancy": (balance - 1000.0) / total if total else 0.0,
            "tp": sum(1 for t in trades if t["result"] == "TP"),
            "be": sum(1 for t in trades if t["result"] == "BE"),
            "sl": sum(1 for t in trades if t["result"] == "SL"),
        }

    r_m1_close = _replay_m1(False, "M1 close-only (60s snap)")
    r_m1_ohlc = _replay_m1(True, "M1 OHLC (sub-bar wicks)")

    print("\n=== Historical Wick Sensitivity on M1/M5 Overlap (2026-08-24 .. 2026-09-11) ===")
    print(sweep.header())
    for row in (r_m5_close, r_m1_close, r_m1_ohlc, r_m5):
        print(sweep.fmt(row))
    return 0


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        rc = _run_unit_scenarios(Path(tmp))
        if rc != 0:
            return rc
    return _compare_m1_vs_m5_resolution()


if __name__ == "__main__":
    raise SystemExit(main())
