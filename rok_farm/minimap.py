"""The minimap as a map: its view outline placed in tiles, its province
lines split into provinces.

The minimap (top right of the client, at readable zooms and at icon zoom,
not in the far view) draws the kingdom the camera stands in, its province
lines, and the view as a white outline. Measured on the home kingdom,
2026-09-24 (tools/dev/minimap_survey.py, minimap_zones.py): the outline
against the HUD read of the same frame places the minimap in tiles, and
the median of many crops split along its light lines gives the provinces --
10 on 4096, the standard 6 on the rim, 3 round the centre, 1 centre.

Pure functions on crops, no game input. The farm builds a map's provinces
from the crops its size probe keeps (MapEdgeMixin._survey_map);
tools/dev/minimap_zones.py does the same from saved folders.
"""

from __future__ import annotations

import json
import time

import cv2
import numpy as np

from rok_farm import map_memory
from rok_farm.map_memory import CELL, HOME_TILES


def crop_of(frame):
    """The frame's top-right quarter, which holds the minimap. Every
    function here takes this crop (and HOME_H is in its pixels)."""
    fh, fw = frame.shape[:2]
    return frame[:fh // 4, fw * 3 // 4:]


# Tiles -> crop pixels on a 1200 map at the widest readable zoom (the view
# outline 24 x 12 px). Fitted on 43 reads on 4096, 2026-09-24 13:19: median
# 0.20 px, worst 1.54; an affine fit left 0.75 / 3.3 -- the minimap is a
# tilted view, 1200 tiles ~127 x 91 px. The same geometry held on S11001, the
# kingdom next door: its 173,714 predicted at (246.5, 38.5), seen at
# (246.9, 38.4).
HOME_H = np.array([[0.12068756, 0.07416308, 217.98613591],
                   [-0.00023254, -0.07802386, 100.92274318],
                   [-7.41424e-06, 0.00025557, 1.0]])
# Outlines at one zoom only: the outline's size is the zoom, and where the
# camera point sits inside it moves with the zoom.
OUTLINE_SIZE_TOL = 2
# The home calibration, scaled to a map's size and shifted by its median
# miss, is taken when it then places the map's own outlines this well
# (median). Only outlines half a view or more from every edge count: near an
# edge the map's edge cuts the outline and its centroid moves inward (up to
# 4-5 px at the east and south edges, 14:50). Away from the edges a notch of
# zoom only moves the camera point inside the outline: at the survey's zoom
# (legs of 96 tiles) the prior misses by 0.19 px unshifted; a notch wider
# (legs of 125, 14:50) by 0.66 px, 0.32 once shifted (-0.01, -0.62) -- 18
# points. Wrong by one map size (1440 read as 1200) no shift saves it: ~17
# px at X 1000, growing across the map.
PRIOR_OK_PX = 1.0
PRIOR_MIN_POINTS = 4
# The prior's pixels a tile (its affine part), for how far a view reaches.
PRIOR_PX_PER_TILE = (0.106, 0.076)
EDGE_PAD_TILES = 10
# Else a fit of the map's own, from at least this many outlines, placing
# them at least this well (median) -- and only from outlines spread over
# the map: fitted on the north-east quarter alone, the home kingdom's far
# corners came out 3-4 px (30-40 tiles) off.
FIT_MIN_POINTS = 12
FIT_OK_PX = 1.0
FIT_MIN_SPREAD = 0.5            # of the map's size, on both axes
# Province lines: white top-hat (5 px) of the minimap on its land, at least
# this. Measured on the median of 411 icon-zoom farm frames: the land between
# lines gave 0-2 (9,169 px, 85.5%), the lines a flat tail from 3 to 39+
# (1,554 px) -- the break is between 2 and 3.
LINE_TOPHAT_MIN = 3
# A piece of land smaller than this is a scrap between lines, not a province.
MIN_PROVINCE_PX = 60
# The map's square through H, pulled in by this many pixels before it is
# split. The province lines stop at the drawn coast, a few pixels inside
# the square, and the rim provinces met round their ends: 9 provinces by
# day, 8 by night on the home kingdom with none. Measured 2026-09-24 against
# the saved split: 10 provinces both ways for 2 to 10 px, the best at 5
# (99.7% of cells by day, 99.5% by night). Cells in the pulled-in rim take
# the nearest province (tile_grid), so none is lost.
RIM_ERODE_PX = 5


def land_box(crop):
    """The minimap's kingdom: the largest dark region of the crop. (x, y, w, h)"""
    v = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 2]
    dark = cv2.morphologyEx((v < 75).astype(np.uint8), cv2.MORPH_CLOSE,
                            np.ones((5, 5), np.uint8))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(dark, 8)
    if n < 2:
        return None
    k = 1 + int(np.argmax(st[1:, 4]))
    return tuple(int(t) for t in st[k, :4])


# How far outside the map's square (through HOME_H) the view outline may
# still be looked for: a view at an edge reaches past it.
OUTLINE_BOX_PAD = 20


def minimap_box(shape):
    """(x0, y0, x1, y1) of the crop the view outline is looked for in: the
    map's square through HOME_H -- the same box for a map of any size drawn
    in it (scaled_prior) -- and OUTLINE_BOX_PAD round it. Not the dark land:
    over the night theme that ran down to the troop panel's white "5/5",
    taken for an outline (2026-09-24 14:50)."""
    corners = np.float32([[[0, 0], [HOME_TILES, 0], [HOME_TILES, HOME_TILES],
                           [0, HOME_TILES]]])
    quad = cv2.perspectiveTransform(corners, HOME_H)[0]
    h, w = shape[:2]
    x0 = max(0, int(quad[:, 0].min()) - OUTLINE_BOX_PAD)
    y0 = max(0, int(quad[:, 1].min()) - OUTLINE_BOX_PAD)
    x1 = min(w, int(np.ceil(quad[:, 0].max())) + OUTLINE_BOX_PAD)
    y1 = min(h, int(np.ceil(quad[:, 1].max())) + OUTLINE_BOX_PAD)
    return x0, y0, x1, y1


def outline(crop):
    """The view outline: the largest thin near-white blob in the minimap's
    box -- the crop also holds white UI text ("4/5").
    (cx, cy, w, h) in crop pixels, or None."""
    found = _outline_blob(crop)
    return None if found is None else found[1]


def _outline_blob(crop):
    """(pixel mask, (cx, cy, w, h)) of the view outline, or None."""
    x0, y0, x1, y1 = minimap_box(crop.shape)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = ((hsv[..., 1] < 35) & (hsv[..., 2] > 225)).astype(np.uint8)
    keep = np.zeros_like(white)
    keep[y0:y1, x0:x1] = 1
    white &= keep
    n, lab, stats, cent = cv2.connectedComponentsWithStats(white, 8)
    best = None
    # As small as 8 x 3: a 2400 map drawn in the home box would show the
    # widest readable view at 12 x 6. On the 50 home crops the smaller
    # bound found only outlines (two more, 8x4 and 11x5, mid zoom), nothing else.
    for k in range(1, n):
        x, y, w, h, a = stats[k]
        if 8 <= w <= 60 and 3 <= h <= 25 and a >= 8 and a / float(w * h) < 0.6:
            if best is None or a > best[4]:
                best = (x, y, w, h, a, cent[k], k)
    if best is None:
        return None
    x, y, w, h, _a, c, k = best
    return lab == k, (float(c[0]), float(c[1]), int(w), int(h))


# How far round the outline's own white pixels a crop is left out of the
# median: its anti-aliased rim is lighter than the land without being white,
# and LINE_TOPHAT_MIN takes a line at 3 grey levels.
OUTLINE_MASK_PX = 2


def median_minimap(crops):
    """The median of the crops, each one's view outline left out of it.

    The outline moves with the camera, so a plain median drops it -- unless
    the camera kept one latitude for half the crops. On 3560 (2026-09-24
    21:31) the city sat 86 tiles from the east edge: the east walk was one
    read, and with the walk back and the legs in, half of the 12 crops had
    the outline's bottom edge on one minimap row. The median kept it as a
    line and cut a province in two -- 11 provinces, where the farm's own 40
    frames give the standard 10 (0.969 of cells alike).
    """
    import warnings

    stack = np.stack([np.asarray(c, np.float32) for c in crops])
    plain = np.median(stack, axis=0)
    k = 2 * OUTLINE_MASK_PX + 1
    for i, c in enumerate(crops):
        found = _outline_blob(np.asarray(c, np.uint8))
        if found is not None:
            gone = cv2.dilate(found[0].astype(np.uint8), np.ones((k, k), np.uint8)) > 0
            stack[i][gone] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        med = np.nanmedian(stack, axis=0)
    # Under the outline in every crop: nothing else saw it, take what there is.
    med = np.where(np.isnan(med), plain, med)
    return np.clip(np.round(med), 0, 255).astype(np.uint8)


def outline_hits(items, map_id):
    """[(x, y, px, py, w, h)]: the outline beside each read on `map_id`."""
    found = []
    for crop, hud in items:
        if not hud or hud[0] != map_id:
            continue
        o = outline(crop)
        if o is not None:
            found.append((hud[1], hud[2], o[0], o[1], o[2], o[3]))
    return found


def away_from_edges(hits, size):
    """The hits whose view does not reach the map's edge: half the
    outline's width and height in tiles, and a margin, from every edge."""
    k = HOME_TILES / float(size)
    sx, sy = PRIOR_PX_PER_TILE[0] * k, PRIOR_PX_PER_TILE[1] * k
    keep = []
    for x, y, px, py, w, h in hits:
        mx = w / 2.0 / sx + EDGE_PAD_TILES
        my = h / 2.0 / sy + EDGE_PAD_TILES
        if mx <= x <= size - 1 - mx and my <= y <= size - 1 - my:
            keep.append((x, y, px, py, w, h))
    return keep


def outline_points(items, map_id, size_px=None):
    """[(x, y, px, py)]: the outline beside each read on `map_id`. The farm
    hands in crops from one zoom (the walks'), all of them count -- the
    outline is drawn smaller toward the minimap's far side (31 x 15 by the
    city, 25 x 14 near the north edge, 14:50). `size_px` keeps only the
    outlines within OUTLINE_SIZE_TOL of that size, "mode" of the commonest
    size -- for folders that mix the zoom's reads in (the dev tools')."""
    found = outline_hits(items, map_id)
    if not found:
        return []
    if size_px is None:
        return [f[:4] for f in found]
    if size_px == "mode":
        sizes, counts = np.unique(np.array([f[4:6] for f in found]), axis=0,
                                  return_counts=True)
        size_px = tuple(sizes[int(np.argmax(counts))])
    return [f[:4] for f in found
            if abs(f[4] - size_px[0]) <= OUTLINE_SIZE_TOL
            and abs(f[5] - size_px[1]) <= OUTLINE_SIZE_TOL]


def residual(H, points):
    """Median pixel error of H over the points."""
    src = np.float32([[p[0], p[1]] for p in points])
    dst = np.float32([[p[2], p[3]] for p in points])
    pred = cv2.perspectiveTransform(src[None], np.asarray(H, np.float64))[0]
    return float(np.median(np.hypot(*(pred - dst).T)))


def fit_h(points):
    """A projective fit tiles -> crop pixels, or None."""
    if len(points) < 4:
        return None
    src = np.float32([[p[0], p[1]] for p in points])
    dst = np.float32([[p[2], p[3]] for p in points])
    H, _mask = cv2.findHomography(src, dst, cv2.LMEDS)
    return H


def scaled_prior(size: int):
    """HOME_H for a map `size` tiles a side, if the minimap draws every map
    in the same box."""
    k = HOME_TILES / float(size)
    return HOME_H @ np.diag([k, k, 1.0])


def shifted(H, dx, dy):
    """H, then a shift of (dx, dy) pixels."""
    return np.array([[1.0, 0.0, dx], [0.0, 1.0, dy], [0.0, 0.0, 1.0]]) @ np.asarray(H, np.float64)


def calibrate(items, map_id, size):
    """(H, how, median px) placing this map's tiles on the minimap, or
    (None, why, None)."""
    pts = [p[:4] for p in away_from_edges(outline_hits(items, map_id), size)]
    if len(pts) >= PRIOR_MIN_POINTS:
        H0 = scaled_prior(size)
        src = np.float32([[p[0], p[1]] for p in pts])
        dst = np.float32([[p[2], p[3]] for p in pts])
        dx, dy = np.median(dst - cv2.perspectiveTransform(src[None], H0)[0], axis=0)
        err = residual(shifted(H0, float(dx), float(dy)), pts)
        if err <= PRIOR_OK_PX:
            # The shift is the walks' zoom moving the camera point inside
            # the outline; the minimap itself does not move with the zoom.
            # So the provinces are placed with the prior as it is -- the
            # same geometry every trip, at whatever zoom it ran.
            return (H0, f"home calibration scaled to {size} (the walks' zoom "
                        f"off by {dx:+.2f},{dy:+.2f} px)", err)
    if len(pts) < FIT_MIN_POINTS:
        return None, f"{len(pts)} outlines, {FIT_MIN_POINTS} needed for a fit", None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if min(max(xs) - min(xs), max(ys) - min(ys)) < FIT_MIN_SPREAD * size:
        return None, "outlines not spread over the map", None
    H = fit_h(pts)
    if H is None:
        return None, "no fit", None
    err = residual(H, pts)
    if err > FIT_OK_PX:
        return None, f"fit misses by {err:.2f} px", None
    return H, f"fitted on {len(pts)} outlines", err


def map_mask(shape, H, size=HOME_TILES):
    """The map's own square, [0, size) both ways, through H onto the crop."""
    corners = np.float32([[[0, 0], [size, 0], [size, size], [0, size]]])
    quad = cv2.perspectiveTransform(corners, np.asarray(H, np.float64))[0]
    mask = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(mask, [np.round(quad).astype(np.int32)], 1)
    return mask


def _dark_land(v):
    """The minimap's land where it is drawn dark (the day theme)."""
    dark = (v < 75).astype(np.uint8)
    n, lab, st, _c = cv2.connectedComponentsWithStats(dark, 8)
    if n < 2:
        return np.zeros(v.shape, np.uint8)
    k = 1 + int(np.argmax(st[1:, 4]))
    land = (lab == k).astype(np.uint8)
    ff = np.pad(1 - land, 1, constant_values=1).astype(np.uint8)
    m = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, m, (0, 0), 2)
    return (ff[1:-1, 1:-1] != 2).astype(np.uint8)


def segment(median, H=None, size=HOME_TILES):
    """(labels, lines) for a median minimap crop; label 0 is not a province.

    The map's ground is its own square through H where the calibration is
    known -- not the colour: the minimap is see-through, and over the night
    theme or the fog its land is not dark at all (2026-09-24 14:50: the
    dark-land mask ran round the panel's margin and joined all six rim
    provinces into one). Without H, the dark land, as measured by day.
    """
    hsv = cv2.cvtColor(median, cv2.COLOR_BGR2HSV)
    s, v = hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    if H is not None:
        k = 2 * RIM_ERODE_PX + 1
        land = cv2.erode(map_mask(median.shape, H, size), np.ones((k, k), np.uint8))
    else:
        land = _dark_land(v)
    if not land.any():
        return np.zeros(median.shape[:2], np.int32), np.zeros(median.shape[:2], np.uint8)
    inside = cv2.erode(land, np.ones((3, 3), np.uint8))
    # Members' cities and the like: saturated dots on the lines -- painted out.
    dots = cv2.dilate((((s > 110) & (v > 90)) & (inside > 0)).astype(np.uint8),
                      np.ones((3, 3), np.uint8))
    clean = cv2.inpaint(median, dots, 2, cv2.INPAINT_TELEA)
    top = cv2.morphologyEx(cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY), cv2.MORPH_TOPHAT,
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    lines = ((top >= LINE_TOPHAT_MIN) & (inside > 0)).astype(np.uint8)
    lines = cv2.morphologyEx(lines, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cells = ((inside > 0) & (lines == 0)).astype(np.uint8)
    n2, lab2, st2, _c2 = cv2.connectedComponentsWithStats(cells, 4)
    labels = np.zeros_like(lab2)
    k2 = 0
    for k in sorted(range(1, n2), key=lambda k: -st2[k, 4]):
        if st2[k, 4] >= MIN_PROVINCE_PX:
            k2 += 1
            labels[lab2 == k] = k2
    return labels, lines


def tile_grid(labels, H, size=HOME_TILES, cell=CELL):
    """Province of every book cell: its centre through H into the minimap,
    the nearest province pixel there (lines and scraps have none)."""
    has = labels > 0
    n = size // cell
    grid = np.zeros((n, n), np.int32)
    if not has.any():
        return grid
    _dist, idx = cv2.distanceTransformWithLabels((~has).astype(np.uint8), cv2.DIST_L2, 3,
                                                 labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(has)
    lut = np.zeros(idx.max() + 1, np.int32)
    lut[idx[ys, xs]] = labels[ys, xs]
    cells = [(i, j) for j in range(n) for i in range(n)]
    centres = np.float32([[(i + 0.5) * cell, (j + 0.5) * cell] for i, j in cells])
    px = cv2.perspectiveTransform(centres[None], np.asarray(H, np.float64))[0]
    h, w = labels.shape
    for (cx, cy), (i, j) in zip(px, cells):
        # Kept inside the crop: a cell whose centre lands a pixel past its
        # edge still takes the nearest province.
        x = min(max(int(round(cx)), 0), w - 1)
        y = min(max(int(round(cy)), 0), h - 1)
        grid[j, i] = lut[idx[y, x]]
    return grid


def build(items, map_id, size, city=None) -> dict:
    """Provinces of `map_id` from (crop, HUD read) pairs: {"grid", "H",
    "how", "fit_px", "provinces", "crops"}, or {"error", "stage"} -- the
    stage that failed: "crops" and "calibrate" want more reads spread over
    the map, "segment" and "city" would not be helped by them."""
    on_map = [(c, h) for c, h in items if h and h[0] == map_id]
    if len(on_map) < 8:
        return {"error": f"{len(on_map)} minimap crop(s) on {map_id}", "stage": "crops"}
    H, how, err = calibrate(on_map, map_id, size)
    if H is None:
        return {"error": how, "stage": "calibrate"}
    median = median_minimap([c for c, _h in on_map])
    labels, _lines = segment(median, H, size)
    grid = tile_grid(labels, H, size)
    n = int(grid.max())
    if n < 2 or n > 255:
        return {"error": f"{n} province(s)", "stage": "segment"}
    if city is not None:
        i, j = int(city[0]) // CELL, int(city[1]) // CELL
        if not (0 <= j < grid.shape[0] and 0 <= i < grid.shape[1]) or grid[j, i] == 0:
            return {"error": f"the city {city} is in no province", "stage": "city"}
    return {"grid": grid, "H": np.asarray(H).tolist(), "how": how, "fit_px": err,
            "provinces": n, "crops": len(on_map)}


def save(res: dict, map_id: str) -> None:
    """data/map_knowledge/<map>_provinces.png (+ .json): pixel (i, j) of the
    PNG is book cell (i, j), its value the province (0: none)."""
    books = map_memory.MEM_DIR
    books.mkdir(parents=True, exist_ok=True)
    grid = np.asarray(res["grid"])
    cv2.imwrite(str(books / f"{map_id}_provinces.png"), grid.astype(np.uint8))
    ids, counts = np.unique(grid[grid > 0], return_counts=True)
    (books / f"{map_id}_provinces.json").write_text(json.dumps({
        "map_id": map_id, "cell": CELL, "provinces": int(grid.max()),
        "cells": {str(int(i)): int(c) for i, c in zip(ids, counts)},
        "homography": res["H"], "how": res.get("how"), "fit_px": res.get("fit_px"),
        "crops": res.get("crops"), "made": time.strftime("%Y-%m-%d %H:%M")},
        indent=1), encoding="utf-8")


def agreement(a, b) -> float:
    """Share of cells two province grids put together: each province read
    as the other grid's province it overlaps most (their numbers need not
    match), both ways, the lower -- one grid splitting what the other joins
    counts against either. 1.0 is the same split."""
    a, b = np.asarray(a), np.asarray(b)
    if a.shape != b.shape or not a.size:
        return 0.0

    def one_way(x, y):
        same = 0
        for k in np.unique(x):
            same += int(np.bincount(y[x == k].astype(np.int64)).max())
        return same / float(x.size)
    return min(one_way(a, b), one_way(b, a))
