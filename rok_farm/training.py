"""Collecting finished troops and starting the next batch.

The operator walked me through this screen by screen on 2026-09-21, and the
reason it exists is the same as the barbarian auto: an account that gathers
sixty deposits a day and does nothing else is a strange shape, and none of the
anti-cheat letters has been explained by anything smaller.

Four steps, each with a signal that was measured rather than guessed:

  1. COLLECT -- click the building under its white "ready" banner.
  2. SELECT  -- click the same spot again; three hexagonal buttons come up.
  3. OPEN    -- press the right-hand hexagon, which opens the training panel.
     Its picture changes with the troop type (a catapult for siege, a horse
     for the stable), so the button is found by shape and colour, never by
     what is drawn inside it.
  4. TRAIN   -- press HUAN LUYEN, and NEVER the orange NGAY beside it, which
     finishes instantly for 1,500 gems.

What that cost to learn, so it does not get undone by a well-meaning tidy-up:

  * The white banner is not enough on its own. Every farm and quarry in the
    city wears a white resource bubble of the same size -- twenty-eight of
    them on one frame. The training banner is the only one with a purple
    shield inside: fraction of its box in H140-155 with S>110 measured 0.124
    to 0.173 against 0.000 for every bubble, and 0.000 for the cherry-blossom
    plaque that a wider purple band had been catching, because blossom pink
    sits at hue 165.
  * The menu buttons are HEXAGONS. HoughCircles found them at one zoom and
    missed them at another, and scanning a whole city for circles returns
    ninety-seven of them -- taking "the rightmost" pressed the build button in
    the corner of the screen and opened a panel nothing here knew how to shut.
  * The dim ratio is no use for any of this. The building menu leaves it at
    1.12 and the search panel at 1.10, both well under the 1.8 a modal is
    supposed to clear. Three separate clicks were reported as "nothing
    happened" on that evidence while they were in fact collecting troops.
    Only the training panel itself dims properly, at 4.3.
"""

from __future__ import annotations

import cv2
import numpy as np

# --- Step 1: the "ready" banner -------------------------------------------
BANNER_SAT_MAX = 45
BANNER_VAL_MIN = 205
BANNER_AREA_MIN = 400
BANNER_W = (34, 70)
BANNER_H = (28, 60)
BANNER_PURPLE_HUE = (140, 155)
BANNER_PURPLE_MIN = 0.05

# How far below the banner the building's own body sits, as a multiple of the
# banner's height rather than a pixel count -- the city camera zooms, and a
# fixed offset that worked at one zoom missed at the next.
BUILDING_DROP = 1.2

# --- Step 2/3: the three hexagons -----------------------------------------
# Measured: the real buttons come out 77x65 and 78x73. A patch of city wall
# passed the first cut at 90x73, which is why the upper bound is 85 rather
# than something generous -- aspect ratio alone did not separate them (1.23
# for the wall against 1.18 for a real button).
HEX_SIDE = (65, 85)
HEX_HUE = (95, 118)
# The HUD has blue hexagons of its own down the left edge and in the corners.
HUD_MARGIN_X = 120
HUD_CORNER_X, HUD_CORNER_Y = 1400, 690

# --- Step 4: the two buttons ----------------------------------------------
# The orange one is the anchor: it separates cleanly, one blob 160x54. HUAN
# LUYEN sits this far to its right, same height. Colour cannot find it
# directly -- the panel's own background is the same blue at the same
# saturation, only the value differs.
NGAY_HUE = (10, 30)
NGAY_W = (120, 220)
NGAY_H = (35, 80)
NGAY_TO_TRAIN_DX = 251
TRAIN_PANEL_DIM_MIN = 2.0


def find_banners(frame) -> list[tuple[int, int, int, int]]:
    """Every "troops ready" banner, as (cx, cy, w, h), top-left first."""
    if frame is None:
        return []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 1] < BANNER_SAT_MAX) &
             (hsv[:, :, 2] > BANNER_VAL_MIN)).astype(np.uint8) * 255
    white = cv2.morphologyEx(
        white, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    n, _, stats, cents = cv2.connectedComponentsWithStats(white, 8)
    out = []
    for s, c in zip(stats[1:], cents[1:]):
        if s[4] < BANNER_AREA_MIN:
            continue
        if not (BANNER_W[0] <= s[2] <= BANNER_W[1]):
            continue
        if not (BANNER_H[0] <= s[3] <= BANNER_H[1]):
            continue
        cx, cy, bw, bh = int(c[0]), int(c[1]), int(s[2]), int(s[3])
        x0, y0 = max(0, cx - bw // 2 - 4), max(0, cy - bh // 2 - 6)
        box = hsv[y0:cy + bh // 2 + 6, x0:cx + bw // 2 + 4].reshape(-1, 3)
        if box.size == 0:
            continue
        purple = ((box[:, 0] >= BANNER_PURPLE_HUE[0]) &
                  (box[:, 0] <= BANNER_PURPLE_HUE[1]) &
                  (box[:, 1] > 110) & (box[:, 2] > 70)).mean()
        if purple < BANNER_PURPLE_MIN:
            continue
        out.append((cx, cy, bw, bh))
    return sorted(out, key=lambda b: (b[1], b[0]))


def building_point(banner) -> tuple[int, int]:
    """Where to click for a banner: the building below it."""
    cx, cy, _, bh = banner
    return cx, cy + int(bh * BUILDING_DROP)


def menu_hexes(frame) -> list[tuple[int, int, int, int]]:
    """The hexagonal buttons of a selected building, left to right."""
    if frame is None:
        return []
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 0] >= HEX_HUE[0]) & (hsv[:, :, 0] <= HEX_HUE[1]) &
         (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 120)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for s, c in zip(st[1:], ce[1:]):
        w, h = int(s[2]), int(s[3])
        if not (HEX_SIDE[0] <= w <= HEX_SIDE[1]):
            continue
        if not (HEX_SIDE[0] <= h <= HEX_SIDE[1]):
            continue
        if not (0.75 < w / max(1, h) < 1.35):
            continue
        cx, cy = int(c[0]), int(c[1])
        if cx < HUD_MARGIN_X:
            continue
        if cx > HUD_CORNER_X and cy > HUD_CORNER_Y:
            continue
        out.append((cx, cy, w, h))
    return sorted(out, key=lambda b: b[0])


def orange_button(frame) -> tuple[int, int] | None:
    """The NGAY button -- the gem one -- used only as a landmark."""
    if frame is None:
        return None
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 0] >= NGAY_HUE[0]) & (hsv[:, :, 0] <= NGAY_HUE[1]) &
         (hsv[:, :, 1] > 110) & (hsv[:, :, 2] > 120)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)))
    n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
    best = None
    for s, c in zip(st[1:], ce[1:]):
        if not (NGAY_W[0] <= s[2] <= NGAY_W[1]):
            continue
        if not (NGAY_H[0] <= s[3] <= NGAY_H[1]):
            continue
        if s[4] < 3000:
            continue
        if best is None or s[4] > best[0]:
            best = (int(s[4]), int(c[0]), int(c[1]))
    return (best[1], best[2]) if best else None


def reads_orange(frame, x: int, y: int) -> bool:
    """Is this spot the gem button? Checked again immediately before clicking.

    1,500 gems is about a day of farming, and the two buttons are one click
    apart, so the guard is worth its few milliseconds.
    """
    if frame is None:
        return True
    patch = frame[max(0, y - 10):y + 10, max(0, x - 30):x + 30]
    if patch.size == 0:
        return True
    hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
    return bool(((hsv[:, :, 0] >= NGAY_HUE[0]) &
                 (hsv[:, :, 0] <= NGAY_HUE[1]) &
                 (hsv[:, :, 1] > 110)).mean() > 0.25)


def train_point(frame) -> tuple[int, int] | None:
    """Where HUAN LUYEN is, or None if the panel does not look right.

    The dim ratio is checked FIRST, and this is the one place in the whole
    flow where it earns its keep: the training panel darkens the city to 4.3
    while the building menu and the search panel leave it at 1.1. Without it,
    something orange and button-shaped out in the city satisfied the rest --
    a test caught it returning (851,29) on a frame with no panel at all.
    """
    if frame is None:
        return None
    from rok_farm.state_probe import dim_ratio
    if dim_ratio(frame) < TRAIN_PANEL_DIM_MIN:
        return None
    anchor = orange_button(frame)
    if anchor is None:
        return None
    x, y = anchor[0] + NGAY_TO_TRAIN_DX, anchor[1]
    if reads_orange(frame, x, y):
        return None
    return x, y
