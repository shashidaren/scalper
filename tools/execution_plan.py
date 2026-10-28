#!/usr/bin/env python3
"""Resolve "follow execution plan gold|bitcoin" into a brief an executor can obey.

Why this exists
---------------
The roadmap lives in two places that can disagree: the prose (STATUS.md, docs/,
`/readiness`) and whatever an agent remembers. This tool makes the plan
**machine-readable and checkable** — `plans/gold.json` / `plans/btc.json` — so a
session that starts with "follow execution plan gold" has one unambiguous
answer to three questions:

  1. what is the next phase, and what may I not touch while doing it?
  2. what does "done" mean for that phase (its exit gate)?
  3. is the published book consistent with what the plan claims?

It renders; it does not decide. There is no code path here that changes a
parameter, a trading mode, or an order.

Design rules
------------
* **Stdlib only.** It runs next to the books, must never be the reason a deploy
  fails, and must not import `config` (gold and BTC configs cannot coexist in
  one process — see btc/_instance.py).
* **Fail closed.** A malformed plan exits 1 with the reason. A plan that asks to
  work on a blocked phase is malformed, not optimistic.
* **Read-only.** Paper state is read, never written.
* **The prose wins on conflict.** If this file and STATUS.md disagree, STATUS.md
  is the record of decisions and the plan is the checklist; fix the plan.

    python3 tools/execution_plan.py gold               # brief for the next phase
    python3 tools/execution_plan.py bitcoin --status   # brief + published book state
    python3 tools/execution_plan.py gold --list        # every phase and its status
    python3 tools/execution_plan.py gold --json        # full resolved plan
    python3 tools/execution_plan.py --validate         # both plans, exit 1 if invalid

Exit codes: 0 ok, 1 invalid plan, 2 usage / unknown book.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN_DIR = ROOT / "plans"

# Aliases so "follow execution plan bitcoin" resolves without a lookup.
ALIASES = {"gold": "gold", "xau": "gold", "xauusd": "gold",
           "btc": "btc", "bitcoin": "btc", "btcusd": "btc"}
STATUSES = ("active", "parallel", "blocked", "waiting", "done")
REQUIRED_PHASE_KEYS = ("id", "order", "status", "title", "goal", "steps",
                       "exit_gate", "blocked_by", "commands", "sources", "evidence")
# Files a plan may cite as sources; a missing one means the plan has rotted.
MAX_PAPER_AGE_HOURS = 24.0


def plan_path(book: str, root: Path = ROOT) -> Path:
    return root / "plans" / f"{book}.json"


def resolve_book(name: str) -> str:
    book = ALIASES.get(str(name).strip().lower())
    if book is None:
        raise SystemExit(f"unknown book {name!r}: try gold | bitcoin (or btc)")
    return book


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def validate(plan: dict, root: Path = ROOT) -> list[str]:
    """Return a list of problems. Empty list = valid. Never raises."""
    problems: list[str] = []

    def need(obj, key, label):
        if key not in obj:
            problems.append(f"{label}: missing key {key!r}")
            return None
        return obj[key]

    for key in ("book", "title", "symbol", "version", "reviewed", "verdict",
                "verdict_reason", "mode_expected", "next", "never", "phases"):
        need(plan, key, "plan")
    if problems:
        return problems

    if plan["schema"] != 1:
        problems.append(f"plan: unsupported schema {plan['schema']!r} (expected 1)")
    if plan["verdict"] not in ("GO", "NO-GO"):
        problems.append(f"plan: verdict must be GO or NO-GO, got {plan['verdict']!r}")
    if not isinstance(plan["never"], list) or not plan["never"]:
        problems.append("plan: 'never' must be a non-empty list of hard rules")
    elif not all(isinstance(x, str) and x.strip() for x in plan["never"]):
        problems.append("plan: every 'never' entry must be a non-empty string")

    phases = plan.get("phases")
    if not isinstance(phases, list) or not phases:
        problems.append("plan: 'phases' must be a non-empty list")
        return problems

    ids, orders = [], []
    for i, ph in enumerate(phases):
        label = f"phase[{i}]"
        if not isinstance(ph, dict):
            problems.append(f"{label}: not an object")
            continue
        missing = [k for k in REQUIRED_PHASE_KEYS if k not in ph]
        if missing:
            problems.append(f"{label}: missing {', '.join(missing)}")
            continue
        label = f"phase {ph['id']!r}"
        ids.append(ph["id"])
        if not isinstance(ph["order"], int) or ph["order"] < 1:
            problems.append(f"{label}: order must be a positive int")
        else:
            orders.append(ph["order"])
        if ph["status"] not in STATUSES:
            problems.append(f"{label}: status {ph['status']!r} not in {STATUSES}")
        for key in ("steps", "blocked_by", "commands", "sources"):
            if not isinstance(ph[key], list):
                problems.append(f"{label}: {key} must be a list")
        for key in ("title", "goal", "exit_gate", "evidence"):
            if not isinstance(ph[key], str) or not ph[key].strip():
                problems.append(f"{label}: {key} must be a non-empty string")
        for src in ph.get("sources", []):
            if not (root / src).exists():
                problems.append(f"{label}: source file missing: {src}")

    if len(set(ids)) != len(ids):
        problems.append("phase ids must be unique")
    if len(set(orders)) != len(orders):
        problems.append("phase orders must be unique")

    by_id = {ph["id"]: ph for ph in phases if isinstance(ph, dict) and "id" in ph}
    for ph in phases:
        if not isinstance(ph, dict) or "blocked_by" not in ph:
            continue
        for blocker in ph["blocked_by"]:
            if blocker not in by_id:
                problems.append(f"phase {ph['id']!r}: blocked_by unknown phase {blocker!r}")
            elif blocker == ph["id"]:
                problems.append(f"phase {ph['id']!r}: blocked_by itself")
        # A done phase cannot be blocked by work that is not done.
        if ph.get("status") == "done":
            for blocker in ph["blocked_by"]:
                other = by_id.get(blocker)
                if other is not None and other.get("status") != "done":
                    problems.append(
                        f"phase {ph['id']!r} is done but its blocker {blocker!r} is "
                        f"{other.get('status')!r}")

    nxt = plan.get("next")
    if nxt not in by_id:
        problems.append(f"plan: 'next' names unknown phase {nxt!r}")
    else:
        phase = by_id[nxt]
        if phase.get("status") == "done":
            problems.append(f"plan: 'next' names {nxt!r}, which is already done")
        open_blockers = [b for b in phase.get("blocked_by", [])
                         if by_id.get(b, {}).get("status") != "done"]
        if open_blockers:
            problems.append(
                f"plan: 'next' names {nxt!r} but it is blocked by "
                f"{', '.join(open_blockers)}; point 'next' at the unblocking work")
    return problems


def load(book: str, root: Path = ROOT) -> dict:
    path = plan_path(book, root)
    try:
        plan = json.loads(path.read_text())
    except FileNotFoundError:
        raise SystemExit(f"no plan for {book!r}: {path} is missing")
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path}: not valid JSON: {e}")
    problems = validate(plan, root)
    if problems:
        detail = "\n  - ".join(problems)
        raise SystemExit(f"{path} is invalid:\n  - {detail}")
    return plan


# --------------------------------------------------------------------------- #
# published book state (read-only, stdlib)
# --------------------------------------------------------------------------- #
def paper_state(plan: dict, root: Path = ROOT) -> dict:
    """Published paper snapshot, or {'error': ...}. Never raises."""
    rel = (plan.get("paths") or {}).get("paper_state")
    if not rel:
        return {"error": "plan declares no paper_state path"}
    path = root / rel
    try:
        data = json.loads(path.read_text())
        closed = data["closed"]
        balance = data["balance"]
        if (type(closed) is not int or closed < 0
                or type(balance) not in (int, float) or not math.isfinite(balance)):
            raise ValueError("invalid counters")
        stamp = datetime.fromisoformat(data["updated_at"])
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0
        return {
            "closed": closed,
            "balance": balance,
            "wins": data.get("wins") if type(data.get("wins")) is int else None,
            "losses": data.get("losses") if type(data.get("losses")) is int else None,
            "updated_at": data["updated_at"],
            "age_hours": round(age, 2),
            "stale": age > MAX_PAPER_AGE_HOURS or age < 0,
            "open_position": bool(data.get("position")),
        }
    except (OSError, ValueError, TypeError, KeyError) as e:
        return {"error": f"{rel}: {type(e).__name__}: {e}"}


def live_mode(plan: dict, root: Path = ROOT) -> str:
    """Observed TRADING_MODE if the machine-local live_status.json is readable."""
    rel = (plan.get("paths") or {}).get("live_status")
    if not rel:
        return "unknown (machine-local file, not published)"
    try:
        data = json.loads((root / rel).read_text())
    except (OSError, ValueError):
        return "unknown (machine-local file, not published)"
    return str(data.get("mode") or "unknown")


# --------------------------------------------------------------------------- #
# rendering
# --------------------------------------------------------------------------- #
def phase_by_id(plan: dict, phase_id: str) -> dict:
    for ph in plan["phases"]:
        if ph["id"] == phase_id:
            return ph
    raise SystemExit(f"unknown phase {phase_id!r}")


def render_brief(plan: dict, state: dict, mode: str, width: int = 78) -> str:
    ph = phase_by_id(plan, plan["next"])
    out = []
    rule = "=" * width
    out.append(rule)
    out.append(f"{plan['title'].upper()}  —  v{plan['version']}  (reviewed {plan['reviewed']})")
    out.append(rule)
    out.append(f"verdict        : {plan['verdict']} — {plan['verdict_reason']}")
    out.append(f"mode expected  : {plan['mode_expected']}   observed: {mode}")
    if "error" in state:
        out.append(f"paper book     : UNKNOWN — {state['error']}")
    else:
        wl = (f"{state['wins']}W/{state['losses']}L "
              if state["wins"] is not None and state["losses"] is not None else "")
        out.append(f"paper book     : {state['closed']} closed, {wl}${state['balance']:.2f}, "
                   f"updated {state['updated_at']} UTC"
                   + ("  [STALE — treat as unknown]" if state["stale"] else ""))
        if state["open_position"]:
            out.append("open position  : yes")
    out.append("")
    out.append(f"NEXT PHASE  {ph['order']}. {ph['title']}   [{ph['status']}]")
    if ph.get("window"):
        out.append(f"window      : {ph['window']}")
    out.append(f"goal        : {ph['goal']}")
    out.append("")
    out.append("steps:")
    for i, step in enumerate(ph["steps"], 1):
        out.append(f"  {i}. {step}")
    out.append("")
    out.append(f"exit gate   : {ph['exit_gate']}")
    if ph["blocked_by"]:
        out.append(f"blocked by  : {', '.join(ph['blocked_by'])}")
    if ph["commands"]:
        out.append("commands:")
        for cmd in ph["commands"]:
            out.append(f"  $ {cmd}")
    out.append(f"sources     : {', '.join(ph['sources'])}")
    out.append(f"evidence    : {ph['evidence']}")
    out.append("")
    out.append("HARD RULES for this book (do not violate while executing):")
    for rule_text in plan["never"]:
        out.append(f"  - {rule_text}")
    out.append("")
    out.append("Stop when the exit gate is met (or proven unreachable) and record the")
    out.append("outcome in STATUS.md + this plan file. Do not start the next phase early.")
    return "\n".join(out)


def render_list(plan: dict) -> str:
    out = [f"{plan['title']} (v{plan['version']}, verdict {plan['verdict']}, next {plan['next']!r})"]
    for ph in sorted(plan["phases"], key=lambda p: p["order"]):
        blocker = f"  <- {', '.join(ph['blocked_by'])}" if ph["blocked_by"] else ""
        mark = "*" if ph["id"] == plan["next"] else " "
        out.append(f" {mark}{ph['order']}. [{ph['status']:<9}] {ph['id']:<24} {ph['title']}{blocker}")
    out.append("  * = the phase 'next' points at")
    return "\n".join(out)


def resolved(plan: dict, state: dict, mode: str) -> dict:
    """The plan plus its live inputs, for an agent that wants JSON."""
    return {"book": plan["book"], "verdict": plan["verdict"],
            "mode_expected": plan["mode_expected"], "mode_observed": mode,
            "next": phase_by_id(plan, plan["next"]), "paper_state": state,
            "never": plan["never"], "phases": plan["phases"],
            "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Resolve an execution plan into a brief for the next phase.")
    ap.add_argument("book", nargs="?",
                    help="gold | bitcoin (btc) — omit only with --validate")
    ap.add_argument("--status", action="store_true",
                    help="include the published paper book state")
    ap.add_argument("--list", action="store_true", help="list every phase and status")
    ap.add_argument("--json", action="store_true", help="emit the resolved plan as JSON")
    ap.add_argument("--validate", action="store_true",
                    help="validate plan(s) and exit 1 on any problem")
    ap.add_argument("--root", default=str(ROOT),
                    help="repo root holding plans/ (default: this checkout)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()

    if args.validate:
        books = [resolve_book(args.book)] if args.book else ["gold", "btc"]
        bad = 0
        for book in books:
            path = plan_path(book, root)
            try:
                plan = load(book, root)
            except SystemExit as e:
                print(f"INVALID {book}: {e}")
                bad += 1
                continue
            print(f"OK {book}: {path.name} v{plan['version']}, "
                  f"{len(plan['phases'])} phases, next {plan['next']!r}")
        return 1 if bad else 0

    if not args.book:
        ap.error("a book is required (gold | bitcoin); use --validate to check both")

    plan = load(resolve_book(args.book), root)
    state = paper_state(plan, root)
    mode = live_mode(plan, root)

    if args.json:
        print(json.dumps(resolved(plan, state, mode), indent=2))
    elif args.list:
        print(render_list(plan))
    elif args.status:
        print(render_brief(plan, state, mode))
    else:
        # Default: the next-phase brief, minus the book state (keeps it short).
        print(render_brief(plan, state, mode))
    return 0


if __name__ == "__main__":
    sys.exit(main())
