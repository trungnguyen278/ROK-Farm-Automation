"""What the farm has done, as numbers and pictures.

Three reports, shared by the Discord bot (!stats, !map, !run) and the dev
tools that print them (tools/dev/gem_rate.py, track_map.py, run_map.py):

  gem_rate   gems an hour of running farm, by hour, band and day, with the
             operator's spending left out
  book_map   where the camera has NOT been and where it went over and over
  run_map    one run out of the city and back: its path, view by view

Kept off rok_farm.flow_steps on purpose: importing that builds the OCR
engine, and the bot has no use for one. The few flow constants needed are
repeated here and locked to the flow's by tests/test_reports.py.
"""

from __future__ import annotations

import io
import json
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from rok_farm import PROJECT_ROOT, pan_model
from rok_farm.map_memory import HOME_TILES

LOG = PROJECT_ROOT / "logs" / "overnight" / "farm_run.log"
BOOKS = PROJECT_ROOT / "data" / "map_knowledge"

# Mirrors of GemFlowMixin -- see the module docstring.
CELL = 8
VIEW_MARGIN = 0.08
SWEEP_RADIUS = 150
SWEEP_STALE_H = 2.0
WIN_W, WIN_H = 1534, 863
CITY_DEFAULT = (577, 615)

TS = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)(?:,(\d+))?")


def _epoch(stamp: str) -> float:
    return time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S"))


def _lines(log: Path):
    with open(log, encoding="utf-8", errors="replace") as fh:
        yield from fh


# --------------------------------------------------------------------------
# gems an hour

# A march carries 10-20 gems home; a rise bigger than this between two
# readings is a reward, a purchase or a misread -- listed, never counted.
MAX_RISE = 120
# Readings further apart than this are not one running farm.
MAX_GAP_MIN = 45
BANDS = (("night", 0, 6), ("morning", 6, 12), ("afternoon", 12, 18),
         ("evening", 18, 24))
_NOW = re.compile(r"Gems now (\d+)")
_START = re.compile(r"Gem counter starts at (\d+)")
_LOAD = re.compile(r"Deploy panel: march=\d+s .*load=(\d+)")


@dataclass
class GemRate:
    since: str
    until: str = ""
    gems: float = 0.0
    seconds: float = 0.0
    hour: dict = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0]))
    day: dict = field(default_factory=lambda: defaultdict(lambda: [0.0, 0.0]))
    marched: dict = field(default_factory=lambda: defaultdict(float))
    falls: list = field(default_factory=list)
    odd: list = field(default_factory=list)

    @property
    def hours(self) -> float:
        return self.seconds / 3600.0

    @property
    def rate(self) -> float:
        return self.gems / self.hours if self.seconds else 0.0

    def band(self, lo: int, hi: int) -> tuple[float, float]:
        """(gems, hours) over hours of the day lo..hi-1."""
        g = sum(self.hour[h][0] for h in range(lo, hi) if h in self.hour)
        s = sum(self.hour[h][1] for h in range(lo, hi) if h in self.hour)
        return g, s / 3600.0


def gem_rate(since: str, until: str | None = None, log: Path = LOG) -> GemRate:
    """Gems brought home per hour of running farm, spending left out.

    Reads the HUD balance ("Gems now N", read after armies come home).
    Between two readings of one run (no "Gem counter starts" between, less
    than MAX_GAP_MIN apart) a rise is gems brought home and a fall is the
    operator spending or the game taking some back -- never counted against
    the farm. The time counted is the time between readings, so hours the
    farm was stopped do not dilute the rate. `since`/`until` are
    "YYYY-MM-DD[ HH:MM]" prefixes of the log's local timestamps.
    """
    r = GemRate(since=since)
    last = None
    last_stamp = ""
    for line in _lines(log):
        m = TS.match(line)
        if not m or m.group(1) < since:
            continue
        if until and m.group(1) >= until:
            break
        stamp = m.group(1)
        hour = int(stamp[11:13])
        sm = _START.search(line)
        if sm:
            last = (_epoch(stamp), int(sm.group(1)))
            continue
        lm = _LOAD.search(line)
        if lm:
            load = int(lm.group(1))
            if load <= 100:              # one misread said 954462
                r.marched[hour] += load
            continue
        nm = _NOW.search(line)
        if not nm:
            continue
        t, bal = _epoch(stamp), int(nm.group(1))
        if last is not None and 0 < t - last[0] <= MAX_GAP_MIN * 60:
            d, dt = bal - last[1], t - last[0]
            r.seconds += dt
            r.hour[hour][1] += dt
            r.day[stamp[:10]][1] += dt
            if 0 < d <= MAX_RISE:
                r.gems += d
                r.hour[hour][0] += d
                r.day[stamp[:10]][0] += d
            elif d > MAX_RISE:
                r.odd.append((stamp, d))
            elif d < 0:
                r.falls.append((stamp, d))
        last = (t, bal)
        last_stamp = stamp
    r.until = last_stamp
    return r


def _font(size: int, bold: bool = False, mono: bool = False):
    from PIL import ImageFont
    names = (["consola.ttf"] if mono else
             ["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"])
    for name in names:
        for folder in (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype")):
            try:
                return ImageFont.truetype(str(folder / name), size)
            except OSError:
                continue
    return ImageFont.load_default()


# Discord's dark theme, so the picture sits in the channel.
_BG = (43, 45, 49)
_FG = (220, 221, 222)
_DIM = (140, 142, 148)
_GRID = (64, 66, 72)
_BAND_COLOURS = {"night": (88, 101, 242), "morning": (250, 166, 26),
                 "afternoon": (59, 165, 93), "evening": (185, 96, 220)}


def rate_chart(r: GemRate) -> bytes:
    """PNG: gems an hour for each hour of the day, coloured by band."""
    from PIL import Image, ImageDraw
    w, h = 960, 430
    left, right, top, bottom = 56, 20, 24, 70
    img = Image.new("RGB", (w, h), _BG)
    d = ImageDraw.Draw(img)
    small, tiny = _font(15), _font(12)
    rates = {hr: (g / (s / 3600.0) if s >= 600 else None, s / 3600.0)
             for hr, (g, s) in r.hour.items()}
    top_rate = max([v for v, _ in rates.values() if v] + [r.rate, 50.0])
    scale = (h - top - bottom) / (top_rate * 1.15)
    base_y = h - bottom
    for k in range(0, int(top_rate * 1.15) + 1, 50):
        y = base_y - k * scale
        d.line([(left, y), (w - right, y)], fill=_GRID)
        d.text((left - 8, y), str(k), fill=_DIM, font=tiny, anchor="rm")
    slot = (w - left - right) / 24.0
    for hr in range(24):
        x0 = left + hr * slot + 4
        x1 = left + (hr + 1) * slot - 4
        band = next(b for b, lo, hi in BANDS if lo <= hr < hi)
        colour = _BAND_COLOURS[band]
        val, run_h = rates.get(hr, (None, 0.0))
        if val is not None:
            y = base_y - val * scale
            thin = run_h < 0.5
            if thin:          # under half an hour of data: outline only
                d.rectangle([x0, y, x1, base_y], outline=colour, width=2)
            else:
                d.rectangle([x0, y, x1, base_y], fill=colour)
            d.text(((x0 + x1) / 2, y - 3), f"{val:.0f}", fill=_FG, font=tiny,
                   anchor="md")
            d.text(((x0 + x1) / 2, base_y + 22), f"{run_h:.1f}h", fill=_DIM,
                   font=tiny, anchor="mt")
        d.text(((x0 + x1) / 2, base_y + 6), f"{hr:02d}", fill=_FG, font=small,
               anchor="mt")
    if r.seconds:
        y = base_y - r.rate * scale
        for x in range(left, w - right, 12):
            d.line([(x, y), (x + 6, y)], fill=_FG, width=1)
        d.text((w - right, y - 4), f"average {r.rate:.0f}/h", fill=_FG,
               font=small, anchor="rd")
    x = left
    for band, _lo, _hi in BANDS:
        d.rectangle([x, h - 18, x + 12, h - 6], fill=_BAND_COLOURS[band])
        d.text((x + 18, h - 12), band, fill=_FG, font=small, anchor="lm")
        x += 130
    d.text((w - right, h - 12), "bar = gems/h, below = hours run; "
           "outline = under half an hour of data", fill=_DIM, font=tiny, anchor="rm")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


# --------------------------------------------------------------------------
# the map book and the camera's track

def active_book() -> Path | None:
    """The map book the farm is using: the one written most recently."""
    books = sorted(BOOKS.glob("*.json"), key=lambda p: p.stat().st_mtime)
    return books[-1] if books else None


def load_book(path: Path | None = None) -> dict:
    path = path or active_book()
    if path is None:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


def view_cells(cam) -> list[tuple[int, int]]:
    """Book cells a view at `cam` shows -- flow_steps._view_cells."""
    corners = pan_model.view_corners(cam, WIN_W, WIN_H)
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    out = []
    for i in range(int(min(xs)) // CELL, int(max(xs)) // CELL + 1):
        for j in range(int(min(ys)) // CELL, int(max(ys)) // CELL + 1):
            centre = (i * CELL + CELL // 2, j * CELL + CELL // 2)
            if pan_model.in_view(cam, centre, WIN_W, WIN_H, margin=VIEW_MARGIN):
                out.append((i, j))
    return out


def marches(since: str, until: str | None = None, log: Path = LOG):
    """Deposits marched to: [(stamp, x, y)]."""
    pat = re.compile(r"Marched to deposit \S+ (\d+):(\d+)")
    out = []
    for line in _lines(log):
        m = TS.match(line)
        if not m or m.group(1) < since:
            continue
        if until and m.group(1) >= until:
            break
        mm = pat.search(line)
        if mm:
            out.append((m.group(1), int(mm.group(1)), int(mm.group(2))))
    return out


_NOT_REACHED = (120, 120, 245)
_SEEN = (120, 205, 120)
_REPEAT_BANDS = [(1, 1, (190, 235, 190)), (2, 3, (90, 200, 90)),
                 (4, 6, (60, 215, 235)), (7, 10, (40, 140, 245)),
                 (11, 10 ** 6, (40, 40, 220))]
_MAP_BG = (238, 238, 238)
JUMP_TILES = 40


def _label(img, lines, colours=None):
    y = 18
    for n, text in enumerate(lines):
        x = 8
        if colours and colours[n] is not None:
            cv2.rectangle(img, (8, y - 11), (22, y + 2), colours[n], -1)
            x = 28
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (255, 255, 255), 3)
        cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (30, 30, 30), 1)
        y += 18


def book_map(since: str, until: str | None = None,
             stale_h: float = SWEEP_STALE_H, radius: int = 200, px: int = 3,
             book: dict | None = None, log: Path = LOG):
    """Two panels -- NOT REACHED and REPEATS -- for the camera track inside
    [since, until]. Returns (png bytes, summary dict), or (None, summary)
    when there is no track in the period."""
    book = book if book is not None else load_book()
    t0 = _epoch(since + (":00" if len(since) == 16 else " 00:00:00"
                         if len(since) == 10 else ""))
    t1 = (_epoch(until + (":00" if len(until) == 16 else " 00:00:00"
                          if len(until) == 10 else ""))
          if until else float("inf"))
    city = tuple(book.get("city") or CITY_DEFAULT)
    tiles = int(book.get("size") or HOME_TILES)
    track = [p for p in book.get("track", []) if t0 <= p[0] <= t1]
    summary = {"views": len(track)}
    if not track:
        return None, summary
    end = track[-1][0]
    fresh_from = max(t0, end - stale_h * 3600)
    counts: dict = {}
    fresh: set = set()
    for t, x, y in track:
        for cell in view_cells((x, y)):
            counts[cell] = counts.get(cell, 0) + 1
            if t >= fresh_from:
                fresh.add(cell)
    size = 2 * radius * px
    x0, y0 = city[0] - radius, city[1] - radius

    def to_px(x, y):
        return (int((x - x0) * px), int(size - (y - y0) * px))

    def rect(img, i, j, colour):
        cv2.rectangle(img, to_px(i * CELL, j * CELL + CELL),
                      to_px(i * CELL + CELL, j * CELL), colour, -1)

    until_txt = time.strftime("%Y-%m-%d %H:%M", time.localtime(end))
    went = marches(since, until_txt[:16] + ":59", log) if log.exists() else []

    def overlay(img):
        for t in range(0, tiles, 50):
            if x0 <= t <= x0 + 2 * radius:
                x, _ = to_px(t, y0)
                cv2.line(img, (x, 0), (x, size), (205, 205, 205), 1)
                cv2.putText(img, str(t), (x + 2, size - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (110, 110, 110), 1)
            if y0 <= t <= y0 + 2 * radius:
                _, y = to_px(x0, t)
                cv2.line(img, (0, y), (size, y), (205, 205, 205), 1)
                cv2.putText(img, str(t), (3, y - 3),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (110, 110, 110), 1)
        cv2.rectangle(img, to_px(city[0] - SWEEP_RADIUS, city[1] + SWEEP_RADIUS),
                      to_px(city[0] + SWEEP_RADIUS, city[1] - SWEEP_RADIUS),
                      (90, 90, 90), 1)
        for a, b in zip(track, track[1:]):
            if b[0] - a[0] > 120:
                continue
            if max(abs(b[1] - a[1]), abs(b[2] - a[2])) > JUMP_TILES:
                # A trip through the city, not a pan: dotted.
                p, q = to_px(a[1], a[2]), to_px(b[1], b[2])
                n = max(2, int(np.hypot(q[0] - p[0], q[1] - p[1]) // 8))
                for k in range(0, n, 2):
                    u = k / n
                    cv2.circle(img, (int(p[0] + (q[0] - p[0]) * u),
                                     int(p[1] + (q[1] - p[1]) * u)), 1,
                               (170, 170, 170), -1)
                continue
            cv2.line(img, to_px(a[1], a[2]), to_px(b[1], b[2]), (60, 60, 60), 1)
        for _s, x, y in went:
            cx, cy = to_px(x, y)
            cv2.line(img, (cx - 5, cy - 5), (cx + 5, cy + 5), (20, 20, 200), 2)
            cv2.line(img, (cx - 5, cy + 5), (cx + 5, cy - 5), (20, 20, 200), 2)
        cv2.drawMarker(img, to_px(*city), (0, 0, 160), cv2.MARKER_STAR, 20, 2)

    left = np.full((size, size, 3), _MAP_BG, np.uint8)
    cx, cy = city[0] // CELL, city[1] // CELL
    r = SWEEP_RADIUS // CELL
    gaps = seen = near_gaps = near_total = 0
    for i in range(cx - r, cx + r + 1):
        for j in range(cy - r, cy + r + 1):
            if i < 0 or j < 0 or i * CELL >= tiles or j * CELL >= tiles:
                continue
            near = max(abs(i - cx), abs(j - cy)) * CELL <= 80
            near_total += near
            if (i, j) in fresh:
                rect(left, i, j, _SEEN)
                seen += 1
            else:
                rect(left, i, j, _NOT_REACHED)
                gaps += 1
                near_gaps += near
    overlay(left)
    right = np.full((size, size, 3), _MAP_BG, np.uint8)
    for (i, j), n in counts.items():
        for lo, hi, colour in _REPEAT_BANDS:
            if lo <= n <= hi:
                rect(right, i, j, colour)
                break
    overlay(right)
    total = gaps + seen
    band_n = [sum(lo <= n <= hi for n in counts.values())
              for lo, hi, _ in _REPEAT_BANDS]
    views_total = sum(counts.values())
    per_cell = views_total / max(1, len(counts))
    _label(left, [f"NOT REACHED within {SWEEP_RADIUS} tiles "
                  f"(last {stale_h:g}h of the period)",
                  f"not reached: {gaps} cells ({100 * gaps / max(1, total):.0f}%),"
                  f" within 80 tiles: {near_gaps}/{near_total}",
                  f"seen: {seen} cells",
                  f"{since} to {until_txt}: {len(track)} views, "
                  f"marches {len(went)}"],
           [None, _NOT_REACHED, _SEEN, None])
    _label(right, ["REPEATS: times each cell was in view in the period"]
           + [f"{lo}{'' if lo == hi else ('+' if hi > 999 else '-' + str(hi))}"
              f" times: {n} cells" for (lo, hi, _), n in zip(_REPEAT_BANDS, band_n)]
           + [f"{views_total} cell-views over {len(counts)} cells = "
              f"{per_cell:.1f} views per cell"],
           [None] + [c for _, _, c in _REPEAT_BANDS] + [None])
    img = np.hstack([left, np.full((size, 6, 3), 255, np.uint8), right])
    far = sorted(max(abs(x - city[0]), abs(y - city[1])) for _s, x, y in went)
    summary.update({
        "until": until_txt, "not_reached": gaps, "cells": total,
        "near_not_reached": near_gaps, "near_cells": near_total,
        "views_per_cell": per_cell, "marches": len(went),
        "march_median": far[len(far) // 2] if far else None,
        "march_max": far[-1] if far else None,
        "repeats": dict(zip(["1", "2-3", "4-6", "7-10", "11+"], band_n)),
    })
    ok, png = cv2.imencode(".png", img)
    return (png.tobytes() if ok else None), summary


# --------------------------------------------------------------------------
# one run out of the city and back

_TARGET = re.compile(r"sweep: target (\d+),(\d+)")
_MARCH = re.compile(r"Marched to deposit \S+ (\d+):(\d+)")
_MINE_END = re.compile(r"^  Mine (\d+) (DONE|FAILED)")


def read_runs(since: str, log: Path = LOG):
    """[(start, end, events)] -- a run starts at "City -> world map" and
    ends at "World map -> city" or a client launch. Events are
    (t, kind, data): target, march, done, failed."""
    runs, cur, last_t = [], None, None
    for line in _lines(log):
        m = TS.match(line)
        if m:
            last_t = _epoch(m.group(1)) + int(m.group(2) or 0) / 1000.0
        if last_t is None or time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(last_t)) < since:
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
        mm = _TARGET.search(line)
        if mm:
            cur[2].append((last_t, "target", (int(mm.group(1)), int(mm.group(2)))))
            continue
        mm = _MARCH.search(line)
        if mm:
            cur[2].append((last_t, "march", (int(mm.group(1)), int(mm.group(2)))))
            continue
        mm = _MINE_END.search(line)
        if mm:
            cur[2].append((last_t, mm.group(2).lower(), int(mm.group(1))))
    if cur is not None:
        cur[1] = time.time()
        runs.append(tuple(cur))
    return runs


def _cross(a, b, c, d) -> bool:
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


def run_summary(run, track, city, stale_h: float = SWEEP_STALE_H) -> dict:
    start, end, events = run
    pts = [p for p in track if start <= p[0] <= end + 1]
    seen_before = set()
    for _t, x, y in (p for p in track if start - stale_h * 3600 <= p[0] < start):
        seen_before.update(view_cells((x, y)))
    counts: dict = {}
    for _t, x, y in pts:
        for c in view_cells((x, y)):
            counts[c] = counts.get(c, 0) + 1
    old = sum(n for c, n in counts.items() if c in seen_before)
    allv = sum(counts.values())
    segs = [((a[1], a[2]), (b[1], b[2])) for a, b in zip(pts, pts[1:])]
    crossings = sum(_cross(*segs[i], *segs[j])
                    for i in range(len(segs)) for j in range(i + 2, len(segs)))
    return {
        "start": start, "end": end, "points": pts, "counts": counts,
        "seen_before": seen_before, "views": len(pts),
        "marches": sum(1 for e in events if e[1] == "march"),
        "failed": sum(1 for e in events if e[1] == "failed"),
        "farthest": max((max(abs(x - city[0]), abs(y - city[1]))
                         for _t, x, y in pts), default=0),
        "new": sum(1 for c in counts if c not in seen_before),
        "shown": len(counts),
        "rescan": old / allv if allv else 0.0,
        "crossings": crossings,
    }


_NEW = [(185, 235, 185), (110, 200, 110)]
_OLD = [(120, 225, 240), (60, 160, 245), (60, 60, 225)]


def run_map(run, idx: int, book: dict | None = None,
            stale_h: float = SWEEP_STALE_H, px: int = 5):
    """PNG of one run and its summary dict."""
    book = book if book is not None else load_book()
    city = tuple(book.get("city") or CITY_DEFAULT)
    tiles = int(book.get("size") or HOME_TILES)
    s = run_summary(run, book.get("track", []), city, stale_h)
    radius = max(60, min(200, s["farthest"] + 30))
    size = 2 * radius * px
    x0, y0 = city[0] - radius, city[1] - radius

    def to_px(x, y):
        return (int((x - x0) * px), int(size - (y - y0) * px))

    img = np.full((size, size, 3), _MAP_BG, np.uint8)
    for (i, j), n in s["counts"].items():
        if (i, j) in s["seen_before"]:
            colour = _OLD[0 if n == 1 else 1 if n <= 3 else 2]
        else:
            colour = _NEW[0 if n == 1 else 1]
        cv2.rectangle(img, to_px(i * CELL, j * CELL + CELL),
                      to_px(i * CELL + CELL, j * CELL), colour, -1)
    for t in range(0, tiles, 25):
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
    pts = s["points"]
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
    for _t, kind, data in run[2]:
        if kind == "target":
            cv2.circle(img, to_px(*data), 7, (160, 40, 160), 2)
        elif kind == "march":
            cx, cy = to_px(*data)
            cv2.line(img, (cx - 7, cy - 7), (cx + 7, cy + 7), (20, 20, 200), 3)
            cv2.line(img, (cx - 7, cy + 7), (cx + 7, cy - 7), (20, 20, 200), 3)
    cv2.drawMarker(img, to_px(*city), (0, 0, 150), cv2.MARKER_STAR, 26, 3)
    start = time.strftime("%m-%d %H:%M:%S", time.localtime(s["start"]))
    stop = time.strftime("%H:%M:%S", time.localtime(s["end"]))
    _label(img, [
        f"run {idx}: {start} -> {stop} ({(s['end'] - s['start']) / 60:.1f} min)",
        f"{s['views']} views, {s['marches']} march(es), {s['failed']} failed"
        f" mine(s), farthest {s['farthest']} tiles, {s['crossings']} crossing(s)",
        f"cells shown: {s['shown']} -- new {s['new']},"
        f" seen in the {stale_h:g}h before {s['shown'] - s['new']}",
        f"views on ground already seen: {100 * s['rescan']:.0f}%",
        "green new ground; yellow/orange/red already seen (1 / 2-3 / 4+)",
        "circle = sweep target, x = marched to, star = city"])
    ok, png = cv2.imencode(".png", img)
    for key in ("points", "counts", "seen_before"):
        s.pop(key)
    return (png.tobytes() if ok else None), s


# --------------------------------------------------------------------------
# periods, as typed on Discord

def parse_since(args, default: str = "yesterday", now: float | None = None) -> str:
    """"YYYY-MM-DD HH:MM" from what was typed after the command.

    today / yesterday, Nh (the last N hours), Nd (the last N days counting
    today), all, YYYY-MM-DD or MM-DD. Anything else falls back to `default`.
    """
    now = time.time() if now is None else now
    word = (args[0] if args else default).strip().lower()
    day0 = time.mktime(time.strptime(time.strftime("%Y-%m-%d", time.localtime(now)),
                                     "%Y-%m-%d"))

    def fmt(t):
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))

    if word == "today":
        return fmt(day0)
    if word == "yesterday":
        return fmt(day0 - 86400)
    if word == "all":
        return "2000-01-01 00:00"
    m = re.fullmatch(r"(\d{1,3})h", word)
    if m:
        return fmt(now - int(m.group(1)) * 3600)
    m = re.fullmatch(r"(\d{1,3})d", word)
    if m:
        return fmt(day0 - (max(1, int(m.group(1))) - 1) * 86400)
    m = re.fullmatch(r"(\d{4})-(\d\d)-(\d\d)", word)
    if m:
        return f"{word} 00:00"
    m = re.fullmatch(r"(\d\d)-(\d\d)", word)
    if m:
        return f"{time.localtime(now).tm_year}-{word} 00:00"
    if word != default:
        return parse_since([], default, now)
    return fmt(day0 - 86400)


# --------------------------------------------------------------------------
# what the Discord bot shows: plain data, turned into an embed by the bot
#
# {"title", "description", "colour", "fields": [(name, value, inline)],
#  "image": attachment file name or None, "footer"}

COLOUR_INFO = 0x5865F2
COLOUR_OK = 0x3BA55D
COLOUR_BAD = 0xED4245


def stats_spec(r: GemRate) -> dict:
    if not r.seconds:
        return {"title": f"Gems since {r.since}", "colour": COLOUR_INFO,
                "description": "No readings of a running farm in that period.",
                "fields": [], "image": None, "footer": None}
    fields = []
    for band, lo, hi in BANDS:
        g, hrs = r.band(lo, hi)
        value = f"**{g / hrs:.0f}**/h · {hrs:.1f} h" if hrs >= 0.25 else "--"
        fields.append((f"{band.capitalize()} {lo:02d}-{hi:02d}", value, True))
    days = [f"{d[5:]}  {g / (s / 3600):4.0f}/h  {s / 3600:4.1f} h  {g:5.0f}"
            for d, (g, s) in sorted(r.day.items()) if s >= 600]
    if days:
        fields.append(("By day   (gems/h  hours  gems)",
                       "```\n" + "\n".join(days[-10:]) + "\n```", False))
    left_out = [f"{d:+,} at {when[5:16]}" for when, d in r.falls[:4]]
    if r.odd:
        left_out.append(f"{len(r.odd)} rise(s) over {MAX_RISE} (rewards/misreads)")
    fields.append(("Left out", "\n".join(left_out) if left_out
                   else "nothing -- no spending in this period", False))
    return {
        "title": f"Gems since {r.since}",
        "description": (f"**{r.gems:,.0f}** gems in **{r.hours:.1f} h** of "
                        f"running farm = **{r.rate:.0f} gems/h**"),
        "colour": COLOUR_INFO, "fields": fields, "image": "gem_rate.png",
        "footer": ("Rises of the gem balance only: spending and gems taken "
                   "back never count against the farm."),
    }


def map_spec(s: dict, since: str) -> dict:
    if not s.get("views"):
        return {"title": f"Map book since {since}", "colour": COLOUR_INFO,
                "description": "No camera track in that period.",
                "fields": [], "image": None, "footer": None}
    rep = s["repeats"]
    far = (f", median {s['march_median']} tiles out, max {s['march_max']}"
           if s["march_median"] is not None else "")
    return {
        "title": f"Map book since {since}",
        "description": f"{s['views']} views, {s['marches']} march(es){far}",
        "colour": COLOUR_INFO,
        "fields": [
            ("Not reached, 80 tiles", f"{s['near_not_reached']}/{s['near_cells']}"
             " cells", True),
            ("Not reached, 150 tiles", f"{s['not_reached']}/{s['cells']} cells", True),
            ("Views per cell", f"{s['views_per_cell']:.1f}", True),
            ("Times each cell was in view",
             " · ".join(f"{k}: {v}" for k, v in rep.items()), False),
        ],
        "image": "map.png",
        "footer": (f"Left: red = not seen in the last {SWEEP_STALE_H:g} h of the "
                   f"period. Right: how often each cell was in view."),
    }


def run_spec(s: dict, idx: int) -> dict:
    start = time.strftime("%m-%d %H:%M", time.localtime(s["start"]))
    stop = time.strftime("%H:%M", time.localtime(s["end"]))
    return {
        "title": f"Run {idx}: {start} -> {stop} "
                 f"({(s['end'] - s['start']) / 60:.1f} min)",
        "description": "One run out of the city and back, view by view.",
        "colour": COLOUR_OK if s["crossings"] <= 2 else COLOUR_INFO,
        "fields": [
            ("Views", str(s["views"]), True),
            ("Marches", f"{s['marches']} ({s['failed']} failed)", True),
            ("Farthest", f"{s['farthest']} tiles", True),
            ("Path crossings", str(s["crossings"]), True),
            ("New / shown cells", f"{s['new']}/{s['shown']}", True),
            ("On ground already seen", f"{100 * s['rescan']:.0f}%", True),
        ],
        "image": "run.png",
        "footer": ("Green = new ground, yellow/orange/red = seen in the last "
                   f"{SWEEP_STALE_H:g} h. Circle = target, x = marched to."),
    }


def runs_spec(rows: list, since: str) -> dict:
    """rows: [(idx, summary)], newest last."""
    lines = [" #  start  min views march far cross seen%"]
    for idx, s in rows:
        lines.append(f"{idx:2d}  {time.strftime('%H:%M', time.localtime(s['start']))}"
                     f" {(s['end'] - s['start']) / 60:4.1f} {s['views']:5d}"
                     f" {s['marches']:5d} {s['farthest']:3d} {s['crossings']:5d}"
                     f" {100 * s['rescan']:4.0f}")
    return {
        "title": f"Runs since {since}",
        "description": "```\n" + "\n".join(lines) + "\n```",
        "colour": COLOUR_INFO, "fields": [], "image": None,
        "footer": "!run N draws one of them (N as numbered here).",
    }
