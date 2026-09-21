"""The wall under the click rhythm.

Measured over every saved log, 9,121 gaps between clicks: ONE was under a
second and NONE under half a second, against a median of 6.73s. A person
clicking two things side by side does it in a fraction of a second. A floor
with nothing at all below it is not a person, and it is the kind of shape a
rhythm check looks for.

It came from the pointer. Every move was a full approach -- accelerate,
cruise, brake -- however short: 257ms to cross twenty pixels. And 11.5% of
9,327 consecutive click pairs land within 20px of the one before (4.0% within
5px), so better than one click in nine paid a full approach to somewhere the
hand already was, then paid the visual-search pause on top.

This file is also the first test of mouse_humanizer at all: 812 lines that
nothing covered.
"""

import random

import pytest

from anti_detection.mouse_humanizer import (MouseHumanizer, NEAR_SETTLE_PX,
                                            NEAR_SETTLE_CHANCE)
from anti_detection.profile_loader import DEFAULT_PROFILE


@pytest.fixture
def mouse():
    return MouseHumanizer(dict(DEFAULT_PROFILE))


def duration(path):
    return sum(p[2] for p in path)


def times(mouse, dist, n=400):
    return sorted(duration(mouse.humanize_move(100, 100, 100 + dist, 100))
                  for _ in range(n))


def test_a_hand_already_on_the_button_does_not_re_approach_it(mouse):
    """Median under a tenth of a second, against 257ms before."""
    t = times(mouse, 12)
    assert t[len(t) // 2] < 120, t[len(t) // 2]


def test_a_real_journey_is_still_a_real_journey(mouse):
    """Nothing beyond the settle radius gets faster -- the velocity envelope
    is the thing that makes motion look human, and it is not being traded
    away here."""
    t = times(mouse, NEAR_SETTLE_PX * 3)
    assert t[len(t) // 2] > 200, t[len(t) // 2]


def test_the_hand_does_not_always_stay_put(mouse):
    """A rule is a fingerprint too. Sometimes it drifts off and comes back."""
    t = times(mouse, 10, n=600)
    slow = sum(1 for v in t if v > 150)
    assert slow > 0, "every near move settled -- that is a rule, not a hand"
    assert slow < len(t) * (1.0 - NEAR_SETTLE_CHANCE) * 2.5, slow


def test_the_settle_still_lands_exactly_on_the_target(mouse):
    """Jitter along the way is motor noise; arriving somewhere else is a bug."""
    for _ in range(200):
        path = mouse.humanize_move(500, 400, 508, 396)
        assert path[-1][0] == 508 and path[-1][1] == 396, path[-1]


def test_the_settle_has_no_fixed_beat(mouse):
    """Fixed intervals are what drew the warning before."""
    delays = []
    for _ in range(80):
        path = mouse.humanize_move(100, 100, 112, 100)
        if duration(path) < 150:
            delays.extend(p[2] for p in path)
    assert len(set(delays)) > 4, sorted(set(delays))


def test_the_click_path_skips_the_search_pause_when_it_is_already_there():
    """The travel is only half the floor; the other half is the pause for
    finding and recognising a button the pointer is already resting on."""
    import ast
    import inspect
    from rok_farm.input_hid import HidInputMixin

    src = inspect.getsource(HidInputMixin._click)
    tree = ast.parse(src.lstrip())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "already_there" in names, (
        "_click no longer shortens the perceive pause for a pointer that is "
        "already on the target")
