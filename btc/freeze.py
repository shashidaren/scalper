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

`--status` — the readiness half
-------------------------------
A freeze recorded in `btc/manifests/` and the `pre_registration.freeze` block in
`plans/btc.json` are two records of the same fact, written at different times by
different hands. Drift between them is how a sweep ends up running on a window
nobody hashed (or on one that has already been read). `--status` reconciles them
and writes nothing:

    python3 btc/freeze.py --status            # PENDING / FROZEN / DRIFT, exit 0|1
    python3 btc/freeze.py --status --json     # the same report, machine-readable

exit 0 = the plan and the disk agree (nothing frozen yet, or frozen and recorded);
exit 1 = they disagree, or the manifest is unsafe (rejected / already inspected /
sha mismatch / cutoff inside the inspected era); exit 2 = the plan is unreadable.

It is deliberately **not** part of the deploy gate. Creating a manifest on the box
is a legitimate step that happens *before* the commit which updates the plan, so
a gate that ran this would red-line every autosync tick between the two — the
2026-10-24 incident, where a red gate made `autosync.sh` roll back its own
merges. `--self-test` covers every case hermetically instead, and the operator
runs `--status` as step 2b of the phase-1 protocol (RUNBOOK "BTC gate").
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import tempfile
from datetime import datetime

TOOL_VERSION = "1.1"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAN_REL = os.path.join("plans", "btc.json")

# --status exit codes (see the docstring).
STATUS_OK, STATUS_DRIFT, STATUS_UNREADABLE = 0, 1, 2

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


def status(root: str = ROOT, plan_rel: str = PLAN_REL) -> tuple[int, dict]:
    """Reconcile the plan's freeze block with the manifest on disk. Read-only.

    Returns (exit_code, report). Every check is a recorded fact, not a guess:
    a missing file is reported as missing, never as "probably fine".
    """
    root = os.path.abspath(root)
    plan_path = os.path.join(root, plan_rel)
    report = {
        "root": root, "plan": plan_rel, "plan_version": None,
        "hypothesis": None, "plan_state": None, "plan_sha256": None,
        "manifest": None, "manifest_exists": False, "manifest_state": None,
        "results_inspected": None, "manifest_sha256": None,
        "cutoff_exclusive": None, "segments": None,
        "csv": None, "csv_exists": False, "csv_sha256": None,
        "phase": None, "phase_status": None,
        "verdict": None, "problems": [], "warnings": [],
    }
    try:
        with open(plan_path) as f:
            plan = json.load(f)
    except FileNotFoundError:
        report["problems"].append(f"{plan_rel} not found under {root}")
        report["verdict"] = "UNREADABLE"
        return STATUS_UNREADABLE, report
    except (ValueError, OSError) as exc:
        report["problems"].append(f"{plan_rel} unreadable: {exc}")
        report["verdict"] = "UNREADABLE"
        return STATUS_UNREADABLE, report

    report["plan_version"] = plan.get("version")
    pre = plan.get("pre_registration")
    if not isinstance(pre, dict):
        report["problems"].append("plan: no pre_registration block")
        pre = {}
    report["hypothesis"] = pre.get("id")
    block = pre.get("freeze") if isinstance(pre.get("freeze"), dict) else {}
    report["plan_state"] = block.get("state")
    report["plan_sha256"] = block.get("raw_sha256")
    report["csv"] = block.get("csv")
    phase_id = block.get("phase")
    report["phase"] = phase_id
    for ph in plan.get("phases") or []:
        if isinstance(ph, dict) and ph.get("id") == phase_id:
            report["phase_status"] = ph.get("status")
            break

    if not block:
        report["problems"].append("plan: pre_registration.freeze block is missing")
    if block.get("state") not in ("pending", "frozen"):
        report["problems"].append(
            f"plan: freeze.state {block.get('state')!r} is neither 'pending' nor 'frozen'")
    if phase_id and report["phase_status"] is None:
        report["problems"].append(
            f"plan: freeze.phase {phase_id!r} names no phase in this plan")

    manifest_rel = block.get("manifest")
    report["manifest"] = manifest_rel
    if not manifest_rel:
        report["problems"].append("plan: freeze.manifest path is missing")
        report["verdict"] = "DRIFT"
        return STATUS_DRIFT, report

    manifest_path = os.path.join(root, manifest_rel)
    report["manifest_exists"] = os.path.exists(manifest_path)

    if not report["manifest_exists"]:
        # The honest pending state: nothing frozen, nothing claimed frozen.
        if block.get("state") == "frozen":
            report["problems"].append(
                f"plan: freeze.state='frozen' but {manifest_rel} does not exist")
        if report["plan_sha256"]:
            report["problems"].append(
                "plan: a raw_sha256 is recorded but no manifest exists to hold it")
        if block.get("state") == "pending" and not report["plan_sha256"]:
            report["warnings"].append(
                "nothing is frozen yet: the reserved window must not be swept")
        csv_rel = report["csv"]
        if csv_rel:
            report["csv_exists"] = os.path.exists(os.path.join(root, csv_rel))
            if not report["csv_exists"]:
                report["warnings"].append(
                    f"{csv_rel} is not in this checkout (data/*.csv stays off git)")
        report["verdict"] = "DRIFT" if report["problems"] else "PENDING"
        return (STATUS_DRIFT if report["problems"] else STATUS_OK), report

    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (ValueError, OSError) as exc:
        report["problems"].append(f"{manifest_rel} unreadable: {exc}")
        report["verdict"] = "DRIFT"
        return STATUS_DRIFT, report

    report["manifest_state"] = manifest.get("state")
    report["results_inspected"] = manifest.get("results_inspected")
    report["manifest_sha256"] = manifest.get("raw_sha256")
    report["cutoff_exclusive"] = manifest.get("cutoff_exclusive")
    report["segments"] = manifest.get("segments")

    if manifest.get("state") != "frozen":
        report["problems"].append(
            f"manifest: state={manifest.get('state')!r} — a rejected freeze must "
            f"not be swept (problems: {manifest.get('problems') or 'none recorded'})")
    if manifest.get("results_inspected") is not False:
        report["problems"].append(
            "manifest: results_inspected is not False — the cold OOS has been read")
    if not manifest.get("raw_sha256"):
        report["problems"].append("manifest: no raw_sha256")
    elif manifest["raw_sha256"] in INSPECTED_SHA256:
        report["problems"].append(
            f"manifest: raw_sha256 is an INSPECTED file "
            f"({INSPECTED_SHA256[manifest['raw_sha256']]})")
    if pre.get("id") and manifest.get("hypothesis") != pre.get("id"):
        report["problems"].append(
            f"manifest: hypothesis {manifest.get('hypothesis')!r} != plan "
            f"pre_registration.id {pre.get('id')!r}")
    try:
        if parse_time(manifest.get("cutoff_exclusive")) > parse_time(INSPECTED_ERA_START):
            report["problems"].append(
                f"manifest: cutoff {manifest.get('cutoff_exclusive')} is inside the "
                f"inspected era (starts {INSPECTED_ERA_START})")
    except (ValueError, TypeError):
        report["problems"].append(
            f"manifest: cutoff_exclusive {manifest.get('cutoff_exclusive')!r} "
            f"is not a time")

    if block.get("state") != "frozen":
        report["problems"].append(
            f"plan: freeze.state={block.get('state')!r} but {manifest_rel} exists — "
            f"record state='frozen' and its raw_sha256 in the same commit")
    if report["plan_sha256"] and report["plan_sha256"] != manifest.get("raw_sha256"):
        report["problems"].append(
            f"plan: raw_sha256 {str(report['plan_sha256'])[:12]}… != manifest "
            f"{str(manifest.get('raw_sha256'))[:12]}…")

    csv_rel = report["csv"]
    if csv_rel:
        csv_path = os.path.join(root, csv_rel)
        report["csv_exists"] = os.path.exists(csv_path)
        if report["csv_exists"]:
            report["csv_sha256"] = sha256_file(csv_path)
            if report["csv_sha256"] != manifest.get("raw_sha256"):
                report["problems"].append(
                    f"{csv_rel} sha256 {report['csv_sha256'][:12]}… != manifest "
                    f"raw_sha256 — the manifest is not for this file")
        else:
            report["warnings"].append(
                f"{csv_rel} is not in this checkout, so the manifest sha256 can "
                f"only be re-verified on the box that froze it")

    if report["phase_status"] == "active" and not report["problems"]:
        report["warnings"].append(
            f"phase {phase_id!r} is still 'active': record the sha in STATUS.md, "
            f"then mark it done and move 'next' forward")

    report["verdict"] = "DRIFT" if report["problems"] else "FROZEN"
    return (STATUS_DRIFT if report["problems"] else STATUS_OK), report


def print_status(report: dict) -> None:
    print("=" * 78)
    print(f"PHASE-1 FREEZE READINESS — {report['verdict']}")
    print("=" * 78)
    print(f"plan        : {report['plan']}  v{report['plan_version']}"
          + (f"   phase {report['phase']!r} [{report['phase_status']}]"
             if report["phase"] else ""))
    print(f"hypothesis  : {report['hypothesis']}")
    print(f"manifest    : {report['manifest']}   "
          f"({'present' if report['manifest_exists'] else 'absent'})")
    print(f"plan freeze : state={report['plan_state']}  "
          f"raw_sha256={report['plan_sha256'] or 'null'}")
    if report["manifest_exists"]:
        print(f"frozen      : state={report['manifest_state']}  "
              f"results_inspected={report['results_inspected']}")
        print(f"sha256      : {report['manifest_sha256']}")
        print(f"cutoff      : < {report['cutoff_exclusive']}")
        for name in ("train", "embargo", "cold_oos"):
            seg = (report["segments"] or {}).get(name)
            if seg:
                print(f"{name:<11} : {seg['bars']:>6} bars  {seg['first_bar']} .. "
                      f"{seg['last_bar']}")
    print(f"source csv  : {report['csv']}   "
          f"({'present' if report['csv_exists'] else 'absent'})")
    for w in report["warnings"]:
        print(f"  [NOTE] {w}")
    for p in report["problems"]:
        print(f"  [DRIFT] {p}")
    if report["verdict"] == "PENDING":
        print("\nNothing is frozen: no sweep may run against the reserved window.")
        print("Next, on `scalping` (RUNBOOK \"BTC gate\"):")
        print("  $ mt5env/bin/python btc/recon.py --timeframe H1 --bars 44000 "
              "--out data/BTCUSD_H1_pre2024.csv")
        print("  $ python3 btc/freeze.py --csv data/BTCUSD_H1_pre2024.csv "
              f"--out {report['manifest']}")
        print("  $ python3 btc/freeze.py --status      # must print FROZEN")
    elif report["verdict"] == "FROZEN":
        print("\nThe window is frozen and the plan records it. Phase 1's remaining "
              "work is the STATUS.md row + marking the phase done.")
    elif report["verdict"] == "DRIFT":
        print("\nNot consistent. Fix the record before any sweep reads this window.")


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
    ap.add_argument("--status", action="store_true",
                    help="reconcile plans/btc.json's freeze block with the manifest "
                         "(read-only; exit 0 consistent, 1 drift, 2 unreadable)")
    ap.add_argument("--root", default=ROOT,
                    help="repo root for --status (default: this checkout)")
    ap.add_argument("--json", action="store_true",
                    help="with --status: print the report as JSON")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    if args.self_test:
        return self_test()
    if args.status:
        code, report = status(args.root)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print_status(report)
        return code
    if not args.csv:
        ap.error("--csv is required (or use --self-test / --status)")

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

    # ------------------------------------------------------------------ #
    # --status: the plan's freeze block and the manifest must agree
    # ------------------------------------------------------------------ #
    import contextlib
    import io

    sroot = os.path.join(tmp, "repo")
    man_rel, csv_rel = "btc/manifests/m.json", "data/pull.csv"
    os.makedirs(os.path.join(sroot, "plans"))
    os.makedirs(os.path.join(sroot, os.path.dirname(man_rel)))
    os.makedirs(os.path.join(sroot, os.path.dirname(csv_rel)))
    def copy_bytes(src, dst):          # bytes, not text: sha256 is byte-exact
        with open(src, "rb") as a, open(dst, "wb") as b:
            b.write(a.read())

    copy_bytes(good, os.path.join(sroot, csv_rel))
    frozen, _ = freeze(good, "H1", INSPECTED_ERA_START, 0.60, 50, 100, 1000, 300,
                       100, INSPECTED_ERA_START, {}, "TEST", "doc.md")
    man_path = os.path.join(sroot, man_rel)

    def write_plan(state="pending", sha=None):
        plan = {"version": "test",
                "phases": [{"id": "btc-hypothesis", "status": "active"}],
                "pre_registration": {"id": "TEST", "freeze": {
                    "manifest": man_rel, "csv": csv_rel, "phase": "btc-hypothesis",
                    "state": state, "raw_sha256": sha}}}
        with open(os.path.join(sroot, "plans", "btc.json"), "w") as f:
            json.dump(plan, f)

    def write_manifest(**over):
        m = json.loads(json.dumps(frozen))
        m.update(over)
        with open(man_path, "w") as f:
            json.dump(m, f)

    # 1. honest pending state: nothing frozen, nothing claimed frozen
    write_plan()
    code, rep = status(sroot)
    assert code == STATUS_OK and rep["verdict"] == "PENDING", (code, rep)
    assert rep["manifest_exists"] is False and rep["csv_exists"] is True
    assert not rep["problems"], rep["problems"]

    # 2. a plan that claims a freeze it does not have
    write_plan(state="frozen")
    code, rep = status(sroot)
    assert code == STATUS_DRIFT and any("does not exist" in p for p in rep["problems"]), rep

    # 3. a manifest on disk that the plan has not recorded yet (the box, pre-commit)
    write_plan()
    write_manifest()
    code, rep = status(sroot)
    assert code == STATUS_DRIFT and any("exists" in p for p in rep["problems"]), rep

    # 4. consistent: manifest frozen, plan records the same hash
    write_plan(state="frozen", sha=frozen["raw_sha256"])
    code, rep = status(sroot)
    assert code == STATUS_OK and rep["verdict"] == "FROZEN", (code, rep)
    assert rep["csv_sha256"] == frozen["raw_sha256"]
    assert any("still 'active'" in w for w in rep["warnings"]), rep["warnings"]

    # 5. unsafe manifests: inspected already / rejected / cutoff inside the era
    for over, needle in (
            ({"results_inspected": True}, "results_inspected"),
            ({"state": "rejected"}, "rejected"),
            ({"cutoff_exclusive": "2025-01-01 00:00:00"}, "inspected era"),
            ({"hypothesis": "SOMETHING-ELSE"}, "hypothesis"),
            ({"raw_sha256": sorted(INSPECTED_SHA256)[0]}, "INSPECTED file")):
        write_manifest(**over)
        code, rep = status(sroot)
        assert code == STATUS_DRIFT and any(needle in p for p in rep["problems"]), \
            (over, rep["problems"])
    write_manifest()

    # 6. the plan records the wrong hash, and the CSV is not the frozen one
    write_plan(state="frozen", sha="0" * 64)
    code, rep = status(sroot)
    assert code == STATUS_DRIFT and any("raw_sha256" in p for p in rep["problems"]), rep
    write_plan(state="frozen", sha=frozen["raw_sha256"])
    with open(os.path.join(sroot, csv_rel), "ab") as f:
        f.write(b"2020-01-01 00:00:00,1,2,0.5,1,10,4000\r\n")
    code, rep = status(sroot)
    assert code == STATUS_DRIFT and any("not for this file" in p
                                        for p in rep["problems"]), rep
    copy_bytes(good, os.path.join(sroot, csv_rel))   # restore: identical again
    assert status(sroot)[0] == STATUS_OK

    # 7. --status is read-only, and --json parses
    before = {p: open(os.path.join(sroot, p), "rb").read()
              for p in ("plans/btc.json", man_rel, csv_rel)}
    listing = sorted(os.listdir(sroot))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--status", "--root", sroot, "--json"])
    assert rc == STATUS_OK, rc
    payload = json.loads(buf.getvalue())
    assert payload["verdict"] == "FROZEN" and payload["manifest_exists"] is True
    after_files = {p: open(os.path.join(sroot, p), "rb").read() for p in before}
    assert after_files == before, "no state file may change"
    assert sorted(os.listdir(sroot)) == listing, "a status run must not create files"

    # 8. no plan at all is UNREADABLE, not "fine"
    empty = os.path.join(tmp, "empty")
    os.makedirs(empty)
    code, rep = status(empty)
    assert code == STATUS_UNREADABLE and rep["verdict"] == "UNREADABLE", (code, rep)
    assert not os.listdir(os.path.join(empty)), "a status run must write nothing"

    print("freeze self-test OK — sha256, cutoff guard, split+embargo, integrity, "
          "one-way manifest, CLI exit codes, plan/manifest reconciliation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
