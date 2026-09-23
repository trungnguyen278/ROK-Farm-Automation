"""The scan leans toward unseen ground near the city -- a pull, never a rail.

The operator, 2026-09-23: keep the trajectory, so ground near the city is not
left unscanned once the wander has gone far; optimise the path for finding
mines close by, but do not fix it.
"""

import math
import random
import time

import pytest

from rok_farm import pan_model as pm
from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import CELL, MapMemory, _key


@pytest.fixture
def book(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    return MapMemory("4096")


def _cover(book, city, radius, but=(), when=None):
    """Mark every cell within radius of the city as seen, except `but`."""
    when = time.time() if when is None else when
    skip = {_key(*t) for t in but}
    cx, cy = city[0] // CELL, city[1] // CELL
    r = radius // CELL
    for i in range(cx - r, cx + r + 1):
        for j in range(cy - r, cy + r + 1):
            k = f"{i},{j}"
            if k not in skip:
                book.reach[k] = {"gem": 0, "empty": 1, "t": when}


def test_the_headings_are_each_others_inverse():
    for dx, dy in ((10, 0), (0, 10), (-7, 3), (5, -12)):
        h = pm.screen_heading(dx, dy, 1534, 863)
        assert abs(pm.tile_heading(h, 1534, 863) - math.atan2(dy, dx)) < 1e-9


def test_a_gap_is_ground_not_seen_lately(book):
    city = (577, 615)
    near, stale = (597, 615), (577, 655)
    _cover(book, city, 150, but=[near])
    book.reach[_key(*stale)]["t"] = time.time() - 7 * 3600
    book.record_wall(577, 575)
    book.reach.pop(_key(577, 575), None)
    gaps = {(x, y) for x, y, _ in book.gaps_near(city, 150, 6.0)}
    keyed = {_key(x, y) for x, y in gaps}
    assert _key(*near) in keyed and _key(*stale) in keyed
    assert _key(577, 575) not in keyed, "a wall is not a gap"
    assert len(gaps) == 2


class Wander(GemFlowMixin):
    def __init__(self, book, cam, city=(577, 615)):
        self.mapmem = book
        self._last_map_xy = cam
        self._city_xy = city
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}


def test_near_gaps_win_more_often_but_not_always(book):
    city = (577, 615)
    near, far = (601, 615), (577, 747)          # 24 and 132 tiles out
    _cover(book, city, 150, but=[near, far])
    w = Wander(book, cam=city)
    random.seed(3)
    picks = {"near": 0, "far": 0}
    for _ in range(400):
        w._sweep_tgt = None                     # force a fresh draw
        t = w._sweep_target()
        picks["near" if _key(*t) == _key(*near) else "far"] += 1
    assert picks["near"] > 3 * picks["far"], picks
    assert picks["far"] > 0, "one route every time is the rail ruled out"


def test_the_target_is_redrawn_even_while_still_a_gap(book):
    city = (577, 615)
    _cover(book, city, 150, but=[(601, 615), (553, 615)])
    w = Wander(book, cam=city)
    w._sweep_target()
    for _ in range(Wander.SWEEP_REDRAW_SCANS):
        w._sweep_target()
    assert w._sweep_age == 0, "held past the redraw count"


def test_a_scan_leans_toward_the_target_by_a_random_amount(book):
    """Target straight up the map (+Y) is screen UP: from a heading of 0
    (screen right) the lean turns part of the way toward -90 degrees."""
    city = (577, 615)
    _cover(book, city, 150, but=[(577, 695)])
    w = Wander(book, cam=city)
    random.seed(1)
    leans = [w._lean_to_sweep(0.0) for _ in range(50)]
    for h in leans:
        assert -math.pi / 2 * 0.61 <= h <= -math.pi / 2 * 0.24, math.degrees(h)
    assert len({round(h, 4) for h in leans}) > 10, "the same lean every time"


def test_no_city_no_lean(book):
    w = Wander(book, cam=(577, 615), city=None)
    assert w._lean_to_sweep(1.0) == 1.0


def test_the_trajectory_is_kept_and_bounded(book):
    for i in range(book.TRACK_MAX + 25):
        book.note_track(500 + i % 7, 600)
    assert len(book.track) == book.TRACK_MAX
    book.save()
    again = MapMemory("4096")
    assert len(again.track) == book.TRACK_MAX


def test_near_ground_wins_even_when_far_ground_is_plentiful(book):
    """The first live target, 2026-09-23 15:50, was 133 tiles out while gaps
    sat next to the city: hundreds of far cells outweighed a few near ones
    one cell at a time. Rings first, then cells."""
    city = (577, 615)
    near = [(593, 615), (561, 615), (577, 631)]          # ~16 tiles out
    far = [(577 + dx, 615 + dy) for dx in range(-150, 151, 8)
           for dy in range(-150, 151, 8)
           if max(abs(dx), abs(dy)) >= 100]              # hundreds of cells
    _cover(book, city, 150, but=near + far)
    assert len(book.gaps_near(city, 150, 6.0)) > 300
    w = Wander(book, cam=city)
    random.seed(11)
    got_near = 0
    for _ in range(400):
        w._sweep_tgt = None
        t = w._sweep_target()
        if max(abs(t[0] - city[0]), abs(t[1] - city[1])) < 40:
            got_near += 1
    assert got_near >= 0.75 * 400, got_near
    assert got_near < 400, "never the far ground: that is a fence, not a sweep"
