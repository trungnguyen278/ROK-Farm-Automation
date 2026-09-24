"""A new sweep target lies near the camera and ahead of it, not across the city.

The operator, 2026-09-24, on the run drawn from 01:42 (tools/dev/run_map.py):
the path cuts across itself again and again -- 16 crossings in 80 views. At
half weight every 80 tiles from the camera, a new target was as likely on
the far side of the city as beside the camera.
"""

import random
import time

import pytest

from rok_farm import pan_model
from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import CELL, MapMemory

CITY = (577, 615)
WIN = {"left": 0, "top": 0, "width": 1534, "height": 863}
RING = 40          # every cell 40 tiles from the city is unseen; the rest seen


@pytest.fixture
def book(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    b = MapMemory("4096")
    b.city = CITY
    now = time.time()
    cx, cy = CITY[0] // CELL, CITY[1] // CELL
    r = 12
    for i in range(cx - r, cx + r + 1):
        for j in range(cy - r, cy + r + 1):
            if max(abs(i - cx), abs(j - cy)) != RING // CELL:
                b.reach[f"{i},{j}"] = {"gem": 0, "empty": 1, "t": now - 60}
    return b


class Farm(GemFlowMixin):
    def __init__(self, book, cam):
        self.mapmem = book
        self._last_map_xy = cam
        self._city_xy = CITY
        self.win = dict(WIN)


NORTH = pan_model.screen_heading(0, 1, WIN["width"], WIN["height"])
EAST_OF_CITY = (CITY[0] + RING, CITY[1])


def _draws(book, heading, n=400, seed=7):
    f = Farm(book, EAST_OF_CITY)
    random.seed(seed)
    out = []
    for _ in range(n):
        f._sweep_tgt = None
        out.append(f._sweep_target(heading))
    return out


def _far(t):
    return max(abs(t[0] - EAST_OF_CITY[0]), abs(t[1] - EAST_OF_CITY[1]))


def test_a_new_target_is_rarely_across_the_city(book):
    """The camera on the ring's east side; its west side lies across the
    city. With the old draw (half every 80 tiles, no heading) 33% of new
    targets were there over 400 draws; now 10-15% across seeds -- the ring
    is still drawn on distance from the city alone, so a ring whose near
    side is all seen can only offer its far side."""
    west = sum(t[0] <= CITY[0] - RING + 7 for t in _draws(book, NORTH))
    assert west < 0.2 * 400, west


def test_a_new_target_lies_ahead_more_often_than_behind(book):
    """Heading north along the ring: north of the camera beats south."""
    targets = _draws(book, NORTH)
    ahead = sum(t[1] > EAST_OF_CITY[1] + 4 for t in targets)
    behind = sum(t[1] < EAST_OF_CITY[1] - 4 for t in targets)
    assert ahead > 2 * behind, (ahead, behind)


def test_behind_is_still_possible_and_the_draw_still_varies(book):
    """Not a rail: the way back is unlikely, never ruled out."""
    targets = _draws(book, NORTH, n=1000)
    assert any(t[1] < EAST_OF_CITY[1] - 4 for t in targets)
    assert len(set(targets)) >= 10


def test_without_a_heading_it_draws_as_before(book):
    """Callers with no heading (tests, the first scan) still get a target."""
    f = Farm(book, EAST_OF_CITY)
    random.seed(1)
    assert f._sweep_target() is not None


def test_each_run_out_of_the_city_draws_its_target_afresh(book):
    f = Farm(book, EAST_OF_CITY)
    f._sweep_tgt = (1, 1)
    f._start_sweep_run()
    assert f._sweep_tgt is None, "the last run's target outlived the run"
