# Port assessment — `gold-trading-bot` → `scalper` (2026-10-20)

Question asked: *the gold bot gained a lot of improvements — can they be added to
the gold scalper?*

Sources compared: `gold-trading-bot/docs/HANDOFF.md` (§1 stance, §4 risk gates,
§5 evidence, §6 next steps), `gold-trading-bot/docs/AUTOSYNC.md`,
`gold-trading-bot/tools/autosync.sh`, the gold `engine.py` guards, and this
repo's `strategy.py`, `config.py`, `run.py`, `paper.py`, `logger.py`,
`deploy.sh`, `STATUS.md`, `docs/loss_analysis_2026-10-02.md`.

**Headline:** the *operational* half of the gold bot transfers almost intact and
is now in this repo. The *strategy* half mostly does **not** transfer, because
the two books trade different shapes — and because this repo already measured
one of gold's key parameters and found it harmful here.

---

## 1. Verdict table

| # | Improvement (gold) | Ports? | Why | What landed here |
|---|---|---|---|---|
| 1 | **Autosync**: publish durable state, deploy on merge, smoke gate + rollback, digest | **Yes** | Pure ops; no strategy coupling | `tools/autosync.sh`, `docs/AUTOSYNC.md` |
| 2 | **Smoke test as the deploy gate** (gold rolls back a bad merge *before* the engine loads it) | **Yes** | The scalper had tests but no single gate | `tools/smoke_test.py` (11 checks) |
| 3 | **`check_data.py`** integrity gate | **Adapted** | Gold reads CSV; this repo writes JSONL + JSON | `tools/check_data.py` |
| 4 | **Phantom-ledger repair** (gold 2026-10-19: 20 rows, −$58,544.65) | **Yes** | Same failure mode is possible here | `tools/repair_phantom_ledger.py` |
| 5 | **Invalid-geometry guards** before booking P&L | **Yes** | The incident fix, independent of strategy | `paper.py` (`valid_position`, load quarantine, atomic save) |
| 6 | **%-risk position sizing** | **Yes — LIVE only** | Gold's own 2026-10-17 correction: sizing the *paper* book off its ledger skipped 76–91% of setups and confounded the experiment | `risk_sizer.py`, `RISK_PCT = 0` (off) |
| 7 | **Max-hold time stop** (`MAX_HOLD_MINUTES`) | **Yes — opt-in** | Neutral bucket, closes the weekend-gap ride | `MAX_HOLD_MINUTES = 0` (off) |
| 8 | **Structural stop** `risk = max(2·ATR, |entry − level| + 0.5·ATR)` | **No (for now)** | Needs a *level anchor*. Gold's entry is a 20-bar floor/ceiling rejection; the scalper's is an RSI cross through EMA200 — there is no level to measure clearance from | — |
| 9 | **BE ratchet 0.75R** | **No** | Direct conflict, and this repo's evidence wins: the 2026-09-30 sweep (20k M5 bars) found 0.75R scratched 94 of 189 trades at entry; 1.5R is the conservative end of the monotone plateau (`config.py`) | — |
| 10 | **SL cooldown 30/60 min, trend-side-only daily breaker** | **No** | `research/loss_analysis.py` already measured the consecutive-loss pause here and did not adopt it; `MAX_CONSECUTIVE_LOSSES` is dead config on purpose | — |
| 11 | **Blackout windows** (London BUY-only, NY, rollover) | **Defer** | The 07–20 UTC session filter already excludes the rollover and Asia; a blackout needs a measured case first | — |
| 12 | **Dashboard read layers** (tape pressure, setup read, location, signal outlook) | **Defer** | Display-only, but needs a calibrated composite (`pressure.py`) and its own analysis doc. Worth doing *after* the book has a sample | — |
| 13 | **`strategy_lab` / `validate_gates` / path-walk sims** | **Defer** | Worth building when this repo starts pre-registering experiments; `research/strategy_sweep.py` covers the current need | — |
| 14 | **Machine-checked handoff snapshot** | **Partial** | Full `handoff_check.py` needs a snapshot block in the status doc. This repo's `STATUS.md` is prose | `autosync` prints a `STATUS.md` age advisory in the digest |
| 15 | **Deploy-boundary dating** (the cutover is the *deploy* time, not the merge or the plan) | **Yes — process** | Gold lost six hours of trades to this mistake (2026-10-06) | `docs/AUTOSYNC.md` §3 |
| 16 | **Pre-registration / REVIEW discipline** before any param change | **Yes — process** | This repo already has `docs/strategy_iteration_*` and `docs/oos_and_execution_fidelity_*`; the rule is restated | `docs/AUTOSYNC.md` §6 |

---

## 2. Why the book is unchanged today

Every port is inert by default:

| Change | Default | Effect on the running paper book |
|---|---|---|
| `MAX_HOLD_MINUTES` | `0` | none — the time-stop branch never runs |
| `RISK_PCT` | `0.0` | none — the LIVE path keeps sending `LOT_SIZE` |
| Geometry guards | always on | none for valid ticks; they only refuse NaN / zero / infinite geometry |
| `paper.save()` | atomic `tmp` + `replace` | none visible; a crash now leaves the last good state instead of a truncated one |
| Spread gate | fails **closed** when `symbol_info.point <= 0` | the old code raised `ZeroDivisionError` into the retry handler; now it logs and waits |
| `autosync.sh` | not yet on cron | none until the crontab is switched (§5) |
| `smoke_test.py` / `check_data.py` / `repair_phantom_ledger.py` | offline | none |

`python3 tools/smoke_test.py` proves this: 11 checks, including the existing
spread-gate, BTC preflight, BTC edge-screen, BTC strategy and deploy-policy
suites, all green.

---

## 3. Why the structural stop does not transfer (the interesting one)

Gold's rule:

```
risk = max(ATR_SL_MULT · ATR, |entry − level| + SL_CLEAR_ATR · ATR)
```

`level` is *the same 20-bar floor or ceiling that the entry was measured
against*: gold buys a wick rejection at the 20-bar floor and sells one at the
ceiling. That is why the rule works there — the entry is anchored to a price,
and "is my stop inside the range?" is a meaningful question (it was inside on
63.8 % of gold's pre-change book).

The scalper's entry is:

```
BUY  if close > EMA200 and RSI crosses up through 40
SELL if close < EMA200 and RSI crosses down through 60
```

There is no tested level, so `|entry − level|` has no argument. Substituting the
20-bar low/high would be a **new strategy**, not a port, and this repo's own
rule (`RUNBOOK.md`, `docs/oos_and_execution_fidelity_2026-10-01.md`) says a new
shape needs a pre-registered bar and a cold out-of-sample pass before it can
trade. Doing it because it worked on a different entry is exactly the
"borrowed evidence" mistake the gold docs warn about.

If you ever want it: `research/strategy_sweep.py` can replay
`SL_ATR_MULT`/`TP_ATR_MULT` variants, and the honest version of the experiment
is *"level-anchored stop on an RSI-pullback entry"* — a new hypothesis with its
own bar, not a config tweak.

---

## 4. The 0.75R BE conflict, in one paragraph

Gold raised `BE_TRIGGER_R` 0.30 → 0.75 on 2026-09-15 because 0.30R scratched
77 % of new trades with a median lifetime of 1.5 minutes and converted +$222 of
runs into $0. This repo did the same exercise in the other direction on
2026-09-30: 0.75R scratched 94 of 189 M5 trades at entry (each paying a full
spread) while the 5R targets rarely survived a 0.75R pullback; the plateau runs
0.5 < 0.75 < 1.0 < 1.25 < 1.5 ≈ off, and 1.5R was chosen as the conservative
end. Both repos are making the same argument — *a ratchet inside the noise
band is a spread-donation machine* — and reach different numbers because the
instruments, timeframes and targets differ. Do not copy gold's number.

---

## 5. What is left to do on the server (manual, one time)

The repo changes deploy themselves. These three do not:

1. **Switch the cron** from `deploy.sh` to `tools/autosync.sh`:

   ```cron
   */15 * * * * cd /root/scalper && ./tools/autosync.sh >> /root/scalper/logs/autosync.cron.log 2>&1
   ```

   Remove the old `deploy.sh` line — running both would double-deploy (they
   share `logs/deploy.lock`, so they cannot overlap, but one of them will
   always lose the race and log a skip).

2. **Let the first run publish the book.** `data collection 1` will contain
   `logs/trades.jsonl`, `logs/daily_stats.json`, `logs/paper_account.json` and
   the BTC equivalents. Check the commit and the digest in
   `logs/autosync.log`.

3. **Decide the two opt-ins.** `MAX_HOLD_MINUTES` and `RISK_PCT` stay off until
   there is a written reason to turn them on (§6).

---

## 6. Proposed sequence

| Step | Action | Gate |
|---|---|---|
| 1 | Ship this session (autosync + guards + tools) | `tools/smoke_test.py` green |
| 2 | Switch the cron, watch two or three merge cycles | digest shows `deployed <sha>`, data commits land |
| 3 | Run the book to ~100 closed paper trades | current bar in `STATUS.md`: PF > ~1.2 sustained |
| 4 | Decide `MAX_HOLD_MINUTES` | replay the hold-time distribution from `trades.jsonl`; if no in-session trade ever exceeds it, enabling is cosmetic — say so and leave it off |
| 5 | Decide `RISK_PCT` | only before any LIVE flip, and only on a separate account (the shared-account rule still applies) |

No strategy parameter should move before step 3 completes. The 2026-10-12
snapshot was `$249.70`, 21 closed, 4W/17L — that is not a sample you tune on.

---

## 7. Files added or changed

**New**

- `tools/autosync.sh` — data publish + safe auto-deploy
- `tools/smoke_test.py` — the deploy gate
- `tools/check_data.py` — ledger/state integrity
- `tools/repair_phantom_ledger.py` — quarantine + restore
- `risk_sizer.py` — LIVE %-risk sizing
- `tests/test_paper_guards.py`, `tests/test_risk_sizer.py`,
  `tests/test_repair_phantom_ledger.py`, `tests/test_autosync.sh`
- `docs/AUTOSYNC.md`, this document

**Changed**

- `paper.py` — geometry guards, atomic save, optional TIME exit
- `run.py` — LIVE sizing, point guard, paper-only time-stop warning
- `mt5_bridge.py` — `open_trade(..., volume=)` (defaults to `LOT_SIZE`)
- `config.py` — `MAX_HOLD_MINUTES`, `RISK_PCT`, `VOLUME_STEP/MIN/MAX`
- `btc/config.py` — explicit `MAX_HOLD_MINUTES = 0`, `RISK_PCT = 0`
- `btc/preflight_test.py` — the gate assertion now follows `btc/config.py`
  instead of a hard-coded (and long-retired) 1500-point placeholder
- `.gitignore` — durable paper state is trackable; everything else in `logs/`
  stays local
- `RUNBOOK.md`, `ARCHITECTURE.md`, `STATUS.md`
