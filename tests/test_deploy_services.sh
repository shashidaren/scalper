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
PASSES=0            # checks passed; printed as the summary line at the end
mkdir -p "$FAKE_BIN" "$TMP/repo/logs"
cp "$ROOT/deploy.sh" "$TMP/repo/deploy.sh"
chmod +x "$TMP/repo/deploy.sh"

cat > "$FAKE_BIN/git" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  fetch)
    [[ "${GIT_FETCH_FAIL:-0}" == "1" ]] && { echo "fatal: unable to access 'origin': network unreachable" >&2; exit 128; }
    exit 0
    ;;
  checkout) exit 0 ;;
  pull)
    if [[ "${GIT_PULL_FAIL:-0}" == "1" ]]; then
      echo "error: Your local changes to the following files would be overwritten by merge:" >&2
      echo "	docker-compose.yml" >&2
      echo "Please commit your changes or stash them before you merge." >&2
      exit 1
    fi
    exit 0
    ;;
  status)
    [[ "${GIT_STATUS_FAIL:-0}" == "1" ]] && exit 3
    if [[ -n "${GIT_STATUS:-}" ]]; then printf '%s\n' "${GIT_STATUS}"; fi
    exit 0
    ;;
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
  set +e
  env -u DEPLOY_SERVICES -u DEPLOY_SERVICE \
    PATH="$FAKE_BIN:$PATH" SYSTEMCTL_LOG="$calls" GIT_COUNT="$TMP/git-count" \
    "$@" "$TMP/repo/deploy.sh" >/dev/null
  LAST_EXIT=$?
  set -e
  local actual
  actual="$(paste -sd ' ' "$calls")"
  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL $name: expected [$expected], got [$actual]" >&2
    exit 1
  fi
  PASSES=$((PASSES + 1))
  echo "PASS $name: restarted [$actual]"
}

expect_log() {
  local name="$1" fragment="$2"
  if ! grep -qF "$fragment" "$TMP/repo/logs/deploy.log"; then
    echo "FAIL $name: deploy.log does not contain [$fragment]" >&2
    cat "$TMP/repo/logs/deploy.log" >&2
    exit 1
  fi
  PASSES=$((PASSES + 1))
  echo "PASS $name: deploy.log records the decision"
}

expect_no_log() {
  local name="$1" fragment="$2"
  if grep -qF "$fragment" "$TMP/repo/logs/deploy.log"; then
    echo "FAIL $name: deploy.log unexpectedly contains [$fragment]" >&2
    cat "$TMP/repo/logs/deploy.log" >&2
    exit 1
  fi
  PASSES=$((PASSES + 1))
  echo "PASS $name: deploy.log has no [$fragment]"
}

expect_exit() {
  local name="$1" want="$2"
  if [[ "${LAST_EXIT:-}" != "$want" ]]; then
    echo "FAIL $name: expected exit $want, got ${LAST_EXIT:-<unset>}" >&2
    cat "$TMP/repo/logs/deploy.log" >&2
    exit 1
  fi
  PASSES=$((PASSES + 1))
  echo "PASS $name: exited $want"
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

# --- BTC units in DEPLOY_SERVICES (user decision 2026-10-07) ---------------
# Both BTC units keep running (observation on), so they are kept in sync with
# the code. They must NOT be treated as "unknown service => restart on every
# commit": a docs-only/BTC-tool-only commit leaves both alone.
run_case btc_runtime_commit_restarts_btc_bot_only 'scalper-btc-bot' \
  DEPLOY_SERVICES='scalper-bot scalper-dashboard scalper-btc-bot scalper-btc-dashboard' \
  GIT_DIFF='btc/strategy_btc.py'
run_case btc_config_restarts_btc_bot 'scalper-btc-bot' \
  DEPLOY_SERVICES='scalper-btc-bot' GIT_DIFF=btc/config.py
run_case gold_config_restarts_btc_bot_failsafe 'scalper-btc-bot' \
  DEPLOY_SERVICES='scalper-btc-bot' GIT_DIFF=config.py
run_case gold_tooling_skips_btc_bot '' \
  DEPLOY_SERVICES='scalper-btc-bot' GIT_DIFF='backtest.py'
run_case btc_dashboard_file_skips_btc_bot '' \
  DEPLOY_SERVICES='scalper-btc-bot' GIT_DIFF='btc/dashboard.py'
run_case btc_dashboard_commit_restarts_btc_dashboard_only 'scalper-btc-dashboard' \
  DEPLOY_SERVICES='scalper-btc-bot scalper-btc-dashboard' GIT_DIFF='btc/dashboard.py'
run_case docs_only_commit_skips_all_four '' \
  DEPLOY_SERVICES='scalper-bot scalper-dashboard scalper-btc-bot scalper-btc-dashboard' \
  GIT_DIFF=$'docs/cron_review_2026-10-07.md\nREADME.md'
run_case engine_commit_restarts_all_four 'scalper-bot scalper-dashboard scalper-btc-bot scalper-btc-dashboard' \
  DEPLOY_SERVICES='scalper-bot scalper-dashboard scalper-btc-bot scalper-btc-dashboard' \
  GIT_DIFF='config.py'

# --- silent-freeze regressions (2026-10-04 12:30 -> 2026-10-07 02:28) ------
# A dirty *tracked* file (server-side docker-compose.yml edit) blocked every
# `git pull --ff-only` for ~63 h / ~250 cron ticks while `set -e` exited before
# any log write, so nothing in logs/deploy.log said why. Two contracts now:
# the pre-check names the dirty file, and a failed pull leaves a PULL FAILED
# line in deploy.log, restarts nothing, and exits non-zero.
run_case dirty_tracked_file_warns_and_pulls scalper-bot \
  GIT_DIFF=config.py GIT_STATUS=' M docker-compose.yml'
expect_log dirty_tracked_file_warns_and_pulls 'DIRTY TREE'
expect_log dirty_tracked_file_warns_and_pulls 'docker-compose.yml'
expect_log dirty_tracked_file_warns_and_pulls 'restarted scalper-bot'
expect_exit dirty_tracked_file_warns_and_pulls 0

# Untracked files are normal on the server (logs/, data/*.csv, /root/ops) - no
# warning, and the deploy still runs.
run_case untracked_files_do_not_warn scalper-bot \
  GIT_DIFF=config.py GIT_STATUS=$'?? logs/deploy.lock\n?? data/BTCUSD_H1.csv'
expect_no_log untracked_files_do_not_warn 'DIRTY TREE'
expect_log untracked_files_do_not_warn 'restarted scalper-bot'

# The freeze itself: pull aborts -> PULL FAILED with git's own reason, the sha
# still running, no restart at all, exit 1.
run_case pull_failure_logs_gold_still_old '' \
  GIT_DIFF=config.py GIT_PULL_FAIL=1 GIT_STATUS=' M docker-compose.yml'
expect_log pull_failure_logs_gold_still_old 'PULL FAILED'
expect_log pull_failure_logs_gold_still_old 'would be overwritten'
expect_log pull_failure_logs_gold_still_old 'code NOT updated (still before)'
expect_exit pull_failure_logs_gold_still_old 1

# A failed fetch (network/auth) is the same class of silent stop.
run_case fetch_failure_logs '' GIT_FETCH_FAIL=1
expect_log fetch_failure_logs 'PULL FAILED'
expect_log fetch_failure_logs 'network unreachable'
expect_exit fetch_failure_logs 1

# A failing pre-check must not abort the deploy (git status is a warning only).
run_case status_failure_still_deploys scalper-bot \
  GIT_DIFF=config.py GIT_STATUS_FAIL=1
expect_log status_failure_still_deploys 'GIT STATUS FAILED'
expect_log status_failure_still_deploys 'restarted scalper-bot'
expect_exit status_failure_still_deploys 0

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

echo "ALL PASS: ${PASSES}/${PASSES} deploy-service checks"
