"""A deposit out of reach puts its whole province out of reach.

The operator's zones, 2026-09-23/24: clicking Gather on a deposit behind a
pass the alliance does not hold carries the camera to the pass and opens no
deploy panel. The book used to close a 30-tile disc round that deposit; with
the map's provinces surveyed (tools/dev/minimap_zones.py), the whole
province -- except ever the city's own.
"""

import cv2
import numpy as np
import pytest

from rok_farm import map_memory as mm
from rok_farm.map_memory import CELL, MapMemory

CITY = (600, 600)


@pytest.fixture
def books(tmp_path, monkeypatch):
    monkeypatch.setattr(mm, "MEM_DIR", tmp_path)
    return tmp_path


def survey(folder, map_id="4096"):
    """West half province 1, east half 2, a square round the city 3."""
    grid = np.zeros((150, 150), np.uint8)
    grid[:, :75] = 1
    grid[:, 75:] = 2
    grid[65:85, 65:85] = 3               # tiles 520-679 both ways
    cv2.imwrite(str(folder / f"{map_id}_provinces.png"), grid)


def test_the_province_of_a_tile(books):
    survey(books)
    b = MapMemory("4096")
    assert b.province_of(100, 900) == 1
    assert b.province_of(1100, 100) == 2
    assert b.province_of(*CITY) == 3
    assert b.province_of(-5, 10) is None and b.province_of(1300, 10) is None


def test_no_survey_no_provinces(books):
    assert MapMemory("4096").province_of(*CITY) is None


def test_one_deposit_closes_its_whole_province(books):
    survey(books)
    b = MapMemory("4096")
    b.set_city(*CITY)
    b.record_unreachable((1000, 300), CITY)
    assert b.unreachable_at(1150, 1150), "far corner of the same province"
    assert not b.unreachable_at(100, 100), "another province"
    assert not b.unreachable_at(*CITY)


def test_never_the_city_own_province(books):
    """A deposit wrongly taken for out of reach inside the city's province
    closes its disc, as before -- not the ground the sweep lives on."""
    survey(books)
    b = MapMemory("4096")
    b.set_city(*CITY)
    b.record_unreachable((600, 650), CITY)
    assert b.unreachable_at(610, 660), "the disc round it"
    assert not b.unreachable_at(530, 530), "the rest of the city's province"


def test_without_a_survey_it_is_the_disc_again(books):
    b = MapMemory("4096")
    b.set_city(*CITY)
    b.record_unreachable((1000, 300), CITY)
    assert b.unreachable_at(1010, 310)
    assert not b.unreachable_at(1150, 1150)


def test_a_new_city_forgets_it(books):
    """Which provinces are open depends on where the city stands."""
    survey(books)
    b = MapMemory("4096")
    b.set_city(*CITY)
    b.record_unreachable((1000, 300), CITY)
    assert not b.unreachable_at(1150, 1150, city=(200, 900))


def test_the_sweep_skips_the_closed_province(books):
    survey(books)
    b = MapMemory("4096")
    b.set_city(*CITY)
    before = b.gaps_near(CITY, 150, 2.0)
    assert any(b.province_of(x, y) == 2 for x, y, _d in before)
    b.record_unreachable((1000, 300), CITY)
    after = b.gaps_near(CITY, 150, 2.0)
    assert after and not any(b.province_of(x, y) == 2 for x, y, _d in after)


def test_the_home_kingdom_survey_puts_the_city_in_the_centre():
    """data/map_knowledge/4096_provinces.png (2026-09-24), when present:
    the city 577,615 in the smallest province, the standard centre."""
    path = mm.PROJECT_ROOT / "data" / "map_knowledge" / "4096_provinces.png"
    if not path.exists():
        pytest.skip("home kingdom not surveyed on this machine")
    grid = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    ids, counts = np.unique(grid[grid > 0], return_counts=True)
    assert len(ids) == 10
    assert grid[615 // CELL, 577 // CELL] == ids[np.argmin(counts)]


def test_a_closed_province_opens_again_after_the_reach_half_life(books):
    """A pass changes hands: after REACH_HALFLIFE_H the deposit no longer
    closes anything; still closed, the next march there records it again."""
    import time
    survey(books)
    b = MapMemory("4096")
    b.set_city(*CITY)
    b.record_unreachable((1000, 300), CITY)
    b.unreachable[-1]["t"] = time.time() - (mm.REACH_HALFLIFE_H * 3600 + 60)
    assert not b.unreachable_at(1150, 1150)
    assert not b.unreachable_at(1000, 300), "not even its own disc"
    b.record_unreachable((1000, 300), CITY)
    assert b.unreachable_at(1150, 1150)


# --- The city's own province, from where its marches went ------------------
# 3560, 2026-09-24: the city 6 tiles from a pass, the surveyed line 20-30
# tiles off, and the grid gave the city the province the pass closes -- four
# refused deposits there and one that went, never closed.

def test_the_city_province_is_where_its_marches_went(books):
    survey(books)
    b = MapMemory("4096")
    b.set_city(*CITY)                          # the grid: province 3
    for site in [(300, 300), (200, 900), (400, 500)]:
        b.record_reached(site, CITY)           # province 1
    assert b.own_province(CITY) == 1
    b.record_unreachable((620, 620), CITY)     # the grid's city square
    assert b.unreachable_at(560, 670), "3 is not the city's own after all"
    assert not b.unreachable_at(100, 1000), "where the marches went"


def test_a_refusal_closes_the_province_beyond_the_marches_that_went(books):
    """3560, 2026-09-25: 13 marches went in a band the grid gave the closed
    province and 12 were refused; counted against each other they kept the
    whole province open, deep in the zone above included."""
    survey(books)
    b = MapMemory("4096")
    b.set_city(*CITY)
    for site in [(300, 300), (200, 900), (400, 500), (1000, 300)]:
        b.record_reached(site, CITY)           # 1, 1, 1 and 2
    b.record_unreachable((1000, 1000), CITY)   # 2
    assert b.unreachable_at(1150, 600), "far from the march that went"
    assert not b.unreachable_at(1020, 320), "beside the march that went"


def test_without_a_march_the_grid_names_the_city_province(books):
    survey(books)
    b = MapMemory("4096")
    b.set_city(*CITY)
    assert b.own_province(CITY) == 3
    b.record_unreachable((620, 620), CITY)
    assert not b.unreachable_at(560, 670)


def test_marches_that_went_are_kept_and_follow_the_city(books):
    survey(books)
    b = MapMemory("4096")
    b.set_city(*CITY)
    b.record_reached((300, 300), CITY)
    assert MapMemory("4096").own_province(CITY) == 1
    b.set_city(900, 900)
    assert b._reached_points((900, 900)) == []


def test_the_mine_records_each_march_that_went():
    import inspect
    from rok_farm.flow_steps import GemFlowMixin
    src = inspect.getsource(GemFlowMixin)
    at = src.index('logger.info("Marched to deposit %s %d:%d"')
    assert "record_reached" in src[at:at + 600]
