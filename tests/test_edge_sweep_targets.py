"""The sweep never aims at ground by the map's edge that no camera can show.

3560, 2026-09-25: the city 86 tiles from the east edge. The sweep drew
targets at X 1148-1164 while the edge veto (128 tiles then) refused every
heading with east in it, and two mines ended on 18 empty scans each.
"""

from rok_farm import map_memory as mm
from rok_farm.map_memory import MapMemory

CITY = (1113, 548)


def test_no_target_in_the_band_by_the_edge(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    book = MapMemory("3560")
    book.set_city(*CITY)
    gaps = book.gaps_near(CITY, 150, 2.0)
    assert gaps, "no gaps at all"
    e = MapMemory.EDGE_BLIND_TILES
    assert max(x for x, _y, _d in gaps) < 1200 - e
    assert any(x >= 1200 - e - 16 for x, _y, _d in gaps), "the band is too wide"


def test_the_camera_can_still_head_for_the_targets_by_the_edge(tmp_path, monkeypatch):
    import math
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    book = MapMemory("3560")
    assert not book.blocked(*CITY, 0.0), "due east from the city"
    assert not book.blocked(1130, 548, math.pi / 4), "north-east, 70 tiles in"
