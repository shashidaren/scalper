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

## Kill switch

Stops new entries only. Open positions keep their broker SL/TP.

```bash
touch /root/scalper/logs/KILL_SWITCH
rm    /root/scalper/logs/KILL_SWITCH
```

## Deploy

```bash
cd /root/scalper && DEPLOY_BRANCH=main ./deploy.sh
```

Cron is `DEPLOY_BRANCH=main` every 15 minutes. Log lines that matter:

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
python3 tests/test_spread_gate.py
python3 btc/preflight_test.py
python3 btc/edge_screen_test.py
python3 btc/strategy_btc_test.py
bash tests/test_deploy_services.sh
```
