#!/bin/bash
# Hands-off deploy: pull the tracked branch and restart bot+dashboard if HEAD moved.
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
DASHBOARD_SERVICE="${DEPLOY_DASHBOARD_SERVICE:-scalper-dashboard}"
LOG_DIR="${REPO_DIR}/logs"
mkdir -p "$LOG_DIR"

cd "$REPO_DIR"

git fetch "$REMOTE"
BEFORE="$(git rev-parse HEAD)"
TS="$(date -Is)"

# Stay on the deploy branch (create local tracking if needed)
if git show-ref --verify --quiet "refs/heads/${BRANCH}"; then
  git checkout "$BRANCH"
else
  git checkout -B "$BRANCH" "${REMOTE}/${BRANCH}"
fi

# Local edits (e.g. accidental script tweaks) block `git pull --ff-only`.
# Stash tracked changes so cron stays hands-off; do not auto-pop (avoids
# silent conflict noise). Untracked files (logs/, .env) are left alone.
if ! git diff --quiet || ! git diff --cached --quiet; then
  STASH_MSG="deploy-stash $(date -u +%Y%m%dT%H%M%SZ)"
  echo "$TS stashing local modifications before pull: $STASH_MSG" | tee -a "${LOG_DIR}/deploy.log"
  git stash push -m "$STASH_MSG" --quiet || true
fi

git pull --ff-only "$REMOTE" "$BRANCH"
AFTER="$(git rev-parse HEAD)"

# GitHub Contents API / some checkouts drop the executable bit on shell scripts.
chmod +x "${REPO_DIR}/deploy.sh" "${REPO_DIR}/scripts/paper_status_daily.sh" 2>/dev/null || true

if [ "$BEFORE" != "$AFTER" ]; then
  if command -v systemctl >/dev/null 2>&1; then
    systemctl restart "$SERVICE"
    if systemctl list-unit-files --type=service 2>/dev/null | grep -q "^${DASHBOARD_SERVICE}\.service"; then
      systemctl restart "$DASHBOARD_SERVICE" || true
    fi
    echo "$TS restarted ${SERVICE} (+ ${DASHBOARD_SERVICE} if present) at ${AFTER} (was ${BEFORE}) branch=${BRANCH}" | tee -a "${LOG_DIR}/deploy.log"
  else
    echo "$TS code updated to ${AFTER} but systemctl not found; restart ${SERVICE} manually" | tee -a "${LOG_DIR}/deploy.log"
  fi
else
  echo "$TS already up to date (${AFTER}) branch=${BRANCH}" >> "${LOG_DIR}/deploy.log"
fi
