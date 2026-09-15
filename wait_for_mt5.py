#!/usr/bin/env python3
"""Wait for the MT5 RPyC bridge to become reachable (and MT5 ready).

Usage:
    python wait_for_mt5.py [--timeout 180] [--interval 5] [--tcp-only]

Polls the RPyC endpoint (HOST:PORT from config.py) until it accepts
connections and, by default, until MetaTrader5 inside it initializes.
Exit code 0 when ready, 1 on timeout.

Used by scalper-bot.service as an ExecStartPre gate so the engine only
starts once the MT5 Docker container is actually up, and useful on its
own as a diagnostic:

    python wait_for_mt5.py --timeout 30
"""
import argparse
import socket
import sys
import time

import config


def probe_tcp(host, port, timeout=5.0):
    """Returns (ok, human_readable_error)."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, None
    except ConnectionRefusedError:
        return False, (
            f"connection refused by {host}:{port} - nothing is listening. "
            f"Is the MT5 Docker container running? (check 'docker ps')"
        )
    except (socket.timeout, TimeoutError):
        return False, f"connection to {host}:{port} timed out (host down or firewalled?)"
    except OSError as e:
        return False, f"connection to {host}:{port} failed: {e}"


def probe_mt5():
    """Connect via RPyC and check that MetaTrader5 initializes. Returns (ok, error)."""
    import rpyc

    conn = None
    try:
        conn = rpyc.classic.connect(config.HOST, config.PORT)
        mt5 = conn.modules.MetaTrader5
        if not mt5.initialize():
            try:
                err = mt5.last_error()
            except Exception:
                err = "unknown"
            return False, f"mt5.initialize() failed: {err}"
        try:
            mt5.shutdown()
        except Exception:
            pass
        return True, None
    except Exception as e:
        return False, str(e)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="Wait for the MT5 RPyC bridge to be ready")
    parser.add_argument("--timeout", type=int, default=180,
                        help="total seconds to wait before giving up (default: 180)")
    parser.add_argument("--interval", type=int, default=5,
                        help="seconds between attempts (default: 5)")
    parser.add_argument("--tcp-only", action="store_true",
                        help="only require the TCP port to accept connections, "
                             "skip the MetaTrader5 initialize() check")
    args = parser.parse_args()

    print(f"[wait_for_mt5] waiting for MT5 bridge at {config.HOST}:{config.PORT} "
          f"(timeout={args.timeout}s, interval={args.interval}s)", flush=True)

    deadline = time.time() + args.timeout
    attempt = 0
    while True:
        attempt += 1
        ok, err = probe_tcp(config.HOST, config.PORT,
                            timeout=getattr(config, "CONNECT_TIMEOUT_SECONDS", 10))
        if ok and not args.tcp_only:
            ok, err = probe_mt5()
        if ok:
            print(f"[wait_for_mt5] MT5 bridge is ready (after {attempt} attempt(s))", flush=True)
            return 0

        remaining = deadline - time.time()
        print(f"[wait_for_mt5] not ready (attempt {attempt}): {err}", flush=True)
        if remaining <= 0:
            print("[wait_for_mt5] timed out waiting for MT5 bridge", flush=True)
            return 1
        time.sleep(min(args.interval, max(remaining, 0.1)))


if __name__ == "__main__":
    sys.exit(main())
