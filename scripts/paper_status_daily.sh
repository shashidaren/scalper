#!/bin/bash
# Snapshot paper account for audit + optional publish for daily-review (no SSH).
#
# Always:
#   logs/paper_latest.json  — latest snapshot (overwrite)
#   logs/paper_daily.jsonl  — append-only history
#
# Optional publish (so Grok daily-review can read without you pasting):
#   Set PAPER_STATUS_TOKEN to a fine-grained PAT with Contents: Read/Write
#   on this repo only. Publishes status/paper_latest.json on branch status/paper.
#
# Cron (after London/NY, weekdays) — local only:
#   5 17 * * 1-5 /root/scalper/scripts/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1
#
# Cron with GitHub publish (no more manual paste for daily review):
#   5 17 * * 1-5 PAPER_STATUS_TOKEN=ghp_xxx /root/scalper/scripts/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1
# Or source a root-only file:
#   5 17 * * 1-5 . /root/scalper/.env.paper_status && /root/scalper/scripts/paper_status_daily.sh >> ...
#
# Optional second snap just before KL morning review (01:00 UTC = 09:00 KL):
#   0 1 * * 1-5 ... same script ...
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"
mkdir -p "$LOG_DIR"
OUT_JSONL="${LOG_DIR}/paper_daily.jsonl"
OUT_LATEST="${LOG_DIR}/paper_latest.json"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PY="${REPO_DIR}/mt5env/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi

# Load optional token file (never commit this file)
if [ -f "${REPO_DIR}/.env.paper_status" ]; then
  # shellcheck disable=SC1091
  set -a
  # shellcheck source=/dev/null
  . "${REPO_DIR}/.env.paper_status"
  set +a
fi

RAW="$("$PY" "${REPO_DIR}/paper.py" 2>/dev/null || true)"
if [ -z "$RAW" ]; then
  echo "$TS paper.py failed or empty" >> "${LOG_DIR}/paper_status.cron.log"
  exit 1
fi

# Build snapshot JSON with ts (jq preferred)
if command -v jq >/dev/null 2>&1; then
  SNAP="$(echo "$RAW" | jq -c --arg ts "$TS" '. + {ts: $ts, source: "paper_status_daily"}')"
  echo "$SNAP" | jq '.' > "$OUT_LATEST"
  echo "$SNAP" >> "$OUT_JSONL"
else
  # Minimal fallback without jq
  SNAP="{\"ts\":\"$TS\",\"source\":\"paper_status_daily\",\"raw\":$(echo "$RAW" | tr -d '\n')}"
  echo "$SNAP" > "$OUT_LATEST"
  echo "$SNAP" >> "$OUT_JSONL"
fi

echo "$TS ok -> $OUT_LATEST (+ jsonl)"

# --- Optional: publish to GitHub status/paper for daily-review ---
TOKEN="${PAPER_STATUS_TOKEN:-${GITHUB_TOKEN:-}}"
OWNER="${PAPER_STATUS_OWNER:-shashidaren}"
REPO="${PAPER_STATUS_REPO:-scalper}"
BRANCH="${PAPER_STATUS_BRANCH:-status/paper}"
PATH_IN_REPO="status/paper_latest.json"
API="https://api.github.com/repos/${OWNER}/${REPO}/contents/${PATH_IN_REPO}"

if [ -z "$TOKEN" ]; then
  echo "$TS skip GitHub publish (set PAPER_STATUS_TOKEN or GITHUB_TOKEN)"
  exit 0
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "$TS skip GitHub publish (jq required)"
  exit 0
fi

CONTENT_B64="$(base64 -w0 < "$OUT_LATEST" 2>/dev/null || base64 < "$OUT_LATEST" | tr -d '\n')"
MSG="paper status ${TS}"

# Existing blob SHA (required for update)
SHA=""
HTTP_BODY="$(curl -sS -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/vnd.github+json" \
  "${API}?ref=${BRANCH}" || true)"
if echo "$HTTP_BODY" | jq -e '.sha' >/dev/null 2>&1; then
  SHA="$(echo "$HTTP_BODY" | jq -r '.sha')"
fi

PAYLOAD="$(jq -n \
  --arg msg "$MSG" \
  --arg content "$CONTENT_B64" \
  --arg branch "$BRANCH" \
  --arg sha "$SHA" \
  'if $sha != "" then {message:$msg, content:$content, branch:$branch, sha:$sha}
   else {message:$msg, content:$content, branch:$branch} end')"

RESP="$(curl -sS -X PUT \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$API")"

if echo "$RESP" | jq -e '.content.path' >/dev/null 2>&1; then
  echo "$TS published ${OWNER}/${REPO}@${BRANCH}:${PATH_IN_REPO}"
else
  echo "$TS GitHub publish failed: $(echo "$RESP" | jq -c '.' 2>/dev/null || echo "$RESP")" >> "${LOG_DIR}/paper_status.cron.log"
  exit 1
fi
