"""How soon do gems come back to ground already looked at?

SWEEP_STALE_H (rok_farm/flow_steps.py) says how long ground seen once is
not worth sweeping again -- 6 hours as a starting value, 2 since this tool
measured one night on 2026-09-24. It measures it from the farm log's "view: cam X,Y gems ..." lines (one per scan at icon zoom,
since 2026-09-24 01:30): every book cell on screen in a view, whether a gem
stood in it, and when. For each cell seen twice, the pair of visits says
whether a gem appeared, stayed or went in between.

Reported per revisit interval:
  appeared  -- gem now, none at the last visit (new ground worth sweeping)
  went      -- none now, a gem at the last visit (taken, by us or anyone)

Only cells well inside the frame count (VIEW_MARGIN), the same footprint
the book records, so a gem half off the edge is not read as one that went.
And a gem is matched by its tile, not its cell: a position read a tile or
two off moves a gem near a cell's edge into the next cell, which would count
as one gem going and another appearing. A gem counts as new only if the
last visit saw none within NEAR_TILES of it, and as gone only if this visit
sees none within NEAR_TILES of where it stood.

Usage:
    .venv\\Scripts\\python tools\\dev\\gem_return.py
    .venv\\Scripts\\python tools\\dev\\gem_return.py --since "2026-09-24 01:30"
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rok_farm import pan_model  # noqa: E402
from rok_farm.map_memory import CELL  # noqa: E402

LOG = ROOT / "logs" / "overnight" / "farm_run.log"
WIN_W, WIN_H = 1534, 863
VIEW_MARGIN = 0.08          # flow_steps.GemFlowMixin.VIEW_MARGIN
MIN_GAP_S = 120             # consecutive scans overlap: not a revisit
NEAR_TILES = 3              # the same deposit, read a little off
BUCKETS = [(2, 10), (10, 30), (30, 60), (60, 120), (120, 240),
           (240, 480), (480, 10 ** 6)]          # minutes

VIEW = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ .*view: cam "
                  r"(\d+),(\d+) gems (\S+)")


def view_cells(cam):
    """Book cells whose centre is on screen -- flow_steps._view_cells."""
    corners = pan_model.view_corners(cam, WIN_W, WIN_H)
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    out = set()
    for i in range(int(min(xs)) // CELL, int(max(xs)) // CELL + 1):
        for j in range(int(min(ys)) // CELL, int(max(ys)) // CELL + 1):
            centre = (i * CELL + CELL // 2, j * CELL + CELL // 2)
            if pan_model.in_view(cam, centre, WIN_W, WIN_H,
                                 margin=VIEW_MARGIN):
                out.add((i, j))
    return out


def parse(path: str, since: str):
    for line in open(path, encoding="utf-8", errors="replace"):
        m = VIEW.match(line)
        if not m or m.group(1) < since:
            continue
        t = time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
        cam = (int(m.group(2)), int(m.group(3)))
        gems = []
        if m.group(4) != "-":
            for pair in m.group(4).split(";"):
                gx, gy = pair.split(",")
                gems.append((int(gx), int(gy)))
        yield t, cam, gems


def _near(tile, tiles) -> bool:
    return any(max(abs(tile[0] - g[0]), abs(tile[1] - g[1])) <= NEAR_TILES
               for g in tiles)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-24 01:30")
    ap.add_argument("--log", default=str(LOG))
    args = ap.parse_args()

    # Per cell, its visits: [start, end, gem tiles in the cell, every gem
    # tile on screen during the visit]. Views of a cell less than MIN_GAP_S
    # apart are one visit -- consecutive scans overlap.
    visits: dict[tuple[int, int], list[list]] = {}
    views = 0
    for t, cam, gems in parse(args.log, args.since):
        views += 1
        cells = view_cells(cam) | {(x // CELL, y // CELL) for x, y in gems}
        for cell in cells:
            mine = [g for g in gems if (g[0] // CELL, g[1] // CELL) == cell]
            vs = visits.setdefault(cell, [])
            if vs and t - vs[-1][1] < MIN_GAP_S:
                vs[-1][1] = t
                vs[-1][2].extend(mine)
                vs[-1][3].extend(gems)
            else:
                vs.append([t, t, list(mine), list(gems)])

    rows = {b: {"pairs": 0, "was_empty": 0, "appeared": 0,
                "had_gem": 0, "went": 0} for b in BUCKETS}
    for vs in visits.values():
        for a, b_ in zip(vs, vs[1:]):
            mins = (b_[0] - a[1]) / 60.0
            for b in BUCKETS:
                if b[0] <= mins < b[1]:
                    r = rows[b]
                    r["pairs"] += 1
                    if a[2]:
                        r["had_gem"] += 1
                        r["went"] += not any(_near(g, b_[3]) for g in a[2])
                    else:
                        r["was_empty"] += 1
                        r["appeared"] += any(not _near(g, a[3]) for g in b_[2])
                    break

    print(f"{views} view(s) since {args.since}, {len(visits)} cell(s) seen")
    # The yardstick: how often a cell shows a gem the first time it is seen
    # in the window. A revisit that finds gems about as often is as good as
    # new ground.
    first = [bool(vs[0][2]) for vs in visits.values()]
    if first:
        print(f"first visit: {sum(first)}/{len(first)} cells had a gem "
              f"({100.0 * sum(first) / len(first):.1f}%)")
    print("revisit after    pairs   appeared/empty        went/had gem")
    for b in BUCKETS:
        r = rows[b]
        hi = "+" if b[1] >= 10 ** 6 else f"-{b[1]}"
        app = (f"{r['appeared']:4d}/{r['was_empty']:<5d} "
               f"{100.0 * r['appeared'] / r['was_empty']:5.1f}%"
               if r["was_empty"] else "      -            ")
        went = (f"{r['went']:4d}/{r['had_gem']:<4d} "
                f"{100.0 * r['went'] / r['had_gem']:5.1f}%"
                if r["had_gem"] else "   -")
        print(f"  {b[0]:4d}{hi:<7s} min {r['pairs']:6d}   {app}   {went}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
