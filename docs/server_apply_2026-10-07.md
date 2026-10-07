# Server apply runbook — 2026-10-07 (`scalping`)

Two server actions, both **approved by the user on 2026-10-07**, to be run in one
session in this order: **(A)** install the reviewed crontab (with the user's
`DEPLOY_SERVICES` choice), then **(B)** restart the gold book + dashboard so the
running code matches `b033986`. Nothing here touches a trading parameter.

Read `docs/cron_review_2026-10-07.md` (§4 for the crontab, §6 for the checklist)
and `HANDOFF.md` §1 for the freeze this is cleaning up after:
a dirty tracked `docker-compose.yml` froze every deploy from **2026-10-04 12:30 →
2026-10-07 02:28 UTC**, so the gold bot has been running `a122e7a`-era code and
PRs #22/#23/#24 are on disk but **not in memory**.

Everything below is copy-pasteable. `# ──` comments are notes, not commands.

---

## 0. Pre-flight (30 s)

```bash
cd /root/scalper
git rev-parse HEAD                      # expect b033986 (or a later main)
git status --porcelain                  # MUST be empty — a dirty tracked file is what froze the deploys
systemctl show scalper-bot -p ActiveEnterTimestamp            # expect ~2026-10-04 12:3x (stale process)
systemctl show scalper-dashboard -p ActiveEnterTimestamp
python3 -c "import json;print('spread_gate:', json.load(open('/root/scalper/logs/live_status.json')).get('spread_gate'))"
#    -> null/None means the running engine predates PR #22. It SHOULD for now; it must be non-null after step B.
mt5env/bin/python paper.py | tail -5    # gold paper position: prefer flat before the restart
```

If `git status --porcelain` prints anything: **stop and resolve it first**
(`git stash push -m deploy-preflight` or `git checkout -- <file>`), and move any
server-only compose tweak to `docker-compose.override.yml` (Compose merges it;
the tracked file stays clean — cron review F11).

---

## A. Install the reviewed crontab

The reviewed block, with the **user's decision** applied:
`SHELL`/`PATH`(mt5env)/`MAILTO`(root)/`CRON_TZ=UTC`, the `mkdir -p` prefix on the
deploy line, **one** daily paper-status line at `7 1 * * *` (the Mon–Fri `0 1`
duplicate is dropped), and `DEPLOY_SERVICES` = **all four units** (both paper
books keep running, so both are kept in sync with the code).

```bash
# 1) Back up the current crontab (rollback path).
crontab -l > "/root/crontab.backup-$(date -u +%F_%H%M%S)" 2>/dev/null || true
ls -l /root/crontab.backup-*

# 2) Optional but recommended (cron review F2): move the server-only status
#    script out of the directory the deploy pulls into.
if [ -d /root/scalper/scripts ]; then
  mkdir -p /root/ops
  git -C /root/scalper status --porcelain /root/scalper/scripts
  mv -v /root/scalper/scripts/paper_status_daily.sh /root/ops/ 2>/dev/null || true
  [ -f /root/scalper/scripts/.env.paper_status ] && mv -v /root/scalper/scripts/.env.paper_status /root/ops/
  rmdir /root/scalper/scripts 2>/dev/null || true
fi

# 3) Install the reviewed crontab.
cat > /tmp/scalper.crontab <<'CRON'
SHELL=/bin/bash
PATH=/root/scalper/mt5env/bin:/usr/local/bin:/usr/bin:/bin
MAILTO=root
CRON_TZ=UTC

# Deploy: pull main every 15 min. deploy.sh restarts a unit only when a changed
# path is a runtime input for it, warns about dirty tracked files, and writes a
# "PULL FAILED: ..." line into logs/deploy.log when a pull cannot apply.
# DEPLOY_SERVICES = all four units (user decision 2026-10-07): both paper books
# are running, so both are kept in sync. NOTE: `systemctl restart` also STARTS a
# stopped unit - if the BTC units are ever deliberately stopped, remove them
# from DEPLOY_SERVICES (or mask them) at the same time.
*/15 * * * * mkdir -p /root/scalper/logs && DEPLOY_BRANCH=main DEPLOY_SERVICES="scalper-bot scalper-dashboard scalper-btc-bot scalper-btc-dashboard" /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1

# Paper status: ONE report per day, 7 minutes after the 01:00 deploy tick so it
# never reads a book mid-restart. Server-only script, outside the deployed tree.
7 1 * * * test -x /root/ops/paper_status_daily.sh && /root/ops/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1 || echo "$(date -Is) paper_status missing or exited non-zero" >> /root/scalper/logs/paper_status.cron.log
CRON

crontab /tmp/scalper.crontab
crontab -l                      # confirm what is installed
```

Rollback at any time: `crontab /root/crontab.backup-<timestamp>`.

---

## B. Restart the gold book + dashboard (make memory match `b033986`)

`DEPLOY_FORCE_RESTART=1` does **not** help here — it only bypasses the
changed-path filter *after* a pull, and HEAD has not moved. Do this **while
flat** (step 0).

```bash
cd /root/scalper
systemctl restart scalper-bot scalper-dashboard

# ── verifications ────────────────────────────────────────────────────────────
systemctl show scalper-bot -p ActiveEnterTimestamp          # expect NOW (was ~2026-10-04 12:3x)
systemctl show scalper-dashboard -p ActiveEnterTimestamp    # expect NOW
systemctl is-active scalper-bot scalper-dashboard scalper-btc-bot scalper-btc-dashboard
journalctl -u scalper-bot -n 25 --no-pager                  # banner shows b033986, no traceback
sleep 45                                                    # let one quote cycle land
python3 -c "import json;print('spread_gate:', json.load(open('/root/scalper/logs/live_status.json')).get('spread_gate'))"
#    -> must now be a dict (quotes/vetoed/verdict), not null
curl -s localhost:8088/api/status | head -c 400; echo       # price card data; open :8088 in a browser for the banner
```

Then watch the next cron tick:

```bash
sleep 120; tail -5 /root/scalper/logs/deploy.log
grep -c "PULL FAILED" /root/scalper/logs/deploy.log          # 0 expected
grep -c "DIRTY TREE"  /root/scalper/logs/deploy.log          # 0 expected
grep -c "would be overwritten" /root/scalper/logs/deploy.cron.log   # history: the freeze
```

The first tick after this PR is on `main` pulls it: `deploy.sh` itself and the
docs/tests are inert for every unit, so expect `restart skipped …` (or
`already up to date`) — that is the correct outcome, not a failure.

---

## C. Then: the Phase-1c collection (read-only)

Once this PR is merged and pulled (the tick above), run the collector and paste
the bundle back:

```bash
cd /root/scalper
bash docs/collect-2026-10-07/collect_phase1c.sh
# -> /root/ops/collect-2026-10-07/collection.md   (paste this back)
```

It never starts/stops/enables/disables a unit, never edits config, never calls
`mt5.shutdown()`, and writes only into `/root/ops/collect-2026-10-07/` plus the
git-ignored `data/BTCUSD_H1.csv`. The gate rule it feeds is in
`docs/collect-2026-10-07/README.md`: **FAIL if `net ≤ 0`, `PF < 1.2`, `n < 60` or
`g ≤ c`** → one-page negative result, no service change, no tuning on that file;
**PASS** → document, then ask before re-deriving `MAX_SPREAD_POINTS` and starting
the BTC paper book.

---

## Decisions this runbook encodes (2026-10-07)

| Decision | Choice |
|---|---|
| BTC paper units while the gate is unread | **Keep running** (observation on). No config change; they stay `FORWARD_TEST` on the 1,500-pt placeholder (100% veto, 0 trades). |
| Crontab | **Install**, deduped to one daily status line, with the env header. |
| `DEPLOY_SERVICES` | **All four units** — both books stay in sync. If a book is ever stopped, remove it here (restart starts stopped units). |
| Restart gold + dashboard | **Yes**, together with the crontab change, while flat. |
| Gold's 100-trade clock | Untouched by all of the above (a restart re-arms only in-memory guards; it does not reset `logs/paper_account.json`). |
