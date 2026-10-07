#!/bin/bash
# Hands-off deploy: pull the tracked branch and restart only the services whose
# runtime code actually changed.
#
# Usage (from repo root or via absolute path):
#   ./deploy.sh
#   DEPLOY_BRANCH=main ./deploy.sh
#   DEPLOY_SERVICES="scalper-bot scalper-dashboard" ./deploy.sh
#   DEPLOY_FORCE_RESTART=1 ./deploy.sh            # ignore the changed-path filter
#
# Cron example (every 15 min; `mkdir -p` first so the redirect cannot silently
# fail before this script gets a chance to create logs/ itself):
#   */15 * * * * mkdir -p /root/scalper/logs && DEPLOY_BRANCH=main /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1
#
# Env:
#   DEPLOY_BRANCH        branch to check out / fast-forward (default: main)
#   DEPLOY_REMOTE        git remote (default: origin)
#   DEPLOY_SERVICES      space-separated systemd units to restart
#                        (default: scalper-bot; DEPLOY_SERVICE still works)
#   DEPLOY_FORCE_RESTART 1 = restart regardless of which paths changed
#   DEPLOY_LOCK_FILE     lock file (default: <repo>/logs/deploy.lock)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="${DEPLOY_BRANCH:-main}"
REMOTE="${DEPLOY_REMOTE:-origin}"
# One or more services, space separated. DEPLOY_SERVICE (singular) still works
# for back-compat with the existing cron. Default to gold only: `systemctl
# restart` starts a disabled-but-installed unit, so BTC must be an explicit
# opt-in after its Phase 1 gate and paper-deployment authorization.
SERVICES="${DEPLOY_SERVICES:-${DEPLOY_SERVICE:-scalper-bot}}"
LOG_DIR="${REPO_DIR}/logs"
mkdir -p "$LOG_DIR"

# ---------------------------------------------------------------------------
# Single-instance lock. The cron fires every 15 min while `systemctl restart`
# can block in ExecStartPre (wait_for_mt5.py, --timeout 180) if the MT5 bridge
# is down, so two runs could otherwise overlap and double-restart the book.
# ---------------------------------------------------------------------------
LOCK_FILE="${DEPLOY_LOCK_FILE:-${LOG_DIR}/deploy.lock}"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  if ! flock -n 9; then
    echo "$(date -Is) deploy already running (lock ${LOCK_FILE}) - skipped" >> "${LOG_DIR}/deploy.log"
    exit 0
  fi
fi

# ---------------------------------------------------------------------------
# Restart policy: restart is the default. A service is skipped only when EVERY
# path that changed is provably not a runtime input for it (allowlist below) -
# an empty diff, a git error, or any unrecognised path restarts. A restart also
# re-arms in-memory-only state (strategy one-shot-per-bar guard, spread-gate
# counters, stale-tick counters), which is why a BTC-only commit must not
# restart the gold book mid-session.
#
#  * docs/, research/, tests/, *.md  - never imported by a service
#  * deploy.sh                       - the cron's own script, not runtime
#  * scalper-bot (gold engine): btc/ is a separate instance with its own
#    config/sys.path, EXCEPT btc/config.py: the shared portfolio gate reads its
#    MAX_DAILY_LOSS / MAX_TRADES_PER_DAY through portfolio.py::_btc_config().
#  * scalper-dashboard is a read-only viewer: only dashboard.py, config.py,
#    logger.py, portfolio.py and templates/ are runtime inputs (templates/ is
#    re-read per request by Jinja; dashboard.py is NOT - uvicorn holds it).
# ---------------------------------------------------------------------------
is_inert_for() {
  local svc="$1" path="$2"
  case "$path" in
    docs/*|research/*|tests/*|*.md|deploy.sh) return 0 ;;
  esac
  case "$svc" in
    scalper-bot)
      case "$path" in
        btc/config.py) return 1 ;;
        btc/*) return 0 ;;
        backtest.py|fetch_data.py|gold.py|balance.py|dashboard.py|templates/*) return 0 ;;
      esac
      ;;
    scalper-dashboard)
      case "$path" in
        dashboard.py|config.py|logger.py|portfolio.py|templates/*) return 1 ;;
        *) return 0 ;;
      esac
      ;;
  esac
  return 1
}

restart_needed() {
  local svc="$1" changed="$2" f
  [ "${DEPLOY_FORCE_RESTART:-0}" = "1" ] && return 0
  [ -n "$changed" ] || return 0          # no/undiffable change: fail safe
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    is_inert_for "$svc" "$f" || return 0
  done <<< "$changed"
  return 1
}

has_service() {
  local s
  for s in $SERVICES; do
    [ "$s" = "$1" ] && return 0
  done
  return 1
}

dashboard_relevant_paths() {
  local f out=""
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    case "$f" in
      dashboard.py|config.py|logger.py|portfolio.py|templates/*) out="${out}${f} " ;;
    esac
  done <<< "$1"
  printf '%s' "$out"
}

cd "$REPO_DIR"

git fetch "$REMOTE"
BEFORE="$(git rev-parse HEAD)"

# Stay on the deploy branch (create local tracking if needed)
if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  git checkout "$BRANCH"
else
  git checkout -B "$BRANCH" "${REMOTE}/${BRANCH}"
fi

git pull --ff-only "$REMOTE" "$BRANCH"
AFTER="$(git rev-parse HEAD)"
TS="$(date -Is)"

if [ "$BEFORE" != "$AFTER" ]; then
  if command -v systemctl >/dev/null 2>&1; then
    # What actually changed in this pull (empty on a git error: fail safe ->
    # restart, the pre-2026-10-07 behaviour).
    CHANGED="$(git diff --name-only "$BEFORE" "$AFTER" 2>/dev/null || true)"
    RESTARTED=""
    SKIPPED=""
    FAILED=""
    for svc in $SERVICES; do
      if systemctl cat "$svc" >/dev/null 2>&1; then
        if restart_needed "$svc" "$CHANGED"; then
          if systemctl restart "$svc"; then
            RESTARTED="${RESTARTED}${RESTARTED:+ }${svc}"
          else
            # Reported below instead of aborting: the remaining services still
            # get their restart decision, and the failure is unmistakable.
            FAILED="${FAILED}${FAILED:+ }${svc}"
          fi
        else
          SKIPPED="${SKIPPED}${SKIPPED:+ }${svc}"
        fi
      else
        echo "$TS note: unit ${svc} not installed - skipped" >> "${LOG_DIR}/deploy.log"
      fi
    done
    MSG=""
    if [ -n "$RESTARTED" ]; then
      MSG="restarted ${RESTARTED} at ${AFTER} (was ${BEFORE}) branch=${BRANCH}"
    fi
    if [ -n "$SKIPPED" ]; then
      MSG="${MSG}${MSG:+; }restart skipped for ${SKIPPED} (no runtime path changed)"
    fi
    if [ -n "$FAILED" ]; then
      MSG="${MSG}${MSG:+; }RESTART FAILED for ${FAILED} - check systemctl status"
    fi
    if [ -z "$MSG" ]; then
      MSG="code updated to ${AFTER} (was ${BEFORE}) but no configured unit is installed; nothing restarted"
    fi
    echo "$TS $MSG" | tee -a "${LOG_DIR}/deploy.log"

    # Visibility: dashboard.py fixes only reach :8088 when that unit is
    # restarted (templates/ hot-reload, imported modules do not).
    DASH_CHANGED="$(dashboard_relevant_paths "$CHANGED")"
    if [ -n "$DASH_CHANGED" ] && ! has_service scalper-dashboard; then
      echo "$TS note: dashboard-relevant change (${DASH_CHANGED% }) but scalper-dashboard is not in DEPLOY_SERVICES - restart it manually or opt in" \
        | tee -a "${LOG_DIR}/deploy.log"
    fi
  else
    echo "$TS code updated to ${AFTER} but systemctl not found; restart ${SERVICES} manually" | tee -a "${LOG_DIR}/deploy.log"
  fi
else
  echo "$TS already up to date (${AFTER}) branch=${BRANCH}" >> "${LOG_DIR}/deploy.log"
fi
