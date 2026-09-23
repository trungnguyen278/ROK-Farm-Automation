"""How soon do gems come back to ground already looked at?

SWEEP_STALE_H (rok_farm/flow_steps.py) says ground seen within 6 hours is
not worth sweeping again. That is a starting value. This measures it from
the farm log's "view: cam X,Y gems ..." lines (one per scan at icon zoom,
since 2026-09-24 01:30): every book cell on screen in a view, whether a gem
stood in it, and when. For each cell seen twice, the pair of visits says
whether a gem appeared, stayed or went in between.

Reported per revisit interval:
  appeared  -- gem now, none at the last visit (new ground worth sweeping)
  went      -- none now, a gem at the last visit (taken, by us or anyone)

Only cells well inside the frame count (VIEW_MARGIN), the same footprint
the book records, so a gem half off the edge is not read as one that went.

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
        gems = set()
        if m.group(4) != "-":
            for pair in m.group(4).split(";"):
                gx, gy = pair.split(",")
                gems.add((int(gx) // CELL, int(gy) // CELL))
        yield t, cam, gems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2026-09-24 01:30")
    ap.add_argument("--log", default=str(LOG))
    args = ap.parse_args()

    # Per cell, its visits: [start, end, gem seen]. Views of a cell less
    # than MIN_GAP_S apart are one visit -- consecutive scans overlap.
    visits: dict[tuple[int, int], list[list]] = {}
    views = 0
    for t, cam, gems in parse(args.log, args.since):
        views += 1
        for cell in view_cells(cam) | gems:
            has = cell in gems
            vs = visits.setdefault(cell, [])
            if vs and t - vs[-1][1] < MIN_GAP_S:
                vs[-1][1] = t
                vs[-1][2] = vs[-1][2] or has
            else:
                vs.append([t, t, has])

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
                        r["went"] += not b_[2]
                    else:
                        r["was_empty"] += 1
                        r["appeared"] += b_[2]
                    break

    print(f"{views} view(s) since {args.since}, {len(visits)} cell(s) seen")
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
