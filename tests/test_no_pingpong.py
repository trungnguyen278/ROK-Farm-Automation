"""A deposit the scan has just dealt with must not drag the camera back to it.

2026-09-23 15:07-15:19, the first run recording whole views: a gem already
tried sat in cell 72,79 and was counted on every scan that showed it --
gem=24 in twelve minutes. Its score pulled the steering back every scan
("steer: 229 -> 103 deg (score 27.5 > -2.7)") and the camera swung back and
forth over the same twenty tiles for thirty-nine scans -- a pattern no
player makes, and a mine thrown away.
"""

import math
import time

import pytest

from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import MapMemory, _key


@pytest.fixture
def book(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    return MapMemory("4096")


def test_a_cell_just_looked_at_does_not_attract(book):
    book.reach["72,79"] = {"gem": 24, "empty": 10, "t": time.time() - 60}
    assert book.score(580, 636) <= 0


def test_old_evidence_still_counts_but_is_capped(book):
    book.reach["72,79"] = {"gem": 24, "empty": 0, "t": time.time() - 2 * 3600}
    s = book.score(580, 636)
    assert 0 < s <= MapMemory.GEM_CAP * 2.0


def test_a_deposit_seen_over_and_over_counts_once_per_visit(book):
    for _ in range(12):
        book.record_view([(580, 636)], [(580, 636)])
    assert book.reach[_key(580, 636)]["gem"] == 1


class Wander(GemFlowMixin):
    def __init__(self, book, cam):
        self.mapmem = book
        self._last_map_xy = cam
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}


def test_the_camera_does_not_swing_back_to_it(book):
    """The camera has just passed the tried deposit and is heading on; the
    ground ahead is unseen. Before the fix the reverse heading scored ~27
    and won every time."""
    now = time.time()
    # everything around the camera was just scanned, the deposit included
    for i in range(66, 80):
        for j in range(74, 86):
            book.reach[f"{i},{j}"] = {"gem": 0, "empty": 3, "t": now - 30}
    book.reach["72,79"] = {"gem": 24, "empty": 10, "t": now - 30, "tg": now - 30}
    w = Wander(book, cam=(560, 640))       # west of the deposit, heading west
    west = math.pi                          # screen heading: camera moves left
    import random
    random.seed(5)
    turns = 0
    for _ in range(20):
        h = w._steer_heading(west)
        d = math.atan2(math.sin(h - west), math.cos(h - west))
        if abs(d) > math.pi / 2:
            turns += 1
    assert turns == 0, "swung back toward ground it has just scanned"
