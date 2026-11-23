#!/usr/bin/env python3
"""Phase 2 runner for BTC-ORB-EU-H1 (docs/btc_hypothesis_orb_h1_2026-10-31.md).

Protocol:
1. TRAIN-only screen:
   - Reads bars up to the end of TRAIN (rows 0..14117).
   - Warm-up 1000 bars (rows 0..999), signals eligible from row 1000 onwards.
   - Evaluates the pre-registered 6-cell grid:
     stop_mult in (1.0, 1.5, 2.0) x trend_filter in ('off', 'ema200')
     with --entry-mode stop.
   - Requires n >= 80 and grossR > costR.
   - Ranks by mean net R; freezes the winner to btc/manifests/btc_orb_winner.json.
2. Cold OOS evaluation:
   - Refuses to run unless a frozen winner exists.
   - Refuses to run if manifest results_inspected is already True (one look only).
   - Reads bars up to the end of cold OOS (rows 0..22864).
   - Runs the frozen winner strictly on the cold OOS segment (rows 14318..22864).
   - Evaluates §6 gate:
     1. net > 0 (mean net R > 0 and net USD > 0)
     2. PF >= 1.2
     3. n >= 60
     4. grossR > costR
     5. Half-spread slippage stress: 1-4 still hold at 1.5x spread cost.
   - Updates manifest results_inspected = True.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import btc.session_screen as ss


DEFAULT_MANIFEST = HERE / "manifests" / "btc_orb_eu_h1_2026-10-31.json"
DEFAULT_WINNER_PATH = HERE / "manifests" / "btc_orb_winner.json"
DEFAULT_CSV = ROOT / "data" / "BTCUSD_H1_pre2024.csv"


def check_sha256(path: Path, expected: str) -> None:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        raise SystemExit(
            f"SHA256 mismatch for {path}!\nExpected: {expected}\nActual:   {actual}"
        )


def evaluate_grid_on_bars(
    bars: list[ss.Bar],
    warmup: int,
    cost_mode: str = "file",
    spread_bp: float = ss.DEFAULT_SPREAD_BP,
    point: float = 0.01,
    entry_mode: str = "stop",
    cost_mult: float = 1.0,
) -> list[dict]:
    """Evaluate the 6 pre-registered cells on the provided slice of bars."""
    days = ss.index_by_day(bars)
    atr = ss.atr_series(bars)
    ema = ss.ema_series(bars)

    results = []
    for k in ss.STOP_MULTS:
        for filt in ss.TREND_FILTERS:
            raw_trades = ss.trades_for(
                bars,
                days,
                atr,
                ema,
                k,
                filt,
                warmup=warmup,
                spread_bp=spread_bp * cost_mult,
                cost=cost_mode,
                point=point * cost_mult,
                family="orb",
                entry_mode=entry_mode,
            )
            stats = ss.summarise(raw_trades)
            results.append({
                "stop_mult": k,
                "trend_filter": filt,
                "stats": stats,
                "trades": raw_trades,
            })
    return results


def run_train(
    manifest_path: Path,
    csv_path: Path,
    winner_out: Path,
    cost_mode: str = "file",
    spread_bp: float = ss.DEFAULT_SPREAD_BP,
    point: float = 0.01,
    write_winner: bool = True,
) -> tuple[dict, list[dict]]:
    manifest = json.loads(manifest_path.read_text())
    expected_sha = manifest["raw_sha256"]
    if csv_path.exists():
        check_sha256(csv_path, expected_sha)
    else:
        raise SystemExit(f"CSV not found: {csv_path}")

    train_end_idx = manifest["segments"]["train"]["row_range"][1]  # row 14117 inclusive
    warmup = manifest["protocol"]["warmup_bars"]                   # 1000

    all_bars, _ = ss.load_csv(str(csv_path))
    # Slice up to train_end_idx (index 0..train_end_idx)
    train_bars = all_bars[: train_end_idx + 1]

    print("=" * 78)
    print("PHASE 2: TRAIN SCREEN — BTC-ORB-EU-H1 (6 pre-registered cells)")
    print("=" * 78)
    print(f"Manifest    : {manifest_path}")
    print(f"Data file   : {csv_path}")
    print(f"TRAIN bars  : {len(train_bars)} (rows 0..{train_end_idx})")
    print(f"Warmup bars : {warmup}")
    print(f"Fill mode   : stop (resting orders at range boundary)")
    print(f"Cost mode   : {cost_mode}")
    print()

    results = evaluate_grid_on_bars(
        train_bars,
        warmup=warmup,
        cost_mode=cost_mode,
        spread_bp=spread_bp,
        point=point,
        entry_mode="stop",
    )

    print(f"{'stop':>5} {'filter':>7}  " + ss.HEADER + "  eligible?  rank_score")
    print("-" * 78)

    eligible = []
    for r in results:
        k = r["stop_mult"]
        filt = r["trend_filter"]
        s = r["stats"]
        # Selection criteria: n >= 80 and grossR > costR
        is_eligible = s["n"] >= 80 and s["gross_R"] > s["cost_R"]
        score = s["net_R"]
        tag = "YES" if is_eligible else "NO"
        line = f"{k:>5.1f} {filt:>7}  " + ss.fmt(s) + f"  {tag:>9}  {score:>+10.4f}"
        print(line)
        if is_eligible:
            eligible.append((score, r))

    if not eligible:
        print("\n[RESULT] No cell met TRAIN eligibility (n >= 80 and grossR > costR).")
        print("Candidate fails on TRAIN. Phase 2 must record failure.")
        return {}, results

    eligible.sort(key=lambda x: x[0], reverse=True)
    best_score, winner = eligible[0]
    w_k = winner["stop_mult"]
    w_filt = winner["trend_filter"]
    w_stats = winner["stats"]

    print("\n" + "=" * 78)
    print(f"WINNER SELECTED ON TRAIN: stop={w_k}x ATR(14), filter={w_filt}")
    print(f"Trades: {w_stats['n']}, mean net R: {w_stats['net_R']:+.4f}, "
          f"PF: {w_stats['pf']:.2f}, net USD: ${w_stats['net_usd']:+.2f}")
    print("=" * 78)

    winner_record = {
        "created_at": datetime.utcnow().isoformat() + "Z",
        "manifest": str(manifest_path),
        "hypothesis": manifest["hypothesis"],
        "stop_mult": w_k,
        "trend_filter": w_filt,
        "entry_mode": "stop",
        "train_stats": {
            "n": w_stats["n"],
            "gross_R": w_stats["gross_R"],
            "cost_R": w_stats["cost_R"],
            "net_R": w_stats["net_R"],
            "pf": w_stats["pf"],
            "net_usd": w_stats["net_usd"],
            "win_pct": w_stats["win"],
            "stops": w_stats["stops"],
            "times": w_stats["times"],
        },
    }

    if write_winner:
        winner_out.parent.mkdir(parents=True, exist_ok=True)
        winner_out.write_text(json.dumps(winner_record, indent=2) + "\n")
        print(f"Winner frozen to: {winner_out}")

    return winner_record, results


def run_oos(
    manifest_path: Path,
    csv_path: Path,
    winner_path: Path,
    cost_mode: str = "file",
    spread_bp: float = ss.DEFAULT_SPREAD_BP,
    point: float = 0.01,
) -> dict:
    if not winner_path.exists():
        raise SystemExit(
            f"No frozen winner found at {winner_path}!\n"
            "You MUST run --train and freeze a winner before reading cold OOS."
        )

    manifest = json.loads(manifest_path.read_text())
    if manifest.get("results_inspected") is True:
        raise SystemExit(
            f"ABORT: {manifest_path} has results_inspected=true.\n"
            "Cold OOS has already been inspected. Exactly one look allowed!"
        )

    winner = json.loads(winner_path.read_text())
    w_k = winner["stop_mult"]
    w_filt = winner["trend_filter"]

    expected_sha = manifest["raw_sha256"]
    if csv_path.exists():
        check_sha256(csv_path, expected_sha)
    else:
        raise SystemExit(f"CSV not found: {csv_path}")

    oos_start_idx = manifest["segments"]["cold_oos"]["row_range"][0]  # row 14318
    oos_end_idx = manifest["segments"]["cold_oos"]["row_range"][1]    # row 22864

    all_bars, _ = ss.load_csv(str(csv_path))
    oos_bars = all_bars[: oos_end_idx + 1]

    # Evaluate the frozen winner across history up to oos_end_idx
    days = ss.index_by_day(oos_bars)
    atr = ss.atr_series(oos_bars)
    ema = ss.ema_series(oos_bars)

    # 1. Standard cost evaluation
    all_trades = ss.trades_for(
        oos_bars,
        days,
        atr,
        ema,
        w_k,
        w_filt,
        warmup=manifest["protocol"]["warmup_bars"],
        spread_bp=spread_bp,
        cost=cost_mode,
        point=point,
        family="orb",
        entry_mode="stop",
    )

    oos_first_time = datetime.strptime(
        manifest["segments"]["cold_oos"]["first_bar"], "%Y-%m-%d %H:%M:%S"
    )
    oos_last_time = datetime.strptime(
        manifest["segments"]["cold_oos"]["last_bar"], "%Y-%m-%d %H:%M:%S"
    )

    oos_trades = [
        t for t in all_trades if oos_first_time <= t["time"] <= oos_last_time
    ]
    oos_stats = ss.summarise(oos_trades)

    # 2. Slippage stress: 1.5x spread cost
    stress_trades = ss.trades_for(
        oos_bars,
        days,
        atr,
        ema,
        w_k,
        w_filt,
        warmup=manifest["protocol"]["warmup_bars"],
        spread_bp=spread_bp * 1.5,
        cost=cost_mode,
        point=point * 1.5,
        family="orb",
        entry_mode="stop",
    )
    stress_oos_trades = [
        t for t in stress_trades if oos_first_time <= t["time"] <= oos_last_time
    ]
    stress_stats = ss.summarise(stress_oos_trades)

    print("=" * 78)
    print(f"COLD OOS EVALUATION — {manifest['hypothesis']} (ONE LOOK)")
    print("=" * 78)
    print(f"Winner evaluated : stop={w_k}x ATR(14), filter={w_filt}")
    print(f"Cold OOS window  : {oos_first_time} .. {oos_last_time}")
    print(f"Trades in OOS    : {oos_stats['n']}")
    print()
    print("STANDARD COST METRICS:")
    print(f"  Trades (n)     : {oos_stats['n']}  (gate: n >= 60)")
    print(f"  Profit Factor  : {oos_stats['pf']:.2f}  (gate: PF >= 1.20)")
    print(f"  Mean Net R     : {oos_stats['net_R']:+.4f}  (gate: > 0)")
    print(f"  Net USD        : ${oos_stats['net_usd']:+.2f}  (gate: > 0)")
    print(f"  Gross R        : {oos_stats['gross_R']:+.4f}")
    print(f"  Cost R         : {oos_stats['cost_R']:.4f}  (gate: grossR > costR)")
    print()
    print("1.5x SPREAD STRESS METRICS (Half-spread slippage test):")
    print(f"  Profit Factor  : {stress_stats['pf']:.2f}  (gate: PF >= 1.20)")
    print(f"  Mean Net R     : {stress_stats['net_R']:+.4f}  (gate: > 0)")
    print(f"  Net USD        : ${stress_stats['net_usd']:+.2f}  (gate: > 0)")
    print()

    # Gate verification
    gate_checks = {
        "net_R_positive": oos_stats["net_R"] > 0,
        "net_usd_positive": oos_stats["net_usd"] > 0,
        "pf_gte_1_2": oos_stats["pf"] >= 1.2,
        "n_gte_60": oos_stats["n"] >= 60,
        "gross_beats_cost": oos_stats["gross_R"] > oos_stats["cost_R"],
        "stress_net_positive": stress_stats["net_R"] > 0 and stress_stats["net_usd"] > 0,
        "stress_pf_gte_1_2": stress_stats["pf"] >= 1.2,
    }

    all_passed = all(gate_checks.values())
    print("GATE CHECKS:")
    for name, ok in gate_checks.items():
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")

    print("\n" + "=" * 78)
    if all_passed:
        print(">>> OVERALL GATE: PASS <<<")
    else:
        print(">>> OVERALL GATE: FAIL <<<")
    print("=" * 78)

    # Mark manifest as inspected
    manifest["results_inspected"] = True
    manifest["inspected_at"] = datetime.utcnow().isoformat() + "Z"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"\nManifest {manifest_path} updated: results_inspected=true.")

    return {
        "winner": winner,
        "oos_stats": oos_stats,
        "stress_stats": stress_stats,
        "gate_checks": gate_checks,
        "gate_passed": all_passed,
    }


def self_test() -> int:
    """Offline test using synthetic data and temporary files."""
    print("Running phase2_orb self-test...")
    import tempfile
    from datetime import timedelta

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        manifest_p = tdp / "manifest.json"
        winner_p = tdp / "winner.json"
        csv_p = tdp / "data.csv"

        # Generate 200 days of data (4800 bars)
        lines = ["time,open,high,low,close,spread\n"]
        d0 = datetime(2022, 1, 1, 0, 0, 0)
        for day in range(200):
            for h in range(24):
                t = d0 + timedelta(days=day, hours=h)
                if h in (7, 8, 9):
                    o, hi, lo, cl = 100.0, 105.0, 95.0, 102.0
                elif h == 10:
                    o, hi, lo, cl = 104.0, 120.0, 104.0, 118.0
                elif h in range(11, 20):
                    o, hi, lo, cl = 118.0, 120.0, 115.0, 118.0
                else:
                    o, hi, lo, cl = 100.0, 102.0, 98.0, 100.0
                lines.append(f"{t.strftime('%Y-%m-%d %H:%M:%S')},{o},{hi},{lo},{cl},20.0\n")
        csv_p.write_text("".join(lines))

        sha = hashlib.sha256(csv_p.read_bytes()).hexdigest()

        man = {
            "hypothesis": "BTC-ORB-EU-H1",
            "raw_sha256": sha,
            "protocol": {"warmup_bars": 100},
            "segments": {
                "train": {"row_range": [100, 2500]},
                "embargo": {"row_range": [2501, 2700]},
                "cold_oos": {
                    "row_range": [2701, 4799],
                    "first_bar": (d0 + timedelta(hours=2701)).strftime("%Y-%m-%d %H:%M:%S"),
                    "last_bar": (d0 + timedelta(hours=4799)).strftime("%Y-%m-%d %H:%M:%S"),
                }
            },
            "results_inspected": False
        }
        manifest_p.write_text(json.dumps(man))

        # Test train screen
        w, res = run_train(manifest_p, csv_p, winner_p, cost_mode="bp", spread_bp=1.0)
        assert len(res) == 6, f"expected 6 cells, got {len(res)}"
        assert winner_p.exists(), "winner record was not written"

        # Test cold OOS run
        oos_res = run_oos(manifest_p, csv_p, winner_p, cost_mode="bp", spread_bp=1.0)
        assert "gate_checks" in oos_res
        assert json.loads(manifest_p.read_text())["results_inspected"] is True

        # Second OOS run should abort
        try:
            run_oos(manifest_p, csv_p, winner_p, cost_mode="bp")
            assert False, "second OOS run should have aborted"
        except SystemExit:
            pass

    print("phase2_orb self-test PASSED")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--train", action="store_true", help="run TRAIN-only screen and select winner")
    ap.add_argument("--oos", action="store_true", help="run single cold OOS read (requires frozen winner)")
    ap.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST, help="path to manifest JSON")
    ap.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="path to raw CSV")
    ap.add_argument("--winner", type=Path, default=DEFAULT_WINNER_PATH, help="path to winner output JSON")
    ap.add_argument("--cost", choices=("file", "bp"), default="file", help="cost calculation method")
    ap.add_argument("--spread-bp", type=float, default=ss.DEFAULT_SPREAD_BP, help="spread bp for --cost bp")
    ap.add_argument("--point", type=float, default=0.01, help="point value for spread column")
    ap.add_argument("--self-test", action="store_true", help="run offline self-test")

    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()

    if not args.train and not args.oos:
        ap.error("Must specify either --train or --oos (or --self-test)")

    if args.train:
        run_train(args.manifest, args.csv, args.winner, cost_mode=args.cost,
                  spread_bp=args.spread_bp, point=args.point)

    if args.oos:
        run_oos(args.manifest, args.csv, args.winner, cost_mode=args.cost,
                spread_bp=args.spread_bp, point=args.point)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
