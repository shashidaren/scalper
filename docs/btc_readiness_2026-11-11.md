# BTC readiness review — 2026-11-11

Executing [`plans/btc.json`](../plans/btc.json) phase 1
(`btc-hypothesis`, "pre-register a new BTC hypothesis on untouched bars") from a
repo checkout that **cannot reach the MT5 bridge**. This note records what was
executed, the decision this session made about the remaining step, and the
readiness state as of today.

**Nothing trades differently because of this note.** `TRADING_MODE` stays
`FORWARD_TEST`, `BTC_STRATEGY` stays `scalp`, `MAX_SPREAD_POINTS` stays 6,250,
`btc/config.py` is untouched, no service unit changed, and both books stay
**NO-GO**.

---

## 1. Where phase 1 actually stands

| | state today |
|---|---|
| pre-registration (`BTC-ORB-EU-H1`) | **written and committed** 2026-10-31, 6-cell grid, gate fixed before data |
| proxy screen behind it | run 2026-10-31, 36 combinations, **proxy only — not evidence** |
| reserved window | XM H1 `time < 2024-06-25 22:00 UTC`, the only era this repo has never read |
| XM H1 bars for that window | **not pulled** (`data/` holds gold CSVs only) |
| freeze manifest | **absent** — `btc/manifests/` does not exist in this checkout |
| `results_inspected` | false, and no result has been read |
| phase status in the plan | `active` — correct, because the exit gate is a *committed manifest* |

Exit gate, quoted from the plan: *"A committed pre-registration with fresh hashes
and boundaries, and no result inspected yet."* One half of that exists. The
half that does not — the hashes — needs `btc/recon.py`, an RPyC bridge and the
`mt5env` interpreter on `scalping`. This sandbox has none of the three.

## 2. The decision: do not manufacture a freeze

Options considered for finishing phase 1 from here:

| option | verdict |
|---|---|
| Freeze the Binance proxy H1 file that the screen already used | **Rejected.** The gate reads XM bars only (`btc/HANDOFF.md` "Do not"), `btc/freeze.py` would hash a file whose bars are not the broker's, and a pass/fail on it would be a statement about the wrong market. |
| Freeze nothing and mark phase 1 `done` so phase 2 can start | **Rejected.** That is precisely the failure mode the phases exist to prevent: a sweep would then run on a window nobody hashed. The plan's validator also forbids `next` pointing past an unfinished blocker. |
| Reuse `data/BTCUSD_H1.csv` (the burnt 2024-06→2026-10 file) | **Rejected by tooling**: it is on the `INSPECTED_SHA256` list and `btc/freeze.py` exits 2. |
| Start phase 2 (implement the `orb` family) while waiting | **Rejected for now.** The plan says phase 1 blocks everything else, and phase 2 exists to run the gate — building it before the freeze invites tuning it against the reserved window by accident. It is the right next move *after* the manifest lands. |
| **Execute everything that does not need the box, and make the one box step self-verifying** | **Chosen.** |

The reasoning is narrow: a pre-registration is worth exactly what its data
protocol is worth, and the protocol's whole claim is "these hashes existed before
anyone looked". A checkout that cannot read XM bars cannot produce that claim.
What it *can* do is remove every remaining way for the claim to be wrong when it
is finally made.

## 3. What this session added

`python3 btc/freeze.py --status` — a read-only reconciliation between the two
records of the same fact: the manifest in `btc/manifests/` and the
`pre_registration.freeze` block in `plans/btc.json`. The freeze tool used to be
one-way: it wrote a manifest and never looked back, so nothing noticed if the
plan and the disk disagreed. They are written at different times, by different
hands, and a mismatch is how a sweep ends up running on a window nobody hashed.

It checks, and reports each as a fact rather than a guess:

- plan `freeze.state` vs whether the manifest exists (both directions);
- manifest `state == "frozen"`, `results_inspected is False`;
- `hypothesis` matches `pre_registration.id`;
- `cutoff_exclusive` is at or before the inspected-era start (`2024-06-25 22:00`);
- `raw_sha256` is present, is not a known inspected file, and equals the plan's;
- when the source CSV is in this checkout, its sha256 equals the manifest's —
  i.e. the manifest really is for this file;
- a note when the phase is still `active`, because a `FROZEN` manifest that
  nobody recorded leaves phase 1 open.

Exit codes: `0` consistent (pending or frozen), `1` drift or an unsafe manifest,
`2` unreadable plan. `--json` emits the report for tooling. It writes nothing —
`btc/freeze.py --self-test` asserts byte-identical files and no new files across
a run.

Deliberately **not** in `tools/smoke_test.py`: creating a manifest on the box is
a legitimate action that happens *before* the commit that records it, so a gate
that ran this would red-line between the two and `autosync.sh` would roll back
every merge — the 2026-10-24 incident, exactly. The cases live in
`--self-test` (hermetic: pending, phantom freeze, uncommitted manifest, consistent, inspected, rejected, widened cutoff, wrong/burnt sha, tampered CSV, missing plan) and in the operator protocol below, and
`btc/freeze.py` is on the inert list of all four units, so this changes no
deploy behaviour.

Also updated: the plan (phase-1 steps now name the reconciliation, verdict
numbers refreshed to this book's published state, `freeze.csv` / `freeze.phase`
added so the tool reads the paths instead of hard-coding them), the RUNBOOK's
BTC gate, and `btc/HANDOFF.md`.

## 4. The paper book, today

It is an observation feed running a shape that already failed. It is allowed to
look like this, and none of it counts as evidence for `BTC-ORB-EU-H1`.

| | 2026-10-31 | **2026-11-11** |
|---|---|---|
| balance | $255.12 | **$244.42** (start $300, 2026-10-07) |
| closed | 158 | **213** — 42W / 171L |
| profit factor | 0.80 | **0.76** |
| exits | — | 142 SL · 42 TP · 29 BE |
| open position | one BUY | one SELL (BE armed) |

The 55 trades since the pre-registration cost **−$10.70** (PF 0.82), which is what
the Phase 1 result predicts rather than a new fact. Source:
`btc/logs/paper_account.json` (updated 2026-11-11 02:11:04 UTC) and
`btc/logs/ledger.jsonl`, 213 `SIM_EXIT` rows.

## 5. The one remaining step (needs `scalping`)

```bash
cd /root/scalper
mkdir -p /root/ops/collect-2026-10-31

# 1. pull — 44,000 H1 bars reaches back past 2021-10. NOT --bars 20000
mt5env/bin/python btc/recon.py --timeframe H1 --bars 44000 \
    --out data/BTCUSD_H1_pre2024.csv \
    --json /tmp/btc_pre2024_recon.json 2>&1 | tee /root/ops/collect-2026-10-31/recon.txt

# 2. freeze — writes the manifest, refuses every unsafe input, never overwrites
python3 btc/freeze.py --csv data/BTCUSD_H1_pre2024.csv --timeframe H1 \
    --cutoff "2024-06-25 22:00:00" --train-frac 0.60 --embargo-bars 200 \
    --warmup 1000 --min-kept 18000 --min-train 10000 --min-oos 7000 \
    --hypothesis BTC-ORB-EU-H1 --doc docs/btc_hypothesis_orb_h1_2026-10-31.md \
    --out btc/manifests/btc_orb_eu_h1_2026-10-31.json

# 3. verify the record, then commit it in the same commit as the plan update
python3 btc/freeze.py --status      # expect FROZEN, no [DRIFT] lines
```

Between steps 2 and 3 the tool will print `DRIFT` with the hint *"...exists —
record state='frozen' and its raw_sha256 in the same commit"*. That is correct,
not a fault: the manifest exists and the plan has not been told yet. The commit
that ends phase 1 contains the manifest, `pre_registration.freeze` with
`state: "frozen"` and the sha256, the STATUS row, and the phase marked `done`
with `next` moved to `btc-hypothesis-test`.

Nothing may read the cold OOS until that commit is on `main`. One look. No
re-selection, no re-split, no extra cell.

## 6. Gaps this session did **not** close

1. **Research tools do not refuse an unfrozen CSV.** `btc/edge_screen.py` and
   `btc/train_select.py` will happily sweep any file handed to them, including
   `data/BTCUSD_H1_pre2024.csv` before a manifest exists. The protocol is
   enforced by documentation and by `--status`, not by those entry points.
   Recommended for phase 2: a guard keyed on the CSV's own bars — if the file
   reaches into the reserved era and no manifest covers its sha256, exit
   non-zero unless an explicit override is passed. Not added here because it
   changes research-tool behaviour and needs its own tests.
2. **`orb` is still unimplemented.** Phase 2 has four items to build before a
   gate can run at all (`docs/btc_hypothesis_orb_h1_2026-10-31.md` §9).
3. **The untouched window is finite.** It is consumed by this test, whatever the
   result. If `BTC-ORB-EU-H1` fails, the next BTC hypothesis has to be
   forward-collected from 2026-11-01 or be a genuinely new mechanism that clears
   a screen first.
4. **Broker recon is still `parallel`** (phase 4): symbol spec, swap, server
   offset. It does not block phase 1 but blocks the demo drill.
