"""The client may not be restarted more than a few times an hour.

The wait threshold is pure arithmetic -- quit whenever the wait costs more
than a relaunch -- and it has no idea that restarts have a shape of their own.
It was not touched between 09-09 and 09-19, yet the gap between restarts fell
from 31 minutes to 12, because the marches started coming home sooner (median
wait 27 min on 09-09, 9 min on 09-18) and so every wait cleared the bar.

2026-09-19, the first hour of the day: seven restarts, median gap 8.2 minutes,
two of them five minutes apart -- about a hundred a day at that rate. The days
that never drew an anti-cheat letter ran 19-34 restarts across a 10-12 hour
window: two to three an hour.
"""

import time

import pytest

from rok_farm.config import QUITS_PER_HOUR_MAX
from rok_farm.phases import PhasesMixin


class Fake(PhasesMixin):
    pass


def test_the_first_few_are_allowed():
    f = Fake()
    for _ in range(QUITS_PER_HOUR_MAX):
        assert f._may_quit_again()
        f._note_quit()


def test_past_the_cap_it_refuses():
    f = Fake()
    for _ in range(QUITS_PER_HOUR_MAX):
        f._note_quit()
    assert not f._may_quit_again(), "the cap does nothing"


def test_an_hour_later_it_allows_again():
    f = Fake()
    old = time.time() - 3601
    f._quit_times = [old] * (QUITS_PER_HOUR_MAX + 2)
    assert f._may_quit_again(), "restarts from over an hour ago still count"


def test_it_counts_only_the_last_hour():
    f = Fake()
    now = time.time()
    f._quit_times = [now - 3700, now - 3650, now - 100]
    assert f._may_quit_again()


def test_the_cap_matches_the_days_that_drew_nothing():
    """19-34 restarts over a 10-12 hour window is two to three an hour."""
    assert 2 <= QUITS_PER_HOUR_MAX <= 4


def test_the_bookkeeping_does_not_grow_without_bound():
    f = Fake()
    for _ in range(200):
        f._note_quit()
        f._may_quit_again()
    assert len(f._quit_times) <= 41


def test_the_wait_branch_asks_before_quitting():
    """A cap nothing consults is not a cap."""
    import ast
    import inspect

    import rok_farm.phases as ph

    src = inspect.getsource(ph)
    tree = ast.parse(src)
    text = ast.unparse(tree)
    assert "_quit_threshold_s() and self._may_quit_again()" in text, (
        "the quit decision no longer consults the rate cap"
    )
    assert "self._note_quit()" in text, "quits are never recorded"
