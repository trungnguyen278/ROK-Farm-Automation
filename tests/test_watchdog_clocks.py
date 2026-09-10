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


def test_silence_limit_clears_the_designed_quiet_periods(source):
    """A threshold that does not clear designed silence restarts healthy runs.

    This one had never actually been enforced: flow_size grew by a byte per
    capture-thread line, so the clock reset on every poll and the timeout could
    not fire. Fixing that armed it for the first time, which makes the question
    real -- the farm quits its client and sleeps out gathers of up to 42
    minutes, and an earlier 900s limit equalled a designed 15-minute wait
    exactly and killed a healthy farm at the boundary.

    Measured against the log rather than the design intent: across every run,
    the farm never actually goes quiet during a planned wait -- it prints a
    countdown roughly every 130-190s.
    """
    from datetime import datetime

    from rok_farm.config import MAX_MARCH_MINUTES
    from tools.dev.overnight import logscan

    farm_log = PROJECT_ROOT / "logs" / "overnight" / "farm_run.log"
    if not farm_log.is_file() or farm_log.stat().st_size < 1_000_000:
        pytest.skip("no substantial farm log on this machine")
    text = farm_log.read_text(encoding="utf-8", errors="replace")

    limit = int(re.search(r"^SILENT_LIMIT = (\d+)", source, re.MULTILINE).group(1))
    stamp = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ ")

    worst = 0.0
    for run in text.split("=== farm start ")[1:]:
        lines = [ln for ln in logscan.CAPTURE_NOISE.sub("", run).splitlines()
                 if ln.strip()]
        marks = [(i, datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
                 for i, ln in enumerate(lines) if (m := stamp.match(ln))]
        for (ia, ta), (ib, tb) in zip(marks, marks[1:]):
            span = (tb - ta).total_seconds()
            if span <= 0:
                continue
            # Untimestamped progress prints inside the span still reset the
            # clock, so the quiet stretch is the span divided between them.
            worst = max(worst, span / (len(lines[ia + 1:ib]) + 1))

    assert worst > 0, "no intervals measured -- has the log format changed?"

    # The bound is not a chosen multiple, it is the design: the toast-vigil
    # branch of the march wait tabs out and reads OS notifications with the
    # capture thread paused, so it emits NOTHING for up to MAX_MARCH_MINUTES.
    # Measured, that is real -- 895s observed on 2026-08-18 and still 820s on
    # 2026-09-09. SILENT_LIMIT must clear the cap itself, not merely the
    # longest silence that happened to be recorded, because a march that runs
    # to the cap is ordinary and would otherwise restart a healthy farm. The
    # margin covers tab-out and tab-back either side of the vigil.
    cap = MAX_MARCH_MINUTES * 60
    assert limit > cap + 300, (
        f"SILENT_LIMIT={limit}s does not clear the {cap}s march-wait cap with "
        f"room for the tab-out and tab-back around it")
    assert limit > worst, (
        f"SILENT_LIMIT={limit}s is below the longest quiet stretch the farm "
        f"has actually produced ({worst:.0f}s)")
