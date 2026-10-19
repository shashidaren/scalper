#!/usr/bin/env bash
# ==============================================================================
# tools/autosync.sh — unattended data publish + safe auto-deploy for the scalper
# Runs from cron (root). Full documentation: docs/AUTOSYNC.md
#
# This is the scalper's port of gold-trading-bot's tools/autosync.sh. It keeps
# the part the scalper already had right (deploy.sh's rule that a *dashboard* or
# *BTC-only* change must not restart the gold book) and adds the part gold had:
#
#   every run
#     1. publishes the durable paper state (trades + balance) to origin/<branch>
#        as a `data collection N` commit — data flows UP the branch;
#     2. fetches. If origin advanced (a merged PR): stop the engines whose
#        runtime code changed -> merge (data conflicts: server wins, everything
#        else: remote wins) -> run tools/smoke_test.py -> roll back on failure
#        -> restart the units that were active before and whose code changed;
#     3. runs tools/check_data.py (integrity), a status-file freshness
#        backstop, and a STATUS.md age advisory;
#     4. writes one digest to logs/autosync.log (and stdout, for the cron log).
#
# Safety model
#   * flock on logs/autosync.lock AND the deploy.sh lock: never two deploys
#   * data is committed BEFORE any merge, and a snapshot of the live files is
#     restored after a rollback, so a bad deploy cannot lose data
#   * refuses to deploy over hand-edited code files on the server
#   * a stopped unit is never started (`systemctl restart` would enable it);
#     only units that were ACTIVE when the run started are restarted
#   * smoke gate + automatic rollback to the pre-merge SHA
#   * .env is read for git identity only, never committed
#
# Env (all optional; see docs/AUTOSYNC.md §5)
#   AUTOSYNC_REPO_DIR, AUTOSYNC_BRANCH, AUTOSYNC_REMOTE, AUTOSYNC_LOCK_FILE
#   AUTOSYNC_PUBLISH_DATA=1  0 = never commit/push data
#   AUTO_DEPLOY=1            0 = data-only mode
#   SMOKE_GATE=1             0 = deploy without the smoke test (not advised)
#   AUTOSYNC_PYTHON          interpreter for the checks (default: mt5env or python3)
#   NOTIFY=always|quiet      quiet = no digest when nothing changed
# ==============================================================================
set -uo pipefail

REPO_DIR="${AUTOSYNC_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
REMOTE="${AUTOSYNC_REMOTE:-origin}"
BRANCH="${AUTOSYNC_BRANCH:-main}"
LOCK_FILE="${AUTOSYNC_LOCK_FILE:-${REPO_DIR}/logs/autosync.lock}"
PUBLISH_DATA="${AUTOSYNC_PUBLISH_DATA:-1}"
AUTO_DEPLOY="${AUTO_DEPLOY:-1}"
SMOKE_GATE="${SMOKE_GATE:-1}"
NOTIFY="${NOTIFY:-always}"
# Seconds to wait after a restart before judging liveness. 20 is right for
# the real bridge; a test (or a very slow box) can lower/raise it.
SETTLE_SECONDS="${AUTOSYNC_SETTLE_SECONDS:-20}"
LOG_DIR="${REPO_DIR}/logs"
LOG_FILE="${LOG_DIR}/autosync.log"

# Durable state only. live_status.json / connection_status.json / system.jsonl
# change every 15 s and are deliberately NOT published — they would turn this
# into ~96 commits a day. These three move only when a trade does.
DATA_FILES=(
    logs/trades.jsonl
    logs/daily_stats.json
    logs/paper_account.json
    btc/logs/trades.jsonl
    btc/logs/daily_stats.json
    btc/logs/paper_account.json
)
SERVICES=(scalper-bot scalper-dashboard scalper-btc-bot scalper-btc-dashboard)
ENGINES=(scalper-bot scalper-btc-bot)

mkdir -p "$LOG_DIR"

log() {
    printf '%s %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

usage() {
    sed -n '2,45p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then usage; exit 0; fi

# --------------------------------------------------------------------------- #
# Interpreter: the box keeps its deps in mt5env/, and a bare `python3` there
# often has no pandas — which would make the smoke gate fail for the wrong
# reason and roll back every deploy.
# --------------------------------------------------------------------------- #
PYTHON="${AUTOSYNC_PYTHON:-}"
if [ -z "$PYTHON" ]; then
    if [ -x "$REPO_DIR/mt5env/bin/python" ]; then
        PYTHON="$REPO_DIR/mt5env/bin/python"
    else
        PYTHON=python3
    fi
fi

# --------------------------------------------------------------------------- #
# Locks. fd 9 = this script; fd 8 = the same lock deploy.sh takes, so a manual
# `./deploy.sh` and an autosync run can never merge underneath each other.
# --------------------------------------------------------------------------- #
exec 9>"$LOCK_FILE" || { log "FATAL: cannot open lock file $LOCK_FILE"; exit 1; }
if command -v flock >/dev/null 2>&1 && ! flock -n 9; then
    log "another autosync run is active - skipping"
    exit 0
fi
if command -v flock >/dev/null 2>&1; then
    exec 8>"$LOG_DIR/deploy.lock" 2>/dev/null || true
    if ! flock -n 8; then
        log "deploy.sh is running - skipping this tick"
        exit 0
    fi
fi

cd "$REPO_DIR" || { log "FATAL: cannot cd to $REPO_DIR"; exit 1; }

if [ -d .git/rebase-merge ] || [ -d .git/rebase-apply ] || [ -f .git/MERGE_HEAD ]; then
    log "repo is mid rebase/merge - manual attention required; autosync paused"
    exit 1
fi

git config user.email >/dev/null 2>&1 || git config user.email "autosync@$(hostname)"
git config user.name  >/dev/null 2>&1 || git config user.name  "scalper-autosync"
export GIT_TERMINAL_PROMPT=0

svc_installed() { systemctl cat "$1" >/dev/null 2>&1; }
svc_active()    { systemctl is-active --quiet "$1" 2>/dev/null; }

# --------------------------------------------------------------------------- #
# Which changed paths are runtime inputs for which unit.
#
# `inert` = provably NOT an input for that unit. Everything not proven inert
# restarts: an empty diff, a git error and an unrecognised new file all fail
# safe, exactly like deploy.sh.
# --------------------------------------------------------------------------- #
is_inert_for_engine() {
    case "$1" in
        docs/*|research/*|tests/*|tools/*|*.md|deploy.sh) return 0 ;;
        dashboard.py|templates/*) return 0 ;;
        backtest.py|fetch_data.py|gold.py|balance.py|wait_for_mt5.py) return 0 ;;
        btc/*)
            # btc/config.py is read by the shared portfolio gate for the gold
            # book too, so it is NOT inert for scalper-bot.
            [ "$1" = "btc/config.py" ] && return 1
            return 0 ;;
    esac
    return 1
}

is_inert_for_dashboard() {
    case "$1" in
        dashboard.py|config.py|logger.py|portfolio.py|templates/*) return 1 ;;
    esac
    return 0
}

is_inert_for_btc_engine() {
    case "$1" in
        docs/*|research/*|tests/*|tools/*|*.md|deploy.sh) return 0 ;;
        dashboard.py|templates/*) return 0 ;;
        backtest.py|fetch_data.py|gold.py|balance.py|wait_for_mt5.py) return 0 ;;
        btc/config.py|btc/run.py|btc/strategy_btc.py|btc/_instance.py) return 1 ;;
        btc/*) return 0 ;;
    esac
    return 1
}

is_inert_for_btc_dashboard() {
    case "$1" in
        btc/dashboard.py|btc/config.py|config.py|logger.py|portfolio.py) return 1 ;;
        dashboard.py|templates/*) return 1 ;;
    esac
    return 0
}

needs_restart() {
    local svc="$1" f
    [ -n "${CHANGED:-}" ] || return 0          # unknown diff -> fail safe
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        case "$svc" in
            scalper-bot)           is_inert_for_engine "$f" || return 0 ;;
            scalper-dashboard)     is_inert_for_dashboard "$f" || return 0 ;;
            scalper-btc-bot)       is_inert_for_btc_engine "$f" || return 0 ;;
            scalper-btc-dashboard) is_inert_for_btc_dashboard "$f" || return 0 ;;
        esac
    done <<< "$CHANGED"
    return 1
}

snapshot_data() {
    KEEP_DIR="$(mktemp -d)"
    local f
    for f in "${DATA_FILES[@]}"; do
        [ -f "$f" ] || continue
        mkdir -p "$KEEP_DIR/$(dirname "$f")"
        cp -p "$f" "$KEEP_DIR/$f" 2>/dev/null || true
    done
}

restore_data() {
    [ -n "${KEEP_DIR:-}" ] && [ -d "$KEEP_DIR" ] || return 0
    local f
    for f in "${DATA_FILES[@]}"; do
        [ -f "$KEEP_DIR/$f" ] && cp -p "$KEEP_DIR/$f" "$f" 2>/dev/null
    done
    rm -rf "$KEEP_DIR"
    log "restored the live data files the engine wrote during the failed merge"
}

# --------------------------------------------------------------------------- #
# Phase 1 — publish the durable paper state
# --------------------------------------------------------------------------- #
DATA_MSG="no new data"
if [ "$PUBLISH_DATA" = "1" ]; then
    for f in "${DATA_FILES[@]}"; do git add -- "$f" 2>/dev/null || true; done
    if ! git diff --cached --quiet 2>/dev/null; then
        NEW_ROWS=$(git diff --cached -- logs/trades.jsonl btc/logs/trades.jsonl 2>/dev/null | grep -c '^+[^+]' || true)
        LAST_N=$(git log --format=%s | sed -n 's/^data collection \([0-9][0-9]*\)$/\1/p' | sort -n | tail -n1)
        N=$(( ${LAST_N:-0} + 1 ))
        if git commit -q -m "data collection $N"; then
            DATA_MSG="committed ${NEW_ROWS} new trade row(s) -> 'data collection $N'"
            log "data: $DATA_MSG"
        else
            DATA_MSG="COMMIT FAILED (will retry next run)"
            log "data: $DATA_MSG"
        fi
    else
        log "data: no changes"
    fi
else
    DATA_MSG="disabled (AUTOSYNC_PUBLISH_DATA=0)"
fi

# --------------------------------------------------------------------------- #
# Phase 2 — fetch, and deploy if origin advanced
# --------------------------------------------------------------------------- #
DEPLOY_MSG="none"
EXTRA=""
STOPPED=""
KEEP_DIR=""

if ! GIT_OUT=$(git fetch "$REMOTE" "$BRANCH" 2>&1); then
    log "WARN: git fetch failed - no deploy this run"
    DEPLOY_MSG="none (fetch failed)"
    EXTRA="${EXTRA}
⚠️ git fetch failed - check credentials on the box"
fi

LOCAL_SHA=$(git rev-parse HEAD 2>/dev/null || echo "")
REMOTE_SHA=$(git rev-parse "$REMOTE/$BRANCH" 2>/dev/null || echo "")
NEED_MERGE=0
if [ -n "$REMOTE_SHA" ] && [ "$LOCAL_SHA" != "$REMOTE_SHA" ]; then
    if ! git merge-base --is-ancestor "$REMOTE_SHA" HEAD 2>/dev/null; then
        NEED_MERGE=1
    fi
fi

if [ "$NEED_MERGE" = "1" ] && [ "$AUTO_DEPLOY" != "1" ]; then
    DEPLOY_MSG="SKIPPED (AUTO_DEPLOY=0) - origin/${BRANCH} is ahead; manual pull needed"
    log "$DEPLOY_MSG"
elif [ "$NEED_MERGE" = "1" ]; then
    # Hand-edits on the box are how the 2026-10-04 freeze started: an
    # uncommitted tracked file makes every pull fail silently. Published data
    # files are expected to be dirty between phase 1 and the merge, so they are
    # exempt; anything else stops the deploy.
    DIRTY_CODE=$(git status --porcelain --untracked-files=no 2>/dev/null \
        | grep -vE '^(..) (logs/|btc/logs/)' || true)
    if [ -n "$DIRTY_CODE" ]; then
        DEPLOY_MSG="SKIPPED - local code edits detected on the server (hand-edits are not supported)"
        log "$DEPLOY_MSG"
        printf '%s\n' "$DIRTY_CODE" | while IFS= read -r l; do log "  dirty: $l"; done
        EXTRA="${EXTRA}
⚠️ uncommitted code on the server - commit or \`git checkout -- <file>\`"
    else
        CHANGED=$(git diff --name-only HEAD "$REMOTE_SHA" 2>/dev/null || echo "")
        CODE_CHANGED=$(printf '%s\n' "$CHANGED" | grep -cE '\.py$' || true)
        PRE_MERGE=$(git rev-parse HEAD)

        # Stop only ACTIVE engines whose runtime code changed, and only before
        # the merge (a dashboard restart does not need the book stopped).
        for svc in "${ENGINES[@]}"; do
            needs_restart "$svc" || continue
            svc_installed "$svc" || continue
            if svc_active "$svc"; then
                if systemctl stop "$svc" >/dev/null 2>&1; then
                    STOPPED="${STOPPED}${STOPPED:+ }${svc}"
                    log "stopped $svc (runtime code changed)"
                else
                    log "WARN: could not stop $svc"
                fi
            else
                log "note: $svc is not active - it will not be started"
            fi
        done

        snapshot_data

        MERGE_RC=0
        if ! git merge "$REMOTE/$BRANCH" -m "autosync: merge upstream (live data kept local)" >/dev/null 2>&1; then
            log "merge conflict - resolving: data files = ours, everything else = theirs"
            for f in $(git diff --name-only --diff-filter=U); do
                case "$f" in
                    logs/trades.jsonl|logs/daily_stats.json|logs/paper_account.json|\
                    btc/logs/trades.jsonl|btc/logs/daily_stats.json|btc/logs/paper_account.json)
                        git checkout --ours -- "$f" ;;
                    *) git checkout --theirs -- "$f" ;;
                esac
                git add -- "$f" >/dev/null 2>&1 || true
            done
            git commit -q -m "autosync: merge upstream (live data kept local)" >/dev/null 2>&1 || MERGE_RC=1
        fi

        SMOKE="not run (no code change)"
        if [ "$MERGE_RC" = "0" ] && [ "$SMOKE_GATE" = "1" ] && [ "${CODE_CHANGED:-0}" -gt 0 ]; then
            if AUTOSYNC_SMOKE=1 "$PYTHON" tools/smoke_test.py >"$LOG_DIR/smoke.log" 2>&1; then
                SMOKE="ok"
            else
                SMOKE="FAIL"
                tail -n 12 "$LOG_DIR/smoke.log" | while IFS= read -r l; do log "  smoke: $l"; done
            fi
            log "smoke gate: $SMOKE"
        fi

        if [ "$MERGE_RC" != "0" ] || [ "$SMOKE" = "FAIL" ]; then
            log "deploy failed (merge_rc=$MERGE_RC smoke=$SMOKE) - rolling back to $PRE_MERGE"
            [ -f .git/MERGE_HEAD ] && git merge --abort >/dev/null 2>&1
            git reset --hard "$PRE_MERGE" >/dev/null 2>&1
            restore_data
            DEPLOY_MSG="ROLLED BACK (smoke=$SMOKE) - needs a manual look"
            EXTRA="${EXTRA}
🚨 deploy rolled back to ${PRE_MERGE} - start a review session"
        else
            DEPLOY_MSG="deployed $(git rev-parse --short HEAD) (code files: ${CODE_CHANGED:-0}, smoke: $SMOKE)"
            log "$DEPLOY_MSG"
        fi

        # Restart policy: a unit is started only if it was ACTIVE before this
        # run; a unit we did not stop gets `restart` (start would no-op on a
        # running process and leave old code in memory).
        RESTARTED=""
        for svc in "${SERVICES[@]}"; do
            needs_restart "$svc" || continue
            svc_installed "$svc" || { log "note: unit $svc not installed - skipped"; continue; }
            case " $STOPPED " in
                *" $svc "*) was_active=1 ;;
                *) was_active=0; svc_active "$svc" && was_active=1 ;;
            esac
            if [ "$was_active" != "1" ]; then
                log "note: $svc was not active - runtime code changed but a stopped unit is not started"
                continue
            fi
            case " $STOPPED " in
                *" $svc "*) cmd=start ;;
                *) cmd=restart ;;
            esac
            if systemctl "$cmd" "$svc" >/dev/null 2>&1; then
                RESTARTED="${RESTARTED}${RESTARTED:+ }${svc}"
            else
                log "RESTART FAILED for $svc - check systemctl status"
                EXTRA="${EXTRA}
🚨 could not restart $svc - check: systemctl status $svc"
            fi
        done
        [ -n "$RESTARTED" ] && log "restarted: $RESTARTED"
        DEPLOY_MSG="${DEPLOY_MSG}; restarted: ${RESTARTED:-none}"

        # Post-restart liveness. A unit that is "active" but has not written its
        # status file for 3+ minutes is the 2026-09-29 failure mode: up, green,
        # and starving.
        if [ -n "$RESTARTED" ] && [ "$SETTLE_SECONDS" -gt 0 ]; then
            sleep "$SETTLE_SECONDS"
            for svc in "${ENGINES[@]}"; do
                case " $RESTARTED " in *" $svc "*) ;; *) continue ;; esac
                if ! svc_active "$svc"; then
                    log "ERROR: $svc is not active after restart"
                    EXTRA="${EXTRA}
🚨 $svc did NOT stay up after the deploy"
                    continue
                fi
                STATUS_FILE="$LOG_DIR/live_status.json"
                [ "$svc" = "scalper-btc-bot" ] && STATUS_FILE="$REPO_DIR/btc/logs/live_status.json"
                if [ -z "$(find "$STATUS_FILE" -mmin -3 2>/dev/null)" ]; then
                    log "WARN: $svc is active but $STATUS_FILE looks stale"
                    EXTRA="${EXTRA}
⚠️ $svc active but its status file looks stale"
                fi
            done
        fi
    fi
fi

# --------------------------------------------------------------------------- #
# Phase 3 — push (data and the merge commit; never force)
# --------------------------------------------------------------------------- #
PUSH_MSG="ok"
if ! git push "$REMOTE" "$BRANCH" >/dev/null 2>&1; then
    PUSH_MSG="FAILED (data is safe in a local commit; retries next run)"
    EXTRA="${EXTRA}
⚠️ push to $REMOTE failed - fix git credentials on the box"
fi
log "push: $PUSH_MSG"

# --------------------------------------------------------------------------- #
# Phase 4 — integrity, freshness, docs
# --------------------------------------------------------------------------- #
CHECK_MSG="not run"
if [ -f tools/check_data.py ]; then
    "$PYTHON" tools/check_data.py >"$LOG_DIR/check_data.log" 2>&1
    CHECK_RC=$?
    CHECK_MSG=$(grep -E '^== result:' "$LOG_DIR/check_data.log" | tail -n1 | sed 's/^== result: //')
    [ -n "$CHECK_MSG" ] || CHECK_MSG="check_data failed to run (rc=$CHECK_RC)"
    if [ "$CHECK_RC" != "0" ]; then
        EXTRA="${EXTRA}
🚨 check_data: $CHECK_MSG - start a review session"
    fi
fi

# Liveness of the engine itself, independent of the deploy: live_status.json is
# rewritten every loop (<= ~15 s, 5 min when a daily gate is sleeping), so a
# 30-minute-old file means the process is wedged even if systemd says active.
FRESH_MSG="not checked"
freshness_one() {   # name, status file
    [ -f "$2" ] || { printf '%s' "$1: no status file yet"; return; }
    local age
    age=$(( $(date -u +%s) - $(stat -c %Y "$2" 2>/dev/null || echo 0) ))
    if [ "$age" -gt 1800 ]; then
        printf '%s: STALE (%d min since last write)' "$1" "$(( age / 60 ))"
    else
        printf '%s: ok (%d min since last write)' "$1" "$(( age / 60 ))"
    fi
}
if svc_active scalper-bot; then
    FRESH_MSG=$(freshness_one gold "$LOG_DIR/live_status.json")
elif svc_installed scalper-bot; then
    FRESH_MSG="gold: engine stopped"
fi
if svc_active scalper-btc-bot; then
    FRESH_MSG="${FRESH_MSG} | $(freshness_one btc "$REPO_DIR/btc/logs/live_status.json")"
fi
case "$FRESH_MSG" in
    *STALE*)
        EXTRA="${EXTRA}
🛑 engine alive but not writing status: $FRESH_MSG - check journalctl" ;;
esac

DOC_MSG="n/a"
if [ -f STATUS.md ]; then
    DOC_DATE=$(grep -m1 -oE 'Last verified on [^:]+: [0-9]{4}-[0-9]{2}-[0-9]{2}' STATUS.md \
        | grep -oE '[0-9]{4}-[0-9]{2}-[0-9]{2}' | tail -n1)
    if [ -n "$DOC_DATE" ]; then
        DOC_AGE=$(( ( $(date -u +%s) - $(date -u -d "$DOC_DATE" +%s) ) / 86400 ))
        DOC_MSG="${DOC_AGE} day(s) since STATUS.md was verified"
    else
        DOC_MSG="no 'Last verified' date in STATUS.md"
    fi
fi

STATS_MSG=$("$PYTHON" - <<'PYEOF' 2>/dev/null
import json
from pathlib import Path
for name, p in (("gold", Path("logs") / "paper_account.json"),
                ("btc", Path("btc/logs") / "paper_account.json")):
    try:
        d = json.loads(p.read_text())
        print(f"{name} ${d.get('balance')} | {d.get('wins')}W/{d.get('losses')}L"
              f"/{d.get('time_exits', 0)}T | position: "
              f"{'open' if d.get('position') else 'flat'}")
    except Exception:
        pass
PYEOF
)
[ -n "$STATS_MSG" ] || STATS_MSG="no paper state yet"

log "done. data=[$DATA_MSG] deploy=[$DEPLOY_MSG] check=[$CHECK_MSG] fresh=[$FRESH_MSG] docs=[$DOC_MSG]"

# --------------------------------------------------------------------------- #
# Digest
# --------------------------------------------------------------------------- #
QUIET_SKIP=0
if [ "$NOTIFY" = "quiet" ] && [ "$DATA_MSG" = "no new data" ] \
   && [ "$DEPLOY_MSG" = "none" ] && [ "$PUSH_MSG" = "ok" ] && [ -z "$EXTRA" ]; then
    QUIET_SKIP=1
fi
if [ "$QUIET_SKIP" = "0" ]; then
    log "──────── autosync digest $(date -u '+%Y-%m-%d %H:%M') UTC ────────"
    log "  data:      $DATA_MSG (push: $PUSH_MSG)"
    log "  deploy:    $DEPLOY_MSG"
    log "  integrity: $CHECK_MSG"
    log "  freshness: $FRESH_MSG"
    log "  docs:      $DOC_MSG"
    log "  books:     $STATS_MSG"
    [ -n "$EXTRA" ] && log "$EXTRA"
fi
exit 0
