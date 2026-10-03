#!/usr/bin/env python3
"""BTC instance entry point: the repo-root engine running on btc/config.py.

    mt5env/bin/python /root/scalper/btc/run.py

systemd unit: services/scalper-btc-bot.service
See btc/HANDOFF.md (architecture, §2) and btc/config.py for what is still a
placeholder. `TRADING_MODE` is `"FORWARD_TEST"` in btc/config.py — no orders.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)          # so `_instance` is importable

import _instance  # noqa: E402

_instance.activate(HERE)          # btc/config.py becomes `config`
_instance.add_engine_path(ROOT)   # shared engine: strategy.py, mt5_bridge.py, ...

# Loaded by path on purpose: a plain `import run` would find THIS file again
# (btc/ is first on sys.path), not the engine at the repo root.
run = _instance.import_engine("run", ROOT)

if __name__ == "__main__":
    run.main()
