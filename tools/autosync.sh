#!/usr/bin/env bash
# ==============================================================================
# tools/autosync.sh — unattended data publish + safe auto-deploy for the scalper
# Runs from the systemd timer (or cron), as root. Full documentation: docs/AUTOSYNC.md
#
#   ./tools/autosync.sh --status   read-only health summary (exit 1 = attention)
#   ./tools/autosync.sh --help     this text
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
#   AUTOSYNC_HEARTBEAT=1     0 = do not publish logs/heartbeat.json
#   AUTOSYNC_HEARTBEAT_BUCKET_MINUTES=60  how often the heartbeat is rewritten
#   AUTO_DEPLOY=1            0 = data-only mode
#   SMOKE_GATE=1             0 = deploy without the smoke test (not advised)
#   AUTOSYNC_PYTHON          interpreter for the checks (default: mt5env or python3)
#   NOTIFY=always|quiet      quiet = no digest when nothing changed
#   AUTOSYNC_GIT_TIMEOUT_SECONDS=120  fetch/push deadline (+10s kill grace)
#   AUTOSYNC_STALE_MINUTES=45  --status: age at which the schedule is STALE
# ==============================================================================
# Bash parses the whole function before running it. A merge may replace this
# file, but cannot replace the remaining instructions of this invocation.
autosync_main() {
set -uo pipefail

REPO_DIR="${AUTOSYNC_REPO_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
REMOTE="${AUTOSYNC_REMOTE:-origin}"
BRANCH="${AUTOSYNC_BRANCH:-main}"
LOCK_FILE="${AUTOSYNC_LOCK_FILE:-${REPO_DIR}/logs/autosync.lock}"
PUBLISH_DATA="${AUTOSYNC_PUBLISH_DATA:-1}"
HEARTBEAT="${AUTOSYNC_HEARTBEAT:-1}"
AUTO_DEPLOY="${AUTO_DEPLOY:-1}"
SMOKE_GATE="${SMOKE_GATE:-1}"
NOTIFY="${NOTIFY:-always}"
# Seconds to wait after a restart before judging liveness. 20 is right for
# the real bridge; a test (or a very slow box) can lower/raise it.
SETTLE_SECONDS="${AUTOSYNC_SETTLE_SECONDS:-20}"
LOG_DIR="${REPO_DIR}/logs"
LOG_FILE="${LOG_DIR}/autosync.log"

# Durable state only. live_status.json / connection_status.json / system.jsonl
# change every 15 s and are deliberately NOT published - they would turn this
# into ~96 commits a day for no analytical value. These move only when a trade
# does.
#
# `ledger.jsonl` is the compact trade record built from trades.jsonl by
# tools/ledger_export.py (lifecycle events only). `trades.jsonl` itself is
# SIGNAL/SKIP telemetry at ~11,500 rows and ~1.7 MB a day - publishing it is
# what put 187,406 rows into `data collection 1` (2026-10-19). It stays local.
# `AUTOSYNC_PUBLISH_EVENT_LOG=1` restores the old behaviour if ever needed.
# `logs/heartbeat.json` is the one derived file here. It carries the AGE of
# each engine's live_status.json, so a repo checkout can tell "healthy and
# idle" from "died on Friday night" - the three paper files above cannot, and
# on a weekend-flat Friday they stay frozen for ~52 h. tools/heartbeat.py
# rewrites it only when its hourly bucket or the verdict changes, so it does
# not add a commit per tick. It is deliberately NOT a copy of live_status.json.
DATA_FILES=(
    logs/ledger.jsonl
    logs/daily_stats.json
    logs/paper_account.json
    logs/heartbeat.json
    btc/logs/ledger.jsonl
    btc/logs/daily_stats.json
    btc/logs/paper_account.json
)
if [ "${AUTOSYNC_PUBLISH_EVENT_LOG:-0}" = "1" ]; then
    DATA_FILES+=(logs/trades.jsonl btc/logs/trades.jsonl)
fi
SERVICES=(scalper-bot scalper-dashboard scalper-btc-bot scalper-btc-dashboard)
ENGINES=(scalper-bot scalper-btc-bot)

log() {
    printf '%s %s\n' "$(date -u '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$LOG_FILE"
}

usage() {
    # Lines 2.. up to the closing '# ====' banner. A fixed line range leaked
    # the variable assignments into --help once the header grew.
    awk 'NR==1 {next}
         /^# =+$/ {n++; if (n==1) next; exit}
         {sub(/^# ?/, ""); print}' "${BASH_SOURCE[0]}"
}

# --------------------------------------------------------------------------- #
# --status — read-only operator summary. Never takes the lock, never writes,
# never fetches, never restarts anything. Exit 0 = OK, 1 = needs attention.
#
# The point is the first line: "OK (last run N min ago)" is the answer to "is
# the 15-minute schedule actually firing?", and STALE means it is not.
# --------------------------------------------------------------------------- #
STATUS_STALE_MINUTES="${AUTOSYNC_STALE_MINUTES:-45}"

status_report() {
    local rc=0 now epoch="" stamp="" age age_min
    local timer_active=0 cron_has=0
    local detail head_line dirty behind units st svc tstate tenabled next_line

    printf 'autosync status — %s (%s/%s)\n' "$REPO_DIR" "$REMOTE" "$BRANCH"
    now=$(date -u +%s)

    # 1. The trigger. Exactly one is correct: the systemd timer, or a cron
    #    line, never both (two triggers = double deploys).
    if command -v systemctl >/dev/null 2>&1 \
       && systemctl cat scalper-autosync.timer >/dev/null 2>&1; then
        tstate=$(systemctl is-active scalper-autosync.timer 2>/dev/null || true)
        tenabled=$(systemctl is-enabled scalper-autosync.timer 2>/dev/null || true)
        printf '  timer:     scalper-autosync.timer %s (%s)\n' \
            "${tstate:-unknown}" "${tenabled:-unknown}"
        [ "${tstate:-}" = "active" ] && timer_active=1
        next_line=$(systemctl list-timers scalper-autosync.timer --no-pager 2>/dev/null \
            | sed -n '2p' | sed 's/^[[:space:]]*//; s/[[:space:]]\{1,\}/ /g')
        [ -n "$next_line" ] && printf '  schedule:  %s\n' "$next_line"
    else
        printf '  timer:     scalper-autosync.timer not installed\n'
    fi
    if command -v crontab >/dev/null 2>&1; then
        local cron_lines
        cron_lines=$(crontab -l 2>/dev/null \
            | grep -E '(^|[[:space:]/])(autosync|deploy)\.sh' || true)
        if [ -n "$cron_lines" ]; then
            cron_has=1
            printf '  cron:      %s\n' \
                "$(printf '%s' "$cron_lines" | tr '\n' ';' | sed 's/;$//')"
        fi
    fi
    if [ "$timer_active" = 1 ] && [ "$cron_has" = 1 ]; then
        printf '  scheduler: TWO TRIGGERS (timer active + cron line) - remove one\n'
        rc=1
    elif [ "$timer_active" = 0 ] && [ "$cron_has" = 0 ]; then
        printf '  scheduler: NONE active (no timer, no autosync cron line) - nothing will run\n'
        rc=1
    fi

    # 2. Last completed run: the newest digest block in logs/autosync.log.
    if [ -f "$LOG_FILE" ]; then
        stamp=$(grep -aE 'autosync digest |done\. data=\[' "$LOG_FILE" 2>/dev/null | tail -n1 \
            | sed -n 's/.*\([0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\} [0-9]\{2\}:[0-9]\{2\}\).*/\1/p')
        [ -n "$stamp" ] && epoch=$(date -u -d "$stamp UTC" +%s 2>/dev/null || true)
    fi
    if [ -z "$epoch" ]; then
        printf '  last run:  NO RUN RECORDED in %s\n' "$LOG_FILE"
        rc=1
    else
        age=$(( now - epoch )); [ "$age" -lt 0 ] && age=0
        age_min=$(( age / 60 ))
        if [ "$age_min" -gt "$STATUS_STALE_MINUTES" ]; then
            printf '  last run:  STALE (last run %s min ago) — %s UTC\n' "$age_min" "$stamp"
            printf '             no completed run for over %s min; check the timer and the log\n' \
                "$STATUS_STALE_MINUTES"
            rc=1
        else
            printf '  last run:  OK (last run %s min ago) — %s UTC\n' "$age_min" "$stamp"
        fi
    fi

    # Any skipped tick since the last completion deserves attention immediately.
    # Use done as well as digest: NOTIFY=quiet legitimately omits the digest.
    if [ -f "$LOG_FILE" ]; then
        local skips
        skips=$(awk '/done\. data=\[/ || /autosync digest / {n=0}
            /another autosync run is active - skipping|deploy.sh is running - skipping this tick/ {n++}
            END {print n+0}' "$LOG_FILE")
        printf '  skips:     %s since last completion\n' "$skips"
        if [ "$skips" -gt 0 ]; then
            printf '             SKIPPED tick(s) — probe locks and inspect the holder before retrying\n'
            rc=1
        fi
    fi

    # 3. The last digest, verbatim. A rollback or a failed push is attention.
    if [ -f "$LOG_FILE" ]; then
        detail=$(grep -aE '^  (data|deploy|integrity|freshness|books):' "$LOG_FILE" 2>/dev/null | tail -n5)
        [ -n "$detail" ] && printf '%s\n' "$detail"
        case "$(tail -n 15 "$LOG_FILE" 2>/dev/null || true)" in
            *"ROLLED BACK"*|*"push: FAILED"*|*"push: REJECTED"*) rc=1 ;;
        esac
    fi

    # 4. Repository state (read-only; no fetch).
    if git -C "$REPO_DIR" rev-parse --git-dir >/dev/null 2>&1; then
        head_line=$(git -C "$REPO_DIR" log -1 --format='%h %s' 2>/dev/null || true)
        dirty=$(git -C "$REPO_DIR" status --porcelain --untracked-files=no 2>/dev/null \
            | grep -vcE '^(..) (logs/|btc/logs/)' || true)
        behind=$(git -C "$REPO_DIR" rev-list --count "HEAD..$REMOTE/$BRANCH" 2>/dev/null || true)
        # "as of last fetch" is not decoration: this command never fetches, so
        # the number comes from the cached remote ref. On 2026-10-24 it read
        # "behind 0" on a box that was two commits behind - the cached ref had
        # not moved because fetch was failing.
        printf '  repo:      %s | dirty code: %s | behind %s/%s: %s (as of last fetch)\n' \
            "${head_line:-unknown}" "${dirty:-0}" "$REMOTE" "$BRANCH" "${behind:-?}"
        [ "${dirty:-0}" -gt 0 ] && rc=1
    fi

    # 5. Units (informational; a stopped unit is not an error by itself).
    units=""
    for svc in "${SERVICES[@]}"; do
        st=$(systemctl is-active "$svc" 2>/dev/null || true)
        units="${units}${units:+ | }${svc} ${st:-unknown}"
    done
    printf '  units:     %s\n' "$units"

    if [ "$rc" = 0 ]; then printf '  result:    OK\n'; else printf '  result:    ATTENTION NEEDED\n'; fi
    return "$rc"
}

case "${1:-}" in
    --help|-h) usage; exit 0 ;;
    --status)  status_report; exit $? ;;
    "")        ;;
    *)
        printf 'autosync: unknown argument: %s\n' "$1" >&2
        printf 'usage: %s [--status|--help]\n' "$0" >&2
        exit 2
        ;;
esac

# Fail before taking locks if timeout is unavailable or misconfigured.
GIT_TIMEOUT_SECONDS="${AUTOSYNC_GIT_TIMEOUT_SECONDS:-120}"
if ! [[ "$GIT_TIMEOUT_SECONDS" =~ ^[1-9][0-9]*$ ]] || ! command -v timeout >/dev/null 2>&1; then
    printf 'autosync: positive AUTOSYNC_GIT_TIMEOUT_SECONDS and GNU timeout required\n' >&2
    exit 1
fi
network_git() {
    timeout --signal=TERM --kill-after=10s "${GIT_TIMEOUT_SECONDS}s" git "$@"
}

mkdir -p "$LOG_DIR"

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
        dashboard.py|scalp_view.py|templates/*) return 0 ;;
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
        # uvicorn holds these as imported modules, so a change needs a restart
        # (templates/ does not - Jinja re-reads them per request).
        dashboard.py|config.py|logger.py|portfolio.py|scalp_view.py) return 1 ;;
        templates/*) return 1 ;;
    esac
    return 0
}

is_inert_for_btc_engine() {
    case "$1" in
        docs/*|research/*|tests/*|tools/*|*.md|deploy.sh) return 0 ;;
        dashboard.py|scalp_view.py|templates/*) return 0 ;;
        backtest.py|fetch_data.py|gold.py|balance.py|wait_for_mt5.py) return 0 ;;
        btc/config.py|btc/run.py|btc/strategy_btc.py|btc/_instance.py) return 1 ;;
        btc/*) return 0 ;;
    esac
    return 1
}

is_inert_for_btc_dashboard() {
    case "$1" in
        btc/dashboard.py|btc/config.py|config.py|logger.py|portfolio.py) return 1 ;;
        dashboard.py|scalp_view.py|templates/*) return 1 ;;
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

# Everything a rollback must put back. `git reset --hard` restores *tracked*
# files, which silently reverts a tracked-but-dirty event log to its last
# committed state - so the live files the engine appended to are snapshotted
# here and copied back after the reset.
KEEP_FILES=("${DATA_FILES[@]}" logs/trades.jsonl btc/logs/trades.jsonl)

snapshot_data() {
    KEEP_DIR="$(mktemp -d)"
    local f
    for f in "${KEEP_FILES[@]}"; do
        [ -f "$f" ] || continue
        mkdir -p "$KEEP_DIR/$(dirname "$f")"
        cp -p "$f" "$KEEP_DIR/$f" 2>/dev/null || true
    done
}

restore_data() {
    [ -n "${KEEP_DIR:-}" ] && [ -d "$KEEP_DIR" ] || return 0
    local f
    for f in "${KEEP_FILES[@]}"; do
        [ -f "$KEEP_DIR/$f" ] && cp -p "$KEEP_DIR/$f" "$f" 2>/dev/null
    done
    rm -rf "$KEEP_DIR"
    log "restored the live data files the engine wrote during the failed merge"
}

# --------------------------------------------------------------------------- #
# Phase 1 — publish the durable paper state
# --------------------------------------------------------------------------- #
DATA_MSG="no new data"
if [ "$PUBLISH_DATA" = "1" ] && [ -f tools/ledger_export.py ]; then
    "$PYTHON" tools/ledger_export.py --quiet >/dev/null 2>&1 \
        || log "WARN: ledger_export.py failed - publishing the previous ledger"
fi
# Liveness, before the commit so it travels with this run's data. Best effort
# on purpose: a broken heartbeat must never cost a deploy or a data publish.
if [ "$PUBLISH_DATA" = "1" ] && [ "$HEARTBEAT" = "1" ] && [ -f tools/heartbeat.py ]; then
    if HB_OUT=$("$PYTHON" tools/heartbeat.py 2>&1); then
        log "${HB_OUT}"
    else
        log "WARN: heartbeat.py failed - not published this run: ${HB_OUT}"
    fi
fi
if [ "$PUBLISH_DATA" = "1" ]; then
    for f in "${DATA_FILES[@]}"; do git add -- "$f" 2>/dev/null || true; done
    if ! git diff --cached --quiet 2>/dev/null; then
        NEW_ROWS=$(git diff --cached -- '*ledger.jsonl' '*trades.jsonl' 2>/dev/null \
            | grep -cE '^\+.*"event": ?"(SIM_ENTRY|SIM_EXIT|ENTRY|EXIT)"' || true)
        LAST_N=$(git log --format=%s | sed -n 's/^data collection \([0-9][0-9]*\)$/\1/p' | sort -n | tail -n1)
        N=$(( ${LAST_N:-0} + 1 ))
        if git commit -q -m "data collection $N"; then
            DATA_MSG="committed ${NEW_ROWS} new trade event(s) -> 'data collection $N'"
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

if ! GIT_OUT=$(network_git fetch "$REMOTE" "$BRANCH" 2>&1); then
    log "WARN: git fetch failed or timed out - no deploy this run"
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
        CODE_CHANGED=$(printf '%s\n' "$CHANGED" | grep -cE '\.(py|sh)$' || true)
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
            # Only a real in-progress merge may be committed. Without this guard a
            # `git merge` that aborted BEFORE writing MERGE_HEAD (a dirty working
            # tree, say) still had its staged leftovers committed and reported as
            # a successful deploy - the upstream change was silently dropped.
            if [ ! -f .git/MERGE_HEAD ]; then
                log "merge produced no MERGE_HEAD - treating it as a failed merge"
                MERGE_RC=1
            elif ! git commit -q -m "autosync: merge upstream (live data kept local)" >/dev/null 2>&1; then
                MERGE_RC=1
            fi
        fi

        SMOKE="not run (no code change)"
        if [ "$MERGE_RC" = "0" ] && [ "$SMOKE_GATE" = "1" ] && [ "${CODE_CHANGED:-0}" -gt 0 ]; then
            : > "$LOG_DIR/smoke.log"
            SHELL_OK=1
            while IFS= read -r shell_file; do
                case "$shell_file" in
                    *.sh) [ ! -f "$shell_file" ] || bash -n -- "$shell_file" >>"$LOG_DIR/smoke.log" 2>&1 || SHELL_OK=0 ;;
                esac
            done <<< "$CHANGED"
            if [ "$SHELL_OK" = 1 ] && AUTOSYNC_SMOKE=1 "$PYTHON" tools/smoke_test.py >"$LOG_DIR/smoke.log" 2>&1; then
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
if ! PUSH_OUT=$(network_git push "$REMOTE" "$BRANCH" 2>&1); then
    # Two very different faults share one exit code, and conflating them sends
    # the operator to the wrong place (on 2026-10-24 the log said "fix git
    # credentials" for a problem that had nothing to do with credentials).
    #
    #   1. NON-FAST-FORWARD - benign and self-healing. This run saw origin
    #      ahead but skipped the merge (dirty tree, AUTO_DEPLOY=0, ...), so
    #      HEAD is an ancestor of $REMOTE/$BRANCH and a push would rewind it.
    #      It resolves on the first tick that actually merges.
    #   2. Anything else - network, timeout, real credentials.
    #
    # Decide (1) from repository STATE, not from the error text: a quiet or
    # relocated git can fail without printing the word "non-fast-forward",
    # while "am I behind the remote" is always answerable locally.
    NONFF=0
    case "$PUSH_OUT" in
        *non-fast-forward*|*"fetch first"*|*"Updates were rejected"*|*\[rejected\]*) NONFF=1 ;;
    esac
    BEHIND_COUNT=$(git rev-list --count "HEAD..$REMOTE/$BRANCH" 2>/dev/null || echo "")
    case "$BEHIND_COUNT" in
        ''|*[!0-9]*) BEHIND_COUNT="" ;;               # unusable -> rely on the text
        *) [ "$BEHIND_COUNT" -gt 0 ] && NONFF=1 ;;
    esac
    if [ "$NONFF" = "1" ]; then
        PUSH_MSG="REJECTED (non-fast-forward): local HEAD is ${BEHIND_COUNT:-?} commit(s) behind $REMOTE/$BRANCH because this run skipped the merge - nothing to push until a tick merges"
        EXTRA="${EXTRA}
ℹ️ push rejected as non-fast-forward: HEAD is behind $REMOTE/$BRANCH (the deploy was skipped, not failed - see 'deploy:')"
    else
        PUSH_MSG="FAILED (failed or timed out; data is safe in a local commit; retries next run)"
        EXTRA="${EXTRA}
⚠️ push to $REMOTE failed - fix git credentials on the box"
    fi
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

}
autosync_main "$@"
