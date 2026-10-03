#!/bin/bash
# Hands-off deploy: pull the tracked branch and restart scalper-bot only if HEAD moved.
# Usage (from repo root or via absolute path):
#   ./deploy.sh
#   DEPLOY_BRANCH=main ./deploy.sh
# Cron example (every 15 min):
#   */15 * * * * /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1
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
    RESTARTED=""
    for svc in $SERVICES; do
      if systemctl cat "$svc" >/dev/null 2>&1; then
        systemctl restart "$svc" && RESTARTED="${RESTARTED}${RESTARTED:+ }${svc}"
      else
        echo "$TS note: unit ${svc} not installed - skipped" >> "${LOG_DIR}/deploy.log"
      fi
    done
    echo "$TS restarted ${RESTARTED:-<none>} at ${AFTER} (was ${BEFORE}) branch=${BRANCH}" | tee -a "${LOG_DIR}/deploy.log"
  else
    echo "$TS code updated to ${AFTER} but systemctl not found; restart ${SERVICES} manually" | tee -a "${LOG_DIR}/deploy.log"
  fi
else
  echo "$TS already up to date (${AFTER}) branch=${BRANCH}" >> "${LOG_DIR}/deploy.log"
fi
