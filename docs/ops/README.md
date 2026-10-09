# Server-only ops copies

These files are the backup. The live copies stay outside the deploy tree.

- `paper_status_daily.sh` runs from `/root/ops/paper_status_daily.sh`.
- `/root/ops/.env.paper_status` holds `PAPER_STATUS_TOKEN`. It is gitignored and must not be committed.
- Cron to install on `scalping` (the 2026-10-10 box had the paper line commented out):

```bash
CRON_TZ=UTC
PATH=/root/scalper/mt5env/bin:/usr/local/bin:/usr/bin:/bin
MAILTO=root

*/15 * * * * mkdir -p /root/scalper/logs && DEPLOY_BRANCH=main /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1
7 1 * * * test -x /root/ops/paper_status_daily.sh && /root/ops/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1 || echo "$(date -Is) paper_status missing or exited non-zero" >> /root/scalper/logs/paper_status.cron.log
```

A pull does not install the crontab or the script. After a change here, copy the script to `/root/ops/`, `chmod +x`, and install the block above with `crontab`.
