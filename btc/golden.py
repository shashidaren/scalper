"""Golden numbers, pinned to the exact data file they were measured on.

The problem this solves
-----------------------
Two offline suites compare a tool's output against a number that was measured
once, by hand, on `data/GOLD_M5.csv`:

    btc/edge_screen_test.py   the code-vs-backtest baseline (n / net / PF)
    btc/preflight_test.py     the spread cost as a fraction of one stop (1R)

`data/GOLD_M5.csv` is **gitignored and replaced** by `tools/pull_gold_m5.sh` -
it is a rolling observation window, not a checked-in fixture. So a bare
`assert trades == 257` is a time bomb: the day the window rolls, the number
changes for a perfectly good reason, the suite goes red, and because both
suites sit inside `tools/smoke_test.py` the autosync **deploy gate** goes red
with it. A red gate does not shout - it silently rolls back every deploy
(compare the 2026-10-04..07 dirty-tree freeze in STATUS.md, ~63 h of stale
code on the box with nothing obviously broken).

Exactly that happened on 2026-10-24: the fresh pull replaced the file, the
old 255 / +$456.58 / PF 1.32 pin no longer matched, and both suites failed
with numbers that were *correct* for the new data.

The policy
----------
A golden number is only asserted against the file it came from. Pin that
file's sha256 alongside the number:

  * sha matches  -> assert the number. Real accounting drift still fails.
  * sha differs  -> report SKIP, print the observed value, do not fail.

A SKIP is loud on purpose: the operator sees "baseline moved" and decides
whether to re-pin. Nothing is asserted about data nobody measured.

Re-pinning is a deliberate act, not a reflex: run the tool, confirm the new
number is explained (fresh window, changed geometry, ...), update the pin in
the calling test, and add a STATUS.md changelog row. Do not re-pin to make a
red light go green when the movement is unexplained.

This module is imported by the two suites above; it is not used at runtime.
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path, chunk: int = 1 << 20) -> str:
    """Hex sha256 of a file, streamed (the CSVs are ~1-2 MB, but stay honest)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def is_pinned(path, pinned_sha: str) -> bool:
    """True when `path` is byte-for-byte the file the golden number came from."""
    p = Path(path)
    if not p.exists():
        return False
    return sha256_file(p) == pinned_sha


def short(sha: str) -> str:
    return sha[:12] + "…" if len(sha) > 12 else sha


def moved(path, pinned_sha: str, observed: str) -> str:
    """The detail string for a SKIP: which file, what it is now, what was pinned."""
    actual = sha256_file(path) if Path(path).exists() else "<absent>"
    return (f"{Path(path).name} is not the pinned file "
            f"(sha256 {short(actual)} != {short(pinned_sha)}); observed {observed} "
            f"- re-pin after confirming the new baseline is explained")
