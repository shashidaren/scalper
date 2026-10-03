#!/usr/bin/env python3
"""BTC dashboard on its own port (8089), reading the BTC instance's log files.

    mt5env/bin/python /root/scalper/btc/dashboard.py

systemd unit: services/scalper-btc-dashboard.service
Reuses the repo-root dashboard app/template; the title and the log directory
come from btc/config.py, so the two boards never show each other's book.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import _instance  # noqa: E402

config = _instance.activate(HERE)
_instance.add_engine_path(ROOT)

# Loaded by path on purpose: a plain `import dashboard` would re-enter THIS file
# (btc/ is first on sys.path) instead of the repo-root app.
dashboard = _instance.import_engine("dashboard", ROOT)

app = dashboard.app

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("DASHBOARD_PORT", getattr(config, "DASHBOARD_PORT", 8089)))
    uvicorn.run(app, host="0.0.0.0", port=port)
