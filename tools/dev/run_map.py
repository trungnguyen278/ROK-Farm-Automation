"""Draw ONE scan run: from leaving the city to coming back to it.

The operator, 2026-09-24: track_map mixes every run together; one run --
out of the city and back -- is what shows whether the path itself is right.

A run starts at "City -> world map" in the farm log and ends at the next
"World map -> city" (a full queue, a failed mine sent home, fog, ...) or a
client launch. Its camera points come from the map book's track. Drawn the
way the game shows the map (X right, Y up):

  * the path, every view numbered in order, S at the start, E at the end
  * cells coloured by what the run's views showed:
        green   ground not seen in the stale window before the run (new)
        yellow / orange / red   ground already seen in that window --
                re-scanned, darker the more often this run went over it
  * the sweep targets the run was given (open circles), the deposits it
    marched to (x), mines that failed (!) and the city (star)

    .venv\\Scripts\\python tools\\dev\\run_map.py --list [--since "2026-09-24 07:56"]
    .venv\\Scripts\\python tools\\dev\\run_map.py --run 12        (index from --list)
    .venv\\Scripts\\python tools\\dev\\run_map.py --all --since "2026-09-24 07:56"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from rok_farm import pan_model  # noqa: E402
from rok_farm.flow_steps import GemFlowMixin  # noqa: E402

BOOK = ROOT / "data" / "map_knowledge" / "4096.json"
LOG = ROOT / "logs" / "overnight" / "farm_run.log"
OUT = ROOT / "screenshots" / "runs"
CELL = 8
PX = 5
WIN_W, WIN_H = 1534, 863

TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),(\d+)")
TARGET = re.compile(r"sweep: target (\d+),(\d+)")
MARCH = re.compile(r"Marched to deposit \S+ (\d+):(\d+)")
MINE_END = re.compile(r"^  Mine (\d+) (DONE|FAILED)")

# BGR
NEW = [(185, 235, 185), (110, 200, 110)]                  # 1, 2+ views
OLD = [(120, 225, 240), (60, 160, 245), (60, 60, 225)]     # 1, 2-3, 4+
BG = (238, 238, 238)


def view_cells(cam):
    """Book cells a view at `cam` shows -- flow_steps._view_cells."""
    corners = pan_model.view_corners(cam, WIN_W, WIN_H)
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    out = []
    for i in range(int(min(xs)) // CELL, int(max(xs)) // CELL + 1):
        for j in range(int(min(ys)) // CELL, int(max(ys)) // CELL + 1):
            centre = (i * CELL + CELL // 2, j * CELL + CELL // 2)
            if pan_model.in_view(cam, centre, WIN_W, WIN_H,
                                 margin=GemFlowMixin.VIEW_MARGIN):
                out.append((i, j))
    return out


def read_runs(since: str):
    """[(start, end, events)] from the farm log; events are (t, kind, data)."""
    runs, cur, last_t = [], None, None
    with LOG.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = TS.match(line)
            if m:
                last_t = (time.mktime(time.strptime(m.group(1),
                                                    "%Y-%m-%d %H:%M:%S"))
                          + int(m.group(2)) / 1000.0)
                if m.group(1) < since:
                    continue
            if last_t is None or time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(last_t)) < since:
                continue
            if "City -> world map" in line:
                if cur is None:
                    cur = [last_t, None, []]
                continue
            if cur is None:
                continue
            if ("World map -> city" in line
                    or "Game is not running -- launching it" in line):
                cur[1] = last_t
                runs.append(tuple(cur))
                cur = None
                continue
            m = TARGET.search(line)
            if m:
                cur[2].append((last_t, "target", (int(m.group(1)), int(m.group(2)))))
                continue
            m = MARCH.search(line)
            if m:
                cur[2].append((last_t, "march", (int(m.group(1)), int(m.group(2)))))
                continue
            m = MINE_END.search(line)
            if m:
                cur[2].append((last_t, m.group(2).lower(), int(m.group(1))))
    if cur is not None:
        cur[1] = time.time()
        runs.append(tuple(cur))
    return runs


def summarise(run, track, city, stale_h):
    start, end, events = run
    pts = [p for p in track if start <= p[0] <= end + 1]
    before = [p for p in track if start - stale_h * 3600 <= p[0] < start]
    seen_before = set()
    for _t, x, y in before:
        seen_before.update(view_cells((x, y)))
    counts: dict = {}
    for _t, x, y in pts:
        for c in view_cells((x, y)):
            counts[c] = counts.get(c, 0) + 1
    new = [c for c in counts if c not in seen_before]
    far = max((max(abs(x - city[0]), abs(y - city[1])) for _t, x, y in pts),
              default=0)
    return pts, counts, seen_before, new, far


def draw(run, idx, track, city, stale_h, out_dir):
    start, end, events = run
    pts, counts, seen_before, new, far = summarise(run, track, city, stale_h)
    radius = max(60, min(200, far + 30))
    size = 2 * radius * PX
    x0, y0 = city[0] - radius, city[1] - radius

    def to_px(x, y):
        return (int((x - x0) * PX), int(size - (y - y0) * PX))

    img = np.full((size, size, 3), BG, np.uint8)
    for (i, j), n in counts.items():
        if (i, j) in seen_before:
            colour = OLD[0 if n == 1 else 1 if n <= 3 else 2]
        else:
            colour = NEW[0 if n == 1 else 1]
        cv2.rectangle(img, to_px(i * CELL, j * CELL + CELL),
                      to_px(i * CELL + CELL, j * CELL), colour, -1)
    for t in range(0, 1200, 25):
        if x0 <= t <= x0 + 2 * radius:
            x, _ = to_px(t, y0)
            cv2.line(img, (x, 0), (x, size), (210, 210, 210), 1)
            cv2.putText(img, str(t), (x + 2, size - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (110, 110, 110), 1)
        if y0 <= t <= y0 + 2 * radius:
            _, y = to_px(x0, t)
            cv2.line(img, (0, y), (size, y), (210, 210, 210), 1)
            cv2.putText(img, str(t), (3, y - 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (110, 110, 110), 1)
    for a, b in zip(pts, pts[1:]):
        cv2.line(img, to_px(a[1], a[2]), to_px(b[1], b[2]), (50, 50, 50), 2)
    for n, (_t, x, y) in enumerate(pts, 1):
        p = to_px(x, y)
        cv2.circle(img, p, 4, (50, 50, 50), -1)
        cv2.putText(img, str(n), (p[0] + 5, p[1] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (20, 20, 20), 1)
    if pts:
        for tag, (_t, x, y) in (("S", pts[0]), ("E", pts[-1])):
            p = to_px(x, y)
            cv2.circle(img, p, 11, (255, 255, 255), -1)
            cv2.circle(img, p, 11, (0, 0, 0), 2)
            cv2.putText(img, tag, (p[0] - 6, p[1] + 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)
    marches = fails = 0
    for _t, kind, data in events:
        if kind == "target":
            cv2.circle(img, to_px(*data), 7, (160, 40, 160), 2)
        elif kind == "march":
            marches += 1
            cx, cy = to_px(*data)
            cv2.line(img, (cx - 7, cy - 7), (cx + 7, cy + 7), (20, 20, 200), 3)
            cv2.line(img, (cx - 7, cy + 7), (cx + 7, cy - 7), (20, 20, 200), 3)
        elif kind == "failed":
            fails += 1
    cv2.drawMarker(img, to_px(*city), (0, 0, 150), cv2.MARKER_STAR, 26, 3)

    old_views = sum(n for c, n in counts.items() if c in seen_before)
    all_views = sum(counts.values())
    lines = [
        f"run {idx}: {time.strftime('%m-%d %H:%M:%S', time.localtime(start))}"
        f" -> {time.strftime('%H:%M:%S', time.localtime(end))}"
        f" ({(end - start) / 60:.1f} min)",
        f"{len(pts)} views, {marches} march(es), {fails} failed mine(s),"
        f" farthest {far} tiles from the city",
        f"cells shown: {len(counts)} -- new {len(new)},"
        f" seen in the {stale_h:g}h before {len(counts) - len(new)}",
        f"cell-views on ground already seen: {old_views}/{all_views}"
        f" ({100 * old_views / max(1, all_views):.0f}%)",
        "green new ground; yellow/orange/red already seen (1 / 2-3 / 4+ views)",
        "circle = sweep target, x = marched to, star = city",
    ]
    y = 20
    for text in lines:
        cv2.putText(img, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 4)
        cv2.putText(img, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (20, 20, 20), 1)
        y += 20
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / (f"run_{idx:03d}_"
                     f"{time.strftime('%m%d_%H%M', time.localtime(start))}.png")
    cv2.imwrite(str(out), img)
    return out, len(pts), marches, fails, far, len(new), len(counts), old_views, all_views


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=time.strftime("%Y-%m-%d 00:00"))
    ap.add_argument("--run", type=int, default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--stale-h", type=float, default=GemFlowMixin.SWEEP_STALE_H)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    book = json.loads(BOOK.read_text(encoding="utf-8"))
    city = tuple(book.get("city") or (577, 615))
    track = book.get("track", [])
    runs = read_runs(args.since)
    if not runs:
        print("no runs since", args.since)
        return 1
    if args.list or (args.run is None and not args.all):
        print(" idx  start     min  views marches failed farthest  new/shown  re-scan%")
        for idx, run in enumerate(runs):
            pts, counts, seen_before, new, far = summarise(run, track, city,
                                                           args.stale_h)
            marches = sum(1 for e in run[2] if e[1] == "march")
            fails = sum(1 for e in run[2] if e[1] == "failed")
            old = sum(n for c, n in counts.items() if c in seen_before)
            tot = sum(counts.values())
            print(f"{idx:4d}  {time.strftime('%H:%M:%S', time.localtime(run[0]))}"
                  f" {(run[1] - run[0]) / 60:5.1f} {len(pts):5d} {marches:7d}"
                  f" {fails:6d} {far:8d}  {len(new):4d}/{len(counts):<4d}"
                  f"  {100 * old / max(1, tot):6.0f}")
        return 0
    todo = range(len(runs)) if args.all else [args.run]
    for idx in todo:
        res = draw(runs[idx], idx, track, city, args.stale_h, Path(args.out))
        print(res[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
