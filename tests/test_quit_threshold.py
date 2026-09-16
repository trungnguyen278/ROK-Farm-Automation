"""When is a wait long enough to close the client for?

Not a fixed number of minutes. The waits move with the game -- a KvK deposit
holds 30 gems and gathers for about 27 minutes, an ordinary-map one holds 10-20
and takes a fraction of that -- while the cost of quitting and coming back does
not move with them. Measured over 83 planned relaunches in the log: coming back
took 78s MORE than the wait it covered at the median (p25 58, p75 105). So the
cost is the threshold, and the farm re-measures its own as it runs.

The 8-minute constant this replaces kept the client OPEN through 110 of the 251
alt-tab waits in the log -- 545 minutes of the account being online for
nothing, which is what the 2026-09-14 gem reclaim was about.
"""

import logging

import pytest

from rok_farm import PROJECT_ROOT
from rok_farm.config import (RELAUNCH_OVERHEAD_S, WAIT_QUIT_FACTOR,
                             WAIT_QUIT_FLOOR_S)
from rok_farm.logging_setup import logger as farm_logger
from rok_farm.phases import PhasesMixin


class Fake(PhasesMixin):
    pass


def test_the_seed_threshold_is_about_a_round_trip():
    t = Fake()._quit_threshold_s()
    assert 90 <= t <= 180, (
        f"{t:.0f}s is not worth a relaunch that costs 78s at the median")


def test_it_follows_what_relaunches_actually_cost():
    slow = Fake()
    for _ in range(3):
        slow._note_relaunch_overhead(200.0)
    assert slow._quit_threshold_s() == pytest.approx(200.0 * WAIT_QUIT_FACTOR)

    quick = Fake()
    for _ in range(3):
        quick._note_relaunch_overhead(20.0)
    assert quick._quit_threshold_s() == WAIT_QUIT_FLOOR_S, (
        "a machine that relaunches fast must still not close the client for "
        "a handful of seconds")


def test_one_reading_does_not_move_it():
    """Three is the smallest median worth having; one slow launch is weather."""
    f = Fake()
    f._note_relaunch_overhead(240.0)
    assert f._quit_threshold_s() == pytest.approx(
        max(WAIT_QUIT_FLOOR_S, RELAUNCH_OVERHEAD_S * WAIT_QUIT_FACTOR))


def test_a_wait_cut_short_and_a_hung_launcher_are_not_costs():
    f = Fake()
    f._note_relaunch_overhead(-120.0)     # a wake request ended the wait early
    f._note_relaunch_overhead(490.0)      # the log's worst launcher hang
    assert getattr(f, "_relaunch_overheads", []) == []


def test_only_the_recent_relaunches_count():
    f = Fake()
    for _ in range(12):
        f._note_relaunch_overhead(100.0)
    assert len(f._relaunch_overheads) == 10


def test_the_wait_branch_asks_the_cost_and_the_constant_is_gone():
    src = (PROJECT_ROOT / "rok_farm" / "phases.py").read_text(encoding="utf-8")
    at = src.index("def _phase_wait_return")
    body = src[at:src.index("\n    def ", at + 10)]
    assert "self._quit_threshold_s()" in body, \
        "the wait branch still decides on something other than the cost"
    assert "WAIT_QUIT_MINUTES" not in src
    cfg = (PROJECT_ROOT / "rok_farm" / "config.py").read_text(encoding="utf-8")
    assert "WAIT_QUIT_MINUTES" not in cfg


def test_each_measurement_reaches_the_log(caplog):
    """The threshold moves itself, so the moves have to be readable later."""
    f = Fake()
    with caplog.at_level(logging.INFO, logger=farm_logger.name):
        f._note_relaunch_overhead(90.0)
    assert "relaunch cost" in caplog.text
