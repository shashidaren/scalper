"""Read-only evidence collector for the `btc/HANDOFF.md` §0 resume protocol.

The handoff forbids claiming that anything is deployed, running, or populated
without the command output that proves it. This script runs exactly that
checklist in one go and prints a timestamped, paste-ready markdown block for
the session notes.

It is strictly read-only: every command below is a query (`git rev-parse`,
`systemctl is-active`, `ss`, `wc -l`, `journalctl`). It never installs,
enables, starts, restarts or writes anything, it imports no MT5 module and it
opens no bridge connection, so it is safe to run while the gold bot trades.

Usage (on `scalping`):
    python3 btc/server_check.py                 # markdown block
    python3 btc/server_check.py --json          # machine readable
    python3 btc/server_check.py --repo /root/scalper

Anything it cannot observe is reported as `unknown` — never as a default.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = os.path.dirname(HERE)

GOLD_UNITS = ("scalper-bot", "scalper-dashboard")
BTC_UNITS = ("scalper-btc-bot", "scalper-btc-dashboard")
PORTS = ("8088", "8089", "18812")


def sh(cmd, cwd=None, timeout=20):
    """Run a read-only command; return (ok, output)."""
    exe = cmd[0]
    if shutil.which(exe) is None:
        return False, f"<{exe} not found>"
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "<timeout>"
    out = (p.stdout or "").strip() or (p.stderr or "").strip()
    return p.returncode == 0, out


def collect(repo: str, journal_lines: int) -> dict:
    r: dict = {
        "collected_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": os.uname().nodename,
        "repo": repo,
        "repo_exists": os.path.isdir(os.path.join(repo, ".git")),
    }
    if r["repo_exists"]:
        r["git_head"] = sh(["git", "rev-parse", "HEAD"], repo)[1]
        r["git_branch"] = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo)[1]
        r["git_status"] = sh(["git", "status", "--short"], repo)[1] or "<clean>"
        r["git_last_commit"] = sh(
            ["git", "log", "-1", "--format=%h %ci %s"], repo)[1]
    else:
        r["git_head"] = r["git_branch"] = r["git_status"] = "unknown (no repo here)"

    units = {}
    for unit in GOLD_UNITS + BTC_UNITS:
        installed = sh(["systemctl", "cat", unit])[0]
        units[unit] = {
            "installed": installed,
            "enabled": sh(["systemctl", "is-enabled", unit])[1] if installed else "not-installed",
            "active": sh(["systemctl", "is-active", unit])[1] if installed else "not-installed",
        }
    r["units"] = units

    ok, ss_out = sh(["ss", "-tlnp"])
    r["ports"] = {}
    for port in PORTS:
        if not ok:
            r["ports"][port] = "unknown (ss unavailable)"
        else:
            hit = [ln.strip() for ln in ss_out.splitlines() if f":{port} " in ln]
            r["ports"][port] = hit[0] if hit else "not listening"

    data = {}
    for name in ("GOLD_M5.csv", "GOLD_M1.csv", "BTCUSD_M5.csv", "BTCUSD_M1.csv"):
        path = os.path.join(repo, "data", name)
        if not os.path.exists(path):
            data[name] = "absent"
            continue
        try:
            with open(path, "r", errors="replace") as fh:
                lines = fh.readlines()
            first = lines[1].split(",")[0] if len(lines) > 1 else "?"
            last = lines[-1].split(",")[0] if len(lines) > 1 else "?"
            data[name] = f"{len(lines) - 1} bars, {first} .. {last}"
        except OSError as exc:
            data[name] = f"unreadable: {exc}"
    r["data_files"] = data

    logs = {}
    for rel in ("logs", os.path.join("btc", "logs")):
        d = os.path.join(repo, rel)
        if not os.path.isdir(d):
            logs[rel] = "absent"
            continue
        entries = []
        for fn in ("trades.jsonl", "daily_stats.json", "paper_account.json", "KILL_SWITCH"):
            p = os.path.join(d, fn)
            if os.path.exists(p):
                mtime = datetime.fromtimestamp(os.path.getmtime(p), timezone.utc)
                entries.append(f"{fn} ({os.path.getsize(p)}B, mtime {mtime:%Y-%m-%d %H:%M}Z)")
        logs[rel] = ", ".join(entries) if entries else "no runtime files"
    r["log_dirs"] = logs

    deploy_log = os.path.join(repo, "logs", "deploy.log")
    if os.path.exists(deploy_log):
        with open(deploy_log, errors="replace") as fh:
            r["deploy_log_tail"] = "\n".join(fh.read().splitlines()[-5:])
    else:
        r["deploy_log_tail"] = "absent"

    r["cron"] = sh(["crontab", "-l"])[1]

    if journal_lines > 0:
        r["journal"] = {}
        for unit in GOLD_UNITS[:1] + BTC_UNITS[:1]:
            if units[unit]["installed"]:
                r["journal"][unit] = sh(
                    ["journalctl", "-u", unit, "-n", str(journal_lines), "--no-pager"])[1]
    return r


def verdict(r: dict) -> list[str]:
    """Plain statements that are safe to copy into the handoff."""
    out = []
    btc_installed = [u for u in BTC_UNITS if r["units"][u]["installed"]]
    if not btc_installed:
        out.append("BTC services: NOT installed (no unit file known to systemd) -> "
                   "nothing BTC-side is running; §0 claim 'not deployed' is evidenced.")
    else:
        for u in btc_installed:
            out.append(f"BTC service {u}: installed, enabled={r['units'][u]['enabled']}, "
                       f"active={r['units'][u]['active']}.")
    btc_csv = r["data_files"].get("BTCUSD_M5.csv", "absent")
    out.append(f"BTC M5 dataset: {btc_csv}" + (" -> Phase 0 recon still pending."
                                               if btc_csv == "absent" else ""))
    out.append(f"Port 8089 (BTC dashboard): {r['ports'].get('8089')}")
    out.append(f"Port 18812 (MT5 bridge): {r['ports'].get('18812')}")
    gold = r["units"]["scalper-bot"]
    out.append(f"Gold bot: installed={gold['installed']}, active={gold['active']} "
               "(must be undisturbed by any BTC work).")
    out.append(f"Repo HEAD: {r.get('git_head')} on {r.get('git_branch')}")
    return out


def to_markdown(r: dict) -> str:
    L = [f"### BTC server evidence — {r['collected_at_utc']} (host `{r['host']}`)", ""]
    L.append(f"- repo `{r['repo']}` HEAD `{r.get('git_head')}` branch `{r.get('git_branch')}`")
    L.append(f"- last commit: {r.get('git_last_commit', 'unknown')}")
    L.append(f"- `git status --short`: `{r.get('git_status')}`")
    L.append("")
    L.append("| unit | installed | enabled | active |")
    L.append("|---|---|---|---|")
    for unit, v in r["units"].items():
        L.append(f"| `{unit}` | {v['installed']} | {v['enabled']} | {v['active']} |")
    L.append("")
    L.append("| port | state |")
    L.append("|---|---|")
    for port, state in r["ports"].items():
        L.append(f"| {port} | `{state}` |")
    L.append("")
    L.append("| data file | observed |")
    L.append("|---|---|")
    for name, v in r["data_files"].items():
        L.append(f"| `data/{name}` | {v} |")
    L.append("")
    for rel, v in r["log_dirs"].items():
        L.append(f"- `{rel}/`: {v}")
    L.append(f"- crontab (`crontab -l`):\n```\n{r.get('cron', 'unknown')}\n```")
    L.append(f"- deploy log tail:\n```\n{r['deploy_log_tail']}\n```")
    if r.get("journal"):
        for unit, text in r["journal"].items():
            L.append(f"- `journalctl -u {unit}` tail:\n```\n{text}\n```")
    L.append("")
    L.append("**Read-off (evidence-led, no inference):**")
    for line in verdict(r):
        L.append(f"- {line}")
    L.append("")
    L.append("_Collected read-only by `btc/server_check.py`; nothing was installed, "
             "started or modified._")
    return "\n".join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=DEFAULT_REPO, help="repo checkout to inspect")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    ap.add_argument("--journal", type=int, default=0, metavar="N",
                    help="also capture N journal lines per bot unit (default 0)")
    args = ap.parse_args(argv)

    r = collect(os.path.abspath(args.repo), args.journal)
    print(json.dumps(r, indent=2) if args.json else to_markdown(r))
    return 0


if __name__ == "__main__":
    sys.exit(main())
