#!/usr/bin/env bash
# Regression test: the cron deploy must not start the BTC unit implicitly.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAKE_BIN="$TMP/bin"
mkdir -p "$FAKE_BIN" "$TMP/repo"
cp "$ROOT/deploy.sh" "$TMP/repo/deploy.sh"
chmod +x "$TMP/repo/deploy.sh"

cat > "$FAKE_BIN/git" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  fetch|checkout|pull) exit 0 ;;
  show-ref) exit 0 ;;
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
  restart) printf '%s\n' "$2" >> "$SYSTEMCTL_LOG" ;;
  *) echo "unexpected fake systemctl command: $*" >&2; exit 2 ;;
esac
SH
chmod +x "$FAKE_BIN/git" "$FAKE_BIN/systemctl"

run_case() {
  local name="$1" expected="$2"
  shift 2
  local calls="$TMP/${name}.calls"
  : > "$calls"
  rm -f "$TMP/git-count"
  env -u DEPLOY_SERVICES -u DEPLOY_SERVICE \
    PATH="$FAKE_BIN:$PATH" SYSTEMCTL_LOG="$calls" GIT_COUNT="$TMP/git-count" \
    "$@" "$TMP/repo/deploy.sh" >/dev/null
  local actual
  actual="$(paste -sd ' ' "$calls")"
  if [[ "$actual" != "$expected" ]]; then
    echo "FAIL $name: expected [$expected], got [$actual]" >&2
    exit 1
  fi
  echo "PASS $name: restarted [$actual]"
}

run_case default_gold_only scalper-bot
run_case explicit_phase2_opt_in 'scalper-bot scalper-btc-bot' \
  DEPLOY_SERVICES='scalper-bot scalper-btc-bot'
run_case legacy_singular_override scalper-btc-bot DEPLOY_SERVICE=scalper-btc-bot
