"""What a drag on the world map buys in tiles, and what one frame holds.

Measured by tools/dev/pan_survey.py, never inside the farm flow. The farm
used to log drag/tile pairs from its own scan, and the first fit of them came
out at a median error of 21 tiles on moves of 47: node clicks, recentres,
retreats and city trips all moved the camera without adding a pixel to the
total. The operator's call, 2026-09-23: measure it on its own, where nothing
moves the camera but the drag being measured.

Conventions, because a sign error here steers the exact opposite way:

  * A drag of (dpx, dpy) screen pixels moves the CAMERA by M @ (dpx, dpy)
    tiles. The map follows the pointer, so the camera goes the other way:
    dragging left shows ground further right.
  * A screen point at (ox, oy) pixels from the frame centre therefore shows
    the tile  camera - M @ (ox, oy).
"""

from __future__ import annotations

import numpy as np


def fit(pairs):
    """Least-squares M from [(dpx, dpy, dX, dY), ...].

    Returns (M, residuals) with d_tiles = M @ d_px. Needs at least two
    non-parallel drags to be determined at all; the survey gives dozens.
    """
    a = np.array([[p[0], p[1]] for p in pairs], dtype=float)
    b = np.array([[p[2], p[3]] for p in pairs], dtype=float)
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    resid = b - a @ sol
    return sol.T, resid


def drag_to_tiles(m, dpx: float, dpy: float) -> tuple[float, float]:
    """How far the camera moves for a drag of (dpx, dpy) pixels."""
    v = np.asarray(m, dtype=float) @ np.array([dpx, dpy], dtype=float)
    return float(v[0]), float(v[1])


def screen_to_tile(m, camera_xy, ox: float, oy: float) -> tuple[float, float]:
    """The tile shown at (ox, oy) pixels from the frame centre."""
    v = np.asarray(m, dtype=float) @ np.array([ox, oy], dtype=float)
    return float(camera_xy[0] - v[0]), float(camera_xy[1] - v[1])


def view_corners(m, width_px: float, height_px: float,
                 camera_xy=(0.0, 0.0)) -> list[tuple[float, float]]:
    """Tiles at the frame's four corners: top-left, top-right, bottom-right,
    bottom-left. An affine view, so the frame holds a parallelogram."""
    hw, hh = width_px / 2.0, height_px / 2.0
    return [screen_to_tile(m, camera_xy, ox, oy)
            for ox, oy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh))]


def view_area_tiles(m, width_px: float, height_px: float) -> float:
    """Tiles covered by one frame of that size."""
    return abs(float(np.linalg.det(np.asarray(m, dtype=float)))) * width_px * height_px
