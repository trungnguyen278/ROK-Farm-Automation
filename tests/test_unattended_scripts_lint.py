"""No undefined name may reach a script that runs unattended for hours.

A watchdog died at 03:30 on a NameError in its HOURLY summary block: a variable
had been removed from the poll loop and one f-string still referenced it. The
module imported, compiled, ran correctly for an hour and then killed itself the
first time that branch was reached -- leaving the farm unsupervised, which is
the one thing a supervisor exists to prevent.

Compiling proves nothing here, because a NameError is raised at runtime. These
files also cannot be imported by a test: watchdog2 starts supervising a live
farm at import. Static analysis is the only thing that reaches the cold branch,
and pyflakes finds exactly this class of error.
"""

import subprocess
import sys

import pytest

from rok_farm import PROJECT_ROOT

# Scripts that run for hours with nobody watching, where a cold branch raising
# NameError means silent death rather than a visible crash.
UNATTENDED = [
    "tools/dev/overnight/watchdog2.py",
    "tools/dev/overnight/logscan.py",
    "tools/dev/overnight/farm_full.py",
    "tools/dev/overnight/report.py",
    "tools/remote/discord_bot.py",
    "rok_farm/session_control.py",
]

FATAL = ("undefined name",
         "syntax error",
         "redefinition of unused")   # a shadowed def silently loses a branch


@pytest.mark.parametrize("rel", UNATTENDED)
def test_no_undefined_names(rel):
    path = PROJECT_ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} not present")
    proc = subprocess.run([sys.executable, "-m", "pyflakes", str(path)],
                          capture_output=True, text=True, timeout=120)
    if proc.returncode != 0 and not proc.stdout and proc.stderr:
        pytest.skip(f"pyflakes unavailable: {proc.stderr.strip()[:120]}")

    bad = [ln for ln in proc.stdout.splitlines()
           if any(f in ln.lower() for f in FATAL)]
    assert not bad, (
        f"{rel} has names that only fail when a cold branch runs:\n  "
        + "\n  ".join(bad))
