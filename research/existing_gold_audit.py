"""Read-only descriptive audit of published Gold data; no strategy search.
Run from any directory: python research/existing_gold_audit.py
Standard library only. Current book = last state['closed'] exits (reset aware).
"""
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def stats(rows):
    p = [r['profit'] for r in rows]
    won = sum(x for x in p if x > 0)
    lost = -sum(x for x in p if x < 0)
    return f"{len(p)} | ${sum(p):.2f} | {won / lost:.2f}" if lost else f"{len(p)} | ${sum(p):.2f} | n/a"


def main():
    state = json.loads((ROOT / 'logs/paper_account.json').read_text())
    events = [json.loads(s) for s in (ROOT / 'logs/ledger.jsonl').read_text().splitlines() if s.strip()]
    all_exits = [e for e in events if e['event'] == 'SIM_EXIT']
    n = state['closed']
    assert 0 < n <= len(all_exits), 'Incomplete current-book ledger'
    exits = all_exits[-n:]
    start = state['balance'] - sum(e['profit'] for e in exits)
    balance = peak = start
    dd = 0
    for e in exits:
        balance += e['profit']
        assert abs(balance - e['balance_after']) < 0.021, 'Balance-chain mismatch'
        peak = max(peak, balance)
        dd = max(dd, peak - balance)
    print('# Existing Gold data audit — 2026-10-26\n')
    print('Descriptive / hypothesis-generating only. No parameters changed, no new OOS gate run.\n')
    print('## Published book\n')
    print(f"State timestamp: {state['updated_at']}. Current book: last {n} exits; {len(all_exits)-n} older exits excluded across reset. Inferred starting balance ${start:.2f}; balance chain verified.\n")
    print('| Group | Closed | Net | PF |\n|---|---:|---:|---:|')
    print('| All | ' + stats(exits) + ' |')
    for key in ('side', 'reason'):
        for value in sorted({r[key] for r in exits}):
            print(f'| {key}={value} | ' + stats([r for r in exits if r[key] == value]) + ' |')
    for label, subset in [('First 34', exits[:34]), ('Remaining 35', exits[34:]), ('Since Oct 23 snapshot', [r for r in exits if r['time'] > '2026-10-23 20:00:00'])]:
        print(f'| {label} | ' + stats(subset) + ' |')
    wins = [r['profit'] for r in exits if r['profit'] > 0]
    losses = [r['profit'] for r in exits if r['profit'] < 0]
    zeros = sum(r['profit'] == 0 for r in exits)
    print(f'\nPositive / negative / zero P&L: {len(wins)} / {len(losses)} / {zeros}. State wins/losses: {state["wins"]}/{state["losses"]}; the state loss counter includes zero-P&L exits, so it is not a count of cash losses.')
    print(f'\nMean winner ${sum(wins)/len(wins):.2f}; mean cash loss ${-sum(losses)/len(losses):.2f}. Closed-equity max drawdown ${dd:.2f} ({dd/start:.1%} of starting balance; not intratrade drawdown).')
    ranked = sorted(wins, reverse=True)
    net = sum(r['profit'] for r in exits)
    print(f'\nLargest three winners total ${sum(ranked[:3]):.2f}; net without them ${net-sum(ranked[:3]):.2f}. This is concentration sensitivity, not a reason to discard winners.')
    days = defaultdict(float)
    for r in exits:
        days[r['time'][:10]] += r['profit']
    rng = random.Random(20261026)
    values = list(days.values())
    boot = sorted(sum(rng.choices(values, k=len(values))) for _ in range(10000))
    print(f'\nExit-day clustered bootstrap (10,000 draws, seed 20261026, {len(days)} exit days): 95% percentile interval for resampled total net [${boot[249]:.2f}, ${boot[9749]:.2f}]. Days without exits excluded; assumes independent exit-day clusters, does not establish an edge or model regime change.')
    print('\n## Candle coverage and integrity\n')
    print('| File | Rows | First | Last | Duplicate times | OHLC violations | Gaps > interval | SHA256 |\n|---|---:|---|---|---:|---:|---:|---|')
    for name, minutes in [('GOLD_M1.csv', 1), ('GOLD_M5.csv', 5)]:
        path = ROOT / 'data' / name
        with path.open() as f:
            rows = list(csv.DictReader(f))
        times = [datetime.fromisoformat(r['time']) for r in rows]
        assert times == sorted(times), 'Unsorted candles'
        bad = sum(not (float(r['low']) <= min(float(r['open']), float(r['close'])) <= max(float(r['open']), float(r['close'])) <= float(r['high'])) for r in rows)
        gaps = sum((b-a).total_seconds() > minutes*60 for a,b in zip(times,times[1:]))
        print(f'| {name} | {len(rows)} | {times[0]} | {times[-1]} | {len(times)-len(set(times))} | {bad} | {gaps} | `{hashlib.sha256(path.read_bytes()).hexdigest()}` |')
    print('\nGaps include scheduled market closures; these counts alone do not prove missing broker data. Candle timestamps are treated as supplied; this audit does not independently verify broker timezone. File hashes identify inputs, not broker provenance.')
    print('\n## Interpretation and next steps\n')
    print('- The open position is excluded from realized P&L; no mark-to-market equity or current terminal access is available here. Published heartbeat is a historical observation, not a fresh liveness check.')
    print('- M1 and M5 are separate rolling exports, not automatically synchronized tick replay. Do not use M1 as intrabar validation unless entry/exit windows actually overlap.')
    print('- Paper BE is booked at zero, whereas backtest BE subtracts spread; summary PF is not directly comparable across these execution models. Entry timing, bid/ask treatment, weekend exit, and intrabar sequencing also need matched replay. Zero paper BE does not by itself prove spread is omitted: spread may be embedded in quote-side fills.')
    print('- BREAKOUT-B protocol needs clarification before any sweep: its Cartesian grid is 3×3×3×3×2 = 162 combinations, not ≤54. Its fresh rolling pull can overlap inspected history; freshness of download is not coldness of OOS. Fix the exact subset/exit rules and reserve genuinely unseen timestamps before results are inspected. Do not silently expand or reinterpret the locked plan.')
    print('- Do not fit side/hour filters from these small, post-hoc groups. Keep FORWARD_TEST and existing geometry; prioritize matched execution diagnostics and a corrected pre-registered prospective test.')


if __name__ == '__main__':
    main()
