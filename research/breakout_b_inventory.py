"""Print BREAKOUT-B v2 input fingerprints, not a readiness verdict or results."""
import argparse
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

START = datetime(2026, 11, 23)
SPLIT = datetime(2027, 1, 4)
END = datetime(2027, 2, 1)
HEADER = b'time,open,high,low,close,tick_volume,spread'


def inventory(path):
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].rstrip(b'\r\n') != HEADER:
        raise ValueError('expected unmodified fetch_data.py GOLD M5 export')
    parts = {key: [] for key in ('train', 'oos')}
    seen_weeks = set()
    first = previous = None
    for line in lines[1:]:
        fields = line.rstrip(b'\r\n').split(b',')
        if len(fields) != 7 or not all(fields):
            raise ValueError('incomplete CSV row')
        t = datetime.strptime(fields[0].decode('ascii'), '%Y-%m-%d %H:%M:%S')
        if t.minute % 5 or t.second or (previous is not None and t <= previous):
            raise ValueError('expected strictly increasing M5 bar times')
        first = first or t
        previous = t
        if START <= t < END:
            parts['train' if t < SPLIT else 'oos'].append((t, line))
            seen_weeks.add((t - START) // timedelta(weeks=1))
    if first is None or first >= START or previous < END or len(seen_weeks) != 10:
        raise ValueError('need a pull bracketing the reservation with data in all ten weeks')

    result = {'protocol': 'BREAKOUT-B v2', 'source': path.name,
              'raw_sha256': sha256(raw).hexdigest()}
    for key, rows in parts.items():
        digest = sha256(lines[0])
        for _, line in rows:
            digest.update(line)
        result[key] = {'rows': len(rows), 'first': str(rows[0][0]),
                       'last': str(rows[-1][0]), 'sha256': digest.hexdigest()}
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('csv', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(inventory(args.csv), indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Inventory refused: {exc}\n')
