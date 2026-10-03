# NEW SESSION — start here (BTCUSD scalper, 2026-10-03)

Self-contained. A brand-new session with **zero prior context** can work from
this page alone. Nothing here is a claim without a command behind it.

---

## 0. What to attach / how to get the code

The work below lives on branch `arena/it5nyylu9o8jzc4zjpw3q-scalper`
(4 commits on top of `main` = `a4d6ecf`). It is **not on GitHub yet** — the
sandbox that made it has no push credentials.

Pick one, then tell the new session which you did:

| Option | Action |
|---|---|
| **Push it yourself** | `bash push_and_open_pr.sh <path>/scalper-btc-phase1b.bundle` — clones, pushes the branch, opens the PR (needs your GitHub auth; `gh` or `GITHUB_TOKEN`) |
| **Attach to the new session** | attach `scalper-btc-phase1b.bundle` **and** `server_phase1b_commands.sh`; the new session creates a clone of `shashidaren/scalper`, fetches the branch from the bundle, and continues |
| **Patch series** | attach `patches/000*.patch`; apply with `git am` onto a clean `main` |

Either way the new session should first confirm the tree matches
`614f0e512e99efc226a8cdff9f569fd9c4d2c56b` (`git rev-parse HEAD^{tree}`).

---

## 1. The mission in one paragraph

Gold's scalper (EMA200 + RSI-pullback + ATR stop/TP, M5) was extended to a
BTCUSD instance (`btc/`) — plumbing merged and verified. Phase 0 is met (BTC
data exists) and Phase 1a measured the economics. **Phase 1b is the open
question: does *any* configuration of this shape clear a near-fixed ~$42
spread on BTCUSD?** If not, the deliverable is a one-page negative result and
**no service**. Gold must stay untouched throughout.

## 2. Verified state (all re-run on this tree)

Repositories/instances:

- Gold regression (must never move): `backtest.py` → **255 trades / +$456.58 /
  PF 1.32 / max DD $108.65 / 72 TP · 43 BE · 140 SL**;
  `research/parity_test.py` → **PASS** (460 signals, 0 mismatches + blackout
  check); `research/paper_exit_test.py` → **PASS** (M5 OHLC 48 / +$89.43 / PF 1.35);
  `btc/tool.py --check` → **10/10**; `btc/e2e_smoke.py` → **ALL PASS** on the
  BTC instance and on `--config-dir .` (gold).
- Env: `python3 -m venv /tmp/v1 && /tmp/v1/bin/pip install pandas numpy rpyc
  jinja2 fastapi uvicorn` (no pandas by default).

Server (`scalping`) — observed 2026-10-03:

- `data/BTCUSD_M5.csv`: 20,000 bars, 2026-07-25 21:55 → 2026-10-03 13:40 UTC,
  5,600 weekend bars ⇒ **24/7 confirmed**. It is **not in git** — research runs
  happen on the server via `mt5env/bin/python btc/tool.py <script>`.
- Measured: median price **$77,304.55**; digits 2; ATR(14) p10/25/50/75/90 =
  **29.58 / 48.32 / 81.62 / 121.31 / 179.03**; spread **mean 4,242 points =
  $42.41, quantised 4,000–5,000 (near-fixed)** ⇒ at inherited 2.0×/5.0× geometry
  = **52% of median ATR, 26% of risk per trade** (gold: 10.5% / 5.3%), so the
  structural break-even WR is ~36% spread-aware. Gold's parameters replayed on
  the BTC file: **433 trades / −$165.84 / PF 0.74**.
- `scalper-btc-bot`: **installed; was enabled+inactive; `systemctl disable
  --now` run 2026-10-03** (user-reported — confirm with `systemctl
  is-enabled`/`is-active`). **`disable` is not sufficient:** `deploy.sh`
  defaults `DEPLOY_SERVICES="scalper-bot scalper-btc-bot"` and `systemctl
  restart` starts a merely-disabled unit, so also set the cron to
  `DEPLOY_SERVICES="scalper-bot"` **or** `systemctl mask scalper-btc-bot`.
- Gold bot: running, `FORWARD_TEST`, live on the shared RPyC terminal
  `localhost:18812`.

## 3. Next task — Phase 1b on the real file

```bash
cd /root/scalper && bash server_phase1b_commands.sh      # read-only, ~2 min
# then paste back logs/phase1b/*.txt
```

Check `02_verify.txt` **first**: the sweep engine must reproduce `backtest.py`
exactly, or every later number is meaningless. (Already proven sound on a
20,000-bar BTC series: 447 / −$189.26 / PF 0.71 both ways.)

The script runs: `derive_params` · `--verify` · sweeps (`sl`, `tp`, `be`, `rsi`,
`spread`) · ATR floors at the measured quantiles + stops 4–6×ATR · combinations
(`be_trigger_r=off`, **never `0`** — 0 arms BE at entry and scratches ~all
trades) · `--candidates` · `loss_analysis` · a 60-config train-select →
cold-OOS grid (`/tmp/btc_train_select.py`, provisional, not part of the repo).

Rule: **select on TRAIN only, read OOS cold.** Never rank the full file — that
is the trap the gold book fell into (`docs/loss_analysis_2026-10-02.md`).

### Indicative result already obtained (proxy data — NOT evidence)

`proxy_runs/00_SUMMARY.md` ran the same battery on a Binance BTCUSDT M5 series
matched to the same window with a 4,500-point spread injected (its ATR
quantiles match the XM file within ~5%):

- **the raw signal is edge-less before costs (+$11.89 over 447 trades) and the
  spread alone makes it −$189.26**; with a gold-like $5 spread the same config
  is ~flat (PF 0.98);
- every one-at-a-time arm stays negative; best (4–5×ATR stop) is PF 0.97;
- the only TRAIN-positive config that is also OOS-positive —
  `SL 2.5×ATR / BE off / atr_min 121.31` — gives +$29.87 on **48 trades**,
  P(net>0)=0.743, CI [−59.9, +115.5], 2/4 walk-forward folds. **Does not clear
  the gate.**

Expect the same answer on the real file. A negative result is acceptable and
is the documented outcome — **do not tune until something looks positive.**

## 4. Remaining blockers before `scalper-btc-bot` may EVER start

1. `MAX_SPREAD_POINTS = 1500` in `btc/config.py` is **below the measured
   4,000–5,000** — a started bot would skip 100% of signals while the backtest
   trades normally. Derive it from the data first.
2. The shared-bridge concurrency probe (`btc/HANDOFF.md` §7) has **never been
   run**, and gold is live on the same RPyC terminal.
3. The unit-deployment matter in §2 above (cron / mask), until Phase 2.

## 5. Standing rules

- Gold untouched: after any shared-code change, `backtest.py` and
  `parity_test.py` must reproduce §2 exactly.
- Both instances stay `TRADING_MODE="FORWARD_TEST"`.
- BTC uses the same XM account/terminal as gold — fine for paper, a hard
  blocker at any LIVE flip without a separate account or a combined risk gate.
- **Never copy gold's parameter values.**
- Update `HANDOFF.md` §1/§3/§5 and `btc/HANDOFF.md` §0/§6/§9 with dated,
  **observed** evidence before the session ends; open the PR from the session
  branch.

## 6. Deliverable if Phase 1b says no

- `docs/btc_phase1_result_<date>.md` — one page: what was swept, the numbers,
  why the spread makes it unviable, what would have to change (e.g. a wider
  stop that is no longer scalping, or a different shape entirely).
- `btc/config.py` stays on its placeholders; `scalper-btc-bot` stays stopped.
- Handoffs updated with the observed output; PR opened.
