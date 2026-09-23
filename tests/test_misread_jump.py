"""A position read far from the last one waits for the next read to agree.

2026-09-24 00:46:40: "map step: 527 tiles (547,584 -> 538,57)". A Y of 57x
lost its last digit, passed every bounds check, sent the scan home through
the city for nothing and put a view of ground 527 tiles away in the book.
"""

import numpy as np
import pytest

from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import MapMemory, _key

FRAME = np.zeros((863, 1534, 3), np.uint8)


class Scan(GemFlowMixin):
    def __init__(self, book, reads):
        self.mapmem = book
        self._home_map_id = "4096"
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
        self._reads = list(reads)

    def _read_map_position(self, frame=None, full=False):
        return self._reads.pop(0)


@pytest.fixture
def book(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    return MapMemory("4096")


def test_a_dropped_digit_is_held_and_forgotten(book):
    s = Scan(book, [("4096", 547, 584), ("4096", 538, 57), ("4096", 547, 574)])
    assert s._map_sync(FRAME, False, force=True) == (547, 584)
    assert s._map_sync(FRAME, False, force=True) == (547, 584), "believed 538,57"
    assert s._map_sync(FRAME, False, force=True) == (547, 574)
    assert _key(538, 57) not in book.reach, "the misread went into the book"


def test_a_real_move_confirms_itself_on_the_next_read(book):
    s = Scan(book, [("4096", 547, 584), ("4096", 800, 300), ("4096", 803, 305)])
    s._map_sync(FRAME, False, force=True)
    assert s._map_sync(FRAME, False, force=True) == (547, 584)
    assert s._map_sync(FRAME, False, force=True) == (803, 305)
