"""Was the pan survey measured at the zoom the farm actually scans at?

The survey (tools/dev/pan_survey.py) refuses to measure unless the HUD gauge
says icon zoom, and gets there through the farm's own step 1. But the gauge
only tells icon from close -- it cannot rule out a notch of difference, and
the scroll routine overshoots now and then.

So this checks the model against the farm's own scans, from its log alone:

  camera at the scan frame   "map step: ... -> X,Y"         (every scan)
  where the icon was          "[n] Clicking icon ... at (fx, fy)"
  where the deposit really is "Marched to deposit <map> X:Y" (read after the
                              click has centred the camera on it)

The model predicts the deposit from the first two. If the survey was taken
at the scan zoom, the prediction lands on the deposit to within a tile or
two; a notch of zoom off would show as a consistent scale error.

Needs the every-scan position reads that started 2026-09-23 13:46.

    .venv\\Scripts\\python tools\\dev\\zoom_check.py [farm_run.log] [since]
"""

from __future__ import annotations

import re
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rok_farm import pan_model  # noqa: E402

LOG = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "logs" / "overnight" / "farm_run.log"
SINCE = sys.argv[2] if len(sys.argv) > 2 else "2026-09-23 13:46:00"
FRAME_W, FRAME_H = 1534, 863

TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)")
STEP = re.compile(r"map step: \d+ tiles \(\d+,\d+ -> (\d+),(\d+)\)")
SCAN = re.compile(r"Scan +(\d+)/\d+:")
CLICK = re.compile(r"\[(\d+)\] Clicking icon conf=[\d.]+ at \((\d+), (\d+)\)")
DEPOSIT = re.compile(r"Marched to deposit \S+ (\d+):(\d+)")
SPOIL = re.compile(r"no-click zone, dragging map|edge gem\(s\)|recentering")
MINE_START = re.compile(r"Step 2: Scan \+ verify")


def pairs(lines):
    """(camera, icon px, deposit) for clicks made on a frame whose position
    was read, with nothing else moving the camera in between."""
    out = []
    cam = None            # position read for the current scan frame
    fresh = False         # read on THIS scan, after its drags
    pending = None        # a read waiting for its scan line
    click = None
    for line in lines:
        if MINE_START.search(line):
            cam, fresh, pending, click = None, False, None, None
            continue
        m = STEP.search(line)
        if m:
            # _map_sync logs the read BEFORE the scan prints its line, so a
            # read belongs to the scan line that follows it.
            pending = (int(m.group(1)), int(m.group(2)))
            continue
        if SCAN.search(line):
            # Before 13:46 the read was every fourth scan: a scan without
            # its own read must not borrow an older one, the drags since
            # have moved the camera.
            cam, fresh, pending = pending, pending is not None, None
            continue
        if SPOIL.search(line):
            fresh = False
            continue
        m = CLICK.search(line)
        if m:
            click = (cam, (int(m.group(2)), int(m.group(3)))) if (cam and fresh) else None
            # The click itself zooms onto the mine: nothing after this frame
            # can reuse the reading.
            fresh = False
            continue
        m = DEPOSIT.search(line)
        if m and click:
            out.append((click[0], click[1], (int(m.group(1)), int(m.group(2)))))
            click = None
    return out


def main() -> int:
    lines = []
    with LOG.open(encoding="utf-8", errors="replace") as fh:
        started = False
        for line in fh:
            t = TS.match(line)
            if t and not started:
                started = t.group(1) >= SINCE
            if started:
                lines.append(line)
    rows = pairs(lines)
    print(f"{len(rows)} clicked deposits with a same-frame position read "
          f"since {SINCE}")
    if not rows:
        print("nothing to check yet -- let the farm gather a few mines")
        return 0
    ex, ey, sx, sy = [], [], [], []
    for cam, (fx, fy), dep in rows:
        ox, oy = fx - FRAME_W / 2.0, fy - FRAME_H / 2.0
        dx, dy = pan_model.ground_offset(ox, oy, FRAME_H)
        px, py = cam[0] + dx, cam[1] + dy
        ex.append(dep[0] - px)
        ey.append(dep[1] - py)
        # scale check: actual offset / predicted offset, where it is big
        # enough for whole-tile rounding not to dominate
        if abs(dx) >= 4:
            sx.append((dep[0] - cam[0]) / dx)
        if abs(dy) >= 4:
            sy.append((dep[1] - cam[1]) / dy)
        print(f"  camera {cam[0]:4d},{cam[1]:4d}  icon at ({fx:4d},{fy:3d})px "
              f"-> predicted {px:6.1f},{py:6.1f}  deposit {dep[0]:4d},{dep[1]:4d}"
              f"  error {dep[0] - px:+5.1f},{dep[1] - py:+5.1f}")
    print(f"\nerror X: median {st.median(ex):+.1f}, |median| "
          f"{st.median([abs(v) for v in ex]):.1f} tiles")
    print(f"error Y: median {st.median(ey):+.1f}, |median| "
          f"{st.median([abs(v) for v in ey]):.1f} tiles")
    if sx:
        print(f"actual/predicted X offset: median {st.median(sx):.2f} (n={len(sx)})")
    if sy:
        print(f"actual/predicted Y offset: median {st.median(sy):.2f} (n={len(sy)})")
    print("(a notch of zoom would put both ratios well away from 1.0)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
