# Runbook

All of these run on `scalping`, from `/root/scalper`, unless noted. The sandbox cannot reach the server.

## Health

```bash
journalctl -u scalper-bot -n 40 --no-pager
journalctl -u scalper-btc-bot -n 40 --no-pager
cat logs/connection_status.json logs/live_status.json
cat btc/logs/live_status.json
```

A missing `spread_gate` field in `live_status.json` means the running process predates the gate banner. That is a deploy-skew signal, not a strategy signal.

### "Is it actually running?" — from anywhere

`logs/heartbeat.json` is the published answer: it carries the **age** of each
engine's `live_status.json`, so a checkout can tell "healthy and idle" from
"died on Friday night". Autosync rewrites it hourly (or immediately when a
verdict flips), so `as_of_utc` may be up to an hour old — it says so itself.

```bash
python3 tools/heartbeat.py --check     # print it; exit 1 unless both books are ok
cat logs/heartbeat.json                # same thing as published
```

`verdict: stale` means a `live_status.json` is older than
`HEARTBEAT_STALE_MINUTES` (10) — the engine is not looping. `unknown` means
there is no such file at all (never started, or the log dir is wrong).
Neither one is ever reported as `ok`. On the box, confirm with
`systemctl is-active` and `python3 btc/server_check.py`.

## LIVE position protection

LIVE only (`docs/live_protection_2026-10-23.md`). Inert in `FORWARD_TEST`.

```bash
cat logs/live_positions.json                          # tickets the guard protects
grep LIVE-GUARD logs/system.jsonl | tail -20
journalctl -u scalper-bot -n 50 --no-pager | grep -E 'LIVE-GUARD|stop verified'
```

Every fill is followed by a read-back that proves a stop is attached 2×ATR from
the **actual** fill price; between fills, a lost stop is restored and the BE
ratchet fires once at `BE_TRIGGER_R` (1.5R). Lines to act on:

- `stop NOT verified: <status>` — the stop is not proven; check that ticket in MT5.
- `EMERGENCY-CLOSED` — a naked position was closed (`LIVE_NAKED_POSITION_ACTION=close`).
- `UNPROTECTED POSITION - act manually` — repair failed; close it by hand.
- `never confirmed` / `unconfirmed` — repair accepted but the broker could not be
  re-read; it was **not** closed. Verify in MT5.

Disable without touching the engine: `LIVE_PROTECT_ENABLED = False` in
`config.py` (stops being managed, nothing is undone).

## Risk controls (weekend flat, equity floor)

Both live in `risk_guard.py`; the measurements are in
`docs/risk_controls_2026-10-23.md`.

```bash
python3 risk_guard.py                 # floor status: start, peak, floor, halted_at
python3 risk_guard.py --reset         # clear a latched floor (deliberate action)
cat logs/equity_floor.json
grep -E 'RISK|weekend flat|closed at market' logs/system.jsonl | tail -20
```

- **Weekend flat** — open positions are closed at market from Friday 20:00 UTC;
  no entries until Monday 00:00 UTC. A `[LIVE-GUARD] ... closed at market
  (WEEKEND)` or a paper `SIM_EXIT reason=WEEKEND` line is this rule working.
- **Equity floor** — `[RISK] EQUITY FLOOR HIT` latches: new entries stop, open
  positions keep their stops, and the engine keeps managing them. It does not
  un-latch on a bounce; reset it deliberately once you know why it fired.
- **Hold cap** — `MAX_HOLD_MINUTES = 0` (off). Measured as noise; the weekend
  rule already bounds the worst hold at ~72h.

## Kill switch

Stops new entries only. Open positions keep their broker SL/TP. The LIVE guard
keeps protecting them (it is independent of the kill switch).

```bash
touch /root/scalper/logs/KILL_SWITCH
rm    /root/scalper/logs/KILL_SWITCH
```

## Autosync (the timer path)

`tools/autosync.sh` publishes the paper state and deploys merged code behind a
smoke gate. Full reference: [`docs/AUTOSYNC.md`](docs/AUTOSYNC.md).

```bash
tools/autosync.sh --status                       # trigger, last run age, last digest
systemctl list-timers scalper-autosync.timer     # NEXT / LAST
crontab -l | grep -E '(autosync|deploy)\.sh'     # must be empty while the timer runs
tail -60 logs/autosync.log                       # digests, one block per run
tail -20 logs/smoke.log                          # only when a deploy was rolled back
sudo -H /root/scalper/tools/autosync.sh          # force a run now
AUTOSYNC_PUBLISH_DATA=0 tools/autosync.sh        # deploy only, publish nothing
AUTO_DEPLOY=0 tools/autosync.sh                  # publish only, deploy nothing
```

What it does each run: commit `logs/{ledger.jsonl,daily_stats.json,paper_account.json}`
(+ `btc/logs/…`) as `data collection N` and push → merge `origin/main` if it
advanced (data conflicts = server wins) → `tools/smoke_test.py` → roll back on
failure → restart only the units that were active and whose runtime paths
changed → integrity, freshness and docs advisories.

The deploy **time**, not the PR merge time, is the era cutover:

```bash
git log --grep 'autosync: merge upstream' --format='%H %cI' -1
```

`deploy.sh` is still here for a manual, deploy-only pull. Do not run both cron
lines; they share `logs/deploy.lock` and the loser logs a skip every tick.

## Deploy (manual)

```bash
cd /root/scalper && DEPLOY_BRANCH=main ./deploy.sh
```

Log lines that matter:

- `restarted scalper-bot at <sha>` — a runtime path changed
- `restart skipped` — docs, research, tests, or markdown only
- `DIRTY TREE` — a tracked file is modified; pull will not proceed
- `PULL FAILED` — fetch, checkout, or ff-only pull failed; nothing restarted
- `deploy already running` — overlapping cron tick, expected

`docs/`, `research/`, `tests/`, `*.md`, and `deploy.sh` are not runtime inputs. Anything else restarts.

## Gold research

```bash
mt5env/bin/python backtest.py
mt5env/bin/python research/parity_test.py
mt5env/bin/python research/strategy_sweep.py --verify
mt5env/bin/python research/strategy_sweep.py --candidates
mt5env/bin/python research/loss_analysis.py
```

`--verify` has to reproduce `backtest.py` before a sweep is evidence.

## BTC gate

Read-only. Do not edit `btc/config.py` from these.

```bash
cd /root/scalper && bash docs/collect-2026-10-07/collect_phase1c.sh
# writes /root/ops/collect-2026-10-07/collection.md
```

Manual pieces, if the collect script is not what you want:

```bash
mt5env/bin/python btc/recon.py --timeframe H1 --bars 20000 --out data/BTCUSD_H1.csv
mt5env/bin/python btc/tool.py btc/edge_screen.py --family donchian --csv data/BTCUSD_H1.csv
mt5env/bin/python btc/tool.py btc/train_select.py --family donchian --csv data/BTCUSD_H1.csv
mt5env/bin/python btc/tool.py btc/strategy_btc_test.py
```

Fail the gate when net ≤ 0, PF < 1.2, n < 60, or g ≤ c. A pass is a document, then a question, not a config edit.

`BTC_STRATEGY=donchian` is refused unless `TRADING_MODE` is `FORWARD_TEST`. Bar-close exits are paper-only.

## Tests that do not need the bridge

```bash
mt5env/bin/python tools/smoke_test.py        # the deploy gate: everything below
python3 tests/test_spread_gate.py
python3 tests/test_risk_sizer.py
python3 tests/test_paper_guards.py
python3 tests/test_repair_phantom_ledger.py
python3 btc/preflight_test.py
python3 btc/edge_screen_test.py
python3 btc/strategy_btc_test.py
bash tests/test_deploy_services.sh
bash tests/test_autosync.sh
```

`tools/smoke_test.py` is what `autosync.sh` reads: exit 0 = deploy, non-zero =
roll back. It must stay hermetic and fast.

**A red gate is a deploy freeze, and it does not announce itself.** After any
`data/GOLD_M5.csv` pull, run the gate by hand before trusting the timer:

```bash
mt5env/bin/python tools/smoke_test.py        # must end "SMOKE TEST PASSED"
tail -40 logs/autosync.log                   # look for repeated rollbacks
git log -1 --format='%h %ci %s'              # vs origin/main: is the box current?
```

Two BTC suites pin golden numbers to the bar file they were measured on
(`btc/golden.py`). A `[SKIP] ... is not the pinned file` line is not a
failure — it means the data window rolled. Re-pin **only** after confirming the
new number is explained, and add a STATUS changelog row; re-pinning to clear a
red light hides the drift it exists to catch.

## Ledger integrity

```bash
mt5env/bin/python tools/check_data.py                 # read-only, 0 fail = healthy
mt5env/bin/python tools/ledger_export.py              # rebuild ledger.jsonl after a manual edit
mt5env/bin/python tools/repair_phantom_ledger.py      # dry run: what is suspect
mt5env/bin/python tools/repair_phantom_ledger.py --book gold --apply
```

`--apply` refuses while `scalper-bot` is active (stop it first), copies the
original ledger to `logs/quarantine/<timestamp>/`, then rewrites. Never run it
against a healthy book just to "clean up": the dry run is the default for a
reason.

`check_data.py` chains the balance **inside the current book only** (the last
`closed` exits, per `paper_account.json`). A `paper.py --reset` leaves a
permanent, legitimate break in the raw log; it is not a failure.

## One-time: stop tracking the raw event log

`logs/trades.jsonl` is SIGNAL/SKIP telemetry (~11.5k rows/day) and should not be
in git. After the first autosync run it is tracked once; untrack it by hand:

```bash
cd /root/scalper
mkdir -p /root/scalper-eventlog
cp logs/trades.jsonl /root/scalper-eventlog/gold-$(date -u +%F).jsonl
cp btc/logs/trades.jsonl /root/scalper-eventlog/btc-$(date -u +%F).jsonl
git rm --cached logs/trades.jsonl btc/logs/trades.jsonl
git commit -m "Stop publishing the raw event log; publish ledger.jsonl instead"
git push origin main
```

`--cached` keeps both files on disk. The bot recreates `trades.jsonl` empty on
its next write; `ledger.jsonl` already holds every closed trade.
