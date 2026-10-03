#!/usr/bin/env python3
"""Run any repo script under the BTC instance config (or verify the isolation).

    # research tooling on BTC data (writes btc/logs/, uses btc/config.py)
    cd /root/scalper
    mt5env/bin/python btc/tool.py research/strategy_sweep.py --verify
    mt5env/bin/python btc/tool.py research/strategy_sweep.py --oos
    mt5env/bin/python btc/tool.py research/parity_test.py
    mt5env/bin/python btc/tool.py research/loss_analysis.py
    mt5env/bin/python btc/tool.py backtest.py
    mt5env/bin/python btc/tool.py fetch_data.py --symbol BTCUSD --bars 20000

    # prove the instance plumbing (no bridge, no MT5 needed)
    mt5env/bin/python btc/tool.py --check

    # use any other instance dir (used to regression-test the plumbing against
    # a gold-identical config; see btc/HANDOFF.md §6)
    mt5env/bin/python btc/tool.py --config-dir /tmp/inst_test backtest.py

Why a wrapper instead of plain `cd btc && python -m research...`: the research
scripts insert the repo root at the FRONT of sys.path at import time, which
would make the gold config.py win. This wrapper loads the instance config into
sys.modules["config"] first, so every `import config` in the process — whatever
the script does to sys.path afterwards — gets the instance config.
"""
from __future__ import annotations

import argparse
import os
import runpy
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def check(instance_dir: str, config) -> int:
    """Assert that the shared modules really picked up the instance config."""
    from pathlib import Path
    import logger
    import paper
    import strategy  # noqa: F401  (import must succeed under this config)

    want_log_dir = (Path(instance_dir) / "logs").resolve()
    checks = [
        ("config.__file__ == instance config", Path(config.__file__).resolve() == (Path(instance_dir) / "config.py").resolve()),
        ("logger.LOG_DIR == instance logs", Path(logger.LOG_DIR).resolve() == want_log_dir),
        ("logger.LOG_DIR != gold logs", Path(logger.LOG_DIR).resolve() != (Path(ROOT) / "logs").resolve()),
        ("paper.CONTRACT_SIZE == config.CONTRACT_SIZE", float(paper.CONTRACT_SIZE) == float(config.CONTRACT_SIZE)),
        ("paper.STATE_FILE under instance logs", Path(paper.STATE_FILE).parent.resolve() == want_log_dir),
        ("MAGIC_NUMBER != gold (999111)", int(config.MAGIC_NUMBER) != 999111),
        ("TRADING_MODE == FORWARD_TEST", str(config.TRADING_MODE) == "FORWARD_TEST"),
    ]

    try:  # needs pandas/numpy (present in mt5env and the local test venv)
        import research.strategy_sweep as sweep
        checks.append(("sweep.CONTRACT_SIZE == config.CONTRACT_SIZE",
                       float(sweep.CONTRACT_SIZE) == float(config.CONTRACT_SIZE)))
        checks.append(("sweep.POINT == 10^-PRICE_DIGITS",
                       abs(sweep.POINT - 10.0 ** -int(config.PRICE_DIGITS)) < 1e-15))
    except ImportError as e:
        print(f"  (skipping sweep checks: {e})")

    print(f"instance check — {instance_dir}")
    print(f"  config.__file__   {config.__file__}")
    print(f"  SYMBOL            {config.SYMBOL}   MAGIC {config.MAGIC_NUMBER}   MODE {config.TRADING_MODE}")
    print(f"  LOG_DIR           {logger.LOG_DIR}")
    print(f"  CONTRACT_SIZE     {config.CONTRACT_SIZE}   PRICE_DIGITS {config.PRICE_DIGITS}   LOT_SIZE {config.LOT_SIZE}")
    failed = 0
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        failed += 0 if ok else 1
    print("OK — instance isolation holds" if not failed else f"{failed} CHECK(S) FAILED")
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config-dir", default=HERE,
                    help="instance directory whose config.py should be used (default: btc/)")
    ap.add_argument("--check", action="store_true",
                    help="verify instance isolation and exit (no bridge needed)")
    ap.add_argument("script", nargs="?", help="repo script to run, e.g. research/strategy_sweep.py")
    ap.add_argument("script_args", nargs=argparse.REMAINDER, help="args passed to that script")
    args = ap.parse_args(argv)

    sys.path.insert(0, HERE)
    import _instance

    config = _instance.activate(args.config_dir)
    _instance.add_engine_path(ROOT)

    if args.check or not args.script:
        return check(args.config_dir, config)

    script = args.script
    if not os.path.isabs(script):
        candidate = script if os.path.isfile(script) else os.path.join(ROOT, script)
        script = os.path.abspath(candidate)
    if not os.path.isfile(script):
        print(f"[ERROR] no such script: {args.script}", file=sys.stderr)
        return 2

    script_dir = os.path.dirname(script)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    sys.argv = [script] + list(args.script_args)
    print(f"[instance {config.SYMBOL}] running {os.path.relpath(script, ROOT)} "
          f"{' '.join(args.script_args)}")
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
