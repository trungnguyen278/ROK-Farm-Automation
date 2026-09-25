"""Beside marches already made, they decide what is out of reach.

3560, 2026-09-25, the operator: "toi o sat mep zone voi zone tren khong vao
duoc" -- the city sits at the edge of its zone and the zone above is closed.
Marches went at Y 531-536 and were refused at Y 563-601, the pass at
1126:554 between; the surveyed province line ran at Y 504, fifty tiles
south, so the grid put both kinds in one province and could not close it.
"""

import numpy as np
import pytest

import cv2

from rok_farm import map_memory as mm
from rok_farm.map_memory import MapMemory

CITY = (1113, 548)
PASS = (1126, 554)
WENT = [(1114, 531), (1085, 536), (1108, 536), (1117, 484), (1135, 514)]
REFUSED = [(1081, 563), (1087, 576), (1137, 581), (1080, 568), (1114, 601)]


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    grid = np.full((150, 150), 6, np.uint8)
    grid[:504 // 8, :] = 2                      # the line fifty tiles south
    cv2.imwrite(str(tmp_path / "3560_provinces.png"), grid)
    b = MapMemory("3560")
    b.set_city(*CITY)
    return b


def test_the_marches_draw_the_line_the_grid_missed(book):
    for p in WENT:
        book.record_reached(p, CITY)
    for p in REFUSED:
        book.record_unreachable(p, CITY, PASS)
    assert not book.unreachable_at(*CITY, CITY)
    assert not book.unreachable_at(1110, 545, CITY), "the city's side"
    assert not book.unreachable_at(1100, 548, CITY)
    assert book.unreachable_at(1100, 560, CITY), "past the pass"
    assert book.unreachable_at(1120, 590, CITY)


def test_refusals_alone_keep_their_disc(book):
    book.record_unreachable((1087, 576), CITY, PASS)
    assert book.unreachable_at(1100, 590, CITY)
    assert not book.unreachable_at(1087, 620, CITY), "44 tiles: past the disc"
