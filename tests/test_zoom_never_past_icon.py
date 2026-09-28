"""No zoom lands past icon level.

2026-09-28, the operator on a frame with the map filter panel up: that panel
only shows when zoomed out too far. Two ways the farm got there: a humanised
scroll overshoot that came back int(extra * 0.6) notches (a two-notch
overshoot kept one -- one notch past icon zoom is where the level labels go),
and the post-march check that read "close" once, mid-animation, and answered
with three more notches (13:13:57, mine 53). 3 of that day's 12 corrections
ended in a no-candidate give-up.

The afternoon, with that fixed: 2 of 3 far-view step-ins were taken on one
look as a zoom ended and landed close, and the in-scan correction's three
notches then threw both mines into the far view (m7, m13).
"""

import inspect
import random

import numpy as np

import rok_farm.flow_steps as fs
import rok_farm.input_hid as ih
from rok_farm.flow_steps import GemFlowMixin
from rok_farm.input_hid import HidInputMixin


class Board:
    def __init__(self):
        self.net = 0

    def send(self, cmd, *args):
        if cmd == "SCROLL":
            self.net += args[0]


class Scroller(HidInputMixin):
    def __init__(self):
        self.cmd = Board()
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
        self._scroll_overshoot_chance = 1.0

    def _center_screen(self):
        return 767, 431

    def _clamp_to_play_area(self, x, y):
        return x, y

    def _moveto(self, x, y):
        pass


def test_an_overshoot_always_scrolls_all_the_way_back(monkeypatch):
    monkeypatch.setattr(ih.time, "sleep", lambda s: None)
    for seed in range(60):
        random.seed(seed)
        s = Scroller()
        s._scroll_at_center(-1, 3)
        assert s.cmd.net == -3, f"seed {seed}: net {s.cmd.net} notches"


class Zoomer(GemFlowMixin):
    """A runner that only zooms: gauge readings and filter-panel looks given."""

    def __init__(self, gauges, panels=()):
        self.gauges, self.panels = list(gauges), list(panels)
        self.scrolls = []
        self._zoomed_in_by_click = True

    def read_zoom_gauge(self, frame=None):
        return self.gauges.pop(0) if self.gauges else "icon"

    def _filter_panel_open(self, frame):
        return self.panels.pop(0) if self.panels else False

    def _grab(self):
        return np.zeros((863, 1534, 3), np.uint8)

    def _scroll_at_center(self, amount, count=1):
        self.scrolls.append((amount, count))

    def _wait_zoom_settled(self):
        return 0.0

    def _wait(self, *a, **k):
        pass

    @staticmethod
    def _zoom_scrolls():
        return 3


def test_one_close_read_is_not_corrected():
    z = Zoomer(["close", "icon"])
    z._return_to_icon_zoom(verify=True, pan=False)
    assert z.scrolls == [(-1, 3)], "only the undo of the click's zoom-in"


def test_a_confirmed_close_is_corrected_a_notch_at_a_time():
    z = Zoomer(["close", "close", "icon"])
    z._return_to_icon_zoom(verify=True, pan=False)
    assert z.scrolls == [(-1, 3), (-1, 1)]


def test_the_far_view_is_stepped_back_from():
    z = Zoomer(["icon"], panels=[True, True, False])
    z._return_to_icon_zoom(verify=True, pan=False)
    assert z.scrolls == [(-1, 3), (1, 1)]


def test_a_glimpse_of_the_panel_is_not_stepped_from():
    """m7 14:18:06, m13 14:52:21: one look as a zoom ended, a notch in, and
    the view landed close -- it had been settling at icon zoom."""
    z = Zoomer(["icon"], panels=[True, False])
    z._return_to_icon_zoom(verify=True, pan=False)
    assert z.scrolls == [(-1, 3)]


# --- the in-place corrections: a notch at a time -------------------------

def test_an_in_place_correction_goes_a_notch_at_a_time():
    z = Zoomer(["close", "close", "icon"])
    assert z._notch_out_of_close("m1") == 2
    assert z.scrolls == [(-1, 1), (-1, 1)]


def test_it_never_goes_further_than_a_whole_level():
    """The old correction's three notches are the ceiling, not the step."""
    z = Zoomer(["close"] * 20)
    assert z._notch_out_of_close("m1") == 3
    assert z.scrolls == [(-1, 1)] * 3


def test_it_steps_back_if_it_ended_in_the_far_view():
    z = Zoomer(["icon"], panels=[True, True, False])
    z._notch_out_of_close("m1")
    assert z.scrolls == [(-1, 1), (1, 1)]


def test_no_correction_sends_a_whole_level_on_a_close_reading():
    """m7 14:18:18 and m13 14:52:33: three notches on a close reading, from
    a camera one notch in, and the scans after were in the far view."""
    src = inspect.getsource(fs)
    at = src.index("def _step_scan_and_verify_gem")
    scan = src[at:src.index("\n    def ", at + 10)]
    assert "_scroll_at_center(-1, self._zoom_scrolls())" not in scan
    assert scan.count("self._notch_out_of_close(tag)") == 3, \
        "the hint, no-candidate and empty-streak corrections"
    at = src.index("Already on world map icon-zoom")
    step1 = src[at:src.index("def _step_stay_and_rezoom", at)]
    loop = step1[step1.index("for _ in range(ZOOM_FIX_ROUNDS)"):]
    assert "self._notch_out_of_close(tag)" in loop
    assert "_scroll_at_center(-1, self._zoom_scrolls())" not in loop


def test_step_one_confirms_close_and_checks_the_far_view():
    src = inspect.getsource(fs)
    start = src.index("Already on world map icon-zoom")
    tail = src[start:src.index('save_screenshot(frame, f"{tag}_icon_zoom")', start)]
    first = tail.index("gauge = self.read_zoom_gauge()")
    assert "gauge = self.read_zoom_gauge()" in tail[first + 10:tail.index("for _ in range(ZOOM_FIX_ROUNDS)")], \
        "a single close reading still sends three notches out"
    assert "self._back_from_too_far(tag)" in tail
