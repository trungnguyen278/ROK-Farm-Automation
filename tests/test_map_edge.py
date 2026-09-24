"""The map's size is read at its bottom-right corner (rok_farm.map_edge).

The operator, 2026-09-24: out to the far view, find the bottom-right corner,
back in and read the coordinates. These tests drive the walk against a
simulated camera held inside [0, size) -- the part that can be checked away
from the game: legs stop once the map stops moving, the far view's vertical
legs drag X along with them (the calibration moved -164 X on one), a far hold
that stops short is finished by the near legs, and the size read is the
right one of 1200, 1440, 2400.
"""

import numpy as np
import pytest

from rok_farm import map_edge
from rok_farm.map_edge import MapEdgeMixin

LIMIT, READABLE = 15, 8          # notches out: the far view; HUD reads at <= 8


class Camera(MapEdgeMixin):
    def __init__(self, size, start=(577, 615), far_margin=0, skew=0.5):
        self.size, self.x, self.y, self.z = size, *start, 0
        self.far_margin = far_margin     # the far view holding short of the edge
        self.skew = skew                 # X lost per tile of a far south leg
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
        self.legs = []

    def _hold(self, v, far):
        m = self.far_margin if far else 0
        return max(m, min(self.size - 1 - m, v))

    def _edge_frame(self, wait=4.0):
        seed = (int(self.x) * 7919 + int(self.y) * 104729 + self.z * 31) % (2 ** 32)
        return np.random.default_rng(seed).integers(0, 255, (180, 320, 3), np.uint8)

    def _edge_notch(self, direction, at=(0.5, 0.5)):
        self.z = max(0, min(LIMIT, self.z - direction))
        if direction > 0 and at != (0.5, 0.5):
            # the zoom keeps the ground under the pointer: toward the corner
            far = self.z > READABLE
            self.x = self._hold(self.x + 20, far)
            self.y = self._hold(self.y - 12, far)

    def _edge_leg(self, dx_frac, dy_frac):
        far = self.z > READABLE
        per = 460 if far else 70
        self.legs.append((round(dx_frac, 2), round(dy_frac, 2), far))
        dx = dx_frac / map_edge.FAR_LEG_FRAC * per
        dy = dy_frac / map_edge.FAR_LEG_FRAC * per
        self.x = self._hold(self.x + dx - (self.skew * dy if far else 0), far)
        self.y = self._hold(self.y - dy, far)

    def _read_map_position(self, frame=None, full=False):
        return ("4096", int(self.x), int(self.y)) if self.z <= READABLE else None


@pytest.mark.parametrize("size", [1200, 1440, 2400])
def test_the_corner_reads_the_size(size):
    cam = Camera(size)
    res = cam._probe_map_size()
    assert res["corner"] == [size - 1, 0]
    assert res["size"] == size
    assert res["short_of_edge"] == 0
    assert res["east"]["held"] and res["south"]["held"]


@pytest.mark.parametrize("skew", [0.0, 0.5, 0.9])
def test_a_south_leg_that_drags_x_along_still_ends_in_the_corner(skew):
    """Held at the bottom, a skewed south leg keeps moving the camera west:
    the frame never stands still on south legs alone."""
    res = Camera(2400, start=(2000, 2300), skew=skew)._probe_map_size()
    assert res["south"]["held"], res["south"]
    assert res["corner"] == [2399, 0]


def test_a_far_hold_short_of_the_edge_is_finished_up_close():
    """If the far view keeps its centre off the edge, the legs with the HUD
    reading walk the rest of the way."""
    cam = Camera(1440, far_margin=120)
    res = cam._probe_map_size()
    assert res["size"] == 1440
    assert res["corner"][0] >= 1440 - 1 - 20, res["corner"]


def test_it_starts_anywhere_on_the_map():
    for start in [(5, 1190), (1190, 5), (600, 600)]:
        res = Camera(1200, start=start)._probe_map_size()
        assert res["corner"] == [1199, 0], (start, res["corner"])


def test_a_leg_that_moves_nothing_is_the_edge_not_one_more_leg():
    cam = Camera(1200, start=(1199, 0))
    cam.z = LIMIT
    legs, held, diffs = cam._edge_pin_far(map_edge.FAR_LEG_FRAC, 0.0)
    assert (legs, held) == (1, True)
    assert diffs[0] < map_edge.EDGE_STILL_DIFF


def test_it_gives_up_on_legs_that_never_stop():
    class Endless(Camera):
        def _hold(self, v, far):
            return v                     # no edge at all: never held
    cam = Endless(1200)
    cam.z = LIMIT
    legs, held, _ = cam._edge_pin_far(map_edge.FAR_LEG_FRAC, 0.0)
    assert (legs, held) == (map_edge.FAR_LEGS_MAX, False)


def test_no_read_on_the_way_in_is_an_error_not_a_size():
    class Blind(Camera):
        def _read_map_position(self, frame=None, full=False):
            return None
    res = Blind(1200)._probe_map_size()
    assert "error" in res and "size" not in res


def test_the_zoom_toward_the_corner_keeps_the_pointer_there():
    """Every notch in is scrolled with the pointer right of and below the
    centre, the corner's side."""
    fx, fy = map_edge.CORNER_POINTER
    assert fx > 0.5 and fy > 0.5
    # and inside the play area the farm keeps its pointer in
    assert 0.12 <= fx - 0.03 and fx + 0.03 <= 0.88
    assert 0.22 <= fy - 0.03 and fy + 0.03 <= 0.70
