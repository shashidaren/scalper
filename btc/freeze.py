#!/usr/bin/env python3
"""Freeze an untouched bar file: hash it, cut it at the inspection boundary,
split TRAIN / embargo / cold OOS, and write a manifest — before any sweep.

Why this exists
---------------
`plans/btc.json` phase 1 exists because both BTC hypotheses were decided on bars
that had already been read. A pre-registration is only worth what its data
protocol is worth, and the protocol has four failure modes a human doing this by
hand gets wrong:

  1. reusing an inspected file (the H1 file's sha256 is published; using it
     again makes the gate worthless);
  2. cutting at the wrong boundary, so a few inspected bars leak into TRAIN or
     OOS;
  3. splitting by a fraction computed after looking at the trades;
  4. writing the hash *after* the sweep, when it proves nothing.

This tool does the four things and refuses to guess:

    python3 btc/freeze.py --csv data/BTCUSD_H1_pre2024.csv --timeframe H1 \\
        --cutoff "2024-06-25 22:00:00" \\
        --out btc/manifests/btc_orb_eu_h1_2026-10-31.json

What it produces (stdout + the committed JSON manifest):

    * sha256 of the raw pull and of the exact row ranges of each segment;
    * the inspected-era cutoff it enforced, and why;
    * TRAIN / embargo / cold-OOS first+last bar timestamps and bar counts;
    * integrity checks (duplicates, non-monotonic time, gaps, missing hours);
    * ``"results_inspected": false`` and the pre-registration it belongs to.

It refuses (exit 2) on: a known inspected sha256, a cutoff later than the
inspected-era start, too few kept bars for the pre-declared minimums, duplicate
or out-of-order timestamps, an existing manifest (a freeze is a one-way door —
``--force`` is an explicit override), or an unreadable file.

It is stdlib-only and imports no `config`, so it can run on the box next to a
live gold book. It never reads or writes engine state.

    python3 btc/freeze.py --self-test      # offline checks, no data needed
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from datetime import datetime

TOOL_VERSION = "1.0"

# Published, inspected XM files (see STATUS.md "Do not" and
# docs/btc_phase1c_result_2026-10-07.md). A new pre-registration must never
# consume any of these.
INSPECTED_SHA256 = {
    "f73054611e9b27a589b55c63f4a9a4f734ac9c423c1f528d1b6c344bc023ab21":
        "data/BTCUSD_H1.csv (2024-06-25 .. 2026-10-07, Phase 1c)",
}
INSPECTED_ERA_START = "2024-06-25 22:00:00"   # the earliest bar of that file
TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240}


def parse_time(text: str) -> datetime:
    s = str(text).strip().strip('"')
    s = s.replace("T", " ").replace("Z", "").split("+")[0].strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognised time {text!r}")


def read_rows(path: str) -> tuple[list[datetime], list[list[str]]]:
    """Return (times, rows) from a bar CSV in the repo's format."""
    times, rows = [], []
    with open(path, newline="") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            raise SystemExit(f"{path}: empty file")
        cols = {name.strip().lstrip("\ufeff").lower(): i
                for i, name in enumerate(header)}
        if "time" not in cols:
            raise SystemExit(f"{path}: no time column; got {header}")
        i_time = cols["time"]
        for row in reader:
            if not row or not row[i_time].strip():
                continue
            times.append(parse_time(row[i_time]))
            rows.append(row)
    if not times:
        raise SystemExit(f"{path}: no bars")
    return times, rows


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def integrity(times: list[datetime], tf_minutes: int) -> dict:
    dup = sum(1 for a, b in zip(times, times[1:]) if a == b)
    back = sum(1 for a, b in zip(times, times[1:]) if b < a)
    gaps = [(b - a).total_seconds() / 60.0 for a, b in zip(times, times[1:])]
    big = sorted((g for g in gaps if g > tf_minutes * 1.5), reverse=True)
    hours = sorted({t.hour for t in times})
    return {"duplicate_timestamps": dup,
            "non_monotonic": back,
            "gaps_over_1.5x_tf": len(big),
            "largest_gaps_minutes": [round(g, 1) for g in big[:5]],
            "utc_hours_present": len(hours),
            "utc_hours_missing": [h for h in range(24) if h not in hours]}


def split(times: list[datetime], cutoff: datetime, train_frac: float,
          embargo: int, warmup: int) -> dict:
    """Row indices for TRAIN / embargo / cold OOS over the pre-cutoff bars."""
    kept = [i for i, t in enumerate(times) if t < cutoff]
    if not kept:
        raise SystemExit("cut: no bars before the cutoff — wrong file or cutoff")
    n = len(kept)
    start = min(warmup - 1, n - 1)                    # warm-up lives in TRAIN
    playable = n - start
    mid = start + int(playable * train_frac)
    mid = max(start + 1, min(mid, n - 1))
    oos_start = mid + embargo
    if oos_start >= n:
        raise SystemExit(f"cut: embargo {embargo} leaves no OOS bars "
                         f"({n} kept, split at {mid})")
    return {
        "kept_rows": n,
        "kept_first_row": kept[0], "kept_last_row": kept[-1],
        "train_rows": (kept[start], kept[mid - 1]),
        "train_bars": mid - start,
        "embargo_rows": (kept[mid], kept[oos_start - 1]) if embargo else None,
        "oos_rows": (kept[oos_start], kept[-1]),
        "oos_bars": n - oos_start,
    }


def freeze(path: str, timeframe: str, cutoff_text: str, train_frac: float,
           embargo: int, warmup: int, min_kept: int, min_train: int,
           min_oos: int, inspection_start_text: str, forbidden: dict,
           hypothesis: str, doc: str) -> tuple[dict, list[str]]:
    """Build the manifest. Returns (manifest, problems). Raises on hard errors."""
    tf_minutes = TF_MINUTES[timeframe]
    cutoff = parse_time(cutoff_text)
    inspection_start = parse_time(inspection_start_text)
    if cutoff > inspection_start:
        raise SystemExit(
            f"cutoff {cutoff} is LATER than the inspected-era start "
            f"{inspection_start}: that would let inspected bars into the split")

    raw_sha = sha256_file(path)
    problems: list[str] = []
    if raw_sha in forbidden:
        raise SystemExit(f"{path} is an INSPECTED file (sha256 {raw_sha[:12]}…, "
                         f"{forbidden[raw_sha]}); a freeze must use a fresh pull")

    times, rows = read_rows(path)
    integ = integrity(times, tf_minutes)
    parts = split(times, cutoff, train_frac, embargo, warmup)

    if parts["kept_rows"] < min_kept:
        problems.append(f"kept {parts['kept_rows']} bars < --min-kept {min_kept}")
    if parts["train_bars"] < min_train:
        problems.append(f"TRAIN {parts['train_bars']} bars < --min-train {min_train}")
    if parts["oos_bars"] < min_oos:
        problems.append(f"cold OOS {parts['oos_bars']} bars < --min-oos {min_oos}")
    if integ["duplicate_timestamps"]:
        problems.append(f"{integ['duplicate_timestamps']} duplicate timestamps")
    if integ["non_monotonic"]:
        problems.append(f"{integ['non_monotonic']} out-of-order timestamps")

    def seg(idx_range):
        if not idx_range:
            return None
        a, b = idx_range
        return {"first_bar": times[a].isoformat(sep=" "),
                "last_bar": times[b].isoformat(sep=" "),
                "bars": b - a + 1,
                "days": round((times[b] - times[a]).total_seconds() / 86400.0, 2),
                "row_range": [a, b]}

    manifest = {
        "tool": "btc/freeze.py", "tool_version": TOOL_VERSION,
        "created_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "hypothesis": hypothesis, "pre_registration": doc,
        "source_csv": os.path.abspath(path), "source_bytes": os.path.getsize(path),
        "raw_sha256": raw_sha, "raw_bars": len(times),
        "raw_first_bar": times[0].isoformat(sep=" "),
        "raw_last_bar": times[-1].isoformat(sep=" "),
        "timeframe": timeframe,
        "cutoff_exclusive": cutoff.isoformat(sep=" "),
        "inspected_era_start": inspection_start.isoformat(sep=" "),
        "inspected_sha256_refused": sorted(forbidden),
        "protocol": {"warmup_bars": warmup, "train_frac": train_frac,
                     "embargo_bars": embargo,
                     "train": "earliest train_frac of the pre-cutoff bars, "
                              "starting after the warm-up",
                     "oos": "everything after the embargo; read exactly once"},
        "segments": {"train": seg(parts["train_rows"]),
                     "embargo": seg(parts["embargo_rows"]),
                     "cold_oos": seg(parts["oos_rows"])},
        "integrity": integ,
        "state": "frozen" if not problems else "rejected",
        "results_inspected": False,
        "problems": problems,
    }
    return manifest, problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", help="fresh bar pull to freeze")
    ap.add_argument("--timeframe", default="H1", choices=sorted(TF_MINUTES))
    ap.add_argument("--cutoff", default=INSPECTED_ERA_START,
                    help="exclusive upper bound of the untouched era")
    ap.add_argument("--inspection-start", default=INSPECTED_ERA_START,
                    help="first bar of the inspected era (a cutoff later than "
                         "this is refused)")
    ap.add_argument("--train-frac", type=float, default=0.60)
    ap.add_argument("--embargo-bars", type=int, default=200)
    ap.add_argument("--warmup", type=int, default=1000)
    ap.add_argument("--min-kept", type=int, default=18000)
    ap.add_argument("--min-train", type=int, default=10000)
    ap.add_argument("--min-oos", type=int, default=7000)
    ap.add_argument("--hypothesis", default="BTC-ORB-EU-H1")
    ap.add_argument("--doc", default="docs/btc_hypothesis_orb_h1_2026-10-31.md")
    ap.add_argument("--out", help="manifest path (default: btc/manifests/<hypothesis>.json)")
    ap.add_argument("--forbid-sha", action="append", default=[],
                    help="extra sha256 to refuse (repeatable)")
    ap.add_argument("--force", action="store_true",
                    help="overwrite an existing manifest (a freeze is a one-way door)")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if not args.csv:
        ap.error("--csv is required (or use --self-test)")

    out = args.out or os.path.join("btc", "manifests",
                                   f"{args.hypothesis.lower().replace('-', '_')}.json")
    forbidden = dict(INSPECTED_SHA256)
    for sha in args.forbid_sha:
        forbidden[sha.strip().lower()] = "listed with --forbid-sha"
    if os.path.exists(out) and not args.force:
        raise SystemExit(f"{out} already exists: a freeze is written once, before "
                         f"any sweep. Use --force only to correct a mistake, and "
                         f"record why in STATUS.md.")

    manifest, problems = freeze(
        args.csv, args.timeframe, args.cutoff, args.train_frac,
        args.embargo_bars, args.warmup, args.min_kept, args.min_train,
        args.min_oos, args.inspection_start, forbidden, args.hypothesis,
        args.doc)

    print("=" * 78)
    print(f"FREEZE — {args.hypothesis}  ({manifest['state'].upper()})")
    print("=" * 78)
    print(f"source     : {manifest['source_csv']}  ({manifest['source_bytes']} bytes)")
    print(f"raw        : {manifest['raw_bars']} bars  "
          f"{manifest['raw_first_bar']} .. {manifest['raw_last_bar']}")
    print(f"sha256     : {manifest['raw_sha256']}")
    print(f"cutoff     : < {manifest['cutoff_exclusive']} (inspected era starts there)")
    for name in ("train", "embargo", "cold_oos"):
        s = manifest["segments"][name]
        if s:
            print(f"{name:<11}: {s['bars']:>6} bars  {s['first_bar']} .. "
                  f"{s['last_bar']}  ({s['days']:.0f} d)")
    integ = manifest["integrity"]
    print(f"integrity  : dups {integ['duplicate_timestamps']}, "
          f"out-of-order {integ['non_monotonic']}, "
          f"gaps {integ['gaps_over_1.5x_tf']} (largest "
          f"{integ['largest_gaps_minutes'][:3]} min), "
          f"missing UTC hours {integ['utc_hours_missing'] or 'none'}")
    if problems:
        for p in problems:
            print(f"  [REJECT] {p}")
        print("\nNOT frozen. Capture more history (e.g. --bars 60000) and re-run.")
        return 2
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    print(f"\n[OK] wrote {out}")
    print("Next: commit the manifest with the pre-registration BEFORE any sweep.")
    print("The cold OOS is now reserved: one read, after the TRAIN winner is frozen.")
    return 0


# --------------------------------------------------------------------------- #
# offline self-test
# --------------------------------------------------------------------------- #
def _write_csv(path: str, rows: list[tuple]) -> None:
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["time", "open", "high", "low", "close", "tick_volume", "spread"])
        for t, o, h, l, c in rows:
            w.writerow([t.strftime("%Y-%m-%d %H:%M:%S"), o, h, l, c, 10, 4000])


def self_test() -> int:
    from datetime import timedelta
    tmp = tempfile.mkdtemp()
    good = os.path.join(tmp, "good.csv")
    t0 = datetime(2023, 1, 2, 0, 0)
    _write_csv(good, [(t0 + timedelta(hours=i), 100, 101, 99, 100)
                      for i in range(2000)])            # all pre-cutoff
    m, problems = freeze(good, "H1", INSPECTED_ERA_START, 0.60, 50, 100,
                         1000, 300, 100, INSPECTED_ERA_START, {}, "TEST", "doc.md")
    assert m["state"] == "frozen" and not problems, problems
    assert m["segments"]["train"]["bars"] == 1140, m["segments"]["train"]   # 60% of 1901
    assert m["segments"]["cold_oos"]["bars"] == 2000 - 99 - 1140 - 50, \
        m["segments"]["cold_oos"]
    assert m["segments"]["embargo"]["bars"] == 50
    assert m["results_inspected"] is False
    assert m["segments"]["train"]["first_bar"] == (
        t0 + timedelta(hours=99)).isoformat(sep=" "), m["segments"]["train"]
    # the split is chronological and disjoint
    assert m["segments"]["train"]["last_bar"] < m["segments"]["embargo"]["first_bar"]
    assert m["segments"]["embargo"]["last_bar"] < m["segments"]["cold_oos"]["first_bar"]

    # a file that reaches into the inspected era: only the pre-cutoff part is kept
    mix = os.path.join(tmp, "mix.csv")
    _write_csv(mix, [(datetime(2024, 5, 26, 22, 0) + timedelta(hours=i), 1, 2, 0.5, 1)
                     for i in range(800)])    # 30 days before .. 3 days after
    m2, _ = freeze(mix, "H1", INSPECTED_ERA_START, 0.60, 5, 10, 1, 1, 1,
                   INSPECTED_ERA_START, {}, "TEST", "doc.md")
    assert m2["raw_bars"] == 800, m2["raw_bars"]
    assert m2["segments"]["cold_oos"]["last_bar"] < INSPECTED_ERA_START, \
        m2["segments"]["cold_oos"]
    assert m2["raw_last_bar"] >= INSPECTED_ERA_START        # the pull went further

    # guards
    try:
        freeze(good, "H1", "2026-01-01 00:00:00", 0.60, 10, 10, 1, 1, 1,
               INSPECTED_ERA_START, {}, "TEST", "doc.md")
        raise AssertionError("a cutoff inside the inspected era must be refused")
    except SystemExit:
        pass
    try:
        freeze(good, "H1", INSPECTED_ERA_START, 0.60, 50, 100, 1, 1, 1,
               INSPECTED_ERA_START, {sha256_file(good): "known"}, "TEST", "doc.md")
        raise AssertionError("a known inspected sha256 must be refused")
    except SystemExit:
        pass
    _, problems = freeze(good, "H1", INSPECTED_ERA_START, 0.60, 50, 100,
                         5000, 300, 100, INSPECTED_ERA_START, {}, "TEST", "doc.md")
    assert problems and "min-kept" in problems[0], problems

    # duplicate / out-of-order detection
    bad = os.path.join(tmp, "bad.csv")
    rows = [(t0 + timedelta(hours=i), 1, 2, 0.5, 1) for i in range(50)]
    rows[10] = rows[9]
    _write_csv(bad, rows)
    _, problems = freeze(bad, "H1", INSPECTED_ERA_START, 0.6, 1, 1, 1, 1, 1,
                         INSPECTED_ERA_START, {}, "TEST", "doc.md")
    assert any("duplicate" in p for p in problems), problems

    # CLI: manifest is written once, and a rejected pull writes nothing
    out = os.path.join(tmp, "m.json")
    rc = main(["--csv", good, "--min-kept", "1000", "--min-train", "300",
               "--min-oos", "100", "--out", out])
    assert rc == 0 and os.path.exists(out), rc
    try:                                    # no silent overwrite of a freeze
        main(["--csv", good, "--min-kept", "1000", "--min-train", "300",
              "--min-oos", "100", "--out", out])
        raise AssertionError("an existing manifest must not be overwritten")
    except SystemExit:
        pass
    rejected = os.path.join(tmp, "no.json")
    assert main(["--csv", good, "--min-kept", "999999", "--out", rejected]) == 2
    assert not os.path.exists(rejected)

    # the manifest is consumable JSON with the fields the doc quotes
    data = json.load(open(out))
    for key in ("raw_sha256", "cutoff_exclusive", "segments", "state",
                "results_inspected", "protocol"):
        assert key in data, key
    print("freeze self-test OK — sha256, cutoff guard, split+embargo, integrity, "
          "one-way manifest, CLI exit codes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
