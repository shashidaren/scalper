# Architecture

Gold is the default instance. BTC is a second instance of the same engine, not a second engine.

```
run.py                         engine loop (risk gates, kill switch, stale-tick, backoff)
  mt5_bridge.MT5Bridge         RPyC :18812 → mt5server.exe (Wine) → MT5
  strategy.ScalpStrategy       gold shape: M5 EMA200, RSI pullback, ATR, session, closed bar
  paper.PaperAccount           FORWARD_TEST fills, logs/paper_account.json
  live_ledger.LiveLedger       LIVE realized PnL, logs/live_ledger.json
  spread_gate.py               entry veto + dashboard banner (does not change the gate)
  logger.py                    logs/{system,trades}.jsonl, live_status.json, …
dashboard.py                   reads those files only, :8088
deploy.sh                      git pull --ff-only; restart only if a runtime path changed

btc/run.py                     shim: btc/config.py becomes `config`, then root run.main()
btc/dashboard.py               same shim, :8089
btc/strategy_btc.py            DonchianBreakoutStrategy, inert until BTC_STRATEGY=donchian
btc/_instance.py               sys.modules["config"] swap, so research scripts cannot grab gold
```

Every engine module does a bare `import config`. Whichever `config.py` is registered first is the instance. `btc/tool.py` is how research runs under the BTC config. Do not `import config` from a script that has already imported the gold one.

Shared on purpose: bridge, loop, paper book, ledger, dashboard app, deploy, systemd pattern.
Not shared: magic number, log dir, contract size, session filter, spread gate, strategy params.
`portfolio.py` is the only module that reads both log dirs. It is a combined-account brake, not a strategy.

Adding a third symbol means another instance dir with its own `config.py` and launcher, not a copy of the engine. The `import config` swap is the fragile part; do not paper over it with another `sys.path` insert.

## Services

| Unit | Entry | Port |
|---|---|---|
| `scalper-bot` | `/root/scalper/run.py` | dashboard 8088 |
| `scalper-dashboard` | `dashboard.py` | 8088 |
| `scalper-btc-bot` | `/root/scalper/btc/run.py` | — |
| `scalper-btc-dashboard` | `btc/dashboard.py` | 8089 |

`deploy.sh` defaults to the gold units. BTC is restarted only when `DEPLOY_SERVICES` names it. A failed pull does not restart anything.

## Image patches not in git

The running MT5 image is not stock `lprett/mt5linux`. Two patches are baked in (fifo recreate, `config.sh` return code). If the container is recreated from upstream, re-apply both or it crash-loops. Write-up: `docs/archive/HANDOFF_2026-10-07.md` §4.
