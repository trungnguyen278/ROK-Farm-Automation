"""Zoomed in mid-scan is caught in two scans, not eighteen.

2026-09-24 03:04:28: a dud icon click zoomed in and the zoom-out did not
land. The fast position read called every following scan close; nothing
read it, and the empty-streak limit found the zoom 18 scans (66 s) later.
The mine had seen candidates earlier, so the no-candidate check never ran.
"""

import time

import numpy as np
import pytest

import rok_farm.flow_steps as fs
from rok_farm.flow_steps import CLOSE_HINT_SCANS, GemFlowMixin


class Scan(GemFlowMixin):
    """The scan loop with the game replaced: no icons anywhere, and a zoom
    hint per scan from a script. The gauge agrees with the hint."""

    def __init__(self, hints):
        self.hints = list(hints)
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
        self.mapmem = None
        self._edge_gems = []
        self._raw_frame = None
        self._pos_zoom_hint = None
        self.scan_no = 0
        self.scrolls = []
        self.gauge_reads = []
        self.went_home = False

    # what the scan loop calls
    def _tiles_from_home(self):
        return None

    def _center_screen(self):
        return 767, 431

    def _grab(self):
        return np.zeros((86, 153, 3), np.uint8)

    def _find_all_icons(self, frame):
        # Candidates seen earlier this mine, as in mine 14: the no-candidate
        # give-up must not be what catches it.
        self._candidates_this_mine = 1
        return []

    def _map_sync(self, frame, found, scan_count=0, force=False, icons=None):
        self.scan_no = scan_count
        i = scan_count - 1
        self._pos_zoom_hint = self.hints[i] if i < len(self.hints) else "icon"

    def _near_map_edge(self):
        return False

    def _steer_heading(self, heading):
        return heading

    def _clamp_to_play_area(self, x, y):
        return x, y

    def _human_drag(self, *a, **k):
        pass

    def _wait(self, *a, **k):
        pass

    def _fog_confirmed(self, frame):
        return False

    def _fog_at_the_edge(self, frame):
        return False

    def read_zoom_gauge(self, frame=None):
        self.gauge_reads.append(self.scan_no)
        return self._pos_zoom_hint

    @staticmethod
    def _zoom_scrolls():
        return 3

    def _scroll_at_center(self, amount, count=1):
        self.scrolls.append((self.scan_no, amount, count))
        self._pos_zoom_hint = "icon"

    def _wait_zoom_settled(self):
        return 0.0

    def _check_reconnect_popup(self):
        return False

    def _step_return_city(self, tag):
        self.went_home = True

    def _record(self, *a, **k):
        pass


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(fs, "save_screenshot", lambda *a, **k: None)
    monkeypatch.setattr(time, "sleep", lambda s: None)


def test_two_close_scans_in_a_row_scroll_out_right_there():
    s = Scan(["close"] * 18)
    s._step_scan_and_verify_gem("m14")
    assert s.scrolls and s.scrolls[0] == (CLOSE_HINT_SCANS, -1, 3), s.scrolls


def test_one_close_scan_alone_asks_nothing():
    """Right after an icon click the bar can still be showing."""
    s = Scan(["icon", "icon", "close", "icon", "icon"])
    s._step_scan_and_verify_gem("m1")
    assert 3 not in s.gauge_reads and 4 not in s.gauge_reads
    assert not [sc for sc in s.scrolls if sc[0] <= 5]


def test_the_gauge_has_the_last_word():
    s = Scan(["close"] * 4)
    s.read_zoom_gauge = lambda frame=None: (s.gauge_reads.append(s.scan_no)
                                            or "icon")
    s._step_scan_and_verify_gem("m1")
    assert s.gauge_reads[:2] == [2, 4], "asked every other scan, no more"
    assert not [sc for sc in s.scrolls if sc[0] <= 4]


def test_it_does_not_scroll_without_end():
    s = Scan(["close"] * 60)
    s._scroll_at_center = lambda amount, count=1: s.scrolls.append(
        (s.scan_no, amount, count))              # the scroll never lands
    s._step_scan_and_verify_gem("m1")
    early = [sc for sc in s.scrolls if sc[0] < 18]
    assert len(early) == fs.ZOOM_FIX_ROUNDS, s.scrolls
