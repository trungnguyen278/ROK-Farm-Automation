"""Turn the minimap into zones: calibrate it to tiles, find its province lines.

Input: folders written by tools/dev/minimap_survey.py or map_edge_probe.py --
the frame's top-right quarter per HUD read (read_NNN.png) and the reads
(survey.json "reads" / probe.json "frames"). The minimap sits in that
quarter at readable zooms and draws the kingdom the camera stands in, its
province lines, and the view as a white outline.

The work is rok_farm.minimap's, the same the farm runs on a new KvK map:
  1. The outline in each crop against the HUD read of the same frame --
     the home calibration scaled to the map's size where it fits, a
     projective fit of the map's own where it does not.
  2. The median of the crops on the map: the outline and anything else that
     moves with the camera drop out.
  3. Light, unsaturated pixels on the dark land are the province lines; the
     land between them, in pieces, the provinces.

Writes screenshots/minimap_zones/<map>_minimap.png (the provinces on the
minimap) and <map>_provinces.png (on the map, north up, a line every 100
tiles) to look at, and prints the fits. With --save, the province of every
book cell goes to data/map_knowledge/<map>_provinces.png (+ .json).

    .venv\\Scripts\\python tools\\dev\\minimap_zones.py <folder> [more folders]
        [--size 1200] [--city 577,615] [--save]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rok_farm import minimap  # noqa: E402
from rok_farm.map_memory import HOME_TILES, is_home_map  # noqa: E402

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


def draw_grid(grid, city=None, cell=8, scale=2):
    """The province grid in tile space, north up, for a person to check."""
    n = grid.shape[0]
    rng = np.random.default_rng(11)
    pal = {k: rng.integers(70, 240, 3).tolist() for k in np.unique(grid)}
    pal[0] = [30, 30, 30]
    s = scale * 2
    img = np.zeros((n * s, n * s, 3), np.uint8)
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
    ap.add_argument("--size", type=int, default=None,
                    help="the map's size (default 1200 for a home kingdom)")
    ap.add_argument("--city", default=None,
                    help="x,y on the map with the most reads -- must fall in a province")
    ap.add_argument("--save", action="store_true",
                    help="write data/map_knowledge/<map>_provinces.png/.json")
    args = ap.parse_args()
    reads = load(args.folders)
    if not reads:
        print("no reads with a crop")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    counts: dict = {}
    for _crop, hud in reads:
        counts[hud[0]] = counts.get(hud[0], 0) + 1
    order = sorted(counts, key=lambda m: -counts[m])
    for map_id in order:
        size = args.size or (HOME_TILES if is_home_map(map_id) else None)
        city = (tuple(int(v) for v in args.city.split(","))
                if args.city and map_id == order[0] else None)
        items = [(c, h) for c, h in reads if h[0] == map_id]
        pts = minimap.outline_points(items, map_id)
        print(f"map {map_id}: {len(items)} read(s), {len(pts)} outline(s) at one zoom")
        if size is None:
            print("  size unknown -- pass --size")
            continue
        if len(pts) >= 4:
            H = minimap.fit_h(pts)
            if H is not None:
                print(f"  its own projective fit: median {minimap.residual(H, pts):.2f} px")
            print(f"  home calibration scaled to {size}: median "
                  f"{minimap.residual(minimap.scaled_prior(size), pts):.2f} px")
        res = minimap.build(items, map_id, size, city)
        if "error" in res:
            print(f"  no provinces: {res['error']}")
            continue
        grid = res["grid"]
        print(f"  {res['provinces']} provinces from {res['crops']} crops, {res['how']} "
              f"({res['fit_px']:.2f} px)")
        median = np.median(np.stack([c for c, _h in items]), axis=0).astype(np.uint8)
        labels, lines = minimap.segment(median)
        vis = median.copy()
        rng = np.random.default_rng(7)
        for k in range(1, labels.max() + 1):
            c = rng.integers(60, 255, 3)
            vis[labels == k] = (0.4 * vis[labels == k] + 0.6 * c).astype(np.uint8)
        vis[lines > 0] = (255, 255, 255)
        vis = cv2.resize(vis, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
        for _x, _y, px, py in pts:
            cv2.circle(vis, (int(4 * px), int(4 * py)), 3, (0, 0, 255), -1)
        cv2.imwrite(str(OUT / f"{map_id}_minimap.png"), vis)
        cv2.imwrite(str(OUT / f"{map_id}_provinces.png"), draw_grid(grid, city))
        ids, cells = np.unique(grid[grid > 0], return_counts=True)
        print("  book cells per province: " + ", ".join(
            f"#{i} {c}" for i, c in sorted(zip(ids, cells), key=lambda t: -t[1])))
        if city:
            print(f"  the city {city} is in province #{grid[city[1] // 8, city[0] // 8]}")
        if args.save:
            minimap.save(res, map_id)
            print(f"  saved data/map_knowledge/{map_id}_provinces.png (+ .json)")
        print(f"  -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
