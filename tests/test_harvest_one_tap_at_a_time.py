"""The city harvest taps what is on screen NOW, one bubble at a time.

Live 2026-09-14: three exits tapped the same 20 spots, all planned from one
frame, and after two of them something covered the game -- the 01:52 frame
shows the road plot's info panel over the city. A tap only opens that when no
bubble is under it, so taps were landing where a bubble had been.

Measured since, over six exits (02:53-06:04): one tap takes every bubble of
its kind -- 116 bubbles in 29 taps. These tests still drive the harvest
against a city that behaves either way, so a change in the game cannot turn
the taps back onto bare ground.
"""

import random

import cv2
import numpy as np
import pytest

import rok_farm.phases as ph
import rok_farm.screenshots as shots
import rok_farm.state_probe as probe
from rok_farm import PROJECT_ROOT
from rok_farm.city_harvest import (HARVEST_KINDS, HARVEST_NEAREST, Bubble,
                                   load_harvest_templates, pick_next)
from rok_farm.config import MODAL_RATIO_MIN
from rok_farm.phases import PhasesMixin

W, H = 1533, 862
FRAME = np.zeros((H, W, 3), np.uint8)
KEEP = PROJECT_ROOT / "screenshots" / "keep"
ROAD = KEEP / "harvest_panel" / "road_panel_after_harvest_015217.png"
CITIES = [
    KEEP / "operator_samples" / "day" / "city_idle_return_city_190516.png",
    KEEP / "operator_samples" / "night" / "city_idle_return_city_205055.png",
    KEEP / "feature_refs" / "city_idle_return_city_192158.png",
    KEEP / "feature_refs" / "city_idle_return_city_193505.png",
]


def grid():
    """Four bubbles of each kind, well apart."""
    return [Bubble(200 + 110 * i, 150 + 120 * k, 0.9, kind)
            for k, kind in enumerate(HARVEST_KINDS) for i in range(4)]


class City:
    """A city whose taps behave the way the test says the game does."""

    def __init__(self, bubbles, takes="kind", sticky=(), opens=()):
        self.bubbles = list(bubbles)
        self.takes = takes          # "kind": a tap takes its whole kind; "one": itself
        self.sticky = set(sticky)   # spots whose bubble a tap does not take
        self.opens = set(opens)     # spots whose tap opens a panel
        self.covered = False
        self.taps = []
        self.misses = 0

    def tap(self, x, y):
        self.taps.append((x, y))
        hit = next((b for b in self.bubbles
                    if (b.x - x) ** 2 + (b.y - y) ** 2 <= 30 ** 2), None)
        if hit is None:
            # Nothing under the finger: a building, a road, the ground.
            self.misses += 1
            self.covered = True
            return
        if (hit.x, hit.y) in self.opens:
            self.covered = True
            return
        if (hit.x, hit.y) in self.sticky:
            return
        if self.takes == "kind":
            self.bubbles = [b for b in self.bubbles if b.kind != hit.kind]
        else:
            self.bubbles.remove(hit)


class Fake(PhasesMixin):
    def __init__(self, city):
        self.city = city
        self._harvest_templates = [("food", FRAME[:10, :10])]
        self.dismissed = 0

    def _grab(self):
        return FRAME

    def _harvest_look(self, templates):
        if self.city.covered:
            return FRAME, 5.18, None
        return FRAME, 1.2, list(self.city.bubbles)

    def _click_pct(self, px, py, jitter_px=0):
        self.city.tap(px * W, py * H)

    def _dismiss_modal(self):
        self.dismissed += 1
        return False


@pytest.fixture
def run(monkeypatch):
    saved = []
    monkeypatch.setattr(ph.time, "sleep", lambda s: None)
    monkeypatch.setattr(shots, "save_screenshot",
                        lambda frame, tag: saved.append(tag))

    def go(city):
        fake = Fake(city)
        fake._harvest_city_before_quit()
        return fake, saved

    return go


def test_if_a_tap_takes_its_whole_kind_five_taps_do_it_and_none_miss(run):
    city = City(grid(), takes="kind")
    run(city)
    assert city.bubbles == []
    assert len(city.taps) == len(HARVEST_KINDS)
    assert city.misses == 0 and not city.covered


def test_if_a_tap_takes_one_bubble_all_twenty_are_still_collected(run):
    city = City(grid(), takes="one")
    run(city)
    assert city.bubbles == []
    assert len(city.taps) == 20
    assert city.misses == 0 and not city.covered


def test_a_panel_stops_the_harvest_on_the_spot(run):
    bubbles = grid()
    city = City(bubbles, takes="one", opens={(b.x, b.y) for b in bubbles})
    fake, saved = run(city)
    assert len(city.taps) == 1, "it kept tapping on top of a panel"
    assert saved == ["HARVEST_PANEL_OPEN"]
    assert fake.dismissed == 1


def test_a_bubble_that_survives_its_tap_is_tapped_once_and_left(run):
    bubbles = grid()
    stuck = bubbles[7]
    city = City(bubbles, takes="one", sticky={(stuck.x, stuck.y)})
    _, saved = run(city)
    on_stuck = [t for t in city.taps
                if (t[0] - stuck.x) ** 2 + (t[1] - stuck.y) ** 2 <= 30 ** 2]
    assert len(on_stuck) == 1
    assert city.bubbles == [stuck]
    assert "HARVEST_LEFTOVER" in saved
    assert city.misses == 0


def test_a_city_already_covered_is_not_tapped_at_all(run):
    city = City(grid())
    city.covered = True
    run(city)
    assert city.taps == []


def test_the_next_tap_is_one_of_the_nearest():
    last = Bubble(0, 0, 0.9, "food")
    far = [Bubble(1000 + i * 70, 800, 0.9, "gold") for i in range(5)]
    near = [Bubble(70 * (i + 1), 0, 0.9, "wood") for i in range(HARVEST_NEAREST)]

    class Spy:
        seen = None

        def choice(self, seq):
            self.seen = list(seq)
            return self.seen[0]

    spy = Spy()
    pick_next(far + near, last, spy)
    assert sorted(spy.seen, key=lambda b: b.x) == near


def test_the_tap_order_differs_between_exits(run):
    orders = set()
    for seed in range(8):
        random.seed(seed)
        city = City(grid(), takes="one")
        run(city)
        orders.add(tuple(city.taps))
    assert len(orders) > 1


def load(path):
    if not path.is_file():
        pytest.skip(f"{path.name} is not kept any more")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip(f"{path.name} did not decode")
    return frame


def test_the_road_panel_is_covered_and_a_city_full_of_bubbles_is_not():
    """Bubbles are bright, and the cover test compares the middle of the
    screen with its rim, so a city full of them is the case to check."""
    assert probe.dim_ratio(load(ROAD)) >= MODAL_RATIO_MIN
    for path in CITIES:
        ratio = probe.dim_ratio(load(path))
        assert ratio < MODAL_RATIO_MIN, f"{path.name} reads as covered ({ratio:.2f})"


def test_the_real_look_refuses_the_road_panel_and_reads_the_city():
    templates = load_harvest_templates()
    if len(templates) < 10:
        pytest.skip("harvest templates are not installed in templates/city")

    class Look(PhasesMixin):
        def __init__(self, frame):
            self.frame = frame

        def _grab(self):
            return self.frame

    _, ratio, bubbles = Look(load(ROAD))._harvest_look(templates)
    assert bubbles is None, f"a covered frame was read as a city (dim {ratio:.2f})"

    _, ratio, bubbles = Look(load(CITIES[0]))._harvest_look(templates)
    assert bubbles is not None and len(bubbles) == 20, (ratio, bubbles)
