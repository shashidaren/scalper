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
#   Does NOT require jq (uses repo python).
#
# Cron (after London/NY, weekdays):
#   5 17 * * 1-5 /root/scalper/scripts/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1
# Optional morning snap before KL review (01:00 UTC = 09:00 Asia/KL):
#   0 1 * * 1-5 /root/scalper/scripts/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1
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

if [ -f "${REPO_DIR}/.env.paper_status" ]; then
  set -a
  # shellcheck source=/dev/null
  . "${REPO_DIR}/.env.paper_status"
  set +a
fi

RAW="$("$PY" "${REPO_DIR}/paper.py" 2>/dev/null || true)"
if [ -z "$RAW" ]; then
  echo "$TS paper.py failed or empty" | tee -a "${LOG_DIR}/paper_status.cron.log"
  exit 1
fi

# Merge ts/source into paper.py JSON without jq
SNAP="$("$PY" -c "
import json,sys
raw = json.loads(sys.stdin.read())
if not isinstance(raw, dict):
    raw = {'raw': raw}
raw['ts'] = sys.argv[1]
raw['source'] = 'paper_status_daily'
print(json.dumps(raw))
" "$TS" <<<"$RAW")"

echo "$SNAP" | "$PY" -c "import json,sys; json.dump(json.load(sys.stdin), sys.stdout, indent=2); print()" > "$OUT_LATEST"
echo "$SNAP" >> "$OUT_JSONL"
echo "$TS ok -> $OUT_LATEST (+ jsonl)"

TOKEN="${PAPER_STATUS_TOKEN:-${GITHUB_TOKEN:-}}"
OWNER="${PAPER_STATUS_OWNER:-shashidaren}"
REPO="${PAPER_STATUS_REPO:-scalper}"
BRANCH="${PAPER_STATUS_BRANCH:-status/paper}"
PATH_IN_REPO="status/paper_latest.json"
API="https://api.github.com/repos/${OWNER}/${REPO}/contents/${PATH_IN_REPO}"

if [ -z "$TOKEN" ]; then
  echo "$TS skip GitHub publish (set PAPER_STATUS_TOKEN in /root/scalper/.env.paper_status)"
  exit 0
fi

CONTENT_B64="$(base64 -w0 < "$OUT_LATEST" 2>/dev/null || base64 < "$OUT_LATEST" | tr -d '\n')"
MSG="paper status ${TS}"

HTTP_BODY="$(curl -sS -H "Authorization: Bearer ${TOKEN}" -H "Accept: application/vnd.github+json" \
  "${API}?ref=${BRANCH}" || true)"

PAYLOAD="$("$PY" -c "
import json,sys
sha=''
try:
    body=json.loads(sys.argv[1])
    if isinstance(body, dict):
        sha=body.get('sha') or ''
except Exception:
    pass
payload={
    'message': sys.argv[2],
    'content': sys.argv[3],
    'branch': sys.argv[4],
}
if sha:
    payload['sha']=sha
print(json.dumps(payload))
" "$HTTP_BODY" "$MSG" "$CONTENT_B64" "$BRANCH")"

RESP="$(curl -sS -X PUT \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Accept: application/vnd.github+json" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD" \
  "$API")"

OK="$("$PY" -c "
import json,sys
try:
    r=json.loads(sys.argv[1])
except Exception:
    print('0'); raise SystemExit
print('1' if isinstance(r, dict) and isinstance(r.get('content'), dict) and r['content'].get('path') else '0')
" "$RESP")"

if [ "$OK" = "1" ]; then
  echo "$TS published ${OWNER}/${REPO}@${BRANCH}:${PATH_IN_REPO}"
else
  echo "$TS GitHub publish failed: $RESP" | tee -a "${LOG_DIR}/paper_status.cron.log"
  exit 1
fi
