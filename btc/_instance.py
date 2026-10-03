"""Instance bootstrap: make a chosen directory's config.py *be* `config`.

Why this exists
---------------
Every engine module at the repo root does a plain `import config`, so whichever
`config.py` Python finds first is the instance. That works by `sys.path` order,
but two things make path order fragile:

  * `research/strategy_sweep.py` (and friends) do
    `sys.path.insert(0, <repo root>)` at import time — which would put the GOLD
    config in front of this one;
  * `python -m` / cwd differences change who is "first".

So instead of ordering `sys.path`, the BTC entry points call
`activate(<instance dir>)` BEFORE importing any engine module: the chosen
config.py is executed and registered in `sys.modules["config"]`. After that,
every `import config` in the process — no matter what the script does to
sys.path — returns the instance config. Verified by `btc/tool.py --check` and
the gold regression (see btc/HANDOFF.md §6).
"""
from __future__ import annotations

import importlib.util
import os
import sys


def activate(instance_dir: str) -> object:
    """Load <instance_dir>/config.py as the process-wide `config` module."""
    instance_dir = os.path.abspath(instance_dir)
    cfg_path = os.path.join(instance_dir, "config.py")
    if not os.path.isfile(cfg_path):
        raise SystemExit(f"[instance] no config.py in {instance_dir}")

    if "config" in sys.modules:
        existing = getattr(sys.modules["config"], "__file__", "?")
        if os.path.abspath(existing) != cfg_path:
            raise SystemExit(
                f"[instance] a different config is already imported: {existing}\n"
                f"           refusing to silently mix instances."
            )
        return sys.modules["config"]

    spec = importlib.util.spec_from_file_location("config", cfg_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["config"] = module          # register BEFORE exec (imports inside see it)
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules["config"]
        raise
    return module


def add_engine_path(root: str) -> None:
    """Make the shared engine modules importable (append — never shadow config)."""
    root = os.path.abspath(root)
    if root not in sys.path:
        sys.path.append(root)


def import_engine(name: str, root: str) -> object:
    """Import a repo-root engine module *by path* and return it.

    Necessary because the instance shims share a filename with the engine
    module they need: `btc/run.py` cannot `import run` and `btc/dashboard.py`
    cannot `import dashboard` — the shim's own directory is first on sys.path,
    so the plain import would re-execute the shim (or trip a circular import).
    Loading by explicit path is immune to both.
    """
    root = os.path.abspath(root)
    if name in sys.modules:
        return sys.modules[name]
    path = os.path.join(root, name + ".py")
    if not os.path.isfile(path):
        raise SystemExit(f"[instance] engine module not found: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise
    return module
