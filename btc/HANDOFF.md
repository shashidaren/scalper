# HANDOFF — Bitcoin (BTCUSD)

Current truth is [`../STATUS.md`](../STATUS.md). Commands are in [`../RUNBOOK.md`](../RUNBOOK.md).
This file orients you on the BTC book only; it is not a second status page.

> **Corrected 2026-10-24.** This file previously said the 1,500-point spread
> placeholder was vetoing the live feed and that "0 trades is correct", and
> that Phase 1c had not been run. All three were false (the gate moved to
> 6,250 on 2026-10-07, the book had closed trades (141 by 2026-10-28), and Phase 1c ran on
> 2026-10-07 and failed). If you are reading a copy that says otherwise, it is
> stale — `STATUS.md` and `btc/logs/` win.

## What this book is

A **second instance of the same engine**, not a second engine. `btc/config.py`
is swapped into `sys.modules["config"]` by `btc/_instance.py`, then the repo
root's `run.py` / `paper.py` / `strategy.py` run unchanged. Full picture:
[`../ARCHITECTURE.md`](../ARCHITECTURE.md).

| | |
|---|---|
| unit | `scalper-btc-bot` (dashboard `scalper-btc-dashboard`, `:8089`) |
| config | `btc/config.py` — the only file that makes it a bitcoin bot |
| mode | `TRADING_MODE = "FORWARD_TEST"` — paper fills only, no orders ever |
| symbol | `BTCUSD`, M5, magic `999112`, shared bridge `:18812` |
| strategy | `scalp` (EMA200 + RSI 40/60 pullback), SL 2.0×ATR, TP 5.0×ATR, BE 1.5R |
| spread gate | `MAX_SPREAD_POINTS = 6250` (1.25× TRAIN p90; live board quotes ~4,000) |
| risk gates | `MAX_DAILY_LOSS = 8.0`, `MAX_TRADES_PER_DAY = 15` |

## Current state (2026-10-24)

From `btc/logs/paper_account.json`, last change **2026-10-28 20:50:07**:

| | |
|---|---|
| balance | **$276.91** (book started $300 on 2026-10-07) |
| closed | **141** — 29 wins / 112 losses |
| profit factor | **0.846** (gross $126.68 won vs $149.77 lost) |
| exits | 92 SL · 29 TP · 20 BE |
| open position | one BUY (entry 81090.25) |

That is a **−7.7% paper drawdown over 21 days**. It is consistent with the
Phase 1 result, not with a working edge: the book is losing for the reason the
research predicted, not because of a bug. Nothing here is a go-live signal, and
these trades do not count as evidence for any successor hypothesis.

## Is it running?

The trade files cannot answer that on their own. `paper_account.json` only
changes on a fill, and `daily_stats.json` only changes at midnight UTC, so a
healthy bot during a quiet stretch looks exactly like a dead one. The engine's
raw status (`live_status.json`, `connection_status.json`, `system.jsonl`)
changes every 15 s and is deliberately **not** published.

**Check the published heartbeat first** — it exists for exactly this question:

```bash
python3 tools/heartbeat.py --check     # exit 0 = both books ok; 1 = stale/unknown
cat logs/heartbeat.json                # the published copy
```

It carries `engine_status_age_min` per book: small = looping, `stale` = not
looping, `unknown` = no `live_status.json` at all. Rewritten hourly by
autosync (immediately on a verdict flip), so `as_of_utc` can be up to an hour
old.

Then confirm on the box:

```bash
cd /root/scalper
python3 btc/server_check.py            # read-only; units, ports, data, ledger
systemctl is-active scalper-btc-bot scalper-btc-dashboard
journalctl -u scalper-btc-bot -n 40 --no-pager | tail -20
cat btc/logs/live_status.json          # updated_at should be seconds old
```

`btc/server_check.py` is safe to run while gold trades: it imports no MT5
module and opens no bridge connection. It reports `unknown` rather than a
guess, which is the point.

The BTC dashboard (`:8089`) has its own **Readiness** tab (`/readiness`). It
renders BTC's gates, not gold's: the two failed hypotheses, the placeholder
parameters still inherited from gold, the recon/swap work, the demo drill, the
shared-account question, and a forward cohort that starts at zero once a
strategy is frozen. The only live number on it is this book's published paper
state; it cannot change `TRADING_MODE`. Gold's 300-trade reference is
deliberately absent — see `docs/dashboard_readiness_btc_2026-10-28.md`.

**Do not expect quiet weekends on BTC.** `WEEKEND_FLAT_ENABLED = False`
(settled 2026-10-24, section below), so this book takes weekend entries and
holds through them; only *gold* flattens Friday 20:00 → Monday 00:00 UTC. A BTC
weekend with zero trades therefore means no signal fired — not that a rule
fired. This paragraph used to claim the opposite; it contradicted both
`btc/config.py` and `STATUS.md`, and was corrected 2026-10-28.

## Why this book has no validated edge

Both pre-registered BTC hypotheses failed their gates. This is the whole
reason the book stays in paper.

- **Phase 1 — M5 RSI pullback (the shipped shape).** FAIL / no-go on real XM
  bars (2026-10-03): cold OOS about −$46, PF 0.75.
  [`../docs/btc_phase1_result_2026-10-03.md`](../docs/btc_phase1_result_2026-10-03.md)
- **Phase 1c — H1 Donchian breakout.** FAIL / no-go. Collected 2026-10-07
  02:55 UTC; train-selected winner cold OOS `n=96`, −$40.03, PF 0.96. The
  baseline (+$129.23, PF 1.18) also fails the gate (PF < 1.2, CI spans 0).
  [`../docs/btc_phase1c_result_2026-10-07.md`](../docs/btc_phase1c_result_2026-10-07.md)

The paper book therefore runs the shape that already failed, on purpose: it is
an observation feed, and it is allowed to look bad.

## Hypothesis D pre-registered 2026-10-31 — pending freeze

`BTC-ORB-EU-H1`: a session-anchored opening-range breakout on XM H1, stop-entry
at the range level, ATR stop, hard time-flat at the 20:00 UTC close, no TP / BE
/ trailing, nothing held overnight, no Saturday entries. Full protocol and the
reasons for it: [`../docs/btc_hypothesis_orb_h1_2026-10-31.md`](../docs/btc_hypothesis_orb_h1_2026-10-31.md).

- Chosen from a screen, not from data: `btc/session_screen.py` on Binance proxy
  H1 (3 families x 6 cells x 2 fill modes). It is the only family whose gross
  edge pays the spread in every era, and it is **thin** — the doc states the
  concentration, the 2022 loss and the 2x-spread sensitivity.
- **Status: reserved, not run.** The deciding window is XM H1
  `time < 2024-06-25 22:00 UTC` — the only era this repo has never read. The
  freeze manifest is pending: `btc/recon.py --bars 44000` then `btc/freeze.py`
  on `scalping` (RUNBOOK "BTC gate"). No sweep may run before that manifest is
  committed.
- **Nothing is configured.** `BTC_STRATEGY` stays `scalp`, `btc/config.py` is
  untouched, and the `orb` family is not implemented yet (phase 2).

## Weekend flat — settled 2026-10-24, and why it was confusing

`WEEKEND_FLAT_ENABLED = False`. **BTC trades through the weekend.**

How this went wrong, so nobody re-breaks it: the key was absent before
2026-10-23, and `risk_guard.weekend_flat_enabled()` defaults to `True` when a
config omits it — so BTC silently flattened Friday 20:00 → Monday 00:00 UTC
without anything having decided that. 2026-10-23 added an explicit `True`;
2026-10-24 a second `False` was added **higher up the same file**, and the
later `True` still won, so the code kept doing one thing while STATUS.md
documented the other.

Now there is exactly **one** assignment, in the strategy-filters section, with
the history in a comment. If you are tempted to add a second: that is the bug.

The evidence for the rule (`research/risk_measure.py`: +$5.46 over 255 trades,
9 holds, 6 losses avoided, against gap risk up to 12.2×ATR the backtest cannot
model) was measured on `data/GOLD_M5.csv` only. Gold closes daily, which hides
much of that gap risk; BTC does not close. So for BTC it was always a risk
judgement rather than a measured result, and the judgement is off. Gold keeps
its Friday flat.

## Do not

- Set `BTC_STRATEGY=donchian` without a passing cold-OOS gate **and** an
  explicit user decision. Phase 1c failed; the plumbing exists, the evidence
  does not.
- Raise `MAX_SPREAD_POINTS` again. 6,250 is an observation gate, not a
  strategy approval.
- Change `TRADING_MODE`, or flip either book to `LIVE` on the shared XM
  account. That needs a separate account or a hard combined risk gate first.
- Treat proxy (Binance) or exchange CSVs as BTC evidence. The gate reads XM
  bars only.
- Re-pull or re-rank on `data/BTCUSD_H1.csv` (sha256 `f7305461…ab21`). That
  file is inspected; reusing it makes any new gate worthless.
- Re-tune the same RSI-pullback / EMA200 shape on overlapping data. A new BTC
  hypothesis needs its own pre-registered rule and a fresh pull.
- Consume the reserved pre-2024-06-25 window on anything other than
  `BTC-ORB-EU-H1`, widen its 6-cell grid, or read its cold OOS twice. Use
  `btc/freeze.py`: it refuses the burnt H1 sha256 and any cutoff inside the
  inspected era.

## Research plumbing (read-only)

Every research script must run through `btc/tool.py` so `btc/config.py` is the
active config; a bare `import config` picks up gold.

```bash
mt5env/bin/python btc/tool.py btc/edge_screen.py --family donchian --csv data/BTCUSD_H1.csv
mt5env/bin/python btc/tool.py btc/train_select.py --family donchian --csv data/BTCUSD_H1.csv
python3 btc/server_check.py              # the "is anything running" collector
mt5env/bin/python btc/preflight.py       # would the spread gate let it trade?
```

Gate rule: fail when net ≤ 0, PF < 1.2, n < 60, or gross ≤ cost. A pass is a
document, then a question — never a config edit.
