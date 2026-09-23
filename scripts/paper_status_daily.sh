#!/bin/bash
# Append a timestamped paper-account snapshot for local audit trail.
# Grok daily-review cannot SSH; paste `python paper.py` into chat when you want
# numbers in HANDOFF. This script only keeps a server-side history.
#
# Cron example (once after London session, ~17:05 UTC = 01:05 KL next day):
#   5 17 * * 1-5 /root/scalper/scripts/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="${REPO_DIR}/logs"
mkdir -p "$LOG_DIR"
OUT="${LOG_DIR}/paper_daily.jsonl"
TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
PY="${REPO_DIR}/mt5env/bin/python"
if [ ! -x "$PY" ]; then
  PY="python3"
fi
JSON="$("$PY" "${REPO_DIR}/paper.py" 2>/dev/null || true)"
if [ -z "$JSON" ]; then
  echo "$TS paper.py failed or empty" >> "${LOG_DIR}/paper_status.cron.log"
  exit 1
fi
# One JSON object per line with ts field prepended via jq if available, else raw
if command -v jq >/dev/null 2>&1; then
  echo "$JSON" | jq -c --arg ts "$TS" '. + {ts: $ts}' >> "$OUT"
else
  echo "{\"ts\":\"$TS\",\"raw\":$(echo "$JSON" | tr -d '\n')}" >> "$OUT"
fi
echo "$TS ok -> $OUT"
