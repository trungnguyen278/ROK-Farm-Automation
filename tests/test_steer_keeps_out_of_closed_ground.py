"""The wander keeps out of ground the farm will not march to.

3560, 2026-09-25: 19% of the views between 10:25 and 11:07 looked at the zone
above the pass, where every deposit is skipped -- the operator on !map: the
track sat round the city instead of keeping out of the disabled zone.
"""

import math

import cv2
import numpy as np
import pytest

from rok_farm import map_memory as mm
from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import MapMemory

CITY = (1113, 548)
PASS = (1126, 554)
WENT = [(1114, 531), (1085, 536), (1108, 536), (1117, 484), (1135, 514),
        (1101, 478), (1066, 485), (1115, 491), (1128, 466), (1103, 488)]
REFUSED = [(1081, 563), (1087, 576), (1137, 581), (1080, 568), (1114, 601)]
NORTH, SOUTH = math.pi / 2, -math.pi / 2          # tile headings: +Y is north


@pytest.fixture
def book(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    grid = np.full((150, 150), 6, np.uint8)
    grid[:504 // 8, :] = 2
    cv2.imwrite(str(tmp_path / "3560_provinces.png"), grid)
    b = MapMemory("3560")
    b.set_city(*CITY)
    for p in WENT:
        b.record_reached(p, CITY)
    for p in REFUSED:
        b.record_unreachable(p, CITY, PASS)
    return b


def test_north_from_the_city_runs_into_the_closed_zone(book):
    assert book.closed_ahead(*CITY, NORTH, CITY)
    assert not book.closed_ahead(*CITY, SOUTH, CITY)


def test_nothing_is_closed_without_a_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    assert not MapMemory("3560").closed_ahead(*CITY, NORTH, CITY)


class Wander(GemFlowMixin):
    def __init__(self, book, at):
        self.mapmem = book
        self._city_xy = CITY
        self._last_map_xy = at
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
        self._sweep_tgt = None

    def _lean_to_sweep(self, heading):
        self._on_sweep = False
        return heading


def screen_north():
    """A screen heading that is north on the map: screen UP (-y on screen)."""
    return -math.pi / 2


def test_the_wander_turns_away_from_the_closed_zone(book):
    from rok_farm import pan_model
    w = Wander(book, CITY)
    out = w._steer_heading(screen_north())
    tile = pan_model.tile_heading(out, 1534, 863)
    assert not book.closed_ahead(*CITY, tile, CITY), math.degrees(tile)


def test_from_inside_the_closed_zone_it_is_not_pinned(book, monkeypatch):
    """Every heading from in there may cross closed cells; the sweep's target
    leads out, so the closed veto stays quiet."""
    import rok_farm.flow_steps as fs
    said = []
    monkeypatch.setattr(fs.logger, "info", lambda msg, *a: said.append(msg % a))
    w = Wander(book, (1100, 590))
    assert book.unreachable_at(1100, 590, CITY)
    w._steer_heading(screen_north())
    assert not any("closed ground ahead" in m for m in said), said


def test_from_the_city_the_veto_says_why(book, monkeypatch):
    import rok_farm.flow_steps as fs
    said = []
    monkeypatch.setattr(fs.logger, "info", lambda msg, *a: said.append(msg % a))
    Wander(book, CITY)._steer_heading(screen_north())
    assert any("closed ground ahead" in m for m in said), said
