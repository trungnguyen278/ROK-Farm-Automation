"""What a drag buys, measured on its own, with the signs locked down.

The farm logged drag/tile pairs from inside its scan for a day. The first fit
of them came out at a median error of 21 tiles on moves of 47, because node
clicks, recentres, retreats and city trips moved the camera without a drag.
The operator's call, 2026-09-23: measure it separately (tools/dev/pan_survey.py),
with the pointer kept inside the window and the window's width and height
each dragged as two halves.

The survey's table, 35 held drags at icon zoom on a 1534x863 client:
    horizontal tiles/100px   row 0.25 1.820   0.50 1.541   0.75 1.359
    vertical   tiles/100px   ~0.34 2.527      ~0.50 2.222  ~0.66 1.792
    axis leakage 0 both ways; dragging down moves the camera to larger Y.
"""

import inspect
import math
import random

import pytest

from rok_farm import pan_model as pm
from rok_farm.flow_steps import GemFlowMixin
from tools.dev import pan_survey

WIN = {"left": 513, "top": 306, "width": 1534, "height": 863}
CX = WIN["left"] + WIN["width"] / 2
CY = WIN["top"] + WIN["height"] / 2


@pytest.mark.parametrize("row,measured", [(0.25, 0.01820), (0.50, 0.01541),
                                          (0.75, 0.01359)])
def test_horizontal_scale_matches_the_survey(row, measured):
    assert abs(pm.kx(row) - measured) / measured < 0.05


@pytest.mark.parametrize("row,measured", [(0.34, 0.02527), (0.50, 0.02222),
                                          (0.66, 0.01792)])
def test_vertical_scale_matches_the_survey(row, measured):
    assert abs(pm.ky(row) - measured) / measured < 0.06


def test_dragging_left_moves_the_camera_to_larger_x():
    """The map follows the pointer, so the camera goes the other way."""
    dx, dy = pm.drag_move((CX + 380, CY), (CX - 380, CY), WIN)
    assert 10 < dx < 14 and dy == 0


def test_dragging_down_moves_the_camera_to_larger_y():
    """The survey: +450px down -> +10 tiles of Y. Screen up is +Y."""
    dx, dy = pm.drag_move((CX, CY - 225), (CX, CY + 225), WIN)
    assert dx == 0 and 9 < dy < 11


def test_the_same_drag_covers_more_ground_higher_on_the_screen():
    top = pm.drag_move((CX + 380, WIN["top"] + 0.25 * 863),
                       (CX - 380, WIN["top"] + 0.25 * 863), WIN)[0]
    low = pm.drag_move((CX + 380, WIN["top"] + 0.75 * 863),
                       (CX - 380, WIN["top"] + 0.75 * 863), WIN)[0]
    assert top > low * 1.2


def test_one_window_is_the_measured_trapezoid():
    tl, tr, br, bl = pm.view_corners((500, 600), 1534, 863)
    assert 29 <= tr[0] - tl[0] <= 33          # 31.2 along the top edge
    assert 15 <= br[0] - bl[0] <= 19          # 16.9 along the bottom
    assert 17 <= tl[1] - bl[1] <= 21          # 19.2 deep
    assert tl[1] > 600 > bl[1], "the top of the frame is the larger Y"


def test_in_view_follows_the_trapezoid():
    cam = (500, 600)
    assert pm.in_view(cam, cam, 1534, 863)
    assert pm.in_view(cam, (500, 611), 1534, 863)       # 11 up: inside
    assert not pm.in_view(cam, (500, 614), 1534, 863)   # 14 up: past the top
    assert pm.in_view(cam, (500, 594), 1534, 863)       # 6 down: inside
    assert not pm.in_view(cam, (500, 591), 1534, 863)   # 9 down: past the bottom
    assert pm.in_view(cam, (514, 611), 1534, 863)       # wide near the top
    assert not pm.in_view(cam, (514, 594), 1534, 863)   # narrow near the bottom


def test_a_screen_heading_becomes_the_right_map_heading():
    """Screen right is east (+X); a swipe that moves the camera DOWN the
    screen goes to smaller Y. The book used to be read at +sin(heading),
    the mirror image."""
    th = lambda h: pm.tile_heading(h, 1534, 863)  # noqa: E731
    assert abs(th(0.0)) < 1e-9
    assert abs(th(math.pi / 2) + math.pi / 2) < 1e-9
    assert abs(th(-math.pi / 2) - math.pi / 2) < 1e-9
    assert abs(abs(th(math.pi)) - math.pi) < 1e-9


def test_a_misread_y_is_not_a_place():
    assert pm.plausible(577, 615)
    assert not pm.plausible(577, 5544)
    assert not pm.plausible(-1, 10)


def test_two_halves_make_exactly_one_window():
    """The operator's spec: the window's full width and height, each as two
    half drags -- not one drag that works the pointer at the window's edge."""
    rng = random.Random(7)
    for kind, total in (("h", WIN["width"]), ("v", WIN["height"])):
        legs = pan_survey.group_legs(kind, 0.5, WIN, total, "hold", rng)
        assert len(legs) == 4
        axis = "x" if kind == "h" else "y"
        span = [l["e" + axis] - l["s" + axis] for l in legs]
        out, back = span[:2], span[2:]
        assert abs(abs(sum(out)) - total) <= 2, (kind, out)
        assert abs(sum(out) + sum(back)) <= 2, "the group does not come home"
        for s in span:
            assert 0.40 * total <= abs(s) <= 0.60 * total, (kind, s)


def test_no_leg_works_the_pointer_at_the_edge():
    rng = random.Random(3)
    legs = []
    for f in pan_survey.H_ROWS:
        legs += pan_survey.group_legs("h", f, WIN, WIN["width"], "hold", rng)
    legs += pan_survey.group_legs("v", 0.5, WIN, WIN["height"], "hold", rng)
    for a, b in pan_survey.V_SPANS:
        legs += pan_survey.span_legs(WIN, a, b, "hold", rng)
    legs += pan_survey.farm_legs(WIN, rng)
    for l in legs:
        for x, y in ((l["sx"], l["sy"]), (l["ex"], l["ey"])):
            assert pan_survey.inside(WIN, x, y), (l, x, y)


def test_the_farm_flow_does_not_measure_the_pan():
    """Pairs taken inside the flow are spoiled by every other camera move."""
    for name in ("_step_scan_and_verify_gem", "_map_sync"):
        src = inspect.getsource(getattr(GemFlowMixin, name))
        assert "_pan_pixels" not in src and "_pan_dirty" not in src, name
