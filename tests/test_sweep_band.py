"""Near first, ring by ring: the scan works a band out to the frontier.

A camera past the band pans back toward a target inside it -- it no longer
takes the city road (tests/test_steer_follows_sweep.py).

2026-09-23 16:20-18:00, clean book: rings out to 39 tiles ~100% seen and
40-87 at 75-90%, yet 45 of 220 scans were past 100 tiles and 22 past 140
while the ring at 88-103 was 38-59% seen. Marches within 70 tiles took a
median 4.5 min, past 100 tiles 16.1 min. The operator: near first.
"""

import random
import time

import pytest

from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import CELL, MapMemory

CITY = (577, 615)


@pytest.fixture
def book(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    b = MapMemory("4096")
    b.city = CITY
    return b


def _seen_out_to(book, tiles, share=1.0, seed=0):
    """Mark every ring out to `tiles` seen now (a share of each ring)."""
    rnd = random.Random(seed)
    now = time.time()
    cx, cy = CITY[0] // CELL, CITY[1] // CELL
    r = tiles // CELL
    for i in range(cx - r, cx + r + 1):
        for j in range(cy - r, cy + r + 1):
            if rnd.random() < share:
                book.reach[f"{i},{j}"] = {"gem": 0, "empty": 1, "t": now}


class Farm(GemFlowMixin):
    def __init__(self, book, cam):
        self.mapmem = book
        self._last_map_xy = cam
        self._city_xy = CITY


def test_the_frontier_is_the_first_ring_not_yet_filled(book):
    _seen_out_to(book, 40)
    assert book.frontier(CITY, 6.0) == 48


def test_a_fresh_book_works_right_beside_the_city(book):
    assert book.frontier(CITY, 6.0) == 0


def test_the_band_is_the_frontier_plus_a_margin(book):
    _seen_out_to(book, 40)
    assert Farm(book, cam=CITY)._sweep_band() == 48 + Farm.SWEEP_BAND_MARGIN


def test_the_band_grows_as_the_rings_fill(book):
    """Real scarcity still takes the scan far -- ring by ring."""
    _seen_out_to(book, 136)
    assert Farm(book, cam=CITY)._sweep_band() == 144 + Farm.SWEEP_BAND_MARGIN


def test_unseen_ground_past_the_band_pulls_nothing(book):
    _seen_out_to(book, 40)
    Farm(book, cam=CITY)._sweep_band()
    assert book.score(577, 600 + 150) == 0.0     # 135 out, past band 72
    assert book.score(577, 615 + 60) > 0         # 60 out, inside, unseen


def test_targets_are_drawn_inside_the_band(book):
    _seen_out_to(book, 40, share=0.9, seed=3)
    f = Farm(book, cam=CITY)
    band = f._sweep_band()
    random.seed(2)
    for _ in range(200):
        f._sweep_tgt = None
        t = f._sweep_target()
        assert max(abs(t[0] - CITY[0]), abs(t[1] - CITY[1])) <= band + CELL
