"""The scan goes where the sweep points -- by panning, not by the city road.

The operator, 2026-09-24: the trip through the city is the quick fix for a
wrong zoom, not a way to steer; going back through the city to scan near
ground is strange -- the scan path itself should find near ground first.

Measured over 381 pans from 2026-09-23 14:52 to 2026-09-24 01:10
(tools/dev/steer_check.py): pans moved toward the sweep target 42% of the
time, mean cosine -0.12 -- worse than no steering at all. The book's own
heading choice overrode the scan on 283 of those scans and turned it AWAY
from the target on 223 of them, toward it on 53: near the city every heading
crosses ground just seen (-1 a cell), so the best-scoring heading was always
the one leading out. The jump home through the city was bolted on to undo it.
"""

import inspect
import math
import random
import time

import pytest

from rok_farm import pan_model
from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import CELL, MapMemory

CITY = (577, 615)
WIN = {"left": 0, "top": 0, "width": 1534, "height": 863}
# The live book of 2026-09-24 00:48: ground within 40 tiles of the city seen
# minutes ago -- except three cells just below it, which a camera sitting on
# the city does not show (the frame reaches 7 tiles down, 12 up) -- and the
# ground beyond never seen. The band is then 8 + 24 = 32 tiles, so unseen
# ground past it scores 0 and ground just seen scores -1 a cell: every
# heading into the city scores worse than every heading out.
GAP = [(572, 604), (580, 604), (588, 604)]
NEAR = 40


@pytest.fixture
def book(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    b = MapMemory("4096")
    b.city = CITY
    now = time.time()
    gap = {f"{x // CELL},{y // CELL}" for x, y in GAP}
    cx, cy = CITY[0] // CELL, CITY[1] // CELL
    r = NEAR // CELL
    for i in range(cx - r, cx + r + 1):
        for j in range(cy - r, cy + r + 1):
            if f"{i},{j}" not in gap:
                b.reach[f"{i},{j}"] = {"gem": 0, "empty": 2, "t": now - 300}
    return b


def _gap_seen(book):
    now = time.time()
    return all((book.last_seen(x, y) or 0) > now - 120 for x, y in GAP)


class Farm(GemFlowMixin):
    def __init__(self, book, cam):
        self.mapmem = book
        self._last_map_xy = cam
        self._city_xy = CITY
        self.win = dict(WIN)


def _pan(heading):
    """Camera move in tiles for one scan swipe along a screen heading --
    the scan loop's own geometry (margin 80, 0.625 of the half reach)."""
    w, h = WIN["width"], WIN["height"]
    cx, cy = w / 2.0, h / 2.0
    hx, hy = (w // 2 - 80) * 0.625, (h // 2 - 80) * 0.625
    press = (cx + math.cos(heading) * hx, cy + math.sin(heading) * hy)
    release = (cx - math.cos(heading) * hx, cy - math.sin(heading) * hy)
    return pan_model.drag_move(press, release, WIN)


def _walk(book, cam, seed, limit):
    """The scan loop's heading process, the real steering and the real book,
    with the view recorded after every pan. Returns (scans until the unseen
    cells were on screen or None, farthest the camera got from the city)."""
    rnd = random.Random(seed)
    random.seed(seed)
    f = Farm(book, cam)
    heading = rnd.uniform(0, 2 * math.pi)
    x, y = float(cam[0]), float(cam[1])
    farthest = 0
    for n in range(1, limit + 1):
        turn = rnd.gauss(0, 0.4)
        if rnd.random() < 0.15:
            turn = rnd.uniform(-math.pi / 2, math.pi / 2)
        if rnd.random() < 0.05:
            turn = rnd.uniform(-math.pi, math.pi)
        heading = f._steer_heading(heading + turn)
        dx, dy = _pan(heading)
        x, y = x + dx, y + dy
        f._last_map_xy = (int(round(x)), int(round(y)))
        book.record_view(f._view_cells(f._last_map_xy))
        farthest = max(farthest, max(abs(x - CITY[0]), abs(y - CITY[1])))
        if _gap_seen(book):
            return n, farthest
    return None, farthest


START = (640, 600)          # 63 tiles east of the city, as at 00:48:55


def _fresh(book, snap):
    book.reach = {k: dict(v) for k, v in snap.items()}


def test_a_camera_out_past_the_band_pans_back_and_scans_the_gap(book):
    """A straight line to the three unseen cells is 5-6 pans."""
    snap = {k: dict(v) for k, v in book.reach.items()}
    reached, farthest = [], []
    for seed in range(20):
        _fresh(book, snap)
        n, far = _walk(book, START, seed, limit=25)
        reached.append(n)
        farthest.append(far)
    got = sorted(n for n in reached if n is not None)
    assert len(got) >= 18, f"scans to the gap, per seed: {reached}"
    assert got[len(got) // 2] <= 12, f"median scans {got}"
    assert max(farthest) <= 90, f"wandered out to {max(farthest):.0f} tiles"


def test_the_road_back_is_not_the_same_twice(book):
    """Near first, but never on rails: the same start takes different roads."""
    snap = {k: dict(v) for k, v in book.reach.items()}
    tracks = set()
    for seed in range(6):
        _fresh(book, snap)
        f = Farm(book, START)
        rnd = random.Random(seed)
        random.seed(seed)
        heading, pts = math.pi, []
        for _ in range(4):
            heading = f._steer_heading(heading + rnd.gauss(0, 0.4))
            dx, dy = _pan(heading)
            f._last_map_xy = (int(f._last_map_xy[0] + dx),
                              int(f._last_map_xy[1] + dy))
            pts.append(f._last_map_xy)
        tracks.add(tuple(pts))
    assert len(tracks) == 6


def test_on_the_sweep_the_book_does_not_argue_with_the_course(book):
    """Ground just seen lies ahead, unseen ground behind: the book scores
    the way out far better. Held to +-40 deg it still took the outer side
    every scan and the camera circled the seen ground, 40-50 tiles out.
    The target already is the book's answer; only a wall may turn it."""
    f = Farm(book, START)
    random.seed(4)
    for _ in range(200):
        f._sweep_tgt = None
        tgt = f._sweep_target()
        want = pan_model.screen_heading(tgt[0] - START[0], tgt[1] - START[1],
                                        WIN["width"], WIN["height"])
        f._sweep_tgt, f._sweep_age = tgt, 0
        h = f._steer_heading(want)
        d = math.atan2(math.sin(h - want), math.cos(h - want))
        assert abs(d) < 1e-6, math.degrees(d)


def test_on_the_sweep_a_map_edge_still_turns_the_scan(book):
    """The veto comes first: a camera near the edge with its target beyond
    the edge's reach is turned, sweep or not."""
    f = Farm(book, (60, 600))
    f._sweep_tgt, f._sweep_age = (4, 600), 0     # a gap past the veto's reach
    book.reach.pop(f"{4 // CELL},{600 // CELL}", None)
    west = math.pi
    h = f._steer_heading(west)
    assert not book.blocked(60, 600, pan_model.tile_heading(
        h, WIN["width"], WIN["height"]))


def test_off_the_sweep_the_book_still_steers_freely(book):
    """With no target (the flow knows no city), the book keeps its wide
    choice -- here it turns the scan right round, toward the unseen ground
    nearer the city it knows, which the corridor would never allow."""
    book.reach = {}
    f = Farm(book, START)
    f._city_xy = None                           # no city, no sweep
    random.seed(2)
    outs = {round(f._steer_heading(0.0), 3) for _ in range(10)}
    assert outs == {round(math.pi, 3)}


def test_the_city_road_is_not_a_way_to_steer():
    """The city trip stays what it was for: a wrong zoom, fog, leaving the
    home map, a burst that is done. Not a shortcut back to near ground."""
    assert not hasattr(GemFlowMixin, "_jump_home_if_out_of_band")
    scan = inspect.getsource(GemFlowMixin._step_scan_and_verify_gem)
    assert "_jump_home" not in scan and "JUMP_" not in scan
