"""How long ground stays covered -- measured, not a starting value.

tools/dev/gem_return.py, 2026-09-24 01:30-07:55, 634 views: cells empty at
one visit showed a new gem at the next on 4.7% after 30-60 min, 6.8% after
60-120 min and 9.9% after 2-4 h, against 6.2% on a first visit. Ground is as
good as unseen after one to two hours; the starting value was 6.
"""

import time

import pytest

from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import CELL, MapMemory

CITY = (577, 615)


def test_ground_is_worth_another_look_after_the_measured_recovery():
    assert 1.0 <= GemFlowMixin.SWEEP_STALE_H <= 2.0


@pytest.fixture
def book(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    b = MapMemory("4096")
    b.city = CITY
    return b


def test_near_ground_seen_three_hours_ago_is_swept_again(book):
    """The night's burst pattern: the rings round the city seen early in the
    session, the scan working further out since. Three hours on, the near
    ground is where the sweep goes -- under the old 6h it was still
    "covered" and the targets stayed out at the frontier."""
    now = time.time()
    cx, cy = CITY[0] // CELL, CITY[1] // CELL
    for i in range(cx - 12, cx + 13):
        for j in range(cy - 12, cy + 13):
            near = max(abs(i - cx), abs(j - cy)) <= 5          # ~40 tiles
            book.reach[f"{i},{j}"] = {"gem": 0, "empty": 1,
                                      "t": now - (3 * 3600 if near else 60)}
    rings = {(i, j) for i in range(cx - 5, cx + 6) for j in range(cy - 5, cy + 6)}

    def gap_cells(stale_h):
        return {(x // CELL, y // CELL)
                for x, y, _d in book.gaps_near(CITY, 150, stale_h)}

    assert rings <= gap_cells(GemFlowMixin.SWEEP_STALE_H)
    assert book.frontier(CITY, GemFlowMixin.SWEEP_STALE_H) == 0
    assert not rings & gap_cells(6.0), "the old window: all still covered"
