"""Clicks in the top of the client were being pushed 40px down.

Every one of 2026-09-21's nine off-target clicks looked the same: aimed at
y=219-225, landed at y=230-235, almost no sideways error. With the window's
client top at 193 that is a floor at 233, which is exactly

    top_pad = max(pad, TITLE_BAR_H)     # TITLE_BAR_H = 40

in _clamp_to_window. But win["top"] is ALREADY the client top --
screen_capture builds it from ClientToScreen(hwnd, (0, 0)) and keeps the
frame's own top separately as "full_top" -- so the title bar was coming off
twice, and every click in the top 4.6% of the client was deformed.

What lives up there: the mail panel's tab strip and its X. The mail check has
spent the day failing to read tabs and failing to close the panel.
"""

import pytest

from rok_farm.capture_svc import CaptureMixin

WIN = {"left": 372, "top": 193, "width": 1533, "height": 862,
       "full_top": 148, "full_height": 909, "titlebar_h": 45}


class Clamper(CaptureMixin):
    def __init__(self):
        self.win = dict(WIN)


@pytest.fixture
def clamp():
    return Clamper()


def test_a_click_near_the_top_of_the_client_stays_where_it_was_aimed(clamp):
    """The mail tab strip, at 3.5% down the client."""
    aim_y = WIN["top"] + int(WIN["height"] * 0.035)
    _, y = clamp._clamp_to_window(WIN["left"] + 500, aim_y)
    assert y == aim_y, f"pushed {y - aim_y}px down"


def test_the_mail_x_is_not_moved_either(clamp):
    """Measured at pct(0.8232, 0.0394) on all 32 saved panel frames."""
    aim_y = WIN["top"] + int(WIN["height"] * 0.0394)
    _, y = clamp._clamp_to_window(WIN["left"] + int(WIN["width"] * 0.8232),
                                  aim_y)
    assert y == aim_y, f"pushed {y - aim_y}px down"


def test_the_days_off_target_clicks_would_now_land(clamp):
    """The nine real ones, by their logged targets."""
    for aim in (220, 220, 219, 222, 219, 220, 225, 222, 225):
        _, y = clamp._clamp_to_window(900, aim)
        assert y == aim, (aim, y)


def test_a_click_outside_the_client_is_still_pulled_in(clamp):
    """The clamp still does its job: nothing lands in the title bar."""
    _, y = clamp._clamp_to_window(900, WIN["top"] - 30)
    assert y >= WIN["top"], y
    _, y = clamp._clamp_to_window(900, WIN["top"] + WIN["height"] + 50)
    assert y <= WIN["top"] + WIN["height"], y
    x, _ = clamp._clamp_to_window(WIN["left"] - 40, 400)
    assert x >= WIN["left"], x


def test_the_client_top_is_not_the_window_top():
    """The premise. If these ever became equal the clamp would need to know."""
    assert WIN["top"] == WIN["full_top"] + WIN["titlebar_h"]
    assert WIN["titlebar_h"] > 0
