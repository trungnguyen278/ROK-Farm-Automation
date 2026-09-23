"""A deposit already marched to is skipped before it is clicked, and a
duplicate found after clicking is actually left behind.

2026-09-23 15:25-15:26: mines 2 to 6 all failed on the same deposit,
632:622. The post-march pan left it on screen, the scan clicked it, the
gather step read its position and saw the duplicate -- and returned with
the camera still centred on it, so the next mine clicked it again.
"""

import inspect

import numpy as np

from rok_farm import pan_model as pm
from rok_farm.flow_steps import GemFlowMixin
from vision.template_matcher import Match

FRAME = np.zeros((863, 1534, 3), np.uint8)


class Scan(GemFlowMixin):
    def __init__(self, cam, sites, read_map="4096"):
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
        self._marched_sites = [(m, x, y, 0.0) for m, x, y in sites]
        self._home_map_id = "4096"
        self._cam = cam
        self._read_map = read_map
        self.reads = 0

    def _read_map_position(self, frame=None, full=False):
        self.reads += 1
        return (self._read_map, self._cam[0], self._cam[1])


def _icon_at_tile(cam, tile):
    """Screen position of a tile, by walking the model's rows."""
    for fy in range(0, 863):
        oy = fy - 863 / 2
        dx0, dy0 = pm.ground_offset(0, oy, 863)
        if abs(cam[1] + dy0 - tile[1]) < 0.06:
            kx = pm.kx(0.5 + oy / 863)
            fx = int(round(1534 / 2 + (tile[0] - cam[0]) / kx))
            return Match("g", fx - 18, fy - 24, 36, 48, 0.9, (fx, fy))
    raise AssertionError("tile not on screen")


def test_the_marched_deposit_is_recognised_on_screen():
    cam = (620, 615)
    s = Scan(cam, [("4096", 632, 622)])
    icon = _icon_at_tile(cam, (632, 622))
    assert s._marched_at_icon(icon, FRAME) == ("4096", 632, 622)


def test_another_deposit_is_not():
    cam = (620, 615)
    s = Scan(cam, [("4096", 632, 622)])
    icon = _icon_at_tile(cam, (612, 610))
    assert s._marched_at_icon(icon, FRAME) is None


def test_one_read_per_frame_whatever_the_icon_count():
    cam = (620, 615)
    s = Scan(cam, [("4096", 632, 622)])
    for t in ((632, 622), (612, 610), (625, 618)):
        s._marched_at_icon(_icon_at_tile(cam, t), FRAME)
    assert s.reads == 1


def test_a_read_from_another_map_decides_nothing():
    cam = (620, 615)
    s = Scan(cam, [("4096", 632, 622)], read_map="S11465")
    assert s._marched_at_icon(_icon_at_tile(cam, (632, 622)), FRAME) is None


def test_the_scan_asks_before_it_clicks():
    src = inspect.getsource(GemFlowMixin._step_scan_and_verify_gem)
    for chunk in src.split("_click_icon_and_verify(")[:-1]:
        assert "_marched_at_icon(" in chunk.split("for icon in icons:")[-1], (
            "an icon can be clicked without asking whether it was marched to")


def test_a_duplicate_is_left_behind():
    src = inspect.getsource(GemFlowMixin._step_click_gather)
    dup = src[src.index("Duplicate deposit %s"):]
    dup = dup[:dup.index("return False")]
    assert "_press_escape()" in dup and "_return_to_icon_zoom(" in dup
