#!/usr/bin/env python3
"""Intraday/session family screen (BTC hypothesis D) — screening only.

Why this exists
---------------
Phase 1 (M5 RSI pullback) and Phase 1c (H1 Donchian) both failed their gates on
real XM bars. `docs/btc_spread_edge_analysis_2026-10-06.md` §6.5 sets the rule
for what happens next:

    new families are screened on proxy/other-instrument bars BEFORE they
    consume an untouched XM pull, and the screen result is recorded as a
    hypothesis — never as a selection.

This is that screen. It covers three **intraday, session-anchored** families —
a mechanism neither failed shape used: a level defined by the UTC clock, a
fixed ATR stop, and a hard time-flat before the daily rollover. No RSI, no
EMA200 pullback entry, no rolling Donchian channel, no take-profit, no
breakeven ratchet, no trailing stop, and nothing held overnight (so the large
negative XM swap on BTC is not paid).

Families
--------
``orb``       today's European opening range. Range = high/low of the three H1
              bars opening 07:00/08:00/09:00 UTC; entry on the first bar
              opening 10:00..15:00 that leaves it.
``momentum``  the 07:00 UTC impulse. Direction = sign(close-open) of the 07:00
              bar; entry at the close of the 08:00 bar (one bar of latency).
``pdr``       prior-day range. Entry on the first bar opening 00:00..15:00 that
              leaves the previous UTC day's high/low.

Fill convention (``--entry-mode``) is not cosmetic — it decides this family.
``close`` waits for the bar to CLOSE outside the level, which is what the
current engine can do with no new plumbing. ``stop`` rests an order at the level
and fills there (a gap-through fills at the open), which is how an opening range
is actually traded:

    close fill, orb, 6 cells:   PF 0.88-0.89, every cell loses money net
    stop fill,  orb, 6 cells:   EMA200 cells net +$409..+$487, PF 1.11-1.14

The pre-registered hypothesis (`docs/btc_hypothesis_orb_h1_2026-10-31.md`) uses
``stop``, so phase 2 has to implement a stop-entry path. A bar that spans both
levels takes the side of its body; a doji bar is skipped.

Shared by all three (the pre-registered geometry):

    stop    : entry -/+ k x ATR(14), fixed for the life of the trade
    exit    : the stop, or the close of the 19:00 UTC bar (20:00 wall clock)
    filter  : optional close > EMA(200) for longs / < for shorts
    one     : at most one entry per UTC day, first trigger wins
    skip    : no entries on Saturday UTC (broker maintenance lands inside the
              range/entry window in one of the two server-DST states)

Cost model
----------
``--spread-bp`` (default the measured XM Standard spread, 5.486 bp of price) is
charged as one round-trip per trade, so bars from a different price regime are
charged this instrument's real cost. ``--spread-bp 0`` prints the gross edge.
If the CSV carries a ``spread`` column (an XM pull does), ``--cost file``
charges ``spread_points x point`` instead (``--point``, default 0.01).

Output: per-family, per-combination gross R, cost R, net R, net PF and net $ at
0.01 lots, plus era buckets (bucketed by entry date, so warm-up and
open-position artefacts cannot move a bucket).

THIS IS NOT THE ENGINE AND NOT EVIDENCE
---------------------------------------
* Proxy bars are exchange spot klines (see
  `docs/btc_spread_edge_analysis_2026-10-06.md` §8 for the sources); XM CFD
  bars differ. Nothing here is an XM result and nothing here may be quoted as
  one. The gate reads XM bars only.
* None of these families is implemented in the engine. A family that screens
  well still has to be added to `btc/strategy_btc.py` and
  `research/strategy_sweep.py` with the usual live/replay parity proof before
  any XM run.
* A good screen justifies a pre-registration. It never selects a parameter:
  selection happens on TRAIN bars of an untouched pull, and the winner is
  frozen before the single cold-OOS read.

Usage
-----
    python3 btc/session_screen.py --csv /tmp/proxy/btc_1h.csv --eras --detail
    python3 btc/session_screen.py --csv /tmp/proxy/btc_1h.csv --family orb \
            --entry-mode stop --eras
    python3 btc/session_screen.py --csv data/BTCUSD_H1.csv --family orb --cost file
    python3 btc/session_screen.py --self-test        # offline checks, no data
"""
from __future__ import annotations

import argparse
import csv
import math
from datetime import datetime, timedelta

# Pre-registered grid: 3 stop multiples x 2 trend-filter states = 6 cells.
STOP_MULTS = (1.0, 1.5, 2.0)
TREND_FILTERS = ("off", "ema200")
FAMILIES = ("orb", "momentum", "pdr")

RANGE_HOURS = (7, 8, 9)          # opening range, bar open-times, UTC
ENTRY_HOURS = range(10, 16)      # orb candidate bars, open-times 10:00..15:00
MOMENTUM_SIGNAL_HOUR = 7         # body direction of the 07:00 bar
MOMENTUM_ENTRY_HOUR = 8          # fill at the close of the 08:00 bar
PDR_ENTRY_HOURS = range(0, 16)   # pdr candidate bars, open-times 00:00..15:00
FLAT_HOUR = 19                   # exit at the close of the 19:00 bar = 20:00 UTC
SATURDAY = 5
DEFAULT_SPREAD_BP = 5.486        # measured XM Standard BTCUSD, 2026-10-03
ERAS = (("2017-2018", "2017-01-01", "2019-01-01"),
        ("2019-2020", "2019-01-01", "2021-01-01"),
        ("2021-2022", "2021-01-01", "2023-01-01"),
        ("2023-2024", "2023-01-01", "2025-01-01"),
        ("2025", "2025-01-01", "2026-01-01"))


# --------------------------------------------------------------------------- #
# loading (stdlib only: this runs on the box next to the books)
# --------------------------------------------------------------------------- #
class Bar:
    __slots__ = ("t", "o", "h", "l", "c", "spread")

    def __init__(self, t, o, h, l, c, spread=None):
        self.t, self.o, self.h, self.l, self.c, self.spread = t, o, h, l, c, spread

    def __repr__(self):                                   # pragma: no cover
        return f"Bar({self.t}, {self.o}, {self.h}, {self.l}, {self.c})"


def parse_time(text: str) -> datetime:
    """Naive-UTC datetime from the formats this repo's bar files use."""
    s = str(text).strip().strip('"')
    if not s:
        raise ValueError("empty time")
    if s.isdigit():                        # epoch seconds or milliseconds
        v = int(s)
        if v > 10 ** 12:
            v //= 1000
        return datetime.utcfromtimestamp(v)
    s = s.replace("T", " ").replace("Z", "")
    s = s.split("+")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
                "%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognised time {text!r}")


def load_csv(path: str) -> tuple[list[Bar], str]:
    """Read OHLC(V[,spread]) bars. Returns (bars, cost_basis_note).

    Accepts this repo's `time,open,high,low,close,...` format and the Binance
    kline dumps used by the proxy screen (`Open Time,Open,High,Low,Close,...`).
    """
    bars: list[Bar] = []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise SystemExit(f"{path}: empty file")
        cols = {name.strip().lstrip("\ufeff").lower(): i
                for i, name in enumerate(header)}
        def col(*names):
            for n in names:
                if n in cols:
                    return cols[n]
            return None
        i_time = col("time", "open time", "date", "datetime")
        i_o, i_h, i_l, i_c = col("open"), col("high"), col("low"), col("close")
        if None in (i_time, i_o, i_h, i_l, i_c):
            raise SystemExit(f"{path}: needs time/open/high/low/close columns; "
                             f"got {header}")
        i_s = col("spread")
        for row in reader:
            if not row or not row[i_time].strip():
                continue
            spread = None
            if i_s is not None and i_s < len(row) and row[i_s].strip():
                try:
                    spread = float(row[i_s])
                except ValueError:
                    spread = None
            bars.append(Bar(parse_time(row[i_time]),
                            float(row[i_o]), float(row[i_h]),
                            float(row[i_l]), float(row[i_c]), spread))
    if not bars:
        raise SystemExit(f"{path}: no bars")
    return bars, ("spread column" if i_s is not None else "no spread column")


# --------------------------------------------------------------------------- #
# indicators (pandas-equivalent definitions, no pandas)
# --------------------------------------------------------------------------- #
def atr_series(bars: list[Bar], period: int = 14) -> list[float | None]:
    """Simple rolling mean of true range — same definition as strategy.py."""
    out: list[float | None] = [None] * len(bars)
    trs: list[float] = []
    for i, b in enumerate(bars):
        if i == 0:
            tr = b.h - b.l
        else:
            pc = bars[i - 1].c
            tr = max(b.h - b.l, abs(b.h - pc), abs(b.l - pc))
        trs.append(tr)
        if i + 1 >= period:
            out[i] = sum(trs[i + 1 - period:i + 1]) / period
    return out


def ema_series(bars: list[Bar], span: int = 200) -> list[float | None]:
    """EMA seeded on the first close — pandas ewm(span, adjust=False)."""
    alpha = 2.0 / (span + 1.0)
    out: list[float | None] = []
    prev = None
    for b in bars:
        prev = b.c if prev is None else alpha * b.c + (1.0 - alpha) * prev
        out.append(prev)
    return out


# --------------------------------------------------------------------------- #
# the rules
# --------------------------------------------------------------------------- #
def index_by_day(bars: list[Bar]) -> dict:
    """{date: {hour: bar_index}} for the UTC days in the file."""
    days: dict = {}
    for i, b in enumerate(bars):
        days.setdefault(b.t.date(), {}).setdefault(b.t.hour, i)
    return days


def _break_side(close: float, hi: float, lo: float) -> int:
    if close > hi:
        return 1
    if close < lo:
        return -1
    return 0


def _entry(bar: Bar, hi: float, lo: float, entry_mode: str):
    """(side, fill_price) for one candidate bar, or None.

    "stop" is the fairer ORB implementation: a resting order at the range
    boundary fills at the level instead of waiting for the bar close, so the
    screen cannot dismiss the family by choosing a late fill on purpose.
    """
    if entry_mode == "close":
        side = _break_side(bar.c, hi, lo)
        return (side, None) if side else None
    up, down = bar.h >= hi, bar.l <= lo
    if up and down:                       # bar spans both: body decides, doji skips
        side = 1 if bar.c > bar.o else (-1 if bar.c < bar.o else 0)
        return (side, hi if side == 1 else lo) if side else None
    if up:
        return (1, max(bar.o, hi))        # gap-through fills at the open
    if down:
        return (-1, min(bar.o, lo))
    return None


def candidates_for(family: str, bars: list[Bar], days: dict, day,
                   ordered_days: list, entry_mode: str = "close") -> list[tuple]:
    """[(bar_index, side, entry_price_or_None)] candidates, in time order.

    entry_mode "close": the bar CLOSES outside the level, fill at that close
    (the engine's existing closed-bar convention).
    entry_mode "stop":  the bar TRADES through the level, fill at the level
    (a resting stop order). If a bar spans both sides, the bar's body picks
    the side; a doji bar is skipped.
    """
    hours = days[day]
    out: list[tuple] = []

    if family == "orb":
        if not all(h in hours for h in RANGE_HOURS):
            return out
        hi = max(bars[hours[h]].h for h in RANGE_HOURS)
        lo = min(bars[hours[h]].l for h in RANGE_HOURS)
        if not hi > lo:
            return out
        for h in ENTRY_HOURS:
            i = hours.get(h)
            if i is None:
                continue
            cand = _entry(bars[i], hi, lo, entry_mode)
            if cand:
                out.append((i, cand[0], cand[1]))

    elif family == "momentum":
        i_sig, i_entry = hours.get(MOMENTUM_SIGNAL_HOUR), hours.get(MOMENTUM_ENTRY_HOUR)
        if i_sig is not None and i_entry is not None:
            b = bars[i_sig]
            side = 1 if b.c > b.o else (-1 if b.c < b.o else 0)
            if side:
                out.append((i_entry, side, None))

    elif family == "pdr":
        pos = ordered_days.index(day)
        if pos == 0:
            return out
        prev = days[ordered_days[pos - 1]]
        if not prev:
            return out
        hi = max(bars[i].h for i in prev.values())
        lo = min(bars[i].l for i in prev.values())
        if not hi > lo:
            return out
        for h in PDR_ENTRY_HOURS:
            i = hours.get(h)
            if i is None:
                continue
            cand = _entry(bars[i], hi, lo, entry_mode)
            if cand:
                out.append((i, cand[0], cand[1]))
    else:
        raise SystemExit(f"unknown family {family!r}; choose from {', '.join(FAMILIES)}")
    return out


def trades_for(bars: list[Bar], days: dict, atr: list, ema: list,
               stop_mult: float, trend_filter: str, warmup: int,
               spread_bp: float = DEFAULT_SPREAD_BP, cost: str = "bp",
               point: float = 0.01, contract: float = 1.0, lot: float = 0.01,
               family: str = "orb", entry_mode: str = "close") -> list[dict]:
    """All trades of one pre-registered combination, in chronological order."""
    trades: list[dict] = []
    ordered_days = sorted(days)
    for day in ordered_days:
        if day.weekday() == SATURDAY:
            continue                                   # broker maintenance
        for i, side, fill in candidates_for(family, bars, days, day,
                                            ordered_days, entry_mode):
            if i < warmup:
                continue
            b = bars[i]
            a = atr[i]
            if not a or a <= 0:
                continue
            if trend_filter == "ema200":
                e = ema[i]
                if e is None or (side == 1 and not b.c > e) \
                        or (side == -1 and not b.c < e):
                    continue
            entry = fill if fill is not None else b.c
            sl_dist = stop_mult * a
            if sl_dist <= 0:
                continue
            stop = entry - side * sl_dist
            if cost == "file":
                if b.spread is None:
                    raise SystemExit("--cost file needs a spread column")
                cost_px = float(b.spread) * point
            else:
                cost_px = abs(entry) * spread_bp / 10000.0
            exit_px, exit_time, reason = _walk_exit(bars, i, side, stop, day)
            gross_px = (exit_px - entry) * side
            net_px = gross_px - cost_px
            trades.append({
                "time": b.t, "side": side, "entry": entry, "exit": exit_px,
                "exit_time": exit_time, "reason": reason,
                "sl_dist": sl_dist, "gross_R": gross_px / sl_dist,
                "cost_R": cost_px / sl_dist, "net_R": net_px / sl_dist,
                "net_usd": net_px * contract * lot,
                "hold_h": (exit_time - b.t).total_seconds() / 3600.0,
            })
            break                    # one entry per UTC day, first trigger wins
    return trades


def _walk_exit(bars: list[Bar], i: int, side: int, stop: float, day) -> tuple:
    """Stop, or the close of the 19:00 UTC bar — never into another day."""
    for j in range(i + 1, len(bars)):
        b = bars[j]
        if b.t.date() != day:
            prev = bars[j - 1]
            return prev.c, prev.t, "time"        # no 19:00 bar: last of the day
        if side == 1 and b.l <= stop:
            return (b.o if b.o <= stop else stop), b.t, "stop"
        if side == -1 and b.h >= stop:
            return (b.o if b.o >= stop else stop), b.t, "stop"
        if b.t.hour >= FLAT_HOUR:
            return b.c, b.t, "time"
    b = bars[-1]
    return b.c, b.t, "time"                      # ran out of file


# --------------------------------------------------------------------------- #
# statistics
# --------------------------------------------------------------------------- #
def summarise(trades: list[dict]) -> dict:
    n = len(trades)
    if not n:
        return {"n": 0, "gross_R": 0.0, "cost_R": 0.0, "net_R": 0.0,
                "pf": 0.0, "net_usd": 0.0, "win": 0.0, "stops": 0,
                "times": 0, "hold_h": 0.0}
    gross = sum(t["gross_R"] for t in trades) / n
    cost = sum(t["cost_R"] for t in trades) / n
    net = sum(t["net_R"] for t in trades) / n
    wins = sum(t["net_usd"] for t in trades if t["net_usd"] > 0)
    loss = -sum(t["net_usd"] for t in trades if t["net_usd"] < 0)
    pf = (wins / loss) if loss > 0 else (float("inf") if wins > 0 else 0.0)
    return {"n": n, "gross_R": gross, "cost_R": cost, "net_R": net,
            "pf": pf, "net_usd": sum(t["net_usd"] for t in trades),
            "win": 100.0 * sum(1 for t in trades if t["net_usd"] > 0) / n,
            "stops": sum(1 for t in trades if t["reason"] == "stop"),
            "times": sum(1 for t in trades if t["reason"] == "time"),
            "hold_h": sum(t["hold_h"] for t in trades) / n}


def era_rows(trades: list[dict]) -> list[tuple]:
    rows = []
    for label, start, end in ERAS:
        lo = datetime.strptime(start, "%Y-%m-%d")
        hi = datetime.strptime(end, "%Y-%m-%d")      # half-open, like §3.2
        sub = [t for t in trades if lo <= t["time"] < hi]
        rows.append((label, summarise(sub)))
    return rows


def fmt(summary: dict) -> str:
    if not summary["n"]:
        return f"{'--':>5} {'--':>8} {'--':>8} {'--':>8} {'--':>6} {'--':>9}"
    pf = "inf" if math.isinf(summary["pf"]) else f"{summary['pf']:.2f}"
    return (f"{summary['n']:>5} {summary['gross_R']:>+8.3f} "
            f"{summary['cost_R']:>8.3f} {summary['net_R']:>+8.3f} "
            f"{pf:>6} {summary['net_usd']:>+9.2f}")


HEADER = (f"{'n':>5} {'grossR':>8} {'costR':>8} {'netR':>8} {'PF':>6} "
          f"{'net$':>9}")

RULE_TEXT = {
    "orb": "range 07-10 UTC, entry 10-16 UTC outside it",
    "momentum": "07:00 bar body sets the side, entry at the 08:00 close",
    "pdr": "prior UTC day's high/low, entry 00-16 UTC outside it",
}


# --------------------------------------------------------------------------- #
# entry points
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", help="bar file (time,open,high,low,close[,spread])")
    ap.add_argument("--family", choices=FAMILIES + ("all",), default="all")
    ap.add_argument("--cost", choices=("bp", "file"), default="bp",
                    help="charge a relative spread (bp) or the CSV's spread column")
    ap.add_argument("--spread-bp", type=float, default=DEFAULT_SPREAD_BP,
                    help=f"round-trip cost in basis points of price "
                         f"(default {DEFAULT_SPREAD_BP}, the measured XM Standard)")
    ap.add_argument("--point", type=float, default=0.01,
                    help="price per spread point for --cost file (BTCUSD: 0.01)")
    ap.add_argument("--warmup", type=int, default=1000,
                    help="bars of history skipped before the first signal")
    ap.add_argument("--entry-mode", choices=("close", "stop"), default="close",
                    help="fill on the bar close outside the level (engine "
                         "convention) or at the level itself (resting order)")
    ap.add_argument("--eras", action="store_true", help="era buckets for each cell")
    ap.add_argument("--detail", action="store_true",
                    help="exit mix / hold time / win rate per cell")
    ap.add_argument("--self-test", action="store_true",
                    help="run the offline checks (no data needed)")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.csv:
        ap.error("--csv is required (or use --self-test)")

    bars, note = load_csv(args.csv)
    days = index_by_day(bars)
    atr = atr_series(bars)
    ema = ema_series(bars)
    span_d = (bars[-1].t - bars[0].t).total_seconds() / 86400.0
    print("=" * 78)
    print("INTRADAY / SESSION FAMILY SCREEN — diagnostic, NOT evidence, NOT a selection")
    print("=" * 78)
    print(f"file     : {args.csv}")
    print(f"bars     : {len(bars)}  {bars[0].t} .. {bars[-1].t} ({span_d:.0f} days)")
    print("cost     : " + (f"file spread column x {args.point:g} px"
                           if args.cost == "file"
                           else f"relative {args.spread_bp:g} bp of price"))
    print(f"data     : {note}; warmup {args.warmup} bars")
    print("shared   : stop k x ATR(14), flat at the 19:00 bar close, no TP/BE, "
          "one entry/day, Saturday off")
    print(f"fill     : {args.entry_mode} " + (
        "(bar close outside the level)" if args.entry_mode == "close"
        else "(at the level: a resting stop order)"))
    print()
    families = FAMILIES if args.family == "all" else (args.family,)
    for family in families:
        print(f"--- family {family!r}: {RULE_TEXT[family]} ---")
        print(f"{'stop':>5} {'filter':>7}  " + HEADER)
        for k in STOP_MULTS:
            for filt in TREND_FILTERS:
                trades = trades_for(bars, days, atr, ema, k, filt, args.warmup,
                                    args.spread_bp, args.cost, args.point,
                                    family=family, entry_mode=args.entry_mode)
                s = summarise(trades)
                print(f"{k:>5.1f} {filt:>7}  " + fmt(s))
                if args.detail and s["n"]:
                    print(f"        stops {s['stops']} / time {s['times']} · "
                          f"win {s['win']:.1f}% · avg hold {s['hold_h']:.1f}h")
                if args.eras and s["n"]:
                    for label, e in era_rows(trades):
                        print(f"        {label:<10} " + fmt(e))
        print()
    print("grossR = mean R with cost at zero; costR = mean spread/stops; "
          "netR = grossR - costR.")
    print("A family only deserves an untouched XM pull when grossR > costR on "
          "the eras that matter.")
    print("Binance proxy klines are NOT XM evidence (docs/btc_spread_edge_"
          "analysis_2026-10-06.md §5).")
    return 0


# --------------------------------------------------------------------------- #
# offline self-test
# --------------------------------------------------------------------------- #
def _synth_bars(day, bars: list[tuple]) -> list[Bar]:
    return [Bar(day + timedelta(hours=h), o, hi, lo, c) for h, o, hi, lo, c in bars]


def self_test() -> int:
    day = datetime(2026, 3, 3)                       # a Tuesday
    # 07/08/09 build a range of 100..110; 10:00 closes at 111 (long breakout).
    # The stop is 1.0 x ATR below entry; a later bar trades through it.
    bars = _synth_bars(day, [
        (7, 102, 104, 100, 103),      # range low 100
        (8, 103, 108, 101, 107),
        (9, 107, 110, 105, 109),      # range high 110
        (10, 109, 112, 108, 111),     # breakout close 111 -> long at 111
        (11, 111, 112, 95, 96),       # trades through the stop
        (12, 96, 97, 95, 96), (13, 96, 97, 95, 96), (14, 96, 97, 95, 96),
        (15, 96, 97, 95, 96), (16, 96, 97, 95, 96), (17, 96, 97, 95, 96),
        (18, 96, 97, 95, 96), (19, 96, 97, 95, 96), (20, 96, 97, 95, 96),
    ])
    days = index_by_day(bars)
    atr = atr_series(bars, period=3)      # 3-bar ATR: the synthetic day is short
    ema = ema_series(bars)
    trades = trades_for(bars, days, atr, ema, 1.0, "off", warmup=0,
                        spread_bp=0.0, family="orb")
    assert len(trades) == 1, trades
    t = trades[0]
    assert t["side"] == 1 and abs(t["entry"] - 111.0) < 1e-9, t
    assert t["reason"] == "stop", t
    assert abs(t["sl_dist"] - atr[3]) < 1e-9, (t["sl_dist"], atr[3])
    assert abs(t["exit"] - (111.0 - atr[3])) < 1e-9, t
    assert t["time"].hour == 10 and t["exit_time"].hour == 11, t

    # No 10:00 breakout -> no trade; and a Saturday is never traded.
    flat = _synth_bars(day, [
        (7, 102, 104, 100, 103), (8, 103, 105, 101, 104), (9, 104, 106, 102, 105),
        (10, 105, 106, 103, 104), (11, 104, 105, 103, 104), (12, 104, 105, 103, 104),
        (13, 104, 105, 103, 104), (14, 104, 105, 103, 104), (15, 104, 105, 103, 104),
        (16, 104, 105, 103, 104), (17, 104, 105, 103, 104), (18, 104, 105, 103, 104),
        (19, 104, 105, 103, 104),
    ])
    assert trades_for(flat, index_by_day(flat), atr_series(flat, 3),
                      ema_series(flat), 1.0, "off", 0, 0.0, family="orb") == []
    sat = datetime(2026, 3, 7)                       # a Saturday
    assert sat.weekday() == SATURDAY
    sb = _synth_bars(sat, [(7, 1, 2, 0.5, 1), (8, 1, 2, 0.5, 1), (9, 1, 2, 0.5, 1),
                           (10, 1, 3, 1, 2.5), (11, 2, 3, 2, 2.9),
                           (19, 2, 3, 2, 2.9)])
    for fam in FAMILIES:
        assert trades_for(sb, index_by_day(sb), atr_series(sb, 3), ema_series(sb),
                          1.0, "off", 0, 0.0, family=fam) == [], fam

    # Time exit: no stop hit -> flat at the 19:00 bar's close, never later.
    tt = _synth_bars(day, [
        (7, 100, 101, 99, 100), (8, 100, 101, 99, 100), (9, 100, 101, 99, 100),
        (10, 100, 102, 100, 101.5),          # break of 101
        (11, 101, 102, 101, 101.5),
        (19, 101, 102, 101, 101.5),          # flat here
        (20, 101, 200, 101, 199),            # must never be used
    ])
    t2 = trades_for(tt, index_by_day(tt), atr_series(tt, 3), ema_series(tt),
                    3.0, "off", 0, 0.0, family="orb")
    assert len(t2) == 1 and t2[0]["reason"] == "time", t2
    assert t2[0]["exit_time"].hour == 19 and abs(t2[0]["exit"] - 101.5) < 1e-9, t2

    # Cost arithmetic: netR = grossR - costR.
    for x in trades_for(bars, days, atr, ema, 1.0, "off", 0, 5.486, family="orb"):
        assert abs(x["net_R"] - (x["gross_R"] - x["cost_R"])) < 1e-12
        assert abs(x["cost_R"] - (111.0 * 5.486 / 10000.0) / x["sl_dist"]) < 1e-12, x

    # momentum: side comes from the 07:00 body, fill at the 08:00 close.
    mo = _synth_bars(day, [
        (5, 99, 100, 98, 99), (6, 99, 101, 99, 100),   # 3-bar ATR needs history
        (7, 100, 103, 99, 102),              # bullish body -> long
        (8, 102, 105, 101, 104),             # fill at 104
        (9, 104, 106, 103, 105),
        (10, 105, 106, 104, 105), (11, 105, 106, 104, 105),
        (12, 105, 106, 104, 105), (13, 105, 106, 104, 105),
        (14, 105, 106, 104, 105), (15, 105, 106, 104, 105),
        (16, 105, 106, 104, 105), (17, 105, 106, 104, 105),
        (18, 105, 106, 104, 105), (19, 105, 106, 104, 105),
    ])
    tm = trades_for(mo, index_by_day(mo), atr_series(mo, 3), ema_series(mo),
                    3.0, "off", 0, 0.0, family="momentum")
    assert len(tm) == 1 and tm[0]["side"] == 1 and abs(tm[0]["entry"] - 104.0) < 1e-9, tm

    # pdr: prior day's high/low; a close above it on the next day is a long.
    d1, d2 = datetime(2026, 3, 3), datetime(2026, 3, 4)
    two = _synth_bars(d1, [(h, 100, 105, 95, 100) for h in range(0, 20)]) + \
          _synth_bars(d2, [(h, 100, 107, 99, 106) for h in range(0, 20)])
    tp = trades_for(two, index_by_day(two), atr_series(two, 3), ema_series(two),
                    3.0, "off", 0, 0.0, family="pdr")
    assert len(tp) == 1 and tp[0]["side"] == 1, tp
    assert tp[0]["time"].date() == d2.date(), tp

    print("session_screen self-test OK — orb range/entry, momentum side, pdr "
          "prior day, stop, time-flat, Saturday, one-per-day, cost arithmetic")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
