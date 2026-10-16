#!/usr/bin/env python3
"""Run every test here. No pytest, because this project has no dependencies.

Each test_*.py is a plain script that asserts and prints, run in its own
process with -I so an import cannot be satisfied from the cwd. None of them
touch the network: the Qobuz and ListenBrainz calls are stubbed, and anything
that writes goes to a temp directory, so a test run cannot damage data/.

    ./tests/run.py              # all of them
    ./tests/run.py dedup        # only ones whose name contains "dedup"
    python3 tests/test_dedup.py # one directly, to read its output
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    wanted = sys.argv[1:]
    tests = sorted(
        path for path in HERE.glob("test_*.py")
        if not wanted or any(word in path.name for word in wanted)
    )
    if not tests:
        print(f"no tests matching {wanted}", file=sys.stderr)
        return 1

    failed = []
    for path in tests:
        done = subprocess.run([sys.executable, "-I", str(path)],
                              capture_output=True, text=True)
        mark = "ok" if done.returncode == 0 else "FAILED"
        print(f"  {path.name:<24} {mark}")
        if done.returncode != 0:
            failed.append((path.name, done))

    for name, done in failed:
        print(f"\n--- {name}\n{done.stdout}{done.stderr}".rstrip())

    print(f"\n{len(tests) - len(failed)} of {len(tests)} passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
