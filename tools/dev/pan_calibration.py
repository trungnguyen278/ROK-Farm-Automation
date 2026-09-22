"""Fit the drag-to-tiles transform from the farm's own log.

The operator's point, 2026-09-22: the coordinates are already read, so the
relationship between a screen drag and the ground it covers is a measurement,
not an assumption. With it the wander could aim AT a cell rather than pick a
heading and hope.

It cannot be assumed because the map is isometric: the tile axes are rotated
from the screen axes by an unknown angle, and a sign error steers the exact
opposite way. So this fits it from pairs the farm now logs --

    map step: 39 tiles (844,465 -> 805,478) after -1200,+300 px

-- solving for the 2x2 matrix M in  (dx_tiles, dy_tiles) = M . (dx_px, dy_px).

Run it after a day's farming. Until it reports a decent fit on a few hundred
pairs, nothing should be built on the numbers.
"""
import re
import sys
from pathlib import Path

import numpy as np

LOG = Path(sys.argv[1] if len(sys.argv) > 1
           else r"D:\ROK Farm Automation\logs\overnight\farm_run.log")
STEP = re.compile(
    r"map step: \d+ tiles \((\d+),(\d+) -> (\d+),(\d+)\) after ([+-]\d+),([+-]\d+) px")

rows = []
with LOG.open(encoding="utf-8", errors="replace") as fh:
    for line in fh:
        m = STEP.search(line)
        if not m:
            continue
        x0, y0, x1, y1, px, py = (int(g) for g in m.groups())
        if px == 0 and py == 0:
            continue
        rows.append((px, py, x1 - x0, y1 - y0))

print("drag/tile pairs: %d" % len(rows))
if len(rows) < 30:
    print("too few to fit -- let it farm for a day with the pan logging on")
    raise SystemExit

a = np.array([[r[0], r[1]] for r in rows], float)
b = np.array([[r[2], r[3]] for r in rows], float)
M, *_ = np.linalg.lstsq(a, b, rcond=None)
pred = a @ M
resid = np.hypot(*(pred - b).T)
scale = np.hypot(*b.T)
print("")
print("tiles = pixels . M, with M =")
print("   [%8.5f %8.5f]" % (M[0, 0], M[0, 1]))
print("   [%8.5f %8.5f]" % (M[1, 0], M[1, 1]))
print("")
print("residual: median %.1f tiles, p90 %.1f, against moves of median %.1f"
      % (np.median(resid), np.percentile(resid, 90), np.median(scale)))
good = (resid < 0.25 * np.maximum(scale, 1)).mean()
print("within 25%% of the move: %.0f%% of pairs" % (100 * good))
print("")
print("A drag of 100px right and 0px down moves %+.1f,%+.1f tiles."
      % tuple(np.array([100.0, 0.0]) @ M))
