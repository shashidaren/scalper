# Time-based exits and the equity floor — 2026-10-23

Closes §4.3 and §4.4 of
[`live_readiness_review_2026-10-23.md`](live_readiness_review_2026-10-23.md).
Everything below was measured **before** a default was chosen, with
`research/risk_measure.py` (new tool, same replay engine as `backtest.py`):

```bash
mt5env/bin/python research/risk_measure.py
```

**Headline.** The weekend flat is free insurance and is now **on** in both
books. The hold cap is noise and stays **off**. The equity floor cannot be set
usefully on a $300 account — it is now a latched catastrophe backstop at 50%,
and the real control is account size.

---

## 1. Weekend flat — ON (`WEEKEND_FLAT_ENABLED = True`)

Gold trades ~24/5. A Thursday or Friday entry can sit through the Friday close
and re-open Sunday at a different price, and **no number in this repo models
that**: `backtest.py` fills a stop *at* the stop price, never through it.

### What the gap actually looks like

| | |
|---|---|
| gaps > 2h in `GOLD_M5.csv` | 15 |
| \|move\| median / p90 / max | $10.84 / $36.56 / **$54.53** |
| median ATR14 | $4.46 |
| largest gap | **12.2× ATR** |

A full stop is 2×ATR ≈ $8.92 at 0.01 lots. A 12.2×ATR adverse gap through that
stop costs ≈ **$54, i.e. ~6R**, instead of ~1R. One such weekend undoes five
years of the edge below.

### What closing at the Friday boundary costs

Counterfactual: every trade that was still open at a Friday 20:00 UTC boundary
is closed there instead.

| | actual | with the rule |
|---|---|---|
| trades | 255 | 255 |
| held over a Friday cut-off | — | **9 (3.5%)** |
| net | +$456.58 | **+$462.04** (+$5.46) |
| PF | 1.32 | 1.34 |

Of those 9: **6 losses avoided (+$62.70)**, 3 winners cut early (−$57.24). The
two worst individual give-ups were a +$50.30 TP that became +$22.95 and a
+$51.99 TP that became +$27.87 — both ran over a weekend into their target. So
the rule is not free, it is *balanced*, and the balance hides an unmodelled
tail worth 6R. That is the trade: a known, bounded give-up for an unbounded,
unmeasurable risk.

**This is not the same rule the loss analysis rejected.** `docs/
loss_analysis_2026-10-02.md` measured "skip Friday after 16:00 UTC" as an
*entry filter* and found it cost P&L. This is an **exit** rule — positions are
already open and the choice is only where they close.

**Why Friday 20:00 UTC.** It is exactly `SESSION_END_HOUR_UTC`, so no entry can
be opened into the weekend anyway; and XM gold closes ~23:55 server (≈20:55
UTC), so 20:00 UTC is still a normal liquid market — this is a market order,
not a gap fill.

**Applies to paper as well as LIVE.** The whole point of §4.1 was that the
paper book measured an exit engine LIVE did not run. Same rule, same code
(`risk_guard.due_exit`), both paths. **Cost: the paper book's "stable config"
clock restarts** — but it is at 60 of the ~330 trades §3 of the review says are
needed, so the sample was not yet usable either way.

## 2. Hold cap — OFF (`MAX_HOLD_MINUTES = 0`)

Same counterfactual, capped at N hours:

| cap | affected | Δ net | net | PF |
|---|---|---|---|---|
| 4h | 31 | −$31.27 | +$425.31 | 1.33 |
| 6h | 23 | −$51.42 | +$405.16 | 1.31 |
| 8h | 21 | +$30.73 | +$487.31 | 1.37 |
| 12h | 13 | +$115.19 | +$571.77 | 1.42 |
| 24h | 6 | +$45.14 | +$501.71 | 1.36 |

Non-monotone in both directions: that is the signature of noise, not a lever.
Picking 12h because it is the best point is exactly the in-sample selection the
repo's OOS discipline exists to prevent. **Default stays 0**, and the weekend
rule already bounds the worst hold at ~72h.

The mechanism now runs on **LIVE too** (`live_position.manage` closes at
market). Before this, `MAX_HOLD_MINUTES` was documented as paper-only, so a
live position could sit indefinitely.

## 3. Equity floor — ON at 50% of start (a backstop, not a control)

Latched: once tripped, new entries stay blocked until
`python risk_guard.py --reset` (or the state file is deleted). Measured on
**equity**, so floating P&L counts.

### What a floor would have done

Backtest, 0.01 lots, $300 account:

| floor | stops at | final | note |
|---|---|---|---|
| 10% | trade 3 | $266.74 | kills the book in the first week |
| 15–50% | — | $756.58 | never binds |

Backtest, $1,000 account: **no floor ≥ 10% ever binds**.

Live paper book, $300 (60 trades, ends $294.35):

| floor | stops at | final | vs no floor |
|---|---|---|---|
| 10% | trade 14 | $269.27 | −$25.08 |
| 15% | trade 16 | $251.47 | −$42.88 |
| 20% | trade 18 | **$232.94** | −$61.41 |
| 25% | trade 20 | $222.39 | −$71.96 |
| 30% | trade 57 | $209.90 | −$84.45 (the trough) |
| 40–50% | — | $294.35 | never binds |

**Every floor tight enough to be a real control made the book worse**, because
the drawdown it cut was the drawdown the strategy recovers from. The observed
worst is **30.0% of start** ($209.90), so a floor must sit beyond that to be
survivable → 40%+ at this account size, where it protects nothing.

### The sizing rule

> Set the floor **beyond the worst drawdown the book has actually produced**,
> and size the account so that number is affordable.

At 0.01 lots the strategy's own max DD is **$104–122** (backtest, paper: $104).
A 20% floor therefore needs an account of **≥ ~$600**, and a comfortable 15%
needs **~$800–1,000**. On $300 there is no useful setting, which is the real
finding: **the minimum viable live balance is ~$1,000**, and at that size a
20–25% floor is a genuine control that still never binds in-sample.

The default (`50%` of start) is the catastrophe switch — it catches a runaway
bug, a bad fill loop or a broken feed, not a normal losing streak. `"peak"`
mode is available as a trailing alternative.

## 4. What changed

| file | change |
|---|---|
| `risk_guard.py` **(new)** | `in_weekend_window`, `due_exit`, `EquityFloor` (latched, persisted, atomic). Pure stdlib + `config`/`logger`. |
| `paper.py` | `on_tick` routes the last exit check through `risk_guard.due_exit`; new `WEEKEND` reason + `weekend_exits` counter; the old `_held_minutes` is gone (`risk_guard.held_minutes`). |
| `live_position.py` | clock exits close at market via `bridge.close_position`, before the stop/BE logic; a rejected close is retried and downgraded to WARNING after the first ERROR. |
| `run.py` | `EquityFloor` constructed once and evaluated on `disp_equity`; two entry blocks next to the kill switch (floor + weekend window), each logged on state change. |
| `config.py` | `WEEKEND_FLAT_ENABLED/WEEKEND_FLAT_HOUR_UTC`, `EQUITY_FLOOR_ENABLED/MODE/PCT`. |
| `tests/test_risk_guard.py` **(new)** | 58 checks: window boundaries, UTC normalisation, `due_exit` precedence, floor latching/bad readings/modes/reset, paper-account wiring, and AST wiring checks on `run.py`. |
| `tests/test_live_position_guards.py` | +10 checks: LIVE clock closes, pre-boundary no-op, hold cap, rejected close retry. |
| `research/risk_measure.py` **(new)** | the measurements above. |

## 5. Book-keeping notes

- **`WEEKEND` is not `TIME`.** A TIME exit keeps its legacy neutral bucket
  (own counter, excluded from the win/loss tally); a WEEKEND exit is an
  ordinary market close at a rule-defined time, so it counts in the tally and
  in its own `weekend_exits` counter. `tools/check_data.py` recomputes exactly
  that way (it excludes only `TIME`), so the integrity gate stays green — I
  verified it on a synthetic ledger (`0 fail, 0 warn`).
- **Every test pins its clock.** The weekend rule is wall-clock dependent, so
  `tests/test_paper_guards.py`, `btc/strategy_btc_test.py` and the stop tests
  set `WEEKEND_FLAT_ENABLED = False` (they are not about the clock), and the
  clock cases pass an explicit `now`. A suite that only passes Monday–Thursday
  would fail the autosync gate every weekend.
- **Existing open position.** On the first restart after this deploy the paper
  book's open trade is closed at market at the next Friday 20:00 UTC — that is
  the rule working, not a bug.

## 6. Still open

- The demo execution drill (review §6.3) — these rules have only run against a
  fake terminal.
- Account size: nothing in the code enforces the ~$1,000 minimum; it is a
  decision, not a guard.
- The ATR floor (§5-A of the review) remains the biggest *signal* lever and is
  still unadopted.
