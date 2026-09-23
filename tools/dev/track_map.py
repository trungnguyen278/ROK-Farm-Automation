"""Draw what the map book knows: where the scan has NOT been, and where it
has been over and over.

The operator, 2026-09-23: "phai ve duoc ra thi moi biet cho nao chua den va
cho nao bi lap" -- it has to be drawn to see which ground was never reached
and which was covered again and again. Two panels, same frame, drawn the way
the game shows the map (X to the right, Y UP):

  left   NOT REACHED: book cells inside the sweep radius that no scan has
         shown in the stale window are red; seen cells green. The camera
         track, the city (star) and the deposits marched to (x) on top.
  right  REPEATS: how many times each cell has been in view -- one colour
         per band (1, 2-3, 4-6, 7-10, 11+). The count is the book's own:
         every scan adds one to every cell its view showed.

    .venv\\Scripts\\python tools\\dev\\track_map.py [--since "2026-09-23 14:45"] [--out file.png]
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BOOK = ROOT / "data" / "map_knowledge" / "4096.json"
LOG = ROOT / "logs" / "overnight" / "farm_run.log"
CELL = 8
PX = 3                       # pixels per tile
STALE_H = 6.0
SWEEP_RADIUS = 150
# Longer than any scan step (7-20 tiles) or node-click recentre: a trip
# through the city. Drawn dotted, not as a pan.
JUMP_TILES = 40
MARCH = re.compile(r"^(\S+ \S+),\d+ .*Marched to deposit (\S+) (\d+):(\d+)")

# BGR
NOT_REACHED = (120, 120, 245)
SEEN = (120, 205, 120)
BANDS = [(1, 1, (190, 235, 190)), (2, 3, (90, 200, 90)), (4, 6, (60, 215, 235)),
         (7, 10, (40, 140, 245)), (11, 10 ** 6, (40, 40, 220))]
BG = (238, 238, 238)


def views(c) -> int:
    return int(c.get("empty", 0)) + int(c.get("gem", 0))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=datetime.now().strftime("%Y-%m-%d 00:00"))
    ap.add_argument("--book", default=str(BOOK))
    ap.add_argument("--out", default=str(ROOT / "screenshots" / "track_map.png"))
    ap.add_argument("--at", default=None,
                    help="judge 'seen lately' at this time (default: the last "
                         "track point)")
    ap.add_argument("--radius", type=int, default=200,
                    help="tiles shown around the city")
    args = ap.parse_args()

    book = json.loads(Path(args.book).read_text(encoding="utf-8"))
    since = datetime.strptime(args.since, "%Y-%m-%d %H:%M").timestamp()
    city = tuple(book.get("city") or (577, 615))
    track = [p for p in book.get("track", []) if p[0] >= since]
    reach = book.get("reach", {})
    # "Seen lately" is judged at the end of the data, not at the moment the
    # picture is drawn -- drawn at 22:22, the 16:21 cells had aged past the
    # window and the same run looked 38 cells worse than at 18:25.
    now = (datetime.strptime(args.at, "%Y-%m-%d %H:%M").timestamp()
           if args.at else (track[-1][0] if track else time.time()))
    size = 2 * args.radius * PX
    x0, y0 = city[0] - args.radius, city[1] - args.radius

    def to_px(x, y):
        return (int((x - x0) * PX), int(size - (y - y0) * PX))

    def cell_rect(img, i, j, colour):
        cv2.rectangle(img, to_px(i * CELL, j * CELL + CELL),
                      to_px(i * CELL + CELL, j * CELL), colour, -1)

    def fresh(c):
        return c and now - c.get("t", 0) < STALE_H * 3600

    marches = []
    if LOG.exists():
        with LOG.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = MARCH.match(line)
                if m and m.group(1) >= args.since:
                    marches.append((int(m.group(3)), int(m.group(4))))

    def overlay(img):
        for t in range(0, 1200, 50):
            if x0 <= t <= x0 + 2 * args.radius:
                x, _ = to_px(t, y0)
                cv2.line(img, (x, 0), (x, size), (205, 205, 205), 1)
                cv2.putText(img, str(t), (x + 2, size - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (110, 110, 110), 1)
            if y0 <= t <= y0 + 2 * args.radius:
                _, y = to_px(x0, t)
                cv2.line(img, (0, y), (size, y), (205, 205, 205), 1)
                cv2.putText(img, str(t), (3, y - 3),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (110, 110, 110), 1)
        cv2.rectangle(img, to_px(city[0] - SWEEP_RADIUS, city[1] + SWEEP_RADIUS),
                      to_px(city[0] + SWEEP_RADIUS, city[1] - SWEEP_RADIUS),
                      (90, 90, 90), 1)
        for a, b in zip(track, track[1:]):
            if b[0] - a[0] > 120:        # a longer gap is a break, not a pan
                continue
            step = max(abs(b[1] - a[1]), abs(b[2] - a[2]))
            if step > JUMP_TILES:
                # Not a swipe: a scan step covers 7-20 tiles. Anything this
                # long is the map reopening on the city after a trip there
                # (or a node click centring far off), and drawing it as a
                # line made it look like one enormous pan. Dotted, faint.
                p, q = to_px(a[1], a[2]), to_px(b[1], b[2])
                n = max(2, int(np.hypot(q[0] - p[0], q[1] - p[1]) // 8))
                for k in range(0, n, 2):
                    u = k / n
                    cv2.circle(img, (int(p[0] + (q[0] - p[0]) * u),
                                     int(p[1] + (q[1] - p[1]) * u)), 1,
                               (170, 170, 170), -1)
                continue
            cv2.line(img, to_px(a[1], a[2]), to_px(b[1], b[2]), (60, 60, 60), 1)
        for x, y in marches:
            cx, cy = to_px(x, y)
            cv2.line(img, (cx - 5, cy - 5), (cx + 5, cy + 5), (20, 20, 200), 2)
            cv2.line(img, (cx - 5, cy + 5), (cx + 5, cy - 5), (20, 20, 200), 2)
        cv2.drawMarker(img, to_px(*city), (0, 0, 160), cv2.MARKER_STAR, 20, 2)

    # --- left: not reached ---------------------------------------------------
    left = np.full((size, size, 3), BG, np.uint8)
    cx, cy = city[0] // CELL, city[1] // CELL
    r = SWEEP_RADIUS // CELL
    gaps = seen_n = 0
    for i in range(cx - r, cx + r + 1):
        for j in range(cy - r, cy + r + 1):
            if i < 0 or j < 0 or i * CELL >= 1200 or j * CELL >= 1200:
                continue
            if fresh(reach.get(f"{i},{j}")):
                cell_rect(left, i, j, SEEN)
                seen_n += 1
            else:
                cell_rect(left, i, j, NOT_REACHED)
                gaps += 1
    overlay(left)

    # --- right: repeats --------------------------------------------------------
    right = np.full((size, size, 3), BG, np.uint8)
    counts = []
    for k, c in reach.items():
        if not fresh(c):
            continue
        n = views(c)
        counts.append(n)
        i, j = (int(v) for v in k.split(","))
        for lo, hi, colour in BANDS:
            if lo <= n <= hi:
                cell_rect(right, i, j, colour)
                break
    overlay(right)

    # --- legends and numbers -----------------------------------------------
    def label(img, lines, colours=None):
        y = 18
        for n, text in enumerate(lines):
            if colours and colours[n] is not None:
                cv2.rectangle(img, (8, y - 11), (22, y + 2), colours[n], -1)
                x = 28
            else:
                x = 8
            cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (255, 255, 255), 3)
            cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (30, 30, 30), 1)
            y += 18

    total = gaps + seen_n
    label(left, [f"NOT REACHED within {SWEEP_RADIUS} tiles (last {STALE_H:.0f}h)",
                 f"not reached: {gaps} cells ({100 * gaps / max(1, total):.0f}%)",
                 f"seen: {seen_n} cells",
                 f"track {len(track)} reads since {args.since}, marches {len(marches)}"],
          [None, NOT_REACHED, SEEN, None])
    band_n = [sum(lo <= n <= hi for n in counts) for lo, hi, _ in BANDS]
    views_total = sum(counts)
    label(right, [f"REPEATS: times each cell was in view (last {STALE_H:.0f}h)"]
          + [f"{lo}{'' if lo == hi else ('+' if hi > 999 else '-' + str(hi))} times: "
             f"{n} cells" for (lo, hi, _), n in zip(BANDS, band_n)]
          + [f"{views_total} cell-views over {len(counts)} cells = "
             f"{views_total / max(1, len(counts)):.1f} views per cell"],
          [None] + [c for _, _, c in BANDS] + [None])

    img = np.hstack([left, np.full((size, 6, 3), 255, np.uint8), right])
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img)
    print(f"{out}")
    print(f"not reached {gaps}/{total} cells within {SWEEP_RADIUS}; "
          f"repeats {dict(zip(['1', '2-3', '4-6', '7-10', '11+'], band_n))}; "
          f"{views_total / max(1, len(counts)):.1f} views per seen cell")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
