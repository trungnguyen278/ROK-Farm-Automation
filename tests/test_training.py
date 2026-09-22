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


# --- Four buildings at once ------------------------------------------------
#
# The operator asked what happens when all four troop types finish together.
# The loop handles them one at a time in the same city visit, and it used to
# take banners[0] on every pass -- which is right only while each one clears.
# 2 of the first 3 live runs failed at "no menu after selecting", and a banner
# whose sequence fails is still there, still first, on the next look.

def test_a_stuck_building_does_not_eat_the_other_three():
    banners = [(100, 100, 50, 40), (300, 100, 50, 40),
               (100, 300, 50, 40), (300, 300, 50, 40)]
    tried = []
    picked = []
    for _ in range(len(banners)):
        b = training.not_yet_tried(banners, tried)
        if b is None:
            break
        tried.append((b[0], b[1]))
        picked.append((b[0], b[1]))
    assert picked == [(100, 100), (300, 100), (100, 300), (300, 300)]


def test_a_banner_that_drifts_a_few_pixels_is_still_the_same_one():
    """Re-detection between clicks moves a centre slightly; that is not a
    second building."""
    tried = [(100, 100)]
    assert training.not_yet_tried([(103, 97, 50, 40)], tried) is None


def test_a_neighbour_is_not_mistaken_for_the_one_already_tried():
    tried = [(100, 100)]
    b = training.not_yet_tried([(100 + training.TRAIN_SAME_BANNER_PX + 5,
                                 100, 50, 40)], tried)
    assert b is not None


def test_nothing_left_to_try_stops_rather_than_looping():
    assert training.not_yet_tried([(100, 100, 50, 40)], [(100, 100)]) is None


# --- Not the city ----------------------------------------------------------
#
# 2026-09-22 10:11: the training step ran on a WORLD MAP frame. find_banners
# returned two hits at x 0.967 and 0.969 -- the vertical strip of HUD buttons
# down the right edge, white glyphs on purple, the same signature a "troops
# ready" banner has. The farm clicked one of them, then a patch of open
# ground, then logged "the panel did not open" and did it again for the second
# false banner. Four clicks nobody asked for.

def test_the_right_hand_hud_column_is_not_a_banner():
    frame = load("NOT_A_BANNER_worldmap_101157.png")
    assert training.find_banners(frame) == [], (
        "the world map's HUD buttons are being read as troop banners")


def test_real_banners_are_not_thrown_away_by_that_guard():
    """Measured on the kept city frames: x 0.480 to 0.601, nowhere near the
    HUD column at 0.93."""
    frame = load("PROBE_city_122348.png")
    banners = training.find_banners(frame)
    assert len(banners) == 4, len(banners)
    w = frame.shape[1]
    for b in banners:
        assert b[0] / w < training.BANNER_HUD_X_MAX, b[0] / w


def test_the_training_step_refuses_to_run_off_the_world_map():
    """The guard that matters, since a banner-shaped thing can be anywhere.
    Read off the source: the view check has to come before find_banners."""
    import ast
    import inspect
    from rok_farm.phases import PhasesMixin

    src = inspect.getsource(PhasesMixin._maybe_train_troops).lstrip()
    tree = ast.parse(src)
    world = banners = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "_on_world_map" and world is None:
                world = node.lineno
            if node.func.attr == "find_banners" and banners is None:
                banners = node.lineno
    assert world is not None, "training no longer checks which view it is on"
    assert banners is not None
    assert world < banners, (
        "the view is checked after the banners are read: world=%s banners=%s"
        % (world, banners))
