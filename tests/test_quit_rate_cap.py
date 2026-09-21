"""How often the client may be restarted -- and why it is not a fixed number.

The wait threshold is pure arithmetic: quit whenever the wait costs more than
a relaunch. It cannot see that restarts have a shape of their own. Nobody
touched it between 09-09 and 09-19 and the gap between them still fell from 31
minutes to 8, because the marches started coming home sooner and every wait
cleared the bar. On the morning of 09-19: seven restarts in the first hour,
median gap 8.2 minutes, two of them five minutes apart.

The first fix capped it at three an hour. The operator asked whether a fixed
number is itself recognisable -- "ban dat tran co dinh 1 so the co the bi nhan
ra khong" -- and it is: every busy hour would land on exactly three and never
four, a flatter line than the rhythm it replaced.

So it is a chance, not a limit: certain once the gap passes a target, and
proportionally less likely before that, with the target drawn fresh per
session. Nothing is forbidden and nothing is guaranteed.
"""

import random
import time

import pytest

from rok_farm.config import QUIT_GAP_TARGET_S
from rok_farm.phases import PhasesMixin


class Fake(PhasesMixin):
    pass


def test_the_first_restart_of_a_session_is_free():
    assert Fake()._may_quit_again()


def test_a_long_gap_always_allows_it():
    f = Fake()
    f._quit_times = [time.time() - 3600]
    f._quit_gap_target = 1200.0
    assert all(f._may_quit_again() for _ in range(20))


def test_a_short_gap_usually_refuses_but_not_always():
    """Not always: an absolute refusal is an edge, and edges are visible."""
    f = Fake()
    f._quit_gap_target = 1200.0
    random.seed(7)
    allowed = 0
    for _ in range(400):
        f._quit_times = [time.time() - 120]     # two minutes ago
        allowed += f._may_quit_again()
    assert 0 < allowed < 120, f"{allowed}/400 -- the chance is not soft"


def test_the_chance_grows_with_the_gap():
    f = Fake()
    f._quit_gap_target = 1200.0
    random.seed(11)

    def rate(gap):
        n = 0
        for _ in range(400):
            f._quit_times = [time.time() - gap]
            n += f._may_quit_again()
        return n / 400

    assert rate(120) < rate(600) < rate(1100)


def test_there_is_no_fixed_ceiling_per_hour():
    """The thing the operator asked about: nothing counts restarts."""
    import ast
    import inspect

    import rok_farm.phases as ph

    code = ast.unparse(ast.parse(
        inspect.getsource(ph.PhasesMixin._may_quit_again).lstrip()))
    assert "3600" not in code, "an hourly window is back"
    assert "len(recent)" not in code, "it counts restarts again"
    assert "random" in code, "the decision is deterministic again"


def test_the_target_matches_the_days_that_drew_nothing():
    """19-34 restarts over 10-12 hours is a gap of 24-31 minutes."""
    lo, hi = QUIT_GAP_TARGET_S
    assert lo < hi, "a fixed target is a fixed rhythm"
    assert 600 <= lo and hi <= 2400


def test_each_session_draws_its_own_target():
    random.seed(3)
    targets = set()
    for _ in range(12):
        f = Fake()
        f._quit_times = [time.time() - 60]
        f._may_quit_again()
        targets.add(round(f._quit_gap_target, 3))
    assert len(targets) > 1, "every session aims at the same number"


def test_the_bookkeeping_does_not_grow_without_bound():
    f = Fake()
    for _ in range(200):
        f._note_quit()
        f._may_quit_again()
    assert len(f._quit_times) <= 200


def test_the_wait_branch_asks_before_quitting():
    import ast
    import inspect

    import rok_farm.phases as ph

    text = ast.unparse(ast.parse(inspect.getsource(ph)))
    assert "_quit_threshold_s() and self._may_quit_again()" in text
    assert "self._note_quit()" in text, "quits are never recorded"
