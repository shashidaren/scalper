# Design note — one XM account, no engine rework (2026-10-04)

Status: decision recorded. No code, config, service, or trading parameter changed.
Phase 1b remains FAIL / No-Go. `TRADING_MODE` stays `FORWARD_TEST`.

## Question

Can gold and BTC share one XM account, and should the repo be reworked so that is easier?

## Decision

Yes, one XM account is the paper design. It already is. Do not rework the engine yet.

- Both instances already use `scalper.env` and the same MT5 terminal / RPyC bridge (`localhost:18812`). Confirmed by the user on 2026-10-03 (`btc/HANDOFF.md` §8 risk 5).
- Ledgers stay separate by magic (`999111` gold, `999112` BTC) and by log dir (`logs/` vs `btc/logs/`).
- A second XM login would not have made `btc/` trade. The folder is stopped because Phase 1b failed, not because login is missing.
- Measured cause: XM BTCUSD spread is about 52% of median ATR and 26% of a 2×ATR stop. Frozen train winner is cold-OOS negative (−$46.11, PF 0.75). See `docs/btc_phase1_result_2026-10-03.md`.

## What not to build now

A one-process multi-symbol runner (one systemd unit, one dashboard, a symbol table with `enabled`, one account-level daily-loss gate) is the simpler end state. Building it now would put a negative-expectancy symbol on the gold restart path. `deploy.sh` stays gold-only. Do not set `DEPLOY_SERVICES` to include `scalper-btc-bot`. Do not loosen `MAX_SPREAD_POINTS`.

## Later shape, only after a new hypothesis passes cold OOS

1. One process, one unit, one dashboard.
2. Symbol table: magic, log namespace, contract, spread gate, `enabled` flag. BTC stays `enabled: false` until its own gate passes.
3. One combined daily-loss gate that sums both books. A separate XM account is an acceptable substitute for that gate before any LIVE flip, not the next build.

## Ops unchanged

`scalper-btc-bot` and `scalper-btc-dashboard` stay disabled/inactive. This note does not authorise a service start.
