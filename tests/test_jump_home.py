"""Far out with near ground still unseen: take the city road back.

2026-09-23 15:48-16:01: the camera sat at a median 146 tiles from the city
(max 208) while 30 of the 121 cells within 40 tiles of it were unseen. The
sweep's lean turns a heading ~10 tiles a scan, and a gem found on the way
ends the mine where it is -- so the camera never got home. The city button
reopens the map on the city in seconds.
"""

import inspect
import random
import time

import pytest

from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import CELL, MapMemory


@pytest.fixture
def book(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    return MapMemory("4096")


def _seen_near(book, city, radius):
    now = time.time()
    cx, cy = city[0] // CELL, city[1] // CELL
    r = radius // CELL
    for i in range(cx - r, cx + r + 1):
        for j in range(cy - r, cy + r + 1):
            book.reach[f"{i},{j}"] = {"gem": 0, "empty": 1, "t": now}


class Farm(GemFlowMixin):
    def __init__(self, book, cam, city=(577, 615)):
        self.mapmem = book
        self._last_map_xy = cam
        self._city_xy = city


def test_far_out_with_near_gaps_goes_home(book, monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.0)
    f = Farm(book, cam=(577, 760))                 # 145 tiles out, nothing seen
    assert f._jump_home_worth_it() is not None


def test_near_ground_covered_means_no_jump(book, monkeypatch):
    """Once the neighbourhood is seen, far is allowed: a route, not a fence."""
    monkeypatch.setattr(random, "random", lambda: 0.0)
    _seen_near(book, (577, 615), 48)
    assert Farm(book, cam=(577, 760))._jump_home_worth_it() is None


def test_close_to_home_never_jumps(book, monkeypatch):
    monkeypatch.setattr(random, "random", lambda: 0.0)
    assert Farm(book, cam=(600, 640))._jump_home_worth_it() is None


def test_not_every_time_and_not_twice_in_a_row(book, monkeypatch):
    f = Farm(book, cam=(577, 760))
    monkeypatch.setattr(random, "random", lambda: 0.99)
    assert f._jump_home_worth_it() is None, "the jump is a chance, not a rule"
    monkeypatch.setattr(random, "random", lambda: 0.0)
    f._last_jump_home = time.time()
    assert f._jump_home_worth_it() is None, "no second jump inside the cooldown"


def test_the_jump_carries_the_mine_on():
    """A road taken on purpose is not a failed mine."""
    src = inspect.getsource(GemFlowMixin._step_scan_and_verify_gem)
    j = src.index("jump = self._jump_home_worth_it()")
    block = src[j:src.index("wander_heading = getattr", j)]
    assert "_step_return_city(" in block and "_step_to_world_map(" in block
    assert block.count("return None") == 1, "the jump ends the mine"
