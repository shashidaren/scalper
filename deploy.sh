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
#
# Failure reporting: a dirty *tracked* file is warned about before the pull and
# a failed fetch/checkout/pull logs one `PULL FAILED:` line (plus the git
# output) into logs/deploy.log, then exits 1. It never restarts anything on a
# failed pull, and it never leaves an update silently un-applied.
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
# Logging + pull-failure reporting. Every line below goes to logs/deploy.log
# (the file the runbook and btc/server_check.py read) AND to stdout, which the
# cron redirect appends to logs/deploy.cron.log. Historically a failed pull was
# invisible in deploy.log: `set -e` aborted the script before any log write, so
# only the cron redirect had a trace and every later tick failed identically.
# That is exactly how a dirty tracked `docker-compose.yml` froze all deploys
# from 2026-10-04 12:30 to 2026-10-07 02:28 UTC (~63 h, ~250 ticks) while the
# bot kept running 2026-10-04-era code. A pull that fails now logs one distinct
# `PULL FAILED:` line naming the reason and the sha the box is still running.
# ---------------------------------------------------------------------------
log_line() {
  printf '%s %s\n' "$(date -Is)" "$*" | tee -a "${LOG_DIR}/deploy.log"
}

log_block() {   # tag, multiline text -> one tagged line each
  local tag="$1" text="$2" line
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    printf '%s %s: %s\n' "$(date -Is)" "$tag" "$line"
  done <<< "$text" | tee -a "${LOG_DIR}/deploy.log"
}

pull_failed() {   # reason, current sha, captured git output
  local reason="$1" sha="$2" out="$3" first
  # Prefer git's actual complaint over the fetch preamble ("From https://…").
  first="$(printf '%s\n' "$out" | grep -m1 -iE '(^|[[:space:]])(error|fatal):' || true)"
  [ -n "$first" ] || first="$(printf '%s\n' "$out" | grep -m1 -v '^[[:space:]]*$' || true)"
  log_line "PULL FAILED: ${reason} - code NOT updated (still ${sha}); reason: ${first:-unknown}"
  log_block "PULL FAILED detail" "$out"
  exit 1
}

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
#  * scalper-btc-bot is the SAME engine under btc/config.py (btc/run.py): every
#    shared engine module is a runtime input, plus btc/config.py, btc/run.py,
#    btc/strategy_btc.py and btc/_instance.py. Gold's config.py is shadowed by
#    btc/config.py in that process, but it is left restart-worthy on purpose
#    (fail safe, same as btc/config.py for gold). The gold dashboard, gold-only
#    tooling and every other btc/ tool are inert for it.
#  * scalper-btc-dashboard mirrors scalper-dashboard under btc/ (btc/dashboard.py
#    + btc/config.py + the shared viewer modules + templates/).
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
    scalper-btc-bot)
      case "$path" in
        btc/dashboard.py|dashboard.py|templates/*) return 0 ;;
        backtest.py|fetch_data.py|gold.py|balance.py) return 0 ;;
      esac
      ;;
    scalper-btc-dashboard)
      case "$path" in
        btc/dashboard.py|btc/config.py|dashboard.py|config.py|logger.py|portfolio.py|templates/*) return 1 ;;
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

# ---------------------------------------------------------------------------
# Pre-flight: a modified *tracked* file is the classic silent freeze. `git pull
# --ff-only` then aborts ("local changes ... would be overwritten by merge") on
# this and every later tick; the bot keeps running old code and fix #22/#23/#24
# never reach memory. Warn loudly, and keep going - the pull below reports its
# own failure with a PULL FAILED line if the dirty file really blocks it.
# Untracked files (logs/, *.csv, server-only scripts) are normal and ignored.
# Server-only compose tweaks belong in docker-compose.override.yml (Compose
# merges it automatically); keep the tracked docker-compose.yml clean.
# ---------------------------------------------------------------------------
DIRTY_TRACKED=""
if STATUS_OUT="$(git status --porcelain 2>/dev/null)"; then
  DIRTY_TRACKED="$(printf '%s\n' "$STATUS_OUT" | grep -vE '^$|^\?\?' || true)"
else
  log_line "GIT STATUS FAILED in ${REPO_DIR} - cannot pre-check for dirty tracked files"
fi
if [ -n "$DIRTY_TRACKED" ]; then
  log_line "DIRTY TREE: modified tracked file(s) - a fast-forward pull will abort until this is resolved: $(printf '%s' "$DIRTY_TRACKED" | tr '\n' ' ')"
  log_line "DIRTY TREE fix: git -C ${REPO_DIR} stash push -m deploy-preflight   (or 'git checkout -- <file>'); server-only compose tweaks go in docker-compose.override.yml, which is NOT tracked"
fi

BEFORE="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

if ! GIT_OUT="$(git fetch "$REMOTE" 2>&1)"; then
  pull_failed "git fetch ${REMOTE} failed" "$BEFORE" "$GIT_OUT"
fi
if [ -n "$GIT_OUT" ]; then printf '%s\n' "$GIT_OUT"; fi

# Stay on the deploy branch (create local tracking if needed)
if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  if ! GIT_OUT="$(git checkout "$BRANCH" 2>&1)"; then
    pull_failed "git checkout ${BRANCH} failed" "$BEFORE" "$GIT_OUT"
  fi
else
  if ! GIT_OUT="$(git checkout -B "$BRANCH" "${REMOTE}/${BRANCH}" 2>&1)"; then
    pull_failed "git checkout -B ${BRANCH} ${REMOTE}/${BRANCH} failed" "$BEFORE" "$GIT_OUT"
  fi
fi
if [ -n "$GIT_OUT" ]; then printf '%s\n' "$GIT_OUT"; fi

if ! GIT_OUT="$(git pull --ff-only "$REMOTE" "$BRANCH" 2>&1)"; then
  pull_failed "git pull --ff-only ${REMOTE} ${BRANCH} failed" "$BEFORE" "$GIT_OUT"
fi
if [ -n "$GIT_OUT" ]; then printf '%s\n' "$GIT_OUT"; fi
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
