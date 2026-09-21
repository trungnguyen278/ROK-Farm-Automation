"""Collecting finished troops and starting the next batch.

Every number in rok_farm/training.py was measured on the frames kept beside
this test, and most of them were measured the second or third time, after the
first attempt pressed the wrong thing. The cases below are exactly those
failures, so they cannot come back quietly:

  * a city frame holds 28 white resource bubbles the same size as the banner;
  * a cherry-blossom plaque is purple enough to pass a loose purple gate;
  * a patch of city wall is a blue hexagon 90px wide;
  * the building menu and the search panel leave the dim ratio at 1.1, so
    "did a panel open" cannot be answered that way;
  * and the orange NGAY button, one click from HUAN LUYEN, costs 1,500 gems.
"""

import cv2
import pytest

from rok_farm import PROJECT_ROOT, training

KEEP = PROJECT_ROOT / "screenshots" / "keep" / "training"

CITY_4_READY = "PROBE_city_122348.png"
CITY_1_READY = "PROBE_city_133758.png"
CITY_NONE_READY = "GO_after_5_134846.png"
MENU_UP = "CONFIRM_no_menu_134129.png"
MENU_UP_2 = "PRESS_before_134513.png"
BUILD_PANEL = "CLOSED_state_133333.png"
TRAIN_PANEL = "PRESS_after_5_134443.png"


def load(name):
    path = KEEP / name
    if not path.is_file():
        pytest.skip(f"{name} is not kept any more")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip(f"{name} did not decode")
    return frame


@pytest.mark.parametrize("name,count", [
    (CITY_4_READY, 4),
    (CITY_1_READY, 1),
    (CITY_NONE_READY, 0),
])
def test_it_counts_the_ready_banners(name, count):
    assert len(training.find_banners(load(name))) == count


def test_resource_bubbles_are_not_mistaken_for_banners():
    """The 12:23 frame carries 16 of them and four real banners."""
    banners = training.find_banners(load(CITY_4_READY))
    assert len(banners) == 4
    # all four sit in the same corner of the city, the bubbles do not
    xs = [b[0] for b in banners]
    ys = [b[1] for b in banners]
    assert max(xs) - min(xs) < 250 and max(ys) - min(ys) < 250


def test_the_click_point_follows_the_banner_size():
    """A pixel offset that worked at one zoom missed at the next."""
    small = (500, 300, 40, 30)
    big = (500, 300, 80, 60)
    assert training.building_point(big)[1] > training.building_point(small)[1]


@pytest.mark.parametrize("name,least", [(MENU_UP, 1), (MENU_UP_2, 2)])
def test_the_menu_buttons_are_found_when_the_menu_is_up(name, least):
    hexes = training.menu_hexes(load(name))
    assert len(hexes) >= least


@pytest.mark.parametrize("name", [CITY_1_READY, CITY_4_READY, BUILD_PANEL])
def test_nothing_is_mistaken_for_the_menu(name):
    """A patch of city wall passed the first cut at 90x73."""
    assert training.menu_hexes(load(name)) == []


def test_the_training_button_is_found_on_the_panel():
    p = training.train_point(load(TRAIN_PANEL))
    assert p is not None
    assert abs(p[0] - 1052) < 12 and abs(p[1] - 620) < 12


def test_the_gem_button_is_never_the_target():
    """HUAN LUYEN is free; NGAY beside it costs 1,500 gems."""
    frame = load(TRAIN_PANEL)
    anchor = training.orange_button(frame)
    assert anchor is not None
    assert training.reads_orange(frame, *anchor), "the anchor is the gem button"
    target = training.train_point(frame)
    assert not training.reads_orange(frame, *target)
    assert target[0] - anchor[0] > 150, "the two are not even far apart"


@pytest.mark.parametrize("name", [CITY_1_READY, MENU_UP, BUILD_PANEL])
def test_no_training_button_when_the_panel_is_not_open(name):
    assert training.train_point(load(name)) is None


def test_the_purple_gate_is_tighter_than_blossom_pink():
    """Blossom sits at hue 165; a band reaching that far caught a plaque."""
    assert training.BANNER_PURPLE_HUE[1] < 160


def test_the_farm_asks_before_clicking_anything():
    """Focus first, window second, and the gem button never.

    The probes this grew from pressed a resource bubble, a building menu and
    the city's build panel before anyone looked at a screenshot, so the phase
    that inherited them is held to checking each step.
    """
    import ast
    import inspect

    import rok_farm.phases as ph

    code = ast.unparse(ast.parse(
        inspect.getsource(ph.PhasesMixin._maybe_train_troops).lstrip()))
    assert "_ensure_game_focused" in code, "it would click into another window"
    assert "_window_check" in code, "it would run outside the run window"
    assert "train_point" in code, "it places HUAN LUYEN some other way"
    assert "dim_ratio" in code, "it never checks the panel actually opened"
    assert "NGAY" not in code and "orange_button" not in code, (
        "the phase reaches for the gem button itself instead of going through "
        "train_point, which refuses when the target reads orange"
    )


def test_it_does_nothing_when_no_batch_is_ready():
    """The common case: the farm passes through the city many times a day."""
    assert training.find_banners(load(CITY_NONE_READY)) == []
