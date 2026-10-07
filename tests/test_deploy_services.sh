#!/usr/bin/env bash
# Regression test for the cron deploy:
#   1. it must not start the BTC unit implicitly (gold-only default), and
#   2. it must restart a service only when a runtime input for it changed
#      (a BTC-only or docs-only commit must not restart the gold book).
# Fake git/systemctl only - no server, no real units, no MT5.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAKE_BIN="$TMP/bin"
mkdir -p "$FAKE_BIN" "$TMP/repo/logs"
cp "$ROOT/deploy.sh" "$TMP/repo/deploy.sh"
chmod +x "$TMP/repo/deploy.sh"

cat > "$FAKE_BIN/git" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  fetch|checkout|pull) exit 0 ;;
  show-ref) exit 0 ;;
  diff)
    [[ "${GIT_DIFF_FAIL:-0}" == "1" ]] && exit 3
    printf '%s\n' "${GIT_DIFF-config.py}"
    ;;
  rev-parse)
    n=0
    [[ ! -f "$GIT_COUNT" ]] || n="$(cat "$GIT_COUNT")"
    n=$((n + 1))
    printf '%s\n' "$n" > "$GIT_COUNT"
    if (( n == 1 )); then echo before; else echo after; fi
    ;;
  *) echo "unexpected fake git command: $*" >&2; exit 2 ;;
esac
SH

cat > "$FAKE_BIN/systemctl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  cat) exit 0 ;;
  restart)
    [[ "${SYSTEMCTL_FAIL:-}" == "$2" ]] && exit 1
    printf '%s\n' "$2" >> "$SYSTEMCTL_LOG" ;;
  *) echo "unexpected fake systemctl command: $*" >&2; exit 2 ;;
esac
SH
chmod +x "$FAKE_BIN/git" "$FAKE_BIN/systemctl"

run_case() {
  local name="$1" expected="$2"
  shift 2
  local calls="$TMP/${name}.calls"
  : > "$calls"
  : > "$TMP/repo/logs/deploy.log"
  rm -f "$TMP/git-count"
  env -u DEPLOY_SERVICES -u DEPLOY_SERVICE \
    PATH="$FAKE_BIN:$PATH" SYSTEMCTL_LOG="$calls" GIT_COUNT="$TMP/git-count" \
    "$@" "$TMP/repo/deploy.sh" >/dev/null
  local actual
  actual="$(paste -sd ' ' "$calls")"
  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL $name: expected [$expected], got [$actual]" >&2
    exit 1
  fi
  echo "PASS $name: restarted [$actual]"
}

expect_log() {
  local name="$1" fragment="$2"
  if ! grep -qF "$fragment" "$TMP/repo/logs/deploy.log"; then
    echo "FAIL $name: deploy.log does not contain [$fragment]" >&2
    cat "$TMP/repo/logs/deploy.log" >&2
    exit 1
  fi
  echo "PASS $name: deploy.log records the decision"
}

# --- service selection (unchanged contract from PR #17) --------------------
run_case default_gold_only scalper-bot
run_case explicit_phase2_opt_in 'scalper-bot scalper-btc-bot' \
  DEPLOY_SERVICES='scalper-bot scalper-btc-bot'
run_case legacy_singular_override scalper-btc-bot DEPLOY_SERVICE=scalper-btc-bot

# --- changed-path filter ---------------------------------------------------
# BTC/docs-only commit: the gold book keeps running (also asserted in the log).
run_case btc_only_commit_skips_gold '' \
  GIT_DIFF=$'btc/strategy_btc.py\nbtc/HANDOFF.md\nREADME.md'
expect_log btc_only_commit_skips_gold 'restart skipped for scalper-bot'

# A dashboard template change is not an engine input, but it is a viewer input.
run_case templates_only_skips_gold '' GIT_DIFF=templates/index.html
expect_log templates_only_skips_gold 'dashboard-relevant change'

# btc/config.py IS a runtime input for gold's shared portfolio gate.
run_case btc_config_restarts_gold scalper-bot GIT_DIFF=btc/config.py

# Any unrecognised path restarts (fail safe), and so do an empty or failed diff.
run_case unknown_path_restarts_gold scalper-bot GIT_DIFF=some/new_file.py
run_case empty_diff_restarts_gold scalper-bot GIT_DIFF=
run_case diff_failure_restarts_gold scalper-bot GIT_DIFF_FAIL=1

# Escape hatch.
run_case forced_restart scalper-bot GIT_DIFF=btc/strategy_btc.py DEPLOY_FORCE_RESTART=1

# Dashboard opt-in: only dashboard-relevant paths restart it, and nothing else.
run_case dashboard_opted_in_restarts_api_only 'scalper-bot' \
  DEPLOY_SERVICES='scalper-bot scalper-dashboard' GIT_DIFF=run.py
run_case dashboard_opted_in_restarts_dashboard 'scalper-dashboard' \
  DEPLOY_SERVICES='scalper-bot scalper-dashboard' GIT_DIFF=dashboard.py

# A failed restart is reported, not swallowed, and does not abort the run.
run_case restart_failure_report '' GIT_DIFF=config.py SYSTEMCTL_FAIL=scalper-bot
expect_log restart_failure_report 'RESTART FAILED for scalper-bot'

# --- lock ------------------------------------------------------------------
if command -v flock >/dev/null 2>&1; then
  flock -n "$TMP/repo/logs/deploy.lock" sleep 10 &
  HOLDER=$!
  sleep 0.5
  run_case locked_run_skips '' GIT_DIFF=config.py
  expect_log locked_run_skips 'deploy already running'
  wait "$HOLDER" 2>/dev/null || true
else
  echo "SKIP lock cases: flock not installed"
fi
