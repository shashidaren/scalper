# Readiness tab, and the 2026-10-28 readiness check of both books

Status: **documentation + read-only UI. No strategy parameter, no `TRADING_MODE`,
no service unit, and no engine path changed.** Gold and BTC remain `FORWARD_TEST`
and LIVE remains **no-go for both**.

## 1. Why the tab needed a second document

The `/readiness` tab was added on 2026-10-27 as a **gold** planning view. The nav
hid it on the BTC dashboard, and the route had a hard-coded branch that rendered
"this roadmap applies to Gold only" for any non-gold instance. Two problems with
that:

- A BTC operator had no readiness view at all, on a book that is also in
  `FORWARD_TEST` with a failed research gate and a losing paper record.
- The route computed `remaining = max(0, 300 - closed)`, i.e. gold's
  forward-evidence reference. Rendered on BTC that would have counted the trades
  of the **shape that already failed** toward a launch number.

So `dashboard.readiness_context()` is now instance-aware: `book_kind()` derives
`gold` / `btc` / `other` from `SYMBOL`, and `templates/readiness.html` includes
exactly one body — `_readiness_gold.html` (the 2026-10-27 text, unchanged) or
`_readiness_btc.html` (new). An unknown symbol gets an explicit "no roadmap"
card instead of borrowing someone else's gates.

`SYMBOL` was chosen over a new config key on purpose: `btc/config.py` is a
runtime input for `scalper-btc-bot`, so a viewer-only key there would restart the
BTC engine on deploy for no trading reason.

The two books deliberately do **not** share a reference count:

| | gold | BTC |
|---|---|---|
| forward reference | 300+ trades (2026-10-23 review) | **none** |
| why | the running shape is the one under review | the running shape already failed its cold-OOS gate |

BTC's card therefore says "0 qualifying trades" and explains why, rather than
counting the 141 closed trades it actually has.

## 2. The BTC gates the tab now shows

Each gate names its exit condition, because a checklist that can be ticked
without evidence is the thing this tab exists to avoid.

1. **Research gate — a new hypothesis on untouched XM bars (blocks everything).**
   Phase 1 (M5 RSI pullback) FAIL: cold OOS ≈ −$46, PF 0.75, 2026-10-03.
   Phase 1c (H1 Donchian) FAIL: train-selected winner cold OOS `n=96`, −$40.03,
   PF 0.96; its baseline (+$129.23, PF 1.18) also misses PF ≥ 1.2, 2026-10-07.
   Successor gate: net > 0, PF ≥ 1.2, n ≥ 60 cold OOS, gross > cost, on
   timestamps never inspected, with hashes and TRAIN/OOS boundaries recorded
   before the sweep.
2. **Derive the parameters instead of inheriting gold's.** `ATR_MIN = 0.0`
   (off rather than derived), SL 2.0 / TP 5.0 ×ATR, BE 1.5R,
   `MAX_DAILY_LOSS = 8.0`, `MAX_TRADES_PER_DAY = 15` are all marked PLACEHOLDER
   in `btc/config.py`. `MAX_SPREAD_POINTS = 6250` is the one measured value
   (1.25× TRAIN p90) and is an observation gate, not an approval.
3. **Broker recon and 24/7 mechanics.** `btc/recon.py` still has to confirm the
   symbol name, digits, contract size, stops level, filling mode, swap
   (including Friday's triple swap) and the server's UTC offset.
   `ENTRY_BLACKOUTS_ENABLED` stays `False` until that offset is known, and the
   engine does not model swap P&L at all. With `WEEKEND_FLAT_ENABLED = False`
   (decided 2026-10-24) a position can be held across a weekend with financing
   the backtest never charges.
4. **Demo execution drill, BTC-specific.** The 20-trade drill from
   `docs/live_readiness_review_2026-10-23.md §6.3` has never been run for either
   book. On BTC a 2×ATR stop is ≈$275 of price (≈$2.76 at 0.01 lots) against
   gold's ≈$6, so minimum stop distance, margin and thin-hour spread all need
   measuring. Only `BTC_STRATEGY=donchian` is refused outside `FORWARD_TEST` in
   code — every other BTC LIVE block is documentary.
5. **Account.** Both books share one XM account and bridge; `portfolio.py` caps
   the pair at $38/day and 25 trades/day, and gold's own $30 limit can consume
   most of that. A BTC pilot needs a separate account or a hard combined gate.
6. **Forward evidence, counted from zero** after a validated strategy is frozen.

## 3. The check, against published data (2026-10-28)

Read from the repo's published state files and ledger only; the box was not
contacted, so "engine alive" is the last published heartbeat
(`logs/heartbeat.json`, `as_of_utc 2026-10-28T22:00:21Z`, verdict `ok`, both
books connected).

`tools/check_data.py`: **0 fail, 0 warn** (gold 215 ledger rows, 107 exits, 80 in
the current book; BTC 283 rows, 141 exits, 141 in the current book, one open
position).

| | gold | BTC |
|---|---|---|
| paper balance | **$239.58** (start $300) | **$276.91** (start $300) |
| closed | **80** | **141** |
| state-file record | 19 W / 61 L | 29 W / 112 L |
| exits by reason | 68 SL / 21 TP / 17 BE / 1 WEEKEND | 92 SL / 29 TP / 20 BE |
| net over current book | −$60.42 | −$23.09 |
| profit factor | **0.855** | **0.846** |
| max closed-equity DD | $103.95 | $44.76 |
| first → last exit | 2026-10-05 → 2026-10-28 | 2026-10-07 → 2026-10-28 |
| mode | FORWARD_TEST | FORWARD_TEST |

Both books lost money over the last three weeks. BTC's PF (0.85) is stable
across its whole 141-trade life, which is what a failed research gate predicts;
gold's has slipped from 0.98 at 69 trades (2026-10-26) to 0.855 at 80.

**Verdicts: unchanged — LIVE no-go for gold and for BTC.** Neither book has a
profitable validated edge, the demo execution drill has not been run, and
neither has a qualifying forward cohort. The tab shows exactly that and offers
no control that could move a book toward LIVE.

## 4. What changed in code

| file | change |
|---|---|
| `dashboard.py` | `book_kind()`, `readiness_snapshot(book)`, `readiness_context()`; per-book subtitles; `live` for the nav badge; reference count only where one exists |
| `templates/readiness.html` | shell + style; includes one body per book |
| `templates/_readiness_gold.html` | the 2026-10-27 gold body, moved verbatim |
| `templates/_readiness_btc.html` | new BTC body (gates above) |
| `templates/_nav.html` | Readiness shows on both boards |
| `tests/test_readiness.py` | 3 → 7 tests: per-book separation, no BTC countdown, optional counters, unknown symbol |
| `tools/smoke_test.py` | the readiness suite runs in the deploy gate (SKIPs where `fastapi`/`httpx` are absent) |

`templates/*` and `dashboard.py` are already **viewer** inputs in `deploy.sh` and
`tools/autosync.sh`, so a deploy restarts both dashboards and neither book.

Verification in this checkout: `tools/smoke_test.py` **PASSED (19 checks, 0
skipped)** with the dashboard's own dependencies installed; both routes return
200 on `:8088` and `:8089` and render their own book's numbers.
