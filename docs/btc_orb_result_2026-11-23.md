# BTC-ORB-EU-H1 — negative research result (FAIL / No-Go), 2026-11-23

**Hypothesis ID:** `BTC-ORB-EU-H1` · **Date evaluated:** 2026-11-23 · **Status:** REJECTED ON TRAIN (FAIL / No-Go)

**Question:** Does the pre-registered European opening-range breakout (`BTC-ORB-EU-H1`) have an edge on the untouched XM `BTCUSD` H1 data after broker spread costs?

**Answer: NO. FAIL / No-Go.** On the 13,119 pre-registered TRAIN bars (`2021-12-09 10:00:00` → `2023-06-27 10:00:00 UTC`), **every one of the 6 pre-registered cells failed TRAIN eligibility**. In every cell, gross edge failed to pay for broker spread costs (`grossR < costR`), net R was negative, and net USD at 0.01 lots was negative (PF 0.69 – 0.94).

Per the pre-registration protocol (`docs/btc_hypothesis_orb_h1_2026-10-31.md` §2.4, §5.4 and `plans/btc.json` Phase 2 step 3):
- No winner was selected.
- The cold OOS segment (`2023-07-05 19:00:00` → `2024-06-25 21:00:00 UTC`, 8,547 bars) **was NOT read** and remains strictly uninspected (`results_inspected: false`).
- Hypothesis D (`BTC-ORB-EU-H1`) is **closed and rejected**.
- Phase 2 (`btc-hypothesis-test`) is **closed with an explicit fail / close**.
- `BTC_STRATEGY` stays `scalp`; `TRADING_MODE` stays `FORWARD_TEST`; LIVE stays **NO-GO**.

---

## 1. TRAIN Screen Results (XM H1 Real Spread)

Executed on `scalping` via `btc/phase2_orb.py --train` against `data/BTCUSD_H1_pre2024.csv` (sha256 `e1bc65a2f680d69dc1a2576b04dce01eeb7ce0b476afd2fa777f1ef34b0f57f6`):

| stop × filter | n | grossR | costR | netR | PF | net$ (0.01 lot) | Eligible? (n ≥ 80 & grossR > costR) |
|---|---|---|---|---|---|---|---|
| 1.0 × off | 449 | −0.006 | 0.230 | −0.236 | 0.69 | −$256.11 | **NO** (grossR < costR, net < 0) |
| 1.0 × ema200 | 314 | +0.135 | 0.235 | −0.100 | 0.88 | −$64.37 | **NO** (grossR < costR, net < 0) |
| 1.5 × off | 449 | +0.005 | 0.153 | −0.148 | 0.76 | −$212.28 | **NO** (grossR < costR, net < 0) |
| 1.5 × ema200 | 314 | +0.106 | 0.157 | −0.050 | 0.94 | −$35.85 | **NO** (grossR < costR, net < 0) |
| 2.0 × off | 449 | −0.017 | 0.115 | −0.132 | 0.72 | −$267.04 | **NO** (grossR < costR, net < 0) |
| 2.0 × ema200 | 314 | +0.049 | 0.117 | −0.068 | 0.86 | −$86.64 | **NO** (grossR < costR, net < 0) |

---

## 2. Why the hypothesis failed

1. **Broker spread is punitive on XM BTCUSD H1:**
   In the proxy Binance spot screen (`docs/btc_hypothesis_orb_h1_2026-10-31.md` §2.1), `costR` was estimated at 0.042 – 0.085 based on an idealized spread percentage. On actual XM broker quotes (`--cost file`), measured `costR` was **0.115 to 0.235** (over 2.5× higher relative to ATR stop distance).
2. **Gross edge does not overcome cost:**
   Even with the EMA(200) trend filter, gross R was only +0.049 to +0.135 — completely wiped out by the 0.117 to 0.235 cost of crossing the spread on entry and exit.
3. **No viable candidate:**
   Without a single cell generating positive net expectation (`grossR > costR`), selecting any cell for cold OOS would be data mining / curve fitting against noise.

---

## 3. Protocol & Integrity Status

- **Cold OOS preserved:** The 8,547 cold OOS bars were never read or evaluated.
- **Manifest:** `btc/manifests/btc_orb_eu_h1_2026-10-31.json` remains frozen with `results_inspected: false`.
- **Verdict:** Do NOT implement `BTC-ORB-EU-H1`. Do NOT loosen the stop multipliers or test alternate timeframes on this data.
- **Next steps for BTC:** Any future BTC candidate requires pre-registering a fundamentally different shape/family (or transitioning focus entirely to gold or broker recon).
