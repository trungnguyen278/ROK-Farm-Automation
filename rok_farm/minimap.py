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
OUTLINE_SIZE = (24, 12)
OUTLINE_SIZE_TOL = 2
# The home calibration, scaled to a map's size, is taken when it places the
# map's own outlines this well (median). Right, it sits near the fit's 0.2;
# wrong by one map size (1440 read as 1200), it misses by ~17 px at X 1000.
PRIOR_OK_PX = 1.0
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


def outline(crop):
    """The view outline: the largest thin near-white blob within reach of
    the minimap's kingdom -- the crop also holds white UI text ("4/5").
    (cx, cy, w, h) in crop pixels, or None."""
    box = land_box(crop)
    if box is None:
        return None
    bx, by, bw, bh = box
    m = 15
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = ((hsv[..., 1] < 35) & (hsv[..., 2] > 225)).astype(np.uint8)
    keep = np.zeros_like(white)
    keep[max(0, by - m):by + bh + m, max(0, bx - m):bx + bw + m] = 1
    white &= keep
    n, _lab, stats, cent = cv2.connectedComponentsWithStats(white, 8)
    best = None
    for k in range(1, n):
        x, y, w, h, a = stats[k]
        if 12 <= w <= 60 and 4 <= h <= 25 and a >= 20 and a / float(w * h) < 0.6:
            if best is None or a > best[4]:
                best = (x, y, w, h, a, cent[k])
    if best is None:
        return None
    x, y, w, h, _a, c = best
    return float(c[0]), float(c[1]), int(w), int(h)


def outline_points(items, map_id, size_px=None):
    """[(x, y, px, py)]: the outline beside each read on `map_id`, at one
    zoom -- `size_px`, or the median outline size of these crops. Where the
    camera point sits inside the outline changes with the zoom."""
    found = []
    for crop, hud in items:
        if not hud or hud[0] != map_id:
            continue
        o = outline(crop)
        if o is not None:
            found.append((hud[1], hud[2], o[0], o[1], o[2], o[3]))
    if not found:
        return []
    if size_px is None:
        size_px = (np.median([f[4] for f in found]), np.median([f[5] for f in found]))
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


def calibrate(items, map_id, size):
    """(H, how, median px) placing this map's tiles on the minimap, or
    (None, why, None)."""
    at_home_zoom = outline_points(items, map_id, OUTLINE_SIZE)
    if len(at_home_zoom) >= 4:
        err = residual(scaled_prior(size), at_home_zoom)
        if err <= PRIOR_OK_PX:
            return scaled_prior(size), f"home calibration scaled to {size}", err
    pts = outline_points(items, map_id)
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


def segment(median):
    """(labels, lines) for a median minimap crop; label 0 is not a province."""
    hsv = cv2.cvtColor(median, cv2.COLOR_BGR2HSV)
    s, v = hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    dark = (v < 75).astype(np.uint8)
    n, lab, st, _c = cv2.connectedComponentsWithStats(dark, 8)
    if n < 2:
        return np.zeros(median.shape[:2], np.int32), np.zeros(median.shape[:2], np.uint8)
    k = 1 + int(np.argmax(st[1:, 4]))
    land = (lab == k).astype(np.uint8)
    ff = np.pad(1 - land, 1, constant_values=1).astype(np.uint8)
    m = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, m, (0, 0), 2)
    inside = cv2.erode((ff[1:-1, 1:-1] != 2).astype(np.uint8), np.ones((3, 3), np.uint8))
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
    median = np.median(np.stack([c for c, _h in on_map]), axis=0).astype(np.uint8)
    labels, _lines = segment(median)
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
