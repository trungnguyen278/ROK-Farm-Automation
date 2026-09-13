"""The map filter panel hides every deposit, and hidden deposits are not fog.

With the world-map "Loc" panel open and its "Tai nguyen" layer unticked the
game draws no deposits at all. Four times in two days: twice the scan found
NOT ONE candidate, and twice plain ground under the panel read as the
featureless map void -- which wrote a PERMANENT wall into the map book.

Measured at the panel's fixed top-left spot over 338 saved frames: panel open
0.824-1.000, every other frame 0.29 or lower. These are those frames.
"""

import cv2
import pytest

from rok_farm import PROJECT_ROOT
from rok_farm.flow_steps import GemFlowMixin

KEEP = PROJECT_ROOT / "screenshots" / "keep" / "filter_panel"
OPEN = ["m4_NO_CANDIDATES_011856.png", "m1_NO_CANDIDATES_122701.png",
        "m13_FOG_01_093252.png", "m10_FOG_01_193049.png"]
SHUT = ["m5_scan_05_011956.png", "m6_scan_03_012101.png"]


class Probe(GemFlowMixin):
    pass


def load(name):
    path = KEEP / name
    if not path.is_file():
        pytest.skip(f"{name} is not kept any more")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip(f"{name} did not decode")
    return frame


@pytest.mark.parametrize("name", OPEN)
def test_the_open_panel_is_recognised(name):
    assert Probe()._filter_panel_open(load(name)), name


@pytest.mark.parametrize("name", SHUT)
def test_an_ordinary_map_is_not_mistaken_for_it(name):
    assert not Probe()._filter_panel_open(load(name)), name


def test_the_threshold_sits_in_the_gap():
    assert 0.29 < GemFlowMixin.FILTER_PANEL_THRESHOLD < 0.82


def test_something_that_is_not_a_frame_is_not_the_panel():
    """The fog tests pass stand-in objects as frames; that must not raise."""
    assert Probe()._filter_panel_open(object()) is False
    assert Probe()._filter_panel_open(None) is False


class FakeFog(GemFlowMixin):
    """Only what _fog_confirmed touches."""

    def __init__(self, panel):
        self.panel = panel
        self.grabs = 0

    def _is_fog(self, frame):
        return True

    def _wait(self, _):
        pass

    def _grab(self):
        self.grabs += 1
        return object()

    def read_zoom_gauge(self, frame=None):
        return "icon"

    def _filter_panel_open(self, frame):
        return self.panel


def test_featureless_under_the_panel_is_not_fog(monkeypatch):
    """Two of the four panel events wrote a permanent wall. Never again."""
    import rok_farm.flow_steps as fs
    monkeypatch.setattr(fs, "save_screenshot", lambda *a, **k: None)
    assert FakeFog(True)._fog_confirmed(object()) is False


def test_featureless_without_the_panel_is_still_fog():
    """The guard must not disarm the detector it guards."""
    assert FakeFog(False)._fog_confirmed(object()) is True
