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


# The farm itself runs unattended too. A cold branch raising NameError there
# is less lethal than in the supervisor -- the watchdog restarts the farm --
# but it still costs a mine every time it is reached, and every guard added on
# the night of 2026-09-13 (zoom, fog, foreground) IS a cold branch: it runs
# only when something has already gone wrong, which is the worst moment to
# discover a typo.
PACKAGES = ("rok_farm", "vision", "capture", "anti_detection")


def _pyflakes(paths):
    proc = subprocess.run([sys.executable, "-m", "pyflakes", *map(str, paths)],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 and not proc.stdout and proc.stderr:
        pytest.skip(f"pyflakes unavailable: {proc.stderr.strip()[:120]}")
    return [ln for ln in proc.stdout.splitlines()
            if any(f in ln.lower() for f in FATAL)]


@pytest.mark.parametrize("pkg", PACKAGES)
def test_the_farm_package_has_no_undefined_names(pkg):
    files = sorted((PROJECT_ROOT / pkg).glob("*.py"))
    if not files:
        pytest.skip(f"{pkg} not present")
    bad = _pyflakes(files)
    assert not bad, (
        f"{pkg} has names that only fail when a cold branch runs: "
        + "; ".join(bad))


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
