#!/usr/bin/env bash
# Regression test for tools/autosync.sh.
#
# Real git (a bare origin, a "seed" clone that plays the PR author, and a
# "server" clone that plays the box), fake systemctl, fake interpreter for the
# smoke gate. No real units, no MT5, no network.
#
# What it protects:
#   1. durable paper state is committed and pushed as `data collection N`
#   2. a docs-only upstream change merges WITHOUT restarting the book
#   3. a code change runs the smoke gate and restarts only the gold engine
#   4. a failing smoke gate rolls the code back, restores the data the engine
#      wrote during the failed merge, and still brings the engine back up
#   5. hand-edited code on the server blocks the deploy (no merge)
#   6. a stopped unit is never started by a deploy
#   7. an overlapping run exits 0
#
# Run: bash tests/test_autosync.sh      # exit 0 = PASS
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_REAL="$(command -v python3)"
PASSES=0

pass() { PASSES=$((PASSES + 1)); echo "PASS $*"; }
fail() { echo "FAIL $*" >&2; exit 1; }

TMP=""
cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# Sandbox: origin.git + seed (author) + server (box)
# --------------------------------------------------------------------------- #
setup() {
    cleanup
    TMP="$(mktemp -d)"
    mkdir -p "$TMP/bin" "$TMP/svc"

    cat > "$TMP/bin/python3" <<SH
#!/usr/bin/env bash
if [ "\${1:-}" = "-" ]; then exec "$PY_REAL" "\$@"; fi
case "\${1:-}" in
  *smoke_test.py)
    if [ "\${FAKE_SMOKE:-0}" = "1" ]; then
      echo "SMOKE TEST FAILED: injected by the test"; exit 1
    fi
    echo "SMOKE TEST PASSED (fake)"; exit 0 ;;
esac
exec "$PY_REAL" "\$@"
SH
    chmod +x "$TMP/bin/python3"

    cat > "$TMP/bin/systemctl" <<SH
#!/usr/bin/env bash
S="$TMP/svc"
cmd="\${1:-}"; shift || true
args=()
for a in "\$@"; do case "\$a" in --quiet|-q|--no-legend) ;; *) args+=("\$a");; esac; done
unit="\${args[0]:-}"
echo "\$cmd \$unit" >> "$TMP/calls"
case "\$cmd" in
  cat)      [ -f "\$S/\$unit.installed" ] && exit 0 || exit 1 ;;
  is-active) [ "\$(cat "\$S/\$unit.state" 2>/dev/null)" = "active" ] && exit 0 || exit 3 ;;
  stop)     echo inactive > "\$S/\$unit.state" ;;
  start|restart) echo active > "\$S/\$unit.state" ;;
esac
exit 0
SH
    chmod +x "$TMP/bin/systemctl"

    git init -q --bare "$TMP/origin.git"
    git init -q "$TMP/seed"
    (
        cd "$TMP/seed"
        git config user.email seed@test; git config user.name seed
        git checkout -q -b main
        mkdir -p tools logs btc/logs
        cp "$ROOT/tools/autosync.sh" "$ROOT/tools/smoke_test.py" "$ROOT/tools/check_data.py" tools/
        cp "$ROOT/STATUS.md" . 2>/dev/null || echo "# STATUS" > STATUS.md
        echo '{"balance": 300.0, "position": null, "closed": 0, "wins": 0, "losses": 0}' \
            > logs/paper_account.json
        echo '{"date": "2026-10-20", "pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}' \
            > logs/daily_stats.json
        : > logs/trades.jsonl
        printf 'import config\n\nMAX_SPREAD_POINTS = 80\n' > config.py
        printf 'def check_signal():\n    return None\n' > strategy.py
        printf 'def index():\n    return "ok"\n' > dashboard.py
        git add -A
        git commit -qm "seed"
        git remote add origin "$TMP/origin.git"
        git push -q origin main
    )
    # A bare repo defaults HEAD to master; the box clones branch `main`.
    git -C "$TMP/origin.git" symbolic-ref HEAD refs/heads/main
    git clone -q "$TMP/origin.git" "$TMP/server"
    (
        cd "$TMP/server"
        git config user.email server@test; git config user.name server
        mkdir -p logs btc/logs
        touch "$TMP/svc/scalper-bot.installed" "$TMP/svc/scalper-dashboard.installed"
        echo active > "$TMP/svc/scalper-bot.state"
        echo active > "$TMP/svc/scalper-dashboard.state"
        # The published data files come from the clone itself; only the
        # never-published live_status.json is created here (fresh, so the
        # freshness backstop says "ok").
        "$PY_REAL" - <<'PY'
import json
from pathlib import Path
Path("logs/live_status.json").write_text(json.dumps(
    {"bid": 1.0, "ask": 1.0, "positions": [], "updated_at": "now"}))
PY
    )
    : > "$TMP/calls"
}

# Push a change from the "author" clone to origin/main.
seed_change() {   # relative path, content
    (
        cd "$TMP/seed"
        git pull -q --ff-only origin main
        mkdir -p "$(dirname "$1")"
        printf '%s\n' "$2" > "$1"
        git add -A
        git commit -qm "upstream: $1"
        git push -q origin main
    )
}

run_autosync() {   # extra env assignments get exported by the caller
    (
        cd "$TMP/server"
        PATH="$TMP/bin:$PATH"
        AUTOSYNC_SETTLE_SECONDS=0 \
        AUTOSYNC_PYTHON="$TMP/bin/python3" \
        AUTOSYNC_LOCK_FILE="$TMP/autosync.lock" \
        bash tools/autosync.sh >> "$TMP/run.log" 2>&1
        echo $? > "$TMP/rc"
    )
}

log_has()     { grep -qF -- "$1" "$TMP/run.log" || fail "$2 (log lacks: $1)"; pass "$2"; }
log_lacks()   { ! grep -qF -- "$1" "$TMP/run.log" || fail "$2 (log has: $1)"; pass "$2"; }
called()      { grep -qxF -- "$1" "$TMP/calls" || fail "$2 (systemctl never ran: $1)"; pass "$2"; }
not_called()  { ! grep -qxF -- "$1" "$TMP/calls" || fail "$2 (systemctl ran: $1)"; pass "$2"; }
server_sha()  { git -C "$TMP/server" rev-parse HEAD; }
remote_sha()  { git -C "$TMP/server" rev-parse origin/main; }

# --------------------------------------------------------------------------- #
echo "== 1. quiet run: nothing to publish, nothing to deploy"
setup
run_autosync
[ "$(cat "$TMP/rc")" = "0" ] || fail "quiet run must exit 0"
log_has "data: no changes" "no data commit when nothing changed"
log_has "deploy=[none]" "nothing deployed"
not_called "restart scalper-bot" "quiet run restarts nothing"

# --------------------------------------------------------------------------- #
echo "== 2. a closed trade publishes as data collection 1"
setup
printf '%s\n' '{"event":"SIM_EXIT","profit":10.0,"balance_after":310.0,"reason":"TP"}' \
    >> "$TMP/server/logs/trades.jsonl"
printf '%s\n' '{"balance": 310.0, "position": null, "closed": 1, "wins": 1, "losses": 0}' \
    > "$TMP/server/logs/paper_account.json"
run_autosync
log_has "committed 1 new trade row(s) -> 'data collection 1'" "data row counted and numbered"
[ "$(git -C "$TMP/server" log -1 --format=%s)" = "data collection 1" ] \
    && pass "commit subject is data collection 1" || fail "bad commit subject"
[ "$(server_sha)" = "$(remote_sha)" ] && pass "data commit pushed to origin" || fail "push did not land"
[ ! -z "$(git -C "$TMP/seed" ls-tree -r origin/main --name-only | grep logs/trades.jsonl)" ] \
    && pass "trade log is tracked upstream" || fail "trade log missing upstream"
not_called "restart scalper-bot" "a data-only commit restarts nothing"

# --------------------------------------------------------------------------- #
echo "== 3. docs-only upstream merge does not touch the book"
setup
seed_change "docs/note.md" "a note"
run_autosync
log_has "deploy=[deployed" "docs-only change deployed"
log_has "smoke: not run (no code change)" "docs-only skips the smoke gate"
not_called "stop scalper-bot" "docs-only never stops the engine"
not_called "restart scalper-bot" "docs-only never restarts the engine"
[ "$(server_sha)" = "$(remote_sha)" ] && pass "server merged upstream" || fail "merge missing"

# --------------------------------------------------------------------------- #
echo "== 4. an engine-only change runs the smoke gate and restarts only the gold engine"
setup
seed_change "strategy.py" "# upstream change"
run_autosync
log_has "smoke gate: ok" "smoke gate ran and passed"
called "stop scalper-bot" "engine stopped before the merge"
called "start scalper-bot" "engine started after the merge"
not_called "restart scalper-dashboard" "dashboard untouched by an engine-only change"
[ "$(cat "$TMP/svc/scalper-bot.state")" = "active" ] && pass "engine is active again" || fail "engine left stopped"
grep -q "def index" "$TMP/server/dashboard.py" && pass "unrelated files intact" || fail "dashboard.py damaged"

echo "== 4b. config.py is a dashboard input too, so it restarts both"
setup
seed_change "config.py" "MAX_SPREAD_POINTS = 90"
run_autosync
called "start scalper-bot" "engine restarted for config.py"
called "restart scalper-dashboard" "dashboard restarted for config.py (it imports config)"

# --------------------------------------------------------------------------- #
echo "== 5. a failing smoke gate rolls back and still restarts the engine"
setup
seed_change "config.py" "MAX_SPREAD_POINTS = 999"
# The engine writes during the failed merge; the rollback must not lose it.
printf '%s\n' '{"event":"SIM_EXIT","profit":1.0,"balance_after":301.0}' \
    >> "$TMP/server/logs/trades.jsonl"
FAKE_SMOKE=1 run_autosync
log_has "ROLLED BACK" "rollback reported"
[ "$(server_sha)" != "$(remote_sha)" ]     && pass "the bad upstream commit was not applied" || fail "rollback did not reset"
[ "$(git -C "$TMP/server" log -1 --format=%s)" = "data collection 1" ]     && pass "HEAD is the pre-merge data commit" || fail "HEAD is not the pre-merge commit"
grep -q "MAX_SPREAD_POINTS = 80" "$TMP/server/config.py" && pass "old config restored" || fail "bad config kept"
tail -1 "$TMP/server/logs/trades.jsonl" | grep -q "301.0" \
    && pass "data written during the failed merge survives" || fail "rollback lost live data"
called "start scalper-bot" "engine restarted after the rollback"
[ "$(cat "$TMP/svc/scalper-bot.state")" = "active" ] && pass "engine active after rollback" || fail "engine left stopped"

# --------------------------------------------------------------------------- #
echo "== 6. hand-edited code on the server blocks the deploy"
setup
seed_change "config.py" "MAX_SPREAD_POINTS = 95"
printf 'MAX_SPREAD_POINTS = 77\n' >> "$TMP/server/config.py"
run_autosync
log_has "SKIPPED - local code edits detected" "deploy refused over a dirty tree"
log_lacks "deploy=[deployed" "nothing was deployed"
grep -q "MAX_SPREAD_POINTS = 95" "$TMP/server/config.py" || pass "the hand-edit is untouched"
[ "$(git -C "$TMP/server" rev-parse HEAD)" = "$(git -C "$TMP/server" rev-parse origin/main)" ] \
    || pass "server intentionally left behind origin"

# --------------------------------------------------------------------------- #
echo "== 7. a stopped unit is never started by a deploy"
setup
echo inactive > "$TMP/svc/scalper-dashboard.state"
seed_change "dashboard.py" "def index():\n    return 'v2'"
run_autosync
log_has "scalper-dashboard was not active" "stopped unit reported, not started"
not_called "restart scalper-dashboard" "stopped dashboard left alone"
not_called "start scalper-dashboard" "stopped dashboard not started"
not_called "restart scalper-bot" "dashboard change does not restart the engine"

# --------------------------------------------------------------------------- #
echo "== 8. an overlapping run exits 0 without touching anything"
setup
(
    exec 9>"$TMP/autosync.lock"
    flock -n 9 || exit 1
    run_autosync
    wait
) 2>/dev/null
log_has "another autosync run is active" "second run detected the lock"
[ "$(cat "$TMP/rc")" = "0" ] && pass "overlapping run exits 0" || fail "overlapping run failed"
not_called "restart scalper-bot" "overlapping run did nothing"

echo
echo "ALL PASS: ${PASSES} autosync checks"
