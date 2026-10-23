# LIVE position protection — implementation, 2026-10-23

Implements §4.1, §4.2 and §4.5 of
[`live_readiness_review_2026-10-23.md`](live_readiness_review_2026-10-23.md).
**LIVE only.** The paper book is unchanged by construction *and* by test.

## 1. What was wrong

1. **The paper book measured an exit engine LIVE would not run.** The BE
   ratchet lived only in `paper.py:280-284`. There was no
   `TRADE_ACTION_SLTP` anywhere in the repo, so a live book would have run
   every trade to the full 2×ATR SL or 5×ATR TP. 43 of the 255 validated exits
   (16.9%) are BE scratches.
2. **Nothing proved a live position had a stop.** `run.py` trusted
   `TRADE_RETCODE_DONE` and moved on. A stop the broker silently drops leaves
   the book open with no SL — the only failure mode here that is not
   self-limiting.
3. **Realized R drifted from modelled R.** The stop was built from the
   pre-fill tick, so slippage changed the risk on every trade without changing
   the recorded 2×ATR.

## 2. What changed

| file | change |
|---|---|
| `live_position.py` **(new)** | `LivePositionGuard` — post-fill stop verification/repair and the BE ratchet. ~430 lines, stdlib + `config` + `logger`, no MT5 import. |
| `mt5_bridge.py` | `positions_get()` (None ≠ []), `modify_position_stops()` (SLTP), `close_position()` (emergency), `_ok_retcodes()` (DONE **and** NO_CHANGES). |
| `run.py` | construct the guard in the LIVE branch only; assign `guard.bridge` after every (re)connect; `guard.manage(...)` once per loop; `guard.on_fill(...)` after a `DONE` entry. All three call sites are `if guard is not None:` and wrapped so a guard fault cannot kill the engine. |
| `config.py` | seven `LIVE_*` keys, documented in place. |
| `tools/smoke_test.py` | the two new suites join the deploy gate; `live_position` joins the engine-import check. |

## 3. Behaviour

### On every LIVE fill

1. Re-read the position (up to `LIVE_STOP_VERIFY_ATTEMPTS`, 1s apart) — a fill
   is not always visible on the first read.
2. Compute the intended stops from the **actual fill price**:
   `SL = fill ∓ 2×ATR`, `TP = fill ± 5×ATR`. This is the slippage fix: the
   trade now risks 2×ATR from where it actually filled.
3. If the stop is missing or further than
   `LIVE_STOP_TOLERANCE_POINTS` from the intended value, re-send it with
   `TRADE_ACTION_SLTP`, **carrying the position's current TP** (a zero tp in a
   SLTP request would remove the target).
4. Re-read to confirm. A modify is only recorded when the position shows the
   new stop.

### Every loop, while a position is open

- A stop that vanished mid-trade (broker edit, margin event) is restored from
  the recorded geometry.
- Once `+BE_TRIGGER_R` (1.5R, the value the paper book and the backtest were
  measured at) is reached on the exit-side price, the SL moves to breakeven —
  once, and only if the broker confirms it. A target inside the broker's
  `stops_level` is skipped and logged, never silently retried.

### Failure semantics (the part that matters)

| situation | action |
|---|---|
| stop missing, repair accepted and confirmed | log `INFO`, trade continues |
| stop drifted (slippage), repaired | log `WARNING`, R now matches the model |
| stop missing, repair rejected **3×** | default `LIVE_NAKED_POSITION_ACTION="close"`: emergency market close + `ERROR` log. `"alert"`: `ERROR` only |
| a fill cannot be located at all | `ERROR`, **never** a close |
| a read fails (`positions_get → None`) | retry; **never** treated as "position gone" |
| repair accepted but never confirmed | `ERROR`, **never** a close — closing on unconfirmed data would flatten a healthy trade |
| `TRADING_MODE != "LIVE"` | every entry point returns immediately |

The rule is one line: **a position is only ever closed when a read of that
position shows it has no stop.** Absence of data is never evidence.

## 4. Config

```python
LIVE_PROTECT_ENABLED = True            # master switch (LIVE only anyway)
LIVE_STOP_VERIFY_ATTEMPTS = 3
LIVE_STOP_VERIFY_SLEEP_SECONDS = 1.0
LIVE_STOP_TOLERANCE_POINTS = 5
LIVE_NAKED_POSITION_ACTION = "close"   # or "alert"
LIVE_BE_ENABLED = True
LIVE_BE_TRIGGER_R = None               # None = inherit BE_TRIGGER_R (1.5R)
```

`LIVE_BE_TRIGGER_R` deliberately has no value of its own: two different BE
triggers between paper and live is the exact mismatch this change removes.

## 5. Operations

State lives in `logs/live_positions.json` (gitignored; `btc/logs/` for the BTC
instance). It is written atomically and holds, per ticket, the side, entry,
`sl_dist`, `tp_dist`, `volume` and `be_armed`.

```bash
cat logs/live_positions.json            # what the guard thinks it is protecting
grep LIVE-GUARD logs/system.jsonl | tail -20
journalctl -u scalper-bot -n 50 --no-pager | grep -E 'LIVE-GUARD|stop verified'
```

Log lines to act on:

| line | meaning |
|---|---|
| `[LIVE] stop verified on ticket N` | normal |
| `stop NOT verified: <status>` | stop not proven — check that ticket in MT5 now |
| `EMERGENCY-CLOSED` | a naked position was closed to avoid unbounded risk |
| `UNPROTECTED POSITION - act manually` | repair failed; the book has an unstopped trade |
| `sl_dist recovered from the broker stop` | state lost; ratchet re-derived safely |

The guard is independent of the kill switch: `logs/KILL_SWITCH` blocks *new*
entries, the guard keeps protecting open ones. On restart it re-reads the state
file, so a deploy mid-trade neither re-arms an armed ratchet nor loses the R
unit.

## 6. Tests

| suite | checks | what it pins |
|---|---|---|
| `tests/test_live_position_guards.py` | 79 | gating (FORWARD_TEST can never act), verification/repair, drift, naked → close vs alert, **no close on unreadable data**, no close on unconfirmed repair, BE fires once at exactly the trigger, preserves TP, respects `stops_level`, restart state, prune, foreign magic, ticket≠order-ticket fallback, and an AST check that `run.py` builds the guard only in the LIVE branch |
| `tests/test_mt5_bridge_sltp.py` | 26 | `positions_get` None-vs-`[]` (via `last_error`), SLTP request shape, NO_CHANGES = success, null result, exception, emergency close sends the opposite deal at the exit-side price |

Both are in `tools/smoke_test.py`, so autosync rolls back a deploy that breaks
them.

## 7. Evidence the paper book is untouched

- `backtest.py`: 255 trades, +$456.58, PF 1.32, 72 TP / 43 BE / 140 SL —
  identical to `docs/loss_analysis_2026-10-02.md`.
- `research/parity_test.py`: PASS, 0 mismatches.
- `tools/smoke_test.py`: 15/15 checks, previously 14.
- `git status`: `logs/` and `btc/logs/` unchanged; no strategy parameter
  changed.

## 8. Still open

- **§4.3 weekend/gap exposure** — no Friday cut-off, `MAX_HOLD_MINUTES` still 0.
- **§4.4 equity floor** — a 34.6% paper drawdown remains possible on a $300
  account.
- **Entry-side `stops_level` preflight** and **min-account-size** rule.
- **A demo execution drill** (review §6.3): the code is unit-tested against a
  fake terminal, not against the broker. Before real money: 20 trades at 0.01
  lots on a demo login, confirming fill price vs requested, `sl != 0` on every
  position, one BE modify round-trip, and realized R within tolerance of
  modelled R.
