#!/usr/bin/env bash
# Phase-1c collection — 2026-10-07 (`scalping`).
#
# WHY THIS EXISTS: the Arena sandbox cannot reach the server (no `ssh scalping`,
# no MT5 bridge, no /root/scalper — see docs/collect-2026-10-07/README.md), so
# the collection in the session plan has to run on `scalping` and come back as
# text. This script runs every step of that plan in one pass, saves each raw
# output under /root/ops/collect-2026-10-07/, and writes one paste-ready bundle
# (/root/ops/collect-2026-10-07/collection.md).
#
# SAFETY CONTRACT (do not "improve" any of this):
#   * read-only w.r.t. services, config and broker state: it never starts,
#     stops, enables, disables or restarts a unit, never edits config.py or
#     btc/config.py, never calls mt5.shutdown() (the gold bot shares the MT5
#     terminal on :18812), and never sends an order.
#   * it writes exactly two things: the raw outputs + bundle under
#     /root/ops/collect-2026-10-07/ and the untouched H1 pull
#     data/BTCUSD_H1.csv (the same file btc/HANDOFF.md §7a prescribes).
#   * it does NOT write anything into the git working tree, deliberately: an
#     untracked file at a path a future commit adds is how every `git pull
#     --ff-only` starts aborting (see docs/cron_review_2026-10-07.md F2).
#   * no `set -e`: one failed probe (docker absent, journal empty) must not
#     abort the rest of the collection.
#
# USAGE (on the server, from the repo root):
#   cd /root/scalper
#   bash docs/collect-2026-10-07/collect_phase1c.sh
#   # then paste /root/ops/collect-2026-10-07/collection.md back into the session
#
# Options:
#   COLLECT_OUT=<dir>          output directory (default /root/ops/collect-2026-10-07)
#   COLLECT_SKIP_PULL=1        skip the H1 pull (offline re-run of the screens)
set -uo pipefail

REPO="${COLLECT_REPO:-/root/scalper}"
OUT="${COLLECT_OUT:-/root/ops/collect-2026-10-07}"
BUNDLE="$OUT/collection.md"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
LABELS=()

cd "$REPO" || { echo "FATAL: no repo at $REPO" >&2; exit 2; }

case "$OUT" in
  "$REPO"/*) echo "FATAL: COLLECT_OUT must be outside the deployed tree ($REPO)" >&2; exit 2 ;;
esac
mkdir -p "$OUT" || exit 2

# ---------------------------------------------------------------------------
# run <label> <timeout-seconds> <shell command>
#   Saves "$ <command>" + combined output + "[exit N]" to $OUT/<label>.txt.
#   Never aborts the collection; the exit code is recorded and printed.
# ---------------------------------------------------------------------------
run() {
  local label="$1" tmo="$2" cmd="$3" rc note=""
  local out="$OUT/${label}.txt"
  LABELS+=("$label")
  printf '$ %s\n' "$cmd" > "$out"
  timeout "$tmo" bash -c "$cmd" >> "$out" 2>&1
  rc=$?
  if [ "$rc" = "124" ]; then note=" (timeout after ${tmo}s)"; fi
  printf '[exit %d%s]\n' "$rc" "$note" >> "$out"
  printf '  %-24s exit %s\n' "$label" "$rc"
  return 0
}

# Secrets must not travel: redact anything that looks like a credential before
# it reaches the bundle. (MT5/XM logins and passwords, API tokens.)
redact() {
  sed -E \
    -e 's/((PASSWORD|PASSWD|TOKEN|SECRET|API_?KEY)[^=:]*[=:][[:space:]]*)[^[:space:],;]+/\1<redacted>/Ig' \
    -e 's/((MT5_)?LOGIN[^=:]*[=:][[:space:]]*)[0-9]+/\1<redacted>/Ig' \
    -e 's/(--password[= ][[:space:]]*)[^[:space:],;]+/\1<redacted>/Ig' \
    "$1"
}

echo "Phase-1c collection -> $OUT"
echo

# ===========================================================================
# 1. STATE — what the box is actually running (read-only)
# ===========================================================================
run state_server_check 300 'mt5env/bin/python btc/server_check.py --journal 30'
run state_crontab      60  'crontab -l'
run state_units        60  '
for u in scalper-bot scalper-dashboard scalper-btc-bot scalper-btc-dashboard; do
  printf "%s: is-enabled=%s is-active=%s ActiveEnterTimestamp=%s\n" \
    "$u" "$(systemctl is-enabled "$u" 2>&1)" "$(systemctl is-active "$u" 2>&1)" \
    "$(systemctl show "$u" -p ActiveEnterTimestamp --value 2>&1)"
done'
run state_ports        30  "ss -ltnp | grep -E '8088|8089|18812'"
run state_docker_ps    60  'docker ps'
run state_repo         60  'git -C . log --oneline -3; echo "--- git status --porcelain ---"; git -C . status --porcelain; echo "--- HEAD ---"; git -C . rev-parse HEAD'
run state_deploy_cron  30  'tail -40 logs/deploy.cron.log'
run state_would_overwrite 30 'echo -n "would-be-overwritten lines: "; grep -c "would be overwritten" logs/deploy.cron.log; echo -n "PULL FAILED lines: "; grep -c "PULL FAILED" logs/deploy.log || true; echo "--- deploy.log tail ---"; tail -20 logs/deploy.log'
# The two checks that decide whether the running process predates PR #22.
run state_spread_gate_field 30 'python3 -c "import json;print(\"gold spread_gate field:\", json.load(open(\"logs/live_status.json\")).get(\"spread_gate\"))"; python3 -c "import json;print(\"btc  spread_gate field:\", json.load(open(\"btc/logs/live_status.json\")).get(\"spread_gate\"))" 2>&1 || true'
run state_btc_config_run 30 'grep -nE "^(BTC_STRATEGY|BTC_TIMEFRAME|TRADING_MODE|MAX_SPREAD_POINTS|TIMEFRAME)" btc/config.py; echo "--- gold ---"; grep -nE "^(TRADING_MODE|MAX_SPREAD_POINTS|TIMEFRAME)" config.py'

# ===========================================================================
# 2. FACTS — H1 recon + THE untouched pull (never the inspected M5 window)
# ===========================================================================
run facts_recon_h1 900 "mt5env/bin/python btc/recon.py --symbol BTCUSD --timeframe H1 --bars 20000 --json $OUT/recon_h1.json"
if [ "${COLLECT_SKIP_PULL:-0}" = "1" ]; then
  echo "  (H1 pull skipped: COLLECT_SKIP_PULL=1)"
else
  run pull_h1_untouched 900 'mt5env/bin/python btc/recon.py --timeframe H1 --bars 20000 --out data/BTCUSD_H1.csv'
fi
run pull_h1_span 60 '
f=data/BTCUSD_H1.csv
if [ -s "$f" ]; then
  echo "file: $f"; echo "bytes: $(stat -c %s "$f")"; echo "bars (excl. header): $(( $(wc -l < "$f") - 1 ))"
  echo "header: $(head -1 "$f")"; echo "first row: $(sed -n 2p "$f")"; echo "last row: $(tail -1 "$f")"
  echo "sha256: $(sha256sum "$f")"
else
  echo "MISSING: $f (the pull failed - the gate cannot be read)"
fi'

# ===========================================================================
# 3. THE GATE — g > c, then the frozen TRAIN->OOS read, then economics/parity
# ===========================================================================
run gate_edge_screen 900 'mt5env/bin/python btc/tool.py btc/edge_screen.py --family donchian --csv data/BTCUSD_H1.csv --detail'
run gate_train_select 1800 'mt5env/bin/python btc/tool.py btc/train_select.py --family donchian --csv data/BTCUSD_H1.csv'
run gate_derive_params 600 'mt5env/bin/python btc/derive_params.py --csv data/BTCUSD_H1.csv'
run gate_parity 600 'mt5env/bin/python btc/tool.py btc/strategy_btc_test.py'   # expect 22/22

# ===========================================================================
# 4. WHAT BTC IS REALLY RUNNING (its own logs/state; no restart, no config)
# ===========================================================================
run btc_paper_account 120 'mt5env/bin/python btc/tool.py paper.py'
run btc_high_spread 60  'echo -n "high_spread lines in btc/logs/trades.jsonl: "; grep -c high_spread btc/logs/trades.jsonl || true; echo -n "BTC trades.jsonl entries: "; wc -l < btc/logs/trades.jsonl 2>/dev/null || echo 0'
run btc_journal 300 'journalctl -u scalper-btc-bot --since 2026-10-03 --no-pager | tail -50'
run btc_paper_state 60 'ls -l btc/logs/ 2>&1; echo "--- btc/logs/paper_account.json ---"; cat btc/logs/paper_account.json 2>&1'
run gold_paper_state 60 'echo "--- gold logs/live_status.json (spread_gate) ---"; python3 -c "import json;d=json.load(open(\"logs/live_status.json\"));print({k:d.get(k) for k in (\"symbol\",\"bid\",\"ask\",\"spread\",\"spread_gate\",\"updated\")})" 2>&1'

# ===========================================================================
# 5. Paste-ready bundle
# ===========================================================================
{
  echo "# Phase-1c collection — \`scalping\` — $TS"
  echo
  echo "Produced read-only by \`docs/collect-2026-10-07/collect_phase1c.sh\`"
  echo "(branch \`arena/c0f67ece-scalper\`). Raw outputs: \`$OUT/<label>.txt\`."
  echo "Nothing was installed, started, stopped, enabled, disabled or reconfigured,"
  echo "and no order was placed; the only file written inside the repo is the"
  echo "untouched H1 pull \`data/BTCUSD_H1.csv\` (git-ignored)."
  echo
  echo "Credentials are redacted. Host \`$(uname -n)\`, user \`$(id -un)\`."
  echo
  echo "---"
  echo
  for label in "${LABELS[@]}"; do
    file="$OUT/${label}.txt"
    [ -s "$file" ] || continue
    echo "## ${label}"
    echo
    echo '```'
    redact "$file"
    echo '```'
    echo
  done
} > "$BUNDLE"

echo
echo "Bundle written: $BUNDLE ($(wc -l < "$BUNDLE") lines, $(stat -c %s "$BUNDLE") bytes)"
echo "Paste that file back into the session. Raw per-step outputs: $OUT/*.txt"
echo "Reminder: nothing was restarted or reconfigured — the decisions (crontab,"
echo "restart, BTC units) stay with the user (btc/HANDOFF.md §5)."
