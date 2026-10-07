# Server-only ops copies

These files are the backup. The live copies stay outside the deploy tree.

- `paper_status_daily.sh` runs from `/root/ops/paper_status_daily.sh`.
- `/root/ops/.env.paper_status` holds `PAPER_STATUS_TOKEN`. It is gitignored and must not be committed.
- Cron, installed 2026-10-08:

```bash
CRON_TZ=UTC
PATH=/root/scalper/mt5env/bin:/usr/local/bin:/usr/bin:/bin
MAILTO=root
*/15 * * * * mkdir -p /root/scalper/logs && DEPLOY_BRANCH=main /root/scalper/deploy.sh >> /root/scalper/logs/deploy.cron.log 2>&1
7 1 * * * /root/ops/paper_status_daily.sh >> /root/scalper/logs/paper_status.cron.log 2>&1
```

A pull does not install the script. After a change here, copy it to `/root/ops/` and `chmod +x`.
