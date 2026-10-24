#!/bin/bash
# One-command fresh GOLD M5 pull with automatic hash + date-range logging.
# Usage (from repo root or anywhere):
#   ./tools/pull_gold_m5.sh
#   ./tools/pull_gold_m5.sh --bars 60000
# Later this can be put on a weekly cron; for now it is manual but no longer multi-step.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Activate the same venv the bot uses if it exists
if [[ -f mt5env/bin/activate ]]; then
  # shellcheck source=/dev/null
  source mt5env/bin/activate
fi

BARS=60000
OUT="data/GOLD_M5.csv"
LOG="data/pull_log.txt"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bars) BARS="$2"; shift 2 ;;
    --out)  OUT="$2";  shift 2 ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

mkdir -p "$(dirname "$OUT")" data

echo "Pulling $BARS M5 bars for GOLD → $OUT …"
python fetch_data.py --symbol GOLD --timeframe M5 --bars "$BARS" --out "$OUT"

if [[ ! -f "$OUT" ]]; then
  echo "ERROR: $OUT was not created" >&2
  exit 1
fi

HASH=$(sha256sum "$OUT" | awk '{print $1}')
# Use python so we get the real first/last timestamps regardless of locale
read -r START END BARS_ACTUAL <<< "$(python -c "
import pandas as pd
df = pd.read_csv('$OUT', parse_dates=['time'])
print(df['time'].iloc[0], df['time'].iloc[-1], len(df))
")"

TIMESTAMP=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "$TIMESTAMP  sha256=$HASH  bars=$BARS_ACTUAL  $START → $END  file=$OUT" | tee -a "$LOG"

echo
echo "=== Pull complete ==="
echo "File   : $OUT"
echo "SHA256 : $HASH"
echo "Range  : $START → $END"
echo "Bars   : $BARS_ACTUAL"
echo "Logged : $LOG"
echo
echo "Copy the hash + range into the active research plan before running any sweep."
