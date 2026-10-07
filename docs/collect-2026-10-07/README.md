# Phase-1c collection — 2026-10-07 (`scalping`) — **PENDING, not yet collected**

**Status: the collection has not been run.** The Arena sandbox this session ran
in cannot reach the server, so Task A of the 2026-10-07 session could not be
executed from here and **no output below is claimed as observed**. The exact
commands and the paste-back path are ready; this directory is the home for the
results.

Evidence that the server is unreachable from the sandbox (run 2026-10-07,
`e2b.local`):

```
$ whoami                                        -> user (uid 1001), no sudo
$ getent hosts scalping                         -> (no DNS entry)
$ ssh -o BatchMode=yes scalping 'echo REACHABLE' -> ssh: Could not resolve hostname scalping: Name or service not known
$ ls /root/scalper                              -> Permission denied
$ (connect 127.0.0.1:18812)                      -> Connection refused    (no MT5 bridge here)
$ (connect 127.0.0.1:8088)                       -> Connection refused    (no dashboard here)
```

This matches every earlier session's note (`HANDOFF.md` §1/§3, `btc/HANDOFF.md`
§6, `docs/btc_phase1_result_2026-10-03.md`): the sandbox reaches only
`github.com` / `api.github.com` / `pypi.org`. **No `ssh scalping`, no MT5, no
`/root/scalper/data/BTCUSD_H1.csv`.**

## What to run on the server (one command, read-only)

```bash
cd /root/scalper
bash docs/collect-2026-10-07/collect_phase1c.sh
# -> /root/ops/collect-2026-10-07/collection.md  (+ one .txt per step)
```

Then paste `collection.md` back into the session (or attach it) and it gets
committed here as `docs/collect-2026-10-07/collection.md`.

The script (`collect_phase1c.sh`, added by this branch) runs every step of the
session's Task A in order and records each command, its combined output and its
exit code:

| step | what it establishes |
|---|---|
| `btc/server_check.py --journal 30` | the §0 read-only state block (units, ports, data files, cron, deploy tail) |
| `crontab -l` | the live crontab as-installed (vs the reviewed block in `docs/cron_review_2026-10-07.md` §4) |
| `is-enabled` / `is-active` / `ActiveEnterTimestamp` for all four units | whether the gold bot is still on 2026-10-04-era code and what the BTC units really are (the handoffs say disabled/inactive; ground truth says enabled/active) |
| `ss -ltnp \| grep -E '8088\|8089\|18812'` | dashboards + shared MT5 bridge listening |
| `docker ps`, `tail -40 logs/deploy.cron.log`, `grep -c "would be overwritten" logs/deploy.cron.log` | the deploy freeze: ~63 h / ~250 ticks, 2026-10-04 12:30 → 2026-10-07 02:28 UTC |
| `git log -3`, `git status --porcelain`, `grep -c "PULL FAILED" logs/deploy.log` | HEAD = b033986 and whether the tree is still dirty |
| `json.load(logs/live_status.json).get("spread_gate")` | **null/missing ⇒ the running process predates PR #22** (this is the confirmation the session asked for) |
| `btc/recon.py --timeframe H1 --bars 20000 --json …/recon_h1.json` | H1 facts for BTCUSD (spread/ATR/price digits) — read-only |
| `btc/recon.py --timeframe H1 --bars 20000 --out data/BTCUSD_H1.csv` | **THE untouched H1 pull.** Never the inspected 2026-07-25..10-03 M5 window; that window is burnt for selection |
| `data/BTCUSD_H1.csv` span + sha256 | proof of *which* bars the gate read |
| `btc/tool.py btc/edge_screen.py --family donchian --csv data/BTCUSD_H1.csv --detail` | the g > c precondition (required; a shape whose gross edge cannot pay the spread may not be gated on) |
| `btc/tool.py btc/train_select.py --family donchian --csv data/BTCUSD_H1.csv` | **the gate**: TRAIN-only rank → one frozen cold-OOS read |
| `btc/derive_params.py --csv data/BTCUSD_H1.csv` | measured economics + the 1.25 × TRAIN p90 spread-gate candidate |
| `btc/tool.py btc/strategy_btc_test.py` | live/replay parity (expect **22/22**) |
| `btc/tool.py paper.py`, `grep -c high_spread btc/logs/trades.jsonl`, `journalctl -u scalper-btc-bot --since 2026-10-03 \| tail -50` | what BTC is *really* running: paper book state, the 100% `high_spread` veto at the 1,500-pt placeholder vs the ~4,242-pt real spread |

Safety: the script never starts/stops/enables/disables/restarts a unit, never
edits `config.py` or `btc/config.py`, never calls `mt5.shutdown()` (the gold bot
shares the terminal on `:18812`), never places an order, and writes nothing
inside the tracked tree except the git-ignored `data/BTCUSD_H1.csv`
(it refuses to write its outputs into the repo — a stray untracked file at a
path a later commit adds is exactly what makes every `git pull --ff-only`
abort, `docs/cron_review_2026-10-07.md` F2). Credentials are redacted
(`PASSWORD`/`TOKEN`/`SECRET`/`API_KEY`/`LOGIN` patterns) before they reach the
bundle.

## The gate rule (fixed — do not improvise, `btc/HANDOFF.md` §5)

From the **cold-OOS** read produced by `train_select --family donchian`:

* **FAIL** if `net <= 0`, or `PF < 1.2`, or `n < 60`, or `g <= c`
  → one-page negative result `docs/btc_phase1c_result_2026-10-07.md`, **no BTC
  service change**, no tuning on that file, and a *new* pre-registered
  hypothesis with its own untouched pull.
* **PASS** → document it, then **ask the user** before anything else. Only if
  approved: re-derive `MAX_SPREAD_POINTS` (1.25 × TRAIN p90), set
  `BTC_STRATEGY="donchian"` + `BTC_TIMEFRAME="H1"`, start **only** the BTC
  paper book (LIVE is refused for donchian by design — bar-close exits cannot
  drive broker orders), and give BTC its own 100-trade clock. Gold's clock
  continues untouched.

No PASS exists yet, so nothing in `btc/config.py` has been touched:
`MAX_SPREAD_POINTS` stays `1500`, `BTC_STRATEGY` stays `"scalp"`, both books
stay `FORWARD_TEST`.

## Open decisions (user's, not the agent's)

1. Whether the two BTC units keep running while the gate is unread (they are
   enabled + active per the 2026-10-07 ground truth, on the 1,500-pt gate that
   vetoes 100% of quotes — not dangerous, but an unrecorded state).
2. Whether the reviewed crontab (`docs/cron_review_2026-10-07.md` §4) is
   installed on `scalping`, and with which `DEPLOY_SERVICES` (gold only /
   `scalper-bot scalper-dashboard` / including the BTC units).

## Also missing: `docs/btc_data_collection_2026-10-07.md`

The session plan said this file was written after PR #24 was merged and could
be recovered with `git show arena/87d768e3-scalper:docs/btc_data_collection_2026-10-07.md`.
**It exists on no branch and in no PR of this repository** (checked:
`git log --all --diff-filter=A -- docs/btc_data_collection_2026-10-07.md`,
`git ls-tree` over every `origin/*` ref including `arena/87d768e3-scalper`
(HEAD `02cc856`) and GitHub code search → 0 hits). It could not be committed,
and whatever it contains needs to be pasted back by the user.
