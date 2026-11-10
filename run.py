#!/usr/bin/env python3
"""Cross-platform command runner for MarketTracker (Windows/macOS/Linux).

Usage:
    python run.py <command>

Examples:
    python run.py up
    python run.py test
    python run.py bench
    python run.py chaos
    python run.py demo
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def get_python() -> str:
    venv_win = ROOT / ".venv" / "Scripts" / "python.exe"
    venv_posix = ROOT / ".venv" / "bin" / "python"
    if venv_win.exists():
        return str(venv_win)
    if venv_posix.exists():
        return str(venv_posix)
    return sys.executable


PYTHON = get_python()

COMMANDS = {
    "up": "Start ClickHouse container and wait for health",
    "down": "Stop Docker containers",
    "test": "Run pytest unit, smoke, and Hypothesis property tests",
    "bench": "Run 4-stage mark-to-market performance ladder",
    "bench-ingest": "Run ClickHouse database ingestion throughput benchmark",
    "bench-book": "Run L2 orderbook latency and GC pause profiling",
    "bench-strategy": "Run tick-to-order latency and strategy profiler",
    "chaos": "Run fault-injection chaos harness (drops, dups, reordering)",
    "build-web": "Install and build production React frontend bundle",
    "demo": "Launch real-time FastAPI server and terminal UI (port 8000)",
    "lint": "Run ruff code linter",
    "format": "Run ruff code formatter",
    "clean": "Stop containers and remove ClickHouse volumes",
}


def run_cmd(cmd: str, cwd: Path = ROOT) -> int:
    print(f"--> Executing: {cmd}", flush=True)
    res = subprocess.run(cmd, shell=True, cwd=cwd)
    return res.returncode


def wait_clickhouse_healthy():
    print("Waiting for ClickHouse to become healthy...", flush=True)
    for _ in range(60):
        try:
            out = (
                subprocess.check_output(
                    "docker inspect --format '{{.State.Health.Status}}' market_tracker_clickhouse",
                    shell=True,
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
                .strip()
                .replace("'", "")
            )
            if out == "healthy":
                print("ClickHouse is healthy!", flush=True)
                return 0
        except Exception:
            pass
        time.sleep(1)
    print("ClickHouse did not report healthy within 60s.", flush=True)
    return 1


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print("MarketTracker Cross-Platform Task Runner")
        print("Usage: python run.py <target>\n")
        print("Available targets:")
        for name, desc in COMMANDS.items():
            print(f"  python run.py {name:<15} - {desc}")
        sys.exit(0)

    target = sys.argv[1].lower()

    if target == "up":
        run_cmd("docker compose up -d clickhouse")
        sys.exit(wait_clickhouse_healthy())

    elif target == "down":
        sys.exit(run_cmd("docker compose down"))

    elif target == "test":
        sys.exit(run_cmd(f'"{PYTHON}" -m pytest tests/ -v'))

    elif target == "bench":
        sys.exit(run_cmd(f'"{PYTHON}" bench/mtm.py'))

    elif target == "bench-ingest":
        sys.exit(run_cmd(f'"{PYTHON}" bench/ingest.py'))

    elif target == "bench-book":
        sys.exit(run_cmd(f'"{PYTHON}" bench/book.py'))

    elif target == "bench-strategy":
        sys.exit(run_cmd(f'"{PYTHON}" bench/strategy_profile.py'))

    elif target == "chaos":
        sys.exit(run_cmd(f'"{PYTHON}" chaos/run_chaos.py'))

    elif target == "build-web":
        web_dir = ROOT / "web"
        print("Building web frontend...", flush=True)
        ret1 = run_cmd("npm install", cwd=web_dir)
        if ret1 != 0:
            sys.exit(ret1)
        sys.exit(run_cmd("npm run build", cwd=web_dir))

    elif target == "demo":
        sys.exit(run_cmd(f'"{PYTHON}" -m market_tracker.api.app'))

    elif target == "lint":
        sys.exit(run_cmd(f'"{PYTHON}" -m ruff check .'))

    elif target == "format":
        sys.exit(run_cmd(f'"{PYTHON}" -m ruff format .'))

    elif target == "clean":
        sys.exit(run_cmd("docker compose down -v"))

    else:
        print(f"Unknown target: '{target}'. Run 'python run.py --help' for available targets.")
        sys.exit(1)


if __name__ == "__main__":
    main()
