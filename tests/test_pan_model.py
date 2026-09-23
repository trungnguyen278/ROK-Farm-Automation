"""What a drag buys is measured on its own, and the maths gets the signs right.

The farm logged drag/tile pairs from inside its scan for a day. The first fit
of them came out at a median error of 21 tiles on moves of 47, because node
clicks, recentres, retreats and city trips moved the camera without a drag.
The operator's call, 2026-09-23: measure it separately
(tools/dev/pan_survey.py), with the pointer kept inside the window and the
window's width and height each dragged as two halves.
"""

import inspect
import random

import numpy as np

from rok_farm import pan_model
from rok_farm.flow_steps import GemFlowMixin
from tools.dev import pan_survey

# An arbitrary skewed transform, the kind an isometric map produces.
M_TRUE = np.array([[-0.023, 0.004],
                   [0.001, -0.031]])


def _pairs(m, n=40, noise=0.0, seed=1):
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        dpx, dpy = rng.uniform(-800, 800), rng.uniform(-450, 450)
        dx, dy = m @ (dpx, dpy)
        out.append((dpx, dpy, dx + rng.gauss(0, noise), dy + rng.gauss(0, noise)))
    return out


def test_the_fit_recovers_the_transform():
    m, resid = pan_model.fit(_pairs(M_TRUE))
    assert np.allclose(m, M_TRUE, atol=1e-9)
    assert np.abs(resid).max() < 1e-6


def test_the_fit_survives_ocr_rounding():
    """The HUD reads whole tiles, so every pair carries +-0.5 of rounding."""
    m, _ = pan_model.fit(_pairs(M_TRUE, n=32, noise=0.5))
    assert np.allclose(m, M_TRUE, atol=2e-3)


def test_a_drag_moves_the_camera_the_other_way_on_screen():
    """The map follows the pointer: the ground that was LEFT of centre is what
    a rightward drag brings to the middle. So the tile shown at an offset is
    the camera minus what a drag of that offset would move it."""
    cam = (500.0, 600.0)
    dx, dy = pan_model.drag_to_tiles(M_TRUE, 300, 0)
    shown = pan_model.screen_to_tile(M_TRUE, cam, 300, 0)
    assert shown == (cam[0] - dx, cam[1] - dy)


def test_the_view_is_centred_on_the_camera():
    corners = pan_model.view_corners(M_TRUE, 1534, 863, camera_xy=(100, 200))
    cx = sum(c[0] for c in corners) / 4
    cy = sum(c[1] for c in corners) / 4
    assert abs(cx - 100) < 1e-9 and abs(cy - 200) < 1e-9


def test_the_view_area_is_the_determinant_times_the_pixels():
    area = pan_model.view_area_tiles(M_TRUE, 1534, 863)
    assert abs(area - abs(np.linalg.det(M_TRUE)) * 1534 * 863) < 1e-6


WIN = {"left": 513, "top": 306, "width": 1534, "height": 863}


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
    legs += pan_survey.farm_legs(WIN, rng)
    for l in legs:
        for x, y in ((l["sx"], l["sy"]), (l["ex"], l["ey"])):
            assert pan_survey.inside(WIN, x, y), (l, x, y)


def test_the_farm_flow_does_not_measure_the_pan():
    """Pairs taken inside the flow are spoiled by every other camera move."""
    for name in ("_step_scan_and_verify_gem", "_map_sync"):
        src = inspect.getsource(getattr(GemFlowMixin, name))
        assert "_pan_pixels" not in src and "_pan_dirty" not in src, name
