"""A route, not a fence.

The wander drifted outward all session because unexplored ground scored
NEUTRAL while explored-and-empty scored negative -- so anywhere it had been
repelled it, and nowhere attracted it. With no preference between the unseen
cell next door and the unseen cell two hundred tiles away, it took whichever
the noise picked, and the noise has no memory of where the city is.

My first fix capped the distance. The operator rejected the cap: gems can be
genuinely scarce near the city, and then a long march is the right answer --
"dung gioi han ban kinh qua chi can tao duong di tranh scan thieu thoi tai no
co the khan hiem that va phai chiu xa". So unexplored ground is attractive,
most so near the city, and distance becomes a decision rather than a drift.
"""

import time

import pytest

from rok_farm.map_memory import MapMemory, CELL


@pytest.fixture
def book(tmp_path, monkeypatch):
    m = MapMemory("testmap")
    m.reach = {}
    m.terrain = {}
    m.set_city(500, 500)
    return m


def test_unexplored_ground_is_worth_going_to(book):
    assert book.score(500, 500) > 0


def test_unscanned_beats_picked_over_even_far_away(book):
    book.reach["1,1"] = {"gem": 0, "empty": 3, "t": time.time()}
    near_empty = book.score(CELL, CELL)
    far_unknown = book.score(500 + 400, 500)
    assert far_unknown > near_empty, (far_unknown, near_empty)


def test_nearer_unexplored_is_preferred(book):
    close = book.score(520, 500)
    far = book.score(500 + 300, 500)
    assert close > far
    assert far > 0, "far ground must stay visible or the sweep cannot expand"


def test_a_remembered_gem_still_wins(book):
    """Remembered = seen a while ago. A gem seen minutes ago is one the scan
    has already dealt with and pulls nothing (test_no_pingpong)."""
    key = f"{(500 + 200) // CELL},{500 // CELL}"
    book.reach[key] = {"gem": 2, "empty": 0, "t": time.time() - 2 * 3600}
    assert book.score(500 + 200, 500) > book.score(505, 500)


def test_walls_and_the_void_still_dominate(book):
    book.terrain[f"{520 // CELL},{500 // CELL}"] = {"wall": 1}
    assert book.score(520, 500) <= -10.0
    assert book.score(-5, 500) <= -10.0


def test_without_a_city_it_still_answers(book):
    m = MapMemory("nocity")
    m.reach = {}
    m.terrain = {}
    assert m.score(123, 456) > 0


def test_the_city_reaches_the_book_when_it_is_learned():
    import inspect
    from rok_farm.flow_steps import GemFlowMixin
    src = inspect.getsource(GemFlowMixin._map_sync)
    assert "set_city" in src, (
        "the city is recorded on the runner but never handed to the map book, "
        "so the sweep has no centre to expand from")


def test_the_radius_is_a_safety_net_not_a_cap():
    """Measured: a march past 240 tiles takes 18 minutes against five near
    home, so beyond that the trip back costs less than the next march."""
    from rok_farm.flow_steps import HOME_RADIUS_TILES
    assert HOME_RADIUS_TILES >= 200, (
        f"{HOME_RADIUS_TILES} is a fence again; scarcity near the city has to "
        f"be allowed to push the search outward")
