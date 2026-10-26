# Dashboard SCALP tab — 2026-10-26

The dashboard had one view: a snapshot of the account and a rolling window of
`trades.jsonl`. Two questions were not answerable from it without reading the
raw event log by hand:

1. **What trade is the bot in right now, and how is it doing?** — the Overview
   shows an open position row with `profit: 0.0` in paper mode (the simulated
   position has no broker-side float), so "am I up or down, and how far to the
   stop" was missing.
2. **Which trades won and which lost, and does the record look like the
   strategy that was researched?** — the recent-events table mixes `SIGNAL` and
   `SKIP` telemetry with lifecycle events, and shows no R multiple, no outcome
   and no pairing of an entry with its exit.

`/scalp` answers both. It is one more **read-only view of the same app** — no
new service, no new port, no new state file.

## What it reads

| File | Used for |
|---|---|
| `logs/ledger.jsonl` | the compact lifecycle ledger (`ENTRY`/`SIM_ENTRY` → `EXIT`/`SIM_EXIT`/`LIVE_EXIT`) |
| `logs/trades.jsonl` | a **512 KB tail** only, so a trade that closed in the last few minutes shows up before the next 15-minute ledger export |
| `logs/paper_account.json` | the open simulated position with `sl_dist`, `tp`, `be_armed`, `opened` |
| `logs/live_status.json` | current `bid`/`ask` (mark-to-market), `balance`, broker-side positions in LIVE |

Both are merged and de-duplicated by canonical JSON key, so the ledger's copy of
a row and the raw log's copy of the same row cannot produce two trades.

The tab never opens MT5, never writes a file, and never recomputes a P&L that
the book already recorded.

## Current scalp

For the open trade: side, ticket, volume, entry, mark (bid for a long, ask for a
short — the price it would actually close at), stop, target, distance to each in
points, unrealized USD and R, risk/reward in dollars, reward:risk, hold time and
whether the breakeven ratchet has armed (`be_armed`). A progress bar shows how
far the price has travelled through its own stop→target band, which re-bases on
the ratcheted stop after a BE move (that is what the trade's risk actually is at
that point).

`R` is `profit ÷ (sl_dist × volume × contract_size)` using `CONTRACT_SIZE` /
`PRICE_DIGITS` from the instance's `config.py` — the same keys `paper.py` uses,
so the tab cannot disagree with the book about what a point is worth.

## Trade record

Entries and exits are paired in file order into one row per trade: `#`, opened,
side, entry, exit, WIN/LOSS/BE/TIME, why it closed (`SL`, `TP`, `BE`, `TIME`,
`WEEKEND`), hold time, R, P&L and the balance after.

* **Win** is `profit > 0`, **loss** is `profit ≤ 0`, **TIME** exits are excluded
  from the tally on both sides. That is exactly `paper.py`'s convention, so the
  tab's `16W / 48L` on 2026-10-26 is the same 16/48 in `paper_account.json` and
  in `STATUS.md`. A breakeven exit (`profit == 0.0`) counts as a loss here
  because it counts as a loss there — shown separately as the BE badge and
  spelled out under the table rather than silently redefined.
* **The current book only.** `paper.py --reset` deliberately leaves the old rows
  in the log, so the record is the last `closed` completed pairs from
  `paper_account.json` — the same rule `tools/check_data.py` uses to chain the
  balance. A reset starts a new record; it does not resurrect the old one.
* Aggregates over the current book: wins/losses/BE, win rate (and last 10 / last
  20), gross won vs lost, net, profit factor, expectancy per trade, average R,
  total R, best/worst, average win/loss, longest win and loss streaks, current
  streak, average hold, max drawdown and a cumulative-P&L sparkline, plus how
  trades ended as a share of the book.
* Filters: `?result=all|wins|losses|breakeven`, with the filtered net and PF
  shown next to the filter. `?limit=N` caps the rows (default 40, max 500).
  `GET /api/scalp` returns the same thing as JSON.

## LIVE caveat (recorded, not hidden)

An `ENTRY` event carries the ticket, side, volume and stop distances but **no
fill price**, and `LIVE_EXIT` carries the deal price and `profit + swap +
commission`. So a LIVE trade appears with `priced = false`: P&L is MT5's own
realized figure, while entry and R show `—`. The tab says why instead of
inventing an entry price from the signal bar. Gold and BTC both run
`FORWARD_TEST`, so today every row is a priced paper trade.

If LIVE ever becomes real, the fix is in `run.py` (log the fill price on the
`ENTRY` row) — not in this view.

## Why not a new ledger file

"Record the winning and losing trades" is already satisfied by the events the
engine writes: `SIM_EXIT` carries side, entry, exit, reason, profit and
`balance_after`. A second append-only store would be a second truth that can
drift from the book, and `tools/check_data.py`, `tools/ledger_export.py` and
`paper_account.json` would all need to learn about it. The view is the honest
place to do the pairing.

## Testing

`tests/test_scalp_view.py` (66 checks, hermetic — every case builds its own temp
book) covers pairing, R multiples, the reset rule, ledger/tail de-duplication,
the open-trade arithmetic including a ratcheted stop and MT5's `tp = 0`, the
unpriced LIVE path, streaks/drawdown/PF, filters and the sparkline. It runs in
`tools/smoke_test.py` ("scalp view"), so it gates every autosync deploy.

```bash
python3 tests/test_scalp_view.py     # exit 0 = PASS
python3 tools/smoke_test.py          # the deploy gate
```
