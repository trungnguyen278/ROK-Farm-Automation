"""The wander drifted halfway across the kingdom and nothing pulled it back.

The operator saw the symptom before any counter did -- "sao tim gem xa the
nhi" -- and asked whether the map was simply barren. It was not. Measured on
kingdom 4096 from 2026-09-20, pairing every deposit with the march time that
followed it:

    0-30 tiles from the city   median  5.3 min
    30-60                      median  5.0 min
    60-100                     median  8.4 min
    100-160                    median 13.0 min
    160-240                    median 13.3 min
    240+                       median 18.1 min

68% of marches were past 60 tiles and 45% past 100, and by evening a round
trip that takes half an hour near home was taking over an hour.

The same evening's log had the fix in it already: "map step: 267 tiles
(844,465 -> 577,582)" straight after a return to the city. The trip resets
the camera; nothing was using that.
"""

import ast
import inspect

import pytest

from rok_farm import flow_steps
from rok_farm.flow_steps import GemFlowMixin, HOME_RADIUS_TILES


class Fake(GemFlowMixin):
    def __init__(self, home=None, here=None):
        if home:
            self._city_xy = home
        if here:
            self._last_map_xy = here


def test_the_radius_is_a_last_resort_not_a_cap():
    """It started at 100 -- where the march time doubles -- and the operator
    rejected that as a fence: scarcity near the city has to be allowed to push
    the search outward. It is 250 now, where a march takes 18 minutes against
    five near home and the trip back costs less than carrying on. The sweep in
    map_memory is what actually keeps the search near the city."""
    assert HOME_RADIUS_TILES >= 200, HOME_RADIUS_TILES


def test_distance_is_unknown_until_both_ends_are():
    assert Fake()._tiles_from_home() is None
    assert Fake(home=(577, 617))._tiles_from_home() is None
    assert Fake(here=(577, 617))._tiles_from_home() is None


def test_it_measures_the_drift():
    f = Fake(home=(577, 617), here=(844, 465))
    assert f._tiles_from_home() == 267


def test_near_home_is_not_a_drift():
    f = Fake(home=(577, 617), here=(600, 640))
    assert f._tiles_from_home() == 23
    assert f._tiles_from_home() <= HOME_RADIUS_TILES


def test_the_scan_walks_back_before_searching_not_after_failing():
    src = inspect.getsource(GemFlowMixin._step_scan_and_verify_gem)
    drift = src.find("_tiles_from_home")
    first_scan = src.find("scan_count = 0")
    assert drift != -1, "the scan no longer checks how far out it is"
    assert drift < first_scan, (
        "the drift check happens after the search has started, which spends "
        "the mine before noticing")


def test_the_city_is_read_the_moment_the_map_opens_on_it():
    """It used to be learned from the first reading after a city trip, which
    the scan only takes every MAP_READ_EVERY-th scan -- after up to four
    scans of dragging. On 2026-09-22/23 that gave 448:621, 532:625 and
    498:664 for a city the survey found at 577,615 on every return."""
    src = inspect.getsource(GemFlowMixin._step_to_world_map)
    toggled = src.find("if toggled_from_city:")
    learn = src.find("_learn_city(")
    assert learn != -1, "nothing reads the city on arrival any more"
    assert toggled != -1 and toggled < learn, (
        "the city is read on arrivals that did not come from the city")
    assert "_expect_home_read" not in inspect.getsource(flow_steps), (
        "the late first-read mechanism is back")


class Reader(GemFlowMixin):
    def __init__(self, pos, home_map=None, misses=0):
        self._pos = pos
        self._misses = misses
        self.reads = 0
        self.mapmem = None
        if home_map:
            self._home_map_id = home_map

    def _read_map_position(self, frame=None, full=False):
        self.reads += 1
        if self.reads <= self._misses:
            return None
        return self._pos

    def _grab(self):
        return "frame"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(flow_steps.time, "sleep", lambda s: None)


def test_a_hud_still_drawing_gets_another_look():
    """2026-09-23 15:31:55: the first read as the map opened saw only the
    resource total ('28.534.274'); the coordinates were not drawn yet."""
    r = Reader(("4096", 577, 615), home_map="4096", misses=2)
    assert r._learn_city("frame") == (577, 615)
    assert r.reads == 3


def test_the_book_keeps_the_city_across_restarts(tmp_path, monkeypatch):
    """A farm restarted on the world map makes no city trip before its first
    mines -- 2026-09-23 15:29 ran three of them with no sweep for want of it."""
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    book = mm.MapMemory("4096")
    book.set_city(577, 615)
    again = mm.MapMemory("4096")
    assert again.city == (577, 615)


def test_the_city_read_sets_home_and_the_camera():
    r = Reader(("4096", 577, 615), home_map="4096")
    assert r._learn_city("frame") == (577, 615)
    assert r._city_xy == (577, 615)
    assert r._last_map_xy == (577, 615), "the camera IS on the city now"
    assert r._tiles_from_home() == 0


def test_home_is_only_taken_from_the_home_kingdom():
    """A read that says another map id is the 8% id misread, not a city."""
    r = Reader(("4093", 577, 615), home_map="4096")
    assert r._learn_city("frame") is None
    assert getattr(r, "_city_xy", None) is None


def test_an_unreadable_hud_teaches_nothing():
    r = Reader(None, home_map="4096")
    assert r._learn_city("frame") is None
    assert getattr(r, "_city_xy", None) is None
