# Go-live countdown review — 2026-11-26

**Recommendation: NO-GO for both books. Keep `TRADING_MODE=FORWARD_TEST`.**
No launch date is committed, and no trade count in the published books is
qualifying forward evidence. This is a review of published files only; the box
was not contacted and no engine, config, service, strategy parameter or spread
gate was changed.

## 1. What the "countdown" actually is

The gold `/readiness` tab computes `max(0, 300 − closed)` and prints the result
as *"N to the 300-count reference; not an approval countdown"*
(`dashboard.py`, `templates/_readiness_gold.html`). At the 2026-11-26 published
snapshot that is **159** (300 − 141). It is a statistical power reference, not
a gate: the tab itself says the current count is "not certified qualifying
evidence". BTC has no reference at all and shows **0 qualifying trades**.

There is no countdown to a live switch. Quantity cannot rescue an edge whose
measurement is negative, and the live-readiness review requires a **frozen,
validated engine** before the forward cohort starts counting
(`docs/live_readiness_review_2026-10-23.md` §6). Both books currently run the
shapes that were already rejected on cold data, so their paper books measure
those failures rather than a candidate for LIVE.

## 2. Published books at 2026-11-26

Source files: `logs/paper_account.json` (updated 2026-11-26 14:33:07 UTC),
`btc/logs/paper_account.json` (updated 2026-11-26 12:24:20 UTC), the last
`closed` `SIM_EXIT` rows of `logs/ledger.jsonl` and `btc/logs/ledger.jsonl`,
and `logs/heartbeat.json` (2026-11-26T15:00:37Z). Profit factors below are
gross wins / gross losses on those current-book exits; state "wins/losses"
counts include zero-P&L BE exits as non-wins.

| | gold | BTC |
|---|---|---|
| balance / start | **$290.19** / $300 (−3.27%) | **$267.61** / $300 (−10.80%) |
| closed (state wins/non-wins) | 141 (37/104) | 292 (63/229) |
| current-book net, PF | **−$9.81, 0.988** (+$783.69 / −$793.50) | **−$32.39, 0.913** (+$341.47 / −$373.86) |
| exits | 89 SL · 36 TP · 14 BE · 2 WEEKEND | 188 SL · 63 TP · 41 BE |
| max drawdown from $300 | $149.51 (49.8%) | $79.22 (26.4%) |
| open position | one BUY, BE armed (entry 3566.35, 11:15:12 UTC) | none |
| heartbeat verdict | `ok`, engine age 0.1 min, gate `ok` | `ok`, engine age 0.2 min, gate `ok` |

The gold book has improved since the 2026-11-23 snapshot ($280.16 / 129
closed) but remains below its $300 start and below a profitable profit factor.
Both books are healthy as *data* (`python3 tools/check_data.py`: 0 fail, 0
warn) and the engines are live in FORWARD_TEST; operational stability is not
an edge. Gold's heartbeat reports 280 reconnects — worth watching, not a
readiness gate. Machine-local `live_status.json` / terminal state remain
unverifiable from this checkout.

## 3. Where the execution plans stand

`python3 tools/execution_plan.py gold --status` and `... bitcoin --status`
both print **NO-GO**; `python3 tools/execution_plan.py --validate` is OK.
The plans are version 2026-11-23 in phase content; only the verdict snapshot
was refreshed to 2026-11-26, with no phase status, `next`, gate or hard rule
changed.

- **Gold — next `breakout-b-protocol` is `blocked`.** BREAKOUT-B v2 rules are
  frozen (54 cells, opposite-channel exit, one TRAIN-only winner), but the
  prospective XM GOLD M5 window does not close until **2027-02-01 UTC**. No
  sweep, no hash, no result. The demo execution drill has not been run.
- **BTC — next `btc-recon` is `parallel`.** The offline sanity check passes
  (`python3 btc/recon.py --self-test`), and the phase-1 freeze is verified
  `FROZEN` with `results_inspected=false`. Symbol spec, swaps, server UTC
  offset and the blackout/weekend decision still need the MT5 bridge on the
  box. All three evaluated strategies failed (M5 RSI PF 0.75 cold OOS, H1
  Donchian PF 0.96 cold OOS, H1 European ORB failed TRAIN on real spreads;
  `docs/btc_orb_result_2026-11-23.md`). A new hypothesis needs a fresh
  pre-registration.

Neither phase is advanceable from this checkout. From the box, the BTC recon
steps are `mt5env/bin/python btc/recon.py --bars 20000` and
`mt5env/bin/python btc/preflight.py`; gold collection follows the RUNBOOK
section "Gold BREAKOUT-B" **after** 2027-02-01.

## 4. Remaining gates before any live decision

All of these are still open (`docs/live_readiness_review_2026-10-23.md` §6,
`plans/gold.json`, `plans/btc.json`, `templates/_readiness_*.html`):

1. Passing cold-OOS research on a genuinely unseen, hashed window (gold:
   BREAKOUT-B after 2027-02-01; BTC: a new pre-registered shape).
2. A second execution-fidelity check: paper/backtest/LIVE entry timing, costs,
   BE and intrabar assumptions on the exact engine that would go live.
3. A 20-trade 0.01-lot demo drill: requested vs filled price, SL attached,
   BE modify round-trip, stop distance and filling mode, realised-R tolerance.
4. A separate account or a tested hard combined risk gate. Both books share
   one XM account; `portfolio.py` caps the pair at $38/day and gold's own
   $30/day can consume most of it. $300 of paper balance is not live capital.
5. A powered forward cohort started from zero on the frozen engine: ~300+
   qualifying trades **or** positive mean R with a bootstrap CI above zero.
   At an illustrative 1.5–3 trades/day that is roughly 20–40 trading weeks
   after strategy validation — a guide, not a forecast.
6. An explicit human go/no-go decision recorded in `STATUS.md`. No file,
   dashboard, countdown or merge can auto-approve LIVE.

The earliest date any of this could happen is therefore months away and
conditional on research that has not passed yet. There is no committed launch
date to count down to.

## 5. Decision

- **Do not** change `TRADING_MODE`, service units, `MAX_SPREAD_POINTS`,
  strategy parameters, `BTC_STRATEGY` or `WEEKEND_FLAT_ENABLED`.
- **Do not** treat 159 remaining paper trades, a green heartbeat, or a merged
  document as progress toward an approval; the qualifying count is zero for
  both books.
- **Do** keep collecting clean FORWARD_TEST data, preserve the BTC cold OOS
  (`results_inspected=false`), and run the box-side recon when convenient.
- Record any future promotion only through an explicit signed decision in
  `STATUS.md`, as the plans and `AGENTS.md` require.

Verification for this review: `check_data` 0 fail / 0 warn; `tools/smoke_test.py`
23/23 PASS with the project venv; `tools/execution_plan.py --validate` OK;
`btc/recon.py --self-test` OK; `btc/freeze.py --status` FROZEN.
