#!/bin/bash
# Hands-off deploy: pull the tracked branch and restart scalper-bot only if HEAD moved.
# Usage (from repo root or via absolute path):
#   ./deploy.sh
#   DEPLOY_BRANCH=main ./deploy.sh
# Cron example (every 15 min):
#   */15 * * * * /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRANCH="${DEPLOY_BRANCH:-arena/01a0a475-scalper}"
REMOTE="${DEPLOY_REMOTE:-origin}"
SERVICE="${DEPLOY_SERVICE:-scalper-bot}"
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
    systemctl restart "$SERVICE"
    echo "$TS restarted ${SERVICE} at ${AFTER} (was ${BEFORE}) branch=${BRANCH}" | tee -a "${LOG_DIR}/deploy.log"
  else
    echo "$TS code updated to ${AFTER} but systemctl not found; restart ${SERVICE} manually" | tee -a "${LOG_DIR}/deploy.log"
  fi
else
  echo "$TS already up to date (${AFTER}) branch=${BRANCH}" >> "${LOG_DIR}/deploy.log"
fi
