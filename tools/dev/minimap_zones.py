"""Turn the minimap into zones: calibrate it to tiles, find its province lines.

Input: folders written by tools/dev/minimap_survey.py or map_edge_probe.py --
the frame's top-right quarter per HUD read (read_NNN.png) and the reads
(survey.json "reads" / probe.json "frames"). The minimap sits in that
quarter at readable zooms and draws the kingdom the camera stands in, its
province lines, and the view as a white outline.

  1. The outline in each crop against the HUD read of the same frame: a fit
     from tiles to minimap pixels, affine and projective, with residuals --
     the numbers say which the minimap is.
  2. The median of the crops on the map: the outline and anything else that
     moves with the camera drop out.
  3. Light, unsaturated pixels on the dark land are the province lines; the
     land between them, in pieces, the provinces.

Writes screenshots/minimap_zones/<map>_minimap.png (the provinces on the
minimap) and <map>_provinces.png (on the map, north up, a line every 100
tiles) to look at, and prints the fits. With --save, the province of every
book cell goes to data/map_knowledge/<map>_provinces.png (+ .json).

    .venv\\Scripts\\python tools\\dev\\minimap_zones.py screenshots\\minimap_survey\\<stamp> [more folders]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "screenshots" / "minimap_zones"


def load(folders):
    """[(crop, (map id, x, y))] for every read that parsed."""
    out = []
    for folder in folders:
        folder = Path(folder)
        meta = None
        for name in ("survey.json", "probe.json"):
            if (folder / name).exists():
                meta = json.loads((folder / name).read_text(encoding="utf-8"))
                break
        if meta is None:
            continue
        for name, hud in meta.get("reads") or meta.get("frames") or []:
            if not hud:
                continue
            crop = cv2.imread(str(folder / name))
            if crop is not None:
                out.append((crop, tuple(hud)))
    return out


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
    (cx, cy, w, h) in crop pixels."""
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


def fit(points):
    """Affine and projective fits tile -> pixel, with the residuals."""
    src = np.float32([[p[0], p[1]] for p in points])
    dst = np.float32([[p[2], p[3]] for p in points])
    res = {}
    A, _ = cv2.estimateAffine2D(src, dst, method=cv2.LMEDS)
    if A is not None:
        pred = src @ A[:, :2].T + A[:, 2]
        err = np.hypot(*(pred - dst).T)
        res["affine"] = (A, float(np.median(err)), float(err.max()))
    if len(points) >= 4:
        H, _ = cv2.findHomography(src, dst, cv2.LMEDS)
        if H is not None:
            pred = cv2.perspectiveTransform(src[None], H)[0]
            err = np.hypot(*(pred - dst).T)
            res["projective"] = (H, float(np.median(err)), float(err.max()))
    return res


# Province lines: white top-hat (5 px) of the minimap on its land, at least
# this. Measured on the median of 411 icon-zoom farm frames (2026-09-24):
# the land between lines gave 0-2 (9,169 px, 85.5%), the lines a flat tail
# from 3 to 39+ (1,554 px) -- the break is between 2 and 3.
LINE_TOPHAT_MIN = 3
# A piece of land smaller than this is a scrap between lines, not a province.
MIN_PROVINCE_PX = 60


def segment(median):
    """(labels, lines, inside) for a median minimap crop: 0 = not a province."""
    hsv = cv2.cvtColor(median, cv2.COLOR_BGR2HSV)
    s, v = hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    dark = (v < 75).astype(np.uint8)
    n, lab, st, _c = cv2.connectedComponentsWithStats(dark, 8)
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
    return labels, lines, inside


def tile_grid(labels, H, cell=8, size=1200):
    """Province of every book cell: its centre through H into the minimap,
    the nearest province pixel there (lines and scraps have none)."""
    has = labels > 0
    dist, idx = cv2.distanceTransformWithLabels((~has).astype(np.uint8), cv2.DIST_L2, 3,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    ys, xs = np.nonzero(has)
    lut = np.zeros(idx.max() + 1, np.int32)
    lut[idx[ys, xs]] = labels[ys, xs]
    n = size // cell
    centres = np.float32([[(i + 0.5) * cell, (j + 0.5) * cell]
                          for j in range(n) for i in range(n)])
    px = cv2.perspectiveTransform(centres[None], H)[0]
    grid = np.zeros((n, n), np.int32)
    h, w = labels.shape
    for (cx, cy), (i, j) in zip(px, [(i, j) for j in range(n) for i in range(n)]):
        x, y = int(round(cx)), int(round(cy))
        if 0 <= x < w and 0 <= y < h:
            grid[j, i] = lut[idx[y, x]]
    return grid


def draw_grid(grid, city=None, cell=8, scale=2):
    """The province grid in tile space, north up, for a person to check."""
    n = grid.shape[0]
    rng = np.random.default_rng(11)
    pal = {k: rng.integers(70, 240, 3).tolist() for k in np.unique(grid)}
    pal[0] = [30, 30, 30]
    img = np.zeros((n * scale * 2, n * scale * 2, 3), np.uint8)
    s = scale * 2
    for j in range(n):
        for i in range(n):
            y = (n - 1 - j) * s                      # +Y is up
            img[y:y + s, i * s:(i + 1) * s] = pal[int(grid[j, i])]
    for t in range(0, n * cell + 1, 100):
        p = t // cell * s
        cv2.line(img, (p, 0), (p, img.shape[0]), (0, 0, 0), 1)
        cv2.line(img, (0, img.shape[0] - p), (img.shape[1], img.shape[0] - p), (0, 0, 0), 1)
    if city:
        cx, cy = city[0] // cell * s, img.shape[0] - city[1] // cell * s
        cv2.drawMarker(img, (cx, cy), (0, 255, 0), cv2.MARKER_STAR, 14, 2)
    return img


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--save", action="store_true",
                    help="write data/map_knowledge/<map>_provinces.png/.json")
    args = ap.parse_args()
    reads = load(args.folders)
    if not reads:
        print("no reads with a crop")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    by_map: dict = {}
    for crop, hud in reads:
        by_map.setdefault(hud[0], []).append((crop, hud))
    for map_id, items in sorted(by_map.items(), key=lambda kv: -len(kv[1])):
        pts, sizes = [], []
        for crop, (_m, x, y) in items:
            o = outline(crop)
            if o is not None:
                pts.append((x, y, o[0], o[1]))
                sizes.append(o[2:])
        print(f"map {map_id}: {len(items)} read(s), outline found in {len(pts)}"
              + (f", outline {np.median([s[0] for s in sizes]):.0f}x"
                 f"{np.median([s[1] for s in sizes]):.0f} px" if sizes else ""))
        # One zoom only: the outline's size is the zoom, and where the camera
        # point sits in the outline changes with it (reads taken on the way
        # out drew it 13x7 to 28x13).
        if sizes:
            mw, mh = np.median([s[0] for s in sizes]), np.median([s[1] for s in sizes])
            pts = [p for p, s in zip(pts, sizes) if abs(s[0] - mw) <= 2 and abs(s[1] - mh) <= 2]
            print(f"  at the survey's zoom: {len(pts)}")
        fits = fit(pts) if len(pts) >= 4 else {}
        for kind, (M, med, worst) in fits.items():
            print(f"  {kind}: median error {med:.2f} px, worst {worst:.2f} px")
            print("   ", np.array2string(np.asarray(M), precision=5, suppress_small=True).replace("\n", "\n    "))
        stack = np.stack([c for c, _h in items])
        median = np.median(stack, axis=0).astype(np.uint8)
        labels, lines, _inside = segment(median)
        print(f"  provinces on the minimap: {labels.max()}")
        vis = median.copy()
        rng = np.random.default_rng(7)
        for k in range(1, labels.max() + 1):
            c = rng.integers(60, 255, 3)
            vis[labels == k] = (0.4 * vis[labels == k] + 0.6 * c).astype(np.uint8)
        vis[lines > 0] = (255, 255, 255)
        vis = cv2.resize(vis, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
        for x, y, px, py in pts:
            cv2.circle(vis, (int(4 * px), int(4 * py)), 3, (0, 0, 255), -1)
        cv2.imwrite(str(OUT / f"{map_id}_minimap.png"), vis)
        if "projective" in fits:
            H = fits["projective"][0]
            grid = tile_grid(labels, H)
            city = (577, 615) if map_id == "4096" else None
            cv2.imwrite(str(OUT / f"{map_id}_provinces.png"), draw_grid(grid, city))
            ids, counts = np.unique(grid[grid > 0], return_counts=True)
            print("  book cells per province: " + ", ".join(
                f"#{i} {c}" for i, c in sorted(zip(ids, counts), key=lambda t: -t[1])))
            if city:
                print(f"  the city {city} is in province #{grid[city[1] // 8, city[0] // 8]}")
            if args.save:
                books = ROOT / "data" / "map_knowledge"
                books.mkdir(parents=True, exist_ok=True)
                # Row j of the PNG is book cell row j (Y = 8j..8j+7), pixel
                # value the province (0: none); 150x150 for a 1200 map.
                cv2.imwrite(str(books / f"{map_id}_provinces.png"), grid.astype(np.uint8))
                (books / f"{map_id}_provinces.json").write_text(json.dumps({
                    "map_id": map_id, "cell": 8, "provinces": int(grid.max()),
                    "cells": {str(int(i)): int(c) for i, c in zip(ids, counts)},
                    "homography": np.asarray(H).tolist(),
                    "fit_median_px": fits["projective"][1],
                    "sources": [str(Path(f)) for f in args.folders],
                    "made": time.strftime("%Y-%m-%d %H:%M")}, indent=1), encoding="utf-8")
                print(f"  saved {books / f'{map_id}_provinces.png'} (+ .json)")
        print(f"  -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
