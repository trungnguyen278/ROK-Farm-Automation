"""Walls come from coordinates now; unreachable ground from the game itself.

The operator, 2026-09-23:
  * the map's edges are known from the coordinates (0-1199), so the two
    learned-wall sources -- a featureless screen, and a change of map id --
    are dropped;
  * a deposit in a zone we cannot enter makes the game carry the camera to
    the pass in the way when Gather is clicked, and no deploy panel opens.
    Remember the ground around it, for as long as the city stays put, and
    join the points into ground rather than leave them scattered.
"""

import inspect
import math
import time
from pathlib import Path

import numpy as np
import pytest

from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import MapMemory
from vision.template_matcher import Match

ROOT = Path(__file__).resolve().parents[1]
CITY = (577, 615)


@pytest.fixture
def book(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    b = MapMemory("4096")
    b.city = CITY
    return b


# --- walls ---------------------------------------------------------------

def test_nothing_writes_learned_walls_any_more():
    for f in (ROOT / "rok_farm").glob("*.py"):
        src = f.read_text(encoding="utf-8")
        assert "record_wall(*" not in src, f.name


def test_all_four_edges_come_from_the_coordinates(book):
    assert book.score(1200, 600) <= -10 and book.score(600, 1205) <= -10
    assert book.score(-1, 600) <= -10
    assert book.blocked(1180, 600, 0.0), "east off the map is not blocked"
    assert book.blocked(600, 1185, math.pi / 2), "north off the map"
    assert not book.blocked(600, 600, 0.0)


class Fogged(GemFlowMixin):
    def __init__(self, pos):
        self._pos = pos

    def _read_map_position(self, frame=None, full=False):
        return self._pos


@pytest.mark.parametrize("pos,void", [(("4096", 577, 615), False),
                                      (("4096", 12, 600), True),
                                      (("4096", 600, 1190), True),
                                      (None, True)])
def test_a_featureless_screen_is_the_void_only_at_the_edge(pos, void):
    assert Fogged(pos)._fog_at_the_edge("frame") is void


# --- unreachable ground ----------------------------------------------------

def test_the_ground_around_an_unreachable_deposit(book):
    book.record_unreachable((700, 800), CITY, (650, 760))
    assert book.unreachable_at(700, 800, CITY)
    assert book.unreachable_at(725, 780, CITY)
    assert not book.unreachable_at(740, 800, CITY)


def test_close_points_join_into_ground(book):
    book.record_unreachable((700, 800), CITY)
    book.record_unreachable((770, 800), CITY)        # 70 apart: same zone
    assert book.unreachable_at(735, 820, CITY), "the strip between is open"


def test_far_points_stay_apart(book):
    book.record_unreachable((700, 800), CITY)
    book.record_unreachable((900, 800), CITY)        # 200 apart
    assert not book.unreachable_at(800, 800, CITY)


def test_it_only_holds_while_the_city_stays(book):
    book.record_unreachable((700, 800), CITY)
    moved = (CITY[0] + 60, CITY[1])
    assert not book.unreachable_at(700, 800, moved)
    book.set_city(*moved)
    assert book.unreachable == [], "a teleport keeps stale reach"


def test_the_sweep_does_not_aim_there_and_the_wander_avoids_it(book):
    book.record_unreachable((620, 660), CITY)
    gaps = book.gaps_near(CITY, 150, 6.0)
    assert not any(max(abs(x - 620), abs(y - 660)) <= 20 for x, y, _ in gaps)
    assert book.score(620, 660) <= -3


class Marcher(GemFlowMixin):
    def __init__(self, book, site, now_at):
        self.mapmem = book
        self._pending_site = site
        self._city_xy = CITY
        self._now_at = now_at

    def _grab(self):
        return np.zeros((863, 1534, 3), np.uint8)

    def _read_map_position(self, frame=None, full=False):
        return self._now_at


def test_carried_off_to_a_pass_marks_the_deposit(book, monkeypatch):
    import rok_farm.flow_steps as fs
    monkeypatch.setattr(fs, "save_screenshot", lambda *a, **k: None)
    m = Marcher(book, ("4096", 700, 800), ("4096", 650, 760))
    assert m._note_if_unreachable("t") is True
    assert book.unreachable_at(700, 800, CITY)


def test_a_panel_that_just_did_not_open_marks_nothing(book, monkeypatch):
    """All eight saved panel failures had the camera still on the deposit."""
    import rok_farm.flow_steps as fs
    monkeypatch.setattr(fs, "save_screenshot", lambda *a, **k: None)
    m = Marcher(book, ("4096", 700, 800), ("4096", 702, 799))
    assert m._note_if_unreachable("t") is False
    assert not book.unreachable_at(700, 800, CITY)


def test_the_panel_failure_asks_the_question():
    src = inspect.getsource(GemFlowMixin._step_click_march)
    i = src.index("Deploy panel never opened after Gather")
    assert "_note_if_unreachable(" in src[i:i + 400]


def test_an_icon_in_that_ground_is_not_clicked(book):
    class Scan(GemFlowMixin):
        def __init__(self):
            self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
            self._marched_sites = []
            self._home_map_id = "4096"
            self.mapmem = book
            self._city_xy = CITY

        def _read_map_position(self, frame=None, full=False):
            return ("4096", 700, 800)
    book.record_unreachable((700, 800), CITY)
    icon = Match("g", 767 - 18, 431 - 24, 36, 48, 0.9, (767, 431))
    why, _x, _y = Scan()._known_at_icon(icon, np.zeros((863, 1534, 3), np.uint8))
    assert why == "in ground we cannot march to"
