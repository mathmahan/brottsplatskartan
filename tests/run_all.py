#!/usr/bin/env python3
"""Run every test suite and exit non-zero if any of them fails.

Running the suites in a shell `for` loop hides failures: the loop's own exit
status is that of its last command, so a failing suite in the middle goes
unnoticed. This reports each suite and fails the run if any one fails.
"""

import pathlib
import subprocess
import sys

TESTS = sorted(pathlib.Path(__file__).resolve().parent.glob("test_*.py"))

failed: list[str] = []
for test in TESTS:
    proc = subprocess.run(
        [sys.executable, str(test)], capture_output=True, text=True
    )
    last = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    summary = last[-1] if last else "(no output)"
    if proc.returncode == 0:
        print(f"ok    {test.name:<26} {summary}")
    else:
        failed.append(test.name)
        print(f"FAIL  {test.name:<26} exit {proc.returncode}")
        for line in proc.stdout.splitlines():
            if line.startswith("FAIL"):
                print(f"        {line}")
        if proc.stderr.strip():
            print("        " + proc.stderr.strip().splitlines()[-1])

print()
if failed:
    print(f"{len(failed)} of {len(TESTS)} suites FAILED: {', '.join(failed)}")
    sys.exit(1)
print(f"all {len(TESTS)} suites passed")
