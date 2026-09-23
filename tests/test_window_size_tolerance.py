"""The resize ran on every startup and never succeeded.

2026-09-23, the operator: "toi vua thay pop up resize 2 lan". The log shows
exactly that, twice in one morning:

    Resizing game 1534x863 -> w=1533
    Window now: 1534x863

The check was `width == TARGET_CONTENT_W`. The client does not land exactly --
asked for 1533 it comes back 1534 -- so the condition was never satisfied, the
farm resized on every single startup, and every one of those put a dialog in
front of whoever was at the machine.

Two earlier resizes from genuinely wrong sizes (2352 and 1860 wide) landed on
1533 exactly, so real mismatches are nowhere near the slack.
"""

import inspect

from rok_farm.capture_svc import CaptureMixin
from rok_farm.config import TARGET_CONTENT_W, TARGET_WIDTH_SLACK


class Fake(CaptureMixin):
    def __init__(self, w, h=862):
        self.win = {"left": 0, "top": 0, "width": w, "height": h}
        self.resized = 0

    def _resize_now(self):
        self.resized += 1


def test_the_slack_is_small_enough_to_be_meaningless_to_a_template():
    assert TARGET_WIDTH_SLACK <= 4, TARGET_WIDTH_SLACK
    assert TARGET_WIDTH_SLACK / TARGET_CONTENT_W < 0.003


def test_the_width_the_client_actually_returns_is_accepted():
    """1534 is what it comes back as, every time."""
    assert abs(1534 - TARGET_CONTENT_W) <= TARGET_WIDTH_SLACK


def test_a_genuinely_wrong_window_is_still_resized():
    """The sizes that really needed fixing: 2352, 1860, 1760."""
    for w in (1760, 1860, 2352):
        assert abs(w - TARGET_CONTENT_W) > TARGET_WIDTH_SLACK, w


def test_the_check_is_no_longer_an_equality():
    src = inspect.getsource(CaptureMixin._ensure_target_size)
    assert 'self.win["width"] == TARGET_CONTENT_W' not in src, (
        "exact equality is back; the client rounds, so this resizes on every "
        "startup and shows the operator a dialog each time")
    assert "TARGET_WIDTH_SLACK" in src


def test_a_resize_that_does_not_land_says_so():
    """Silence is how this went unnoticed -- the only sign was a popup, and
    only a human at the machine could see it."""
    src = inspect.getsource(CaptureMixin._ensure_target_size)
    assert "logger.warning" in src, (
        "a failed resize leaves no record, so it can only be found by someone "
        "watching the screen")
