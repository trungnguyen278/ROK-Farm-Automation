"""The supervisor's halt clocks must be drivable, and its kill must not
include itself. Both were broken in ways that only show up on a long run.

`prev` in watchdog2 is the HOURLY summary baseline. Any "did this counter just
increase" test written against it stays true for the rest of the hour after a
single increment. That is how the stuck detector went blind: the planned-wait
guard refreshes the stuck clock, the farm takes a planned wait every gather
cycle, so the guard was effectively always true and the 75-minute timeout could
never fire. A watchdog that cannot time out is not a watchdog.

Checked statically. The failure reads correctly at the point of use and is
wrong because of WHEN the other operand moves, so what is worth locking down is
that no such comparison exists -- not the behaviour of one instance. The module
cannot be imported either way: its poll loop runs at import.
"""

import os
import re
from pathlib import Path

import pytest

from rok_farm import PROJECT_ROOT

SRC = Path(os.environ.get(
    # Overridable so the suite can be pointed at an older revision of the file
    # and shown to FAIL on it. A static test that has never been seen to fail
    # is indistinguishable from one that cannot.
    "WATCHDOG_SRC",
    PROJECT_ROOT / "tools" / "dev" / "overnight" / "watchdog2.py"))


@pytest.fixture(scope="module")
def source():
    if not SRC.is_file():
        pytest.skip(f"{SRC} not present")
    return SRC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def poll_body(source):
    """The poll loop, without the hourly summary block that ends it."""
    start = source.index("while True:")
    end = source.index("if time.time() - last_summary >= SUMMARY_EVERY:", start)
    return source[start:end]


def test_no_halt_clock_reads_the_hourly_baseline(poll_body):
    offenders = [
        (i, line.strip())
        for i, line in enumerate(poll_body.splitlines(), 1)
        if re.search(r"\bprev\b(?!_)", line.split("#", 1)[0])
    ]
    assert not offenders, (
        "the poll body compares against the hourly summary baseline, which "
        "makes the comparison stay true for an hour: "
        + "; ".join(f"+{i}: {t}" for i, t in offenders))


def test_per_poll_baseline_advances_before_any_early_exit(poll_body):
    """Advancing it late is the same bug wearing a different name.

    Every edge test has to be taken before poll_prev moves, and poll_prev has
    to move before any `continue` can skip it -- otherwise it stops tracking
    the previous poll and quietly becomes a second `prev`.
    """
    adv = poll_body.find("poll_prev = cur")
    assert adv != -1, ("there is no per-poll baseline at all, so every edge "
                       "test is comparing against something slower")
    reads = [m.start() for m in re.finditer(r"poll_prev\[", poll_body)]
    assert reads, "nothing compares against the per-poll baseline"
    assert not [r for r in reads if r > adv], \
        "an edge test reads poll_prev after it has already been advanced"

    # Only the window between the first edge read and the advance matters. A
    # `continue` earlier just means this poll computed no edges at all, which
    # is correct -- the baseline then still describes the last poll that did.
    gap = poll_body[min(reads):adv]
    assert "continue" not in gap, \
        "a `continue` sits between reading the edges and advancing the baseline"


def test_every_halt_path_relaunches(source):
    """Killing without relaunching turns any false positive into a lost night.

    Both halt branches used to end in kill_farm; the restart-per-hour one never
    brought the farm back, and its trigger is not even a failure -- the farm
    quits its own client between gathers by design.
    """
    body = source[source.index("while True:"):]
    # The --deadline stop is the one halt that is meant to be final: the
    # operator asked for the run to end at a wall-clock time, so relaunching
    # there would defy the instruction. Every OTHER halt is a fault verdict,
    # and a fault verdict must bring the farm back.
    body = re.sub(r"if DEADLINE and datetime\.now\(\) >= DEADLINE:.*?\n\n",
                  "", body, count=1, flags=re.DOTALL)
    calls = re.findall(r"^\s*(?:if )?(?:restarted = )?(kill_farm|restart_farm)\(",
                       body, re.MULTILINE)
    assert calls, "no halt calls found -- has the loop been restructured?"
    assert "kill_farm" not in calls, (
        "a fault halt calls kill_farm directly instead of restart_farm, so it "
        "stops the farm without bringing it back")


def test_the_supervisor_cannot_kill_itself(source):
    """kill_farm enumerates processes now, so the matcher it uses matters."""
    assert 'sc.farm_procs()' in source, \
        "kill_farm no longer asks the project's matcher who the farm is"
    assert 'sc.wd_procs()' not in source, \
        "the watchdog enumerates watchdog processes -- it could kill itself"


def test_the_farm_is_relaunched_detached(source):
    """A child farm dies with the watchdog; that took a live run down once."""
    assert "sc.spawn_detached(" in source, \
        "restart_farm spawns the farm as a plain child again"
    assert "subprocess.Popen(roles.command(" not in source, \
        "restart_farm still has the old attached-child launch"
