# Paper status (published snapshots)

This directory is maintained on branch **`status/paper`** by
`scripts/paper_status_daily.sh` when `PAPER_STATUS_TOKEN` is set on the server.

- **`paper_latest.json`** — latest paper book (balance, closed, wins, losses, position, ts).
- No secrets. Safe to read from the daily-review agent via GitHub API.

Daily review protocol: prefer this file over asking the user to paste `python paper.py`.
