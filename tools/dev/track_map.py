"""Draw what the map book knows: where the camera went and what it saw.

The operator asked for the trajectory to be drawn so its correctness can be
checked by eye (2026-09-23). Drawn the way the game shows the map: X grows
to the right, Y grows UP.

  grey      book cells never seen
  green     seen within the sweep's stale window (6h) -- fades to yellow
  orange    seen longer ago
  black     walls (mountain, map void)
  blue dot  a gem seen in that cell
  line      the camera's track, light (old) to dark (new), one dot per read
  red x     deposits marched to (from the farm log)
  star      the city; the square is the sweep's 150-tile radius

    .venv\\Scripts\\python tools\\dev\\track_map.py [--since "2026-09-23 14:45"] [--out file.png]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BOOK = ROOT / "data" / "map_knowledge" / "4096.json"
LOG = ROOT / "logs" / "overnight" / "farm_run.log"
CELL = 8
PX = 4                       # pixels per tile in the picture
STALE_H = 6.0
MARCH = re.compile(r"^(\S+ \S+),\d+ .*Marched to deposit (\S+) (\d+):(\d+)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=datetime.now().strftime("%Y-%m-%d 00:00"))
    ap.add_argument("--book", default=str(BOOK))
    ap.add_argument("--out", default=str(ROOT / "screenshots" / "track_map.png"))
    ap.add_argument("--radius", type=int, default=200,
                    help="tiles shown around the city")
    args = ap.parse_args()

    book = json.loads(Path(args.book).read_text(encoding="utf-8"))
    since = datetime.strptime(args.since, "%Y-%m-%d %H:%M").timestamp()
    city = tuple(book.get("city") or (577, 615))
    track = [p for p in book.get("track", []) if p[0] >= since]
    now = time.time()

    x0, y0 = city[0] - args.radius, city[1] - args.radius
    size = 2 * args.radius * PX
    img = np.full((size, size, 3), 235, np.uint8)

    def to_px(x, y):
        # Y grows up the screen in the game, so it grows up the picture.
        return (int((x - x0) * PX), int(size - (y - y0) * PX))

    # cells
    for k, c in book.get("reach", {}).items():
        i, j = (int(v) for v in k.split(","))
        age_h = (now - c.get("t", 0)) / 3600.0
        if age_h < STALE_H:
            f = age_h / STALE_H
            colour = (int(90 + 60 * f), int(200 - 10 * f), int(90 + 140 * f))
        else:
            colour = (80, 170, 245)
        p1 = to_px(i * CELL, j * CELL + CELL)
        p2 = to_px(i * CELL + CELL, j * CELL)
        cv2.rectangle(img, p1, p2, colour, -1)
        if c.get("gem", 0):
            cx, cy = to_px(i * CELL + CELL / 2, j * CELL + CELL / 2)
            cv2.circle(img, (cx, cy), 5, (200, 90, 20), -1)
    for k, c in book.get("terrain", {}).items():
        if c.get("wall", 0) > 0:
            i, j = (int(v) for v in k.split(","))
            cv2.rectangle(img, to_px(i * CELL, j * CELL + CELL),
                          to_px(i * CELL + CELL, j * CELL), (20, 20, 20), -1)

    # grid every 50 tiles, labelled
    for t in range(0, 1200, 50):
        if x0 <= t <= x0 + 2 * args.radius:
            x, _ = to_px(t, y0)
            cv2.line(img, (x, 0), (x, size), (200, 200, 200), 1)
            cv2.putText(img, str(t), (x + 2, size - 6), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (120, 120, 120), 1)
        if y0 <= t <= y0 + 2 * args.radius:
            _, y = to_px(x0, t)
            cv2.line(img, (0, y), (size, y), (200, 200, 200), 1)
            cv2.putText(img, str(t), (4, y - 3), cv2.FONT_HERSHEY_SIMPLEX,
                        0.4, (120, 120, 120), 1)

    # sweep radius
    cv2.rectangle(img, to_px(city[0] - 150, city[1] + 150),
                  to_px(city[0] + 150, city[1] - 150), (160, 160, 160), 1)

    # track, old -> new
    n = len(track)
    for a, b in zip(track, track[1:]):
        f = (a[0] - track[0][0]) / max(1.0, track[-1][0] - track[0][0])
        shade = int(200 - 170 * f)
        # a gap longer than two minutes is a break (city trip, wait), not a pan
        if b[0] - a[0] > 120:
            continue
        cv2.line(img, to_px(a[1], a[2]), to_px(b[1], b[2]), (shade, shade, shade), 1)
    for p in track:
        cv2.circle(img, to_px(p[1], p[2]), 2, (40, 40, 40), -1)

    # marches from the log
    marches = []
    if LOG.exists():
        with LOG.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = MARCH.match(line)
                if m and m.group(1) >= args.since:
                    marches.append((int(m.group(3)), int(m.group(4))))
    for x, y in marches:
        cx, cy = to_px(x, y)
        cv2.line(img, (cx - 6, cy - 6), (cx + 6, cy + 6), (30, 30, 220), 2)
        cv2.line(img, (cx - 6, cy + 6), (cx + 6, cy - 6), (30, 30, 220), 2)

    # city
    cx, cy = to_px(*city)
    cv2.drawMarker(img, (cx, cy), (0, 0, 180), cv2.MARKER_STAR, 22, 2)

    cv2.putText(img, f"map 4096  city {city[0]}:{city[1]}  since {args.since}  "
                     f"track {n} reads  marches {len(marches)}",
                (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (40, 40, 40), 1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    print(f"{out}  ({n} track points, {len(marches)} marches, "
          f"{len(book.get('reach', {}))} cells)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
