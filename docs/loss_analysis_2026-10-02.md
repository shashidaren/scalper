# Loss analysis — 2026-10-02 (do we change the strategy or remain?)

**Question.** After PR #12 the backtest reads **255 trades / +$456.58 / PF 1.32 /
max DD $108.65** with a **28.2% win rate** and exits **72 TP / 43 BE / 140 SL**.
183 of 255 trades lose. Is that a defect to fix, or the designed cost of the
payoff structure? Should any parameter change, or should the config stay put
and the paper book be left to accumulate?

**Tooling.** New: `research/loss_analysis.py` (per-trade loss anatomy) and
`research/strategy_sweep.py --candidates` (train-select → cold-OOS re-test of
the exit/risk knobs). Both replay through the *existing verified* engine:

```
$ python research/strategy_sweep.py --verify
sweep engine (default)          255   456.58   1.32   28.2   0.11   108.65    72    43   140    1.79
reference backtest.py: 255 trades / PF 1.32 / +$456.58 / max DD $108.65 / 72 TP, 43 BE, 140 SL   [identical]

$ python research/parity_test.py
replay signals across the file: 460 ... 0 mismatches
PASS: live check_signal and sweep replay agree on every sampled bar
```

So the numbers below come from the same code path as the live strategy, not a
re-implementation. Note the R convention: **1R = the SL distance** (2×ATR), so
a full stop-out is **−1R**, a TP is **+2.5R**, and `BE_TRIGGER_R` uses the same
units.

---

## 1. Verdict first

**Remain.** Do not change the strategy config. The losses are the arithmetic of
a 1R-stop / 2.5R-target design, not a leak; every "obvious fix" fails
train-only validation; and the candidates that do survive are worth
~$80–120 over 101 days on a 0.01-lot book — inside the bootstrap noise — at the
cost of the trade frequency PR #11 was raised specifically to fix.

Two non-strategy items *are* worth acting on (§5): the dead
`MAX_CONSECUTIVE_LOSSES` control should stay unwired (wiring it at 4 costs
$31.49), and the §5 "skip Friday after 16:00 UTC" TODO is **contradicted by the
data** and should be closed.

## 2. Where the losses actually are

```
exit       n       net$      avg$     avgR   % of trades   % of gross loss
TP        72    1864.50     25.90     2.45        28.2%             0.0%
BE        43     -18.99     -0.44    -0.05        16.9%             1.3%
SL       140   -1388.93     -9.92    -1.05        54.9%            98.7%
```

Three things fall out of that table:

1. **98.7% of the gross loss is full stop-outs.** The 43 breakeven scratches
   cost **$18.99 in total** (avg $0.44 — spread only). Exit *management* is not
   the problem; there is almost nothing left to save on the scratch side. Any
   improvement has to come from **entry quality** or **payoff shape**.
2. **Costs are not the leak.** Spread paid across all 255 trades is
   **$112.24 = 6% of the $1,864.50 gross profit** (net before spread $568.82 →
   $456.58 after). The 2026-09-30 spread-assumption fix already removed that
   distortion; there is no second cost problem hiding.
3. **The book sits just above its structural break-even.** With a 1R stop and a
   2.5R target, break-even WR is 1/3.5 = **28.6%** before costs. The strategy
   wins **28.2%** — nominally *below* it — and is profitable only because 43
   losers are scratched for spread instead of −1R. That is a real fragility and
   the reason `TRADING_MODE` should stay `FORWARD_TEST`: the edge is a thin
   tail, not a fat one. Median trade is **−$6.05**; mean **+$1.79**.

**Concentration.** Top-5 winners = **$261.51 = 57% of net**; top-10 =
**$473.65 = 104%** of net, i.e. trades 11–255 collectively net to roughly zero.
Removing the top 5 still leaves +$195.07, so it is not *one* lucky trade — but
the payoff is tail-driven and should be judged on many more trades than 255.

## 3. Loss clustering, and what the risk gates would do

- **Streaks:** 58 losing runs, mean 3.16, **max 10 in a row**. 12 runs exceeded
  `MAX_CONSECUTIVE_LOSSES=4`.
- **Days:** 68 trading days; worst **−$42.09** (4 trades), best +$86.76. **8 days
  breached `MAX_DAILY_LOSS` (−$30)**, together −$280.98 = **20% of gross loss**.
- **Backtest vs live fidelity:** `backtest.py` does not model the gates that
  `run.py:151-159` enforces live. Replaying the same 255 trades through them
  blocks 5 trades → **net $438.48, i.e. −$18.10 vs the ungated backtest**. So
  the daily gate is cheap insurance, not a PnL lever, and the paper/live book
  should be expected to read ~$18 below the ungated backtest over this window.
  `MAX_TRADES_PER_DAY=15` never binds (busiest day: 7 trades).

**Wiring `MAX_CONSECUTIVE_LOSSES` would make things worse** (pause for the rest
of the day after N straight losses, applied to the same trade sequence):

| N | trades blocked | net $ | Δ vs ungated |
|---|---|---|---|
| 3 | 35 | 272.24 | **−184.34** |
| **4 (the config value)** | 11 | 425.09 | **−31.49** |
| 5 | 3 | 427.50 | −29.08 |
| 6 | 1 | 434.60 | −21.98 |

Losing streaks are **not** followed by more losses in this sample — the book
recovers, and pausing skips trades that were net profitable. The §5 TODO to
"wire `MAX_CONSECUTIVE_LOSSES`" should be closed as *measured and rejected*
(keep the constant as documentation, or delete it).

## 4. Which conditions lose (and why not to filter on them)

By hour (UTC), worst → best:

| hour | n | net $ | PF | | hour | n | net $ | PF |
|---|---|---|---|---|---|---|---|---|
| 18 | 16 | −107.87 | 0.36 | | 14 | 22 | +14.70 | 1.14 |
| 07 | 32 | −94.02 | 0.47 | | 09 | 19 | +63.09 | 1.62 |
| 12 | 18 | −59.95 | 0.37 | | 17 | 21 | +78.81 | 1.45 |
| 13 | 22 | −39.08 | 0.66 | | 15 | 19 | +130.01 | 2.87 |
| 08 | 20 | −19.89 | 0.79 | | 19 | 15 | +159.52 | 3.20 |
| 11 | 9 | −14.85 | 0.72 | | 16 | 23 | +330.98 | 5.41 |

By weekday: Mon +$153.83 (PF 1.65), Wed +$199.16 (1.88), Thu +$197.03 (1.65),
**Tue −$27.28 (0.91)**, **Fri −$66.17 (0.81)**. By side: BUY +$197.60 (PF 1.27),
SELL +$258.98 (1.38) — both sides work. By month: all four positive
(Jun +155.07, Jul +128.79, Aug +65.30, Sep +107.42).

**The ATR filter is dead code.** `config.atr_min = 0.50`, but ATR over the whole
file has **min 1.22, p5 2.44, median 4.47** — **0.0000 of bars are below 0.50**,
so the filter has never gated a single signal. Meanwhile the bottom ATR quartile
of entries (≤3.5) is the only losing bucket (**−$60.85, PF 0.76**) and the top
quartile (>5.92) makes **+$402.44, PF 1.82**. The filter isn't mis-tuned, it's
set ~7× below the data's floor.

**Why not just filter the bad hours/days?** 16–32 trades per hourly bucket and
~50 per weekday is far too thin to select on — that is precisely the overfitting
PR #12's OOS discipline exists to prevent. It also fails on its own terms: see
`session 09-20` in §5, which wins on TRAIN and *just* clears OOS, then loses
money in one of four walk-forward quarters.

## 5. Re-testing the exit/risk knobs the honest way

`sweep_be` / `sweep_sl` / `sweep_tp` rank configs on the **same 20k bars** the
adopted config was chosen from, so their in-sample winners are not evidence.
`--candidates` selects on **TRAIN only** (2026-06-08..07-27) and then reads
**OOS cold** (2026-07-27..09-11), the discipline PR #12 established. Adopted
config as the bar: TRAIN +$286.06 / OOS +$170.52.

| lever | in-sample full-file said | TRAIN says | cold OOS | verdict |
|---|---|---|---|---|
| **BE off** | best: **+$563.46**, PF 1.37 | **+$250.11 (worse)** | +$313.35 | **rejected** — the full-file ranking was an OOS-half artefact |
| BE 2.0R | +$447 | +$287.13 (better) | +$162.42 (worse) | rejected (overfit) |
| **SL 2.5×ATR** | **+$520.66**, PF 1.34, lower DD | **+$245.56 (worse)** | +$275.10 | **rejected** — in-sample artefact |
| SL 3.0×ATR | +$494.26 | +$122.50 (worse) | +$371.76 | rejected |
| time exit 12–72 bars | never tested | all worse (+$208 best) | mixed | rejected at every length |
| ATR floor 4.0 | n/a | +$300.39 (better) | +$169.27 (worse) | rejected (overfit) |
| **TP 6.0×ATR** | +$538.06 | **+$342.62 (better)** | **+$195.44 (better)** | **survives** |
| ATR floor 2.5 / 3.0 / 3.5 | n/a | +$291 / +$315 / +$336 | +$180 / +$199 / +$176 | survive (but cost trades) |
| session 08-20 | n/a | +$317.06 (better) | +$223.36 (better) | survives |
| session 09-20 | n/a | +$376.70 (better) | +$172.04 (+$1.52, marginal) | **fails walk-forward: Q3 −$38.80, 3/4 folds** |

Two lessons worth recording:

- **The in-sample sweeps are actively misleading on this dataset.** "Remove the
  breakeven ratchet" (+$563) and "widen the stop to 2.5×ATR" (+$520) are the two
  biggest in-sample improvements available, and *both* are worse than the
  adopted config on TRAIN alone. Anyone tuning on the full file would have
  adopted either and been fitting the second half.
- **Surviving TRAIN+OOS is not sufficient.** `session 09-20` clears both (OOS by
  $1.52) and then loses a walk-forward quarter. The regime split and 4-fold
  walk-forward are load-bearing checks, not decoration.

**The one candidate that survives everything** is `TP 5.0 → 6.0 ×ATR`:
TRAIN +$342.62, OOS +$195.44, better in **both** regimes (Jun–Jul $347.00 vs
$283.86; Aug–Sep $191.06 vs $172.72), **4/4 walk-forward folds** and it
specifically repairs the weak quarters (Q3 +$45.6 vs +$5.8; Q2 +$141.0 vs
+$112.0). Full sample: 251 trades, **+$538.06, PF 1.38, max DD $104.49**,
bootstrap P(net>0)=0.968. It is also monotone up to the plateau
(TP 3.5/4.0/5.0/6.0 = +$176/+$242/+$286/+$343 on TRAIN, flattening at 8.0), so
it is not a single lucky point. `TP 6.0 + ATR floor 3.0` is stronger again
(228 trades, +$580.90, PF 1.44, max DD $98.98, and the only config whose 95%
bootstrap CI excludes zero: **[$25.48, $1,145.70]**, P(net>0)=0.980).

**Why not adopt it now anyway:**

1. **It is inside the noise.** +$81 over 101 days against a 95% CI roughly
   ±$570 wide. It is a better point estimate, not a demonstrated improvement.
2. **This dataset is already spent.** `GOLD_M5.csv` was inspected in PR #7,
   tuned on in PR #11 and split in PR #12. "Survives a retrospective split of a
   file we have looked at three times" is weaker evidence than it looks — PR #12
   says exactly this, and the untouched pre-June-2026 pull
   (`fetch_data.py --start-pos 20000`) still has not been run.
3. **It costs the thing PR #11 bought.** 255 → 251 trades for TP 6.0, and
   → 228 with the ATR floor. The user's last instruction was that the bot was
   "hardly taking any trades"; ATR floor 3.5 alone cuts OOS trades 124 → 88.
4. **It resets the launch clock.** PR #11 merged **2026-10-01 12:01:18 UTC**
   (verified via `gh`), so the paper book has been running the new config for
   about a day. §5's gate to LIVE is *100+ paper trades under a stable config*;
   changing parameters a third time in three days throws away the sample that
   actually gates the decision.

**Pre-registered instead of adopted.** Re-test, on the untouched pre-June pull
plus the accumulating post-`2026-09-11` paper book, in this order:
`TP 6.0×ATR`, then `TP 6.0 + ATR floor 3.0`, then `session 08-20`. Adopt only if
each is still better on data not used here.

## 6. Also closed by this analysis

- **§5 "skip new entries after 16:00 UTC on Friday (thin gold)" is wrong for
  this data.** Friday ≥16:00 is **+$51.90 over 16 trades** (Fri 16:00 +$63.31,
  Fri 17:00 +$25.15) — the profitable part of Friday. Friday's damage is in the
  **morning/early afternoon**: Fri 07:00 −$36.74, Fri 13:00 −$34.58. Adopting
  the TODO as written would cut Friday's winners and keep its losers.
- **`MAX_CONSECUTIVE_LOSSES`** — measured at 3/4/5/6, rejected (§3).
- **`MAX_TRADES_PER_DAY=15`** never binds (max 7/day in 101 days); leave it.
- **Backtest vs live gate divergence** is ~$18 over this window (§3) — worth
  remembering when the paper book is compared trade-by-trade with the backtest.

## 7. Reproduce

```bash
python research/strategy_sweep.py --verify          # engine == backtest.py
python research/parity_test.py                      # engine == live check_signal
python research/loss_analysis.py                    # §2-§4 anatomy
python research/loss_analysis.py --json trades.json # per-trade dump
python research/strategy_sweep.py --candidates      # §5 train-select -> cold OOS
python research/strategy_sweep.py --oos             # splits/walk-forward (PR #12)
python research/strategy_sweep.py --detail --bootstrap 10000 --set tp_atr_mult=6.0
```

## 8. Changes made in this pass

- **`research/loss_analysis.py`** (new): per-trade loss anatomy via the verified
  replay — exit-type P&L decomposition, spread-vs-edge cost split, streak/day
  clustering, replay of the live `MAX_DAILY_LOSS` / `MAX_TRADES_PER_DAY` gates,
  counterfactual `MAX_CONSECUTIVE_LOSSES` wiring, conditional expectancy by
  hour/weekday/side/month/ATR quartile, MFE-excursion analysis for the BE
  trigger, and concentration/tail stats.
- **`research/strategy_sweep.py`**: added `--candidates` /
  `candidate_report()` — re-tests BE, SL, TP, time-exit, ATR floor and session
  under the **adopted** config with train-select → cold-OOS → regime split →
  4-fold walk-forward, which `--oos` only did for the pre-PR#11 configs.
- **No change to `config.py`, `strategy.py`, `run.py` or `backtest.py`.**
  `TRADING_MODE` stays `"FORWARD_TEST"`.
