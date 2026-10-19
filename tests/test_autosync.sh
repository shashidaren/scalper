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
#   8. --status is read-only, reports OK for a recent run and STALE otherwise
#
# Run: bash tests/test_autosync.sh      # exit 0 = PASS
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_REAL="$(command -v python3)"
PASSES=0

pass() { PASSES=$((PASSES + 1)); echo "PASS $*"; }
fail() { echo "FAIL $*" >&2; exit 1; }

TMP=""
# --------------------------------------------------------------------------- #
# Push shim (this test only).
#
# A sandbox whose pull request was merged blocks EVERY `git push`, including to
# a local bare repo, so the suite could not run there at all. When
# FAKE_GIT_PUSH_TARGET is set, `git push` is emulated with the equivalent fetch
# into the bare origin: same refs, same result, no push call. With the variable
# unset (a normal box, CI) the real binary is used and the real push path is
# exercised.
# --------------------------------------------------------------------------- #
SHIM="$(mktemp -d)/bin"
mkdir -p "$SHIM"
cat > "$SHIM/git" <<'SHIMEOF'
#!/usr/bin/env bash
if [ "${1:-}" = "${FAKE_STALL_GIT:-}" ]; then
    sleep 30
    exit 1
fi
if [ "${1:-}" = "push" ] && [ -n "${FAKE_GIT_PUSH_TARGET:-}" ]; then
    shift
    remote=""; ref=""
    for a in "$@"; do
        case "$a" in -*) continue ;; esac
        if [ -z "$remote" ]; then remote="$a"; else ref="$a"; fi
    done
    src="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 1
    [ -n "$ref" ] || ref="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
    dest="${ref##*:}"
    exec /usr/bin/git -C "$FAKE_GIT_PUSH_TARGET" fetch -q --no-tags "$src" "${ref}:refs/heads/${dest}"
fi
exec /usr/bin/git "$@"
SHIMEOF
chmod +x "$SHIM/git"
export PATH="$SHIM:$PATH"

cleanup() { [ -n "$TMP" ] && [ "${KEEP_TMP:-0}" = "1" ] && { echo "kept $TMP"; return; }; [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT

# --------------------------------------------------------------------------- #
# Sandbox: origin.git + seed (author) + server (box)
# --------------------------------------------------------------------------- #
setup() {
    cleanup
    TMP="$(mktemp -d)"
    export FAKE_GIT_PUSH_TARGET=""          # never inherit a dead sandbox
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
  is-active) if [ "\$(cat "\$S/\$unit.state" 2>/dev/null)" = "active" ]; then
                echo active; exit 0
            else
                echo inactive; exit 3
            fi ;;
  stop)     echo inactive > "\$S/\$unit.state" ;;
  start|restart) echo active > "\$S/\$unit.state" ;;
esac
exit 0
SH
    chmod +x "$TMP/bin/systemctl"

    git init -q --bare "$TMP/origin.git"
    export FAKE_GIT_PUSH_TARGET="$TMP/origin.git"
    git init -q "$TMP/seed"
    (
        cd "$TMP/seed"
        git config user.email seed@test; git config user.name seed
        git checkout -q -b main
        mkdir -p tools logs btc/logs
        cp "$ROOT/tools/autosync.sh" "$ROOT/tools/smoke_test.py" \
           "$ROOT/tools/check_data.py" "$ROOT/tools/ledger_export.py" tools/
        cp "$ROOT/STATUS.md" . 2>/dev/null || echo "# STATUS" > STATUS.md
        echo '{"balance": 300.0, "position": null, "closed": 0, "wins": 0, "losses": 0}' \
            > logs/paper_account.json
        echo '{"date": "2026-10-20", "pnl": 0.0, "trades": 0, "wins": 0, "losses": 0}' \
            > logs/daily_stats.json
        # A realistic event log: SIGNAL noise + one lifecycle event. Only the
        # lifecycle event may ever be published.
        printf '%s\n' \
            '{"time":"t1","event":"SIGNAL","signal":null}' \
            '{"time":"t2","event":"SIM_ENTRY","side":"BUY","entry":4000.0}' \
            '{"time":"t3","event":"SKIP","reason":"high_spread"}' > logs/trades.jsonl
        # The box exports the ledger on the first autosync run; the seed ships
        # it already current so a quiet run stays quiet.
        "$PY_REAL" "$ROOT/tools/ledger_export.py" --root "$TMP/seed" --book gold --quiet
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

# Remove a tracked file upstream (the 2026-10-20 "stop publishing the event
# log" migration).
seed_delete() {
    (
        cd "$TMP/seed"
        git pull -q --ff-only origin main
        git rm -q -- "$1"
        git commit -qm "upstream: stop tracking $1"
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

run_status() {
    (
        cd "$TMP/server"
        PATH="$TMP/bin:$PATH"
        AUTOSYNC_PYTHON="$TMP/bin/python3" \
        AUTOSYNC_LOCK_FILE="$TMP/autosync.lock" \
        bash tools/autosync.sh --status
        echo $? > "$TMP/status.rc"
    ) > "$TMP/status.out" 2>&1
}

log_has()     { grep -qF -- "$1" "$TMP/run.log" || fail "$2 (log lacks: $1)"; pass "$2"; }
log_lacks()   { ! grep -qF -- "$1" "$TMP/run.log" || fail "$2 (log has: $1)"; pass "$2"; }
called()      { grep -qxF -- "$1" "$TMP/calls" || fail "$2 (systemctl never ran: $1)"; pass "$2"; }
not_called()  { ! grep -qxF -- "$1" "$TMP/calls" || fail "$2 (systemctl ran: $1)"; pass "$2"; }
server_sha()  { git -C "$TMP/server" rev-parse HEAD; }
# Read the REAL remote (the bare repo), not the clone's cached
# refs/remotes/origin/main - that cache only advances on fetch.
remote_sha()  { git -C "$TMP/origin.git" rev-parse refs/heads/main; }

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
log_has "committed 1 new trade event(s) -> 'data collection 1'" "trade event counted and numbered"
[ "$(git -C "$TMP/server" log -1 --format=%s)" = "data collection 1" ] \
    && pass "commit subject is data collection 1" || fail "bad commit subject"
[ "$(server_sha)" = "$(remote_sha)" ] && pass "data commit pushed to origin" || fail "push did not land"
[ "$(git -C "$TMP/origin.git" log -1 --format=%s main)" = "data collection 1" ] \
    && pass "origin/main really moved" || fail "origin/main did not advance"
git -C "$TMP/server" ls-tree -r HEAD --name-only | grep -qx "logs/ledger.jsonl" \
    && pass "the compact ledger is tracked" || fail "ledger missing from the commit"
git -C "$TMP/server" show HEAD:logs/ledger.jsonl | grep -q "SIM_EXIT" \
    && pass "the ledger carries the closed trade" || fail "ledger content wrong"
git -C "$TMP/server" show HEAD:logs/ledger.jsonl | grep -q "SIGNAL" \
    && fail "the ledger still carries SIGNAL noise" || pass "SIGNAL noise stayed local"
git -C "$TMP/server" show HEAD:logs/ledger.jsonl | grep -q "SIM_ENTRY" \
    && pass "the ledger carries the entry" || fail "entry missing from the ledger"
not_called "restart scalper-bot" "a data-only commit restarts nothing"

# --------------------------------------------------------------------------- #
echo "== 2b. an upstream that deletes the tracked event log is refused, not faked"
setup
# `git merge` aborts before writing MERGE_HEAD here (the local log is dirty and
# upstream deletes it). Before the guard, autosync committed the staged
# leftovers, reported `deployed`, and silently dropped the upstream change.
printf '%s\n' '{"time":"engine","event":"SIGNAL"}' >> "$TMP/server/logs/trades.jsonl"
before_lines="$(wc -l < "$TMP/server/logs/trades.jsonl")"
seed_delete "logs/trades.jsonl"
run_autosync
log_has "ROLLED BACK" "an aborted merge is reported as a rollback"
log_has "merge produced no MERGE_HEAD" "the real reason is logged" || true
[ -f "$TMP/server/logs/trades.jsonl" ] \
    && pass "the local event log survives" || fail "the log was deleted"
[ "$(wc -l < "$TMP/server/logs/trades.jsonl")" -ge "$before_lines" ] \
    && pass "no local telemetry was lost" || fail "local rows disappeared"
called "start scalper-bot" "the engine comes back after the rollback"

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
[ "$(git -C "$TMP/server" log -1 --format=%s)" != "upstream: config.py" ]     && pass "the bad upstream commit was not applied" || fail "rollback did not reset"
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
[ "$(git -C "$TMP/server" log -1 --format=%s)" != "upstream: config.py" ] \
    && pass "the upstream commit was not merged" || fail "the skipped deploy merged anyway"

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

# --------------------------------------------------------------------------- #
echo "== 9. --status is read-only and says whether the schedule is firing"
setup
touch "$TMP/svc/scalper-autosync.timer.installed"
echo active > "$TMP/svc/scalper-autosync.timer.state"
run_autosync
sha_before="$(server_sha)"
log_bytes="$(wc -c < "$TMP/server/logs/autosync.log")"
: > "$TMP/calls"

run_status
grep -q "OK (last run" "$TMP/status.out" \
    && pass "--status reports a recent run" || fail "--status did not report OK"
[ "$(cat "$TMP/status.rc")" = "0" ] \
    && pass "--status exits 0 when the timer is active and the run is recent" \
    || fail "--status exited $(cat "$TMP/status.rc") on a healthy box"
[ "$(server_sha)" = "$sha_before" ] && pass "--status made no commit" || fail "--status moved HEAD"
[ "$(wc -c < "$TMP/server/logs/autosync.log")" = "$log_bytes" ] \
    && pass "--status did not write the digest log" || fail "--status appended to autosync.log"
grep -qE '^(stop|start|restart) ' "$TMP/calls" \
    && fail "--status changed a unit" || pass "--status only read unit state"

# An old digest at the very end = the schedule stopped firing.
grep -a 'autosync digest' "$TMP/server/logs/autosync.log" | tail -n1 \
    | sed 's/[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\} [0-9]\{2\}:[0-9]\{2\}/2020-01-01 00:00/g' \
    >> "$TMP/server/logs/autosync.log"
run_status
grep -q "STALE (last run" "$TMP/status.out" \
    && pass "--status detects a stale schedule" || fail "--status missed a stale run"
[ "$(cat "$TMP/status.rc")" = "1" ] \
    && pass "--status exits 1 when stale" || fail "--status exits 0 when stale"

# A recent successful digest must not hide one or several skipped ticks.
setup
touch "$TMP/svc/scalper-autosync.timer.installed"
echo active > "$TMP/svc/scalper-autosync.timer.state"
run_autosync
for count in 1 2 3; do
    echo "$(date -u '+%Y-%m-%d %H:%M:%S') another autosync run is active - skipping" >> "$TMP/server/logs/autosync.log"
    run_status
    [ "$(cat "$TMP/status.rc")" = 1 ] && pass "skip $count needs attention despite recent digest" || fail "skip hidden"
done
run_autosync
run_status
[ "$(cat "$TMP/status.rc")" = 0 ] && pass "completion clears skipped-tick attention" || fail "skip not cleared"

setup
printf '%s another autosync run is active - skipping\n' "$(date -u '+%Y-%m-%d %H:%M:%S')" > "$TMP/server/logs/autosync.log"
run_status
grep -q 'NO RUN RECORDED' "$TMP/status.out" && pass "skip-only log is not a completion" || fail "skip counted as completion"
setup
NOTIFY=quiet run_autosync
run_status
grep -q 'OK (last run' "$TMP/status.out" && pass "quiet done line counts as completion" || fail "quiet completion lost"

echo "== 10. shell-only deploys are gated without restarting books"
setup
seed_change "tools/probe.sh" 'if then'
run_autosync
log_has "ROLLED BACK" "invalid shell deploy rolls back"
not_called "stop scalper-bot" "shell rollback does not stop the book"
setup
seed_change "tools/probe.sh" '# valid shell'
FAKE_SMOKE=1 run_autosync
log_has "ROLLED BACK" "shell-only changes run the smoke gate"
setup
# Replace the running file completely with valid but hostile instructions.
# The old invocation must finish from its already parsed function body.
seed_change "tools/autosync.sh" 'exit 99'
run_autosync
[ "$(cat "$TMP/rc")" = 0 ] && pass "self-replacement cannot change current invocation" || fail "script read replacement"
log_has "done. data=" "self-replacing deploy finishes its digest"
log_has "smoke gate: ok" "self-replacing shell deploy gated"
not_called "stop scalper-bot" "self replacement does not stop book"

for op in fetch push; do
    setup
    AUTOSYNC_GIT_TIMEOUT_SECONDS=1 FAKE_STALL_GIT="$op" run_autosync
    log_has "timed out" "$op timeout reported"
    flock -n "$TMP/autosync.lock" -c true && pass "$op timeout releases autosync lock" || fail "lock leaked"
    flock -n "$TMP/server/logs/deploy.lock" -c true && pass "$op timeout releases deploy lock" || fail "deploy lock leaked"
    log_has "done. data=" "$op timeout still completes digest"
done

# --help must print the header only, never the script body.
bash "$TMP/server/tools/autosync.sh" --help > "$TMP/help.out" 2>&1
grep -q '^set -uo pipefail' "$TMP/help.out" \
    && fail "--help leaked the script body" || pass "--help prints the header only"

echo
echo "ALL PASS: ${PASSES} autosync checks"
