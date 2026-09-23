"""What a drag on the world map buys in tiles, and what one frame holds.

Measured by tools/dev/pan_survey.py, never inside the farm flow. The farm
used to log drag/tile pairs from its own scan, and the first fit of them came
out at a median error of 21 tiles on moves of 47: node clicks, recentres,
retreats and city trips all moved the camera without adding a pixel. The
operator's call, 2026-09-23: measure it on its own, where nothing moves the
camera but the drag being measured, and count only drags whose pointer stays
inside the game window.

What the survey found on the live client (icon zoom, 1534x863 client,
35 held drags with the pointer steered closed-loop, 2026-09-23 09:53):

  * The tile axes ARE the screen axes. Horizontal drags moved Y by 0 tiles
    (median), vertical drags moved X by 0. Screen right is +X, screen UP is
    +Y -- dragging the pointer down moves the camera up the map.
  * The camera is tilted, so the ground per pixel depends on the row, and
    the game pans by keeping the ground under the pointer under the pointer:
        horizontal, tiles/100px: row 0.25 1.820 (n=8), 0.50 1.541 (n=8),
                                 0.75 1.359 (n=5)
        vertical,   tiles/100px: around 0.34 2.527 (n=4), 0.50 2.222 (n=8),
                                 0.66 1.792 (n=2)
  * No carry-on after a moving release: scan-speed drags, released while
    still moving, landed at 0.86-1.16x what the pointer alone predicts
    (median 0.97, n=14) -- rounding of whole-tile readings, nothing more.

So one 1534x863 frame holds a trapezoid: about 31 tiles wide along its top
edge, 24 across the middle, 17 along the bottom, and 19 deep (12 above the
centre, 7 below) -- roughly 460 tiles.

Rows are fractions of the client height, 0 at the top. Linear in the row is
an approximation of the perspective; inside the frame it holds to the
survey's rounding (residual sd 0.06 tiles/100px horizontally, 0.11 vertically).
"""

from __future__ import annotations

import math

# kx(r) = KX_MID + KX_SLOPE * (0.5 - r), tiles per pixel, horizontal, row r.
KX_MID = 0.01568
KX_SLOPE = 0.00929
# ky(r) = KY_MID + KY_SLOPE * (0.5 - r), tiles per pixel, vertical, row r.
KY_MID = 0.02223
KY_SLOPE = 0.02480

# The world is 1200 tiles a side. Over 3,433 logged position reads the
# largest X was 999, and every Y above 1199 was the known misread where the
# last digit collides with the icon after it ("Y:182" -> "1822").
MAP_SIZE = 1200


def kx(row: float) -> float:
    return KX_MID + KX_SLOPE * (0.5 - row)


def ky(row: float) -> float:
    return KY_MID + KY_SLOPE * (0.5 - row)


def _ky_integral(r1: float, r2: float) -> float:
    """Integral of ky(r) dr from r1 to r2."""
    def f(r):
        return KY_MID * r + KY_SLOPE * (0.5 * r - r * r / 2.0)
    return f(r2) - f(r1)


def ground_offset(ox: float, oy: float, height_px: float) -> tuple[float, float]:
    """Tiles from the camera to the ground shown (ox, oy) px from the centre.

    X grows to the right; Y grows UP the screen, so a point below the centre
    (oy > 0) shows a smaller Y.
    """
    row = 0.5 + oy / float(height_px)
    return kx(row) * ox, -height_px * _ky_integral(0.5, row)


def drag_move(press, release, win) -> tuple[float, float]:
    """How far the camera moves for a drag from `press` to `release`.

    Screen pixels, absolute. The ground under the press point ends up under
    the release point, so the camera moves by the difference of the two
    ground offsets.
    """
    cx = win["left"] + win["width"] / 2.0
    cy = win["top"] + win["height"] / 2.0
    h = win["height"]
    gp = ground_offset(press[0] - cx, press[1] - cy, h)
    gr = ground_offset(release[0] - cx, release[1] - cy, h)
    return gp[0] - gr[0], gp[1] - gr[1]


def view_corners(camera_xy, width_px: float, height_px: float):
    """Tiles at the frame's corners: top-left, top-right, bottom-right,
    bottom-left. A trapezoid, wider at the top."""
    hw, hh = width_px / 2.0, height_px / 2.0
    out = []
    for ox, oy in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)):
        dx, dy = ground_offset(ox, oy, height_px)
        out.append((camera_xy[0] + dx, camera_xy[1] + dy))
    return out


def in_view(camera_xy, tile_xy, width_px: float, height_px: float,
            margin: float = 0.0) -> bool:
    """Is this tile on screen when the camera is at camera_xy?

    `margin` shrinks the frame by that fraction on every side, for callers
    that only trust the middle of it.
    """
    dy = tile_xy[1] - camera_xy[1]
    # Walk the rows: find the row whose ground is dy tiles from the camera.
    lo, hi = margin, 1.0 - margin
    ylo = -height_px * _ky_integral(0.5, lo)
    yhi = -height_px * _ky_integral(0.5, hi)
    if not (yhi <= dy <= ylo):
        return False
    a, b = lo, hi
    for _ in range(30):
        mid = (a + b) / 2.0
        if -height_px * _ky_integral(0.5, mid) > dy:
            a = mid
        else:
            b = mid
    row = (a + b) / 2.0
    half = width_px / 2.0 * (1.0 - 2.0 * margin)
    return abs(tile_xy[0] - camera_xy[0]) <= kx(row) * half


def tile_heading(screen_heading: float, width_px: float, height_px: float,
                 margin: float = 80.0) -> float:
    """The map direction the camera travels when the scan swipes along
    `screen_heading`.

    The scan's swipe for heading h moves the pointer along -(cos h, sin h),
    scaled by its reach -- (width/2 - margin) across, (height/2 - margin)
    down -- so the camera moves along +(cos h, sin h) on screen. On the map
    that is +X for screen right and -Y for screen down, each at its own
    tiles-per-pixel. The two used to be treated as the same angle, which put
    every reading of the map book for a vertical heading on the wrong side
    of the camera.
    """
    rx = (width_px / 2.0 - margin) * KX_MID
    ry = (height_px / 2.0 - margin) * KY_MID
    return math.atan2(-ry * math.sin(screen_heading),
                      rx * math.cos(screen_heading))


def screen_heading(dx_tiles: float, dy_tiles: float, width_px: float,
                   height_px: float, margin: float = 80.0) -> float:
    """The scan heading that moves the camera toward (dx, dy) tiles away.

    The inverse of tile_heading: same reach, same per-axis scales.
    """
    rx = (width_px / 2.0 - margin) * KX_MID
    ry = (height_px / 2.0 - margin) * KY_MID
    return math.atan2(-dy_tiles / ry, dx_tiles / rx)


def plausible(x: int, y: int) -> bool:
    """Could this be a real position? Rejects the known Y misread."""
    return 0 <= x < MAP_SIZE and 0 <= y < MAP_SIZE
