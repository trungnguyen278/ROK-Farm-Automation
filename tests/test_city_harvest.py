"""The city harvest finds every unobstructed bubble and nothing that is not one.

Frames are the bot's own saved city views; the templates were cut from frames
like them by the operator. Counts are what the merged detector returns at the
production threshold, and each was checked against the picture:

    190516 (day)    20 -- every bubble clear
    205055 (night)  20 -- every bubble clear; an alliance shield scores 0.550
                          and stays out
    192158 (day)    18 -- a wood bubble under a UI label scores 0.756 and is
                          left for the next exit
    193505 (night)  19 -- a crystal under a text banner (0.657) is left, and
                          the quest scroll (0.641) is never tapped
"""

from collections import Counter

import cv2
import numpy as np
import pytest

from rok_farm import PROJECT_ROOT
from rok_farm.city_harvest import (HARVEST_KINDS, HARVEST_THRESHOLD,
                                   find_harvest_bubbles,
                                   load_harvest_templates)

SAMP = PROJECT_ROOT / "screenshots" / "keep" / "operator_samples"
REFS = PROJECT_ROOT / "screenshots" / "keep" / "feature_refs"

DAY = SAMP / "day" / "city_idle_return_city_190516.png"
NIGHT = SAMP / "night" / "city_idle_return_city_205055.png"
FRAMES = [
    (DAY, 20),
    (NIGHT, 20),
    (REFS / "city_idle_return_city_192158.png", 18),
    (REFS / "city_idle_return_city_193505.png", 19),
]
NOT_BUBBLES = [
    (REFS / "city_idle_return_city_193505.png", 625, 725, "the quest scroll"),
    (NIGHT, 1191, 228, "an alliance shield"),
]


@pytest.fixture(scope="module")
def templates():
    t = load_harvest_templates()
    if len(t) < 10:
        pytest.skip("harvest templates are not installed in templates/city")
    return t


def load(path):
    if not path.is_file():
        pytest.skip(f"{path.name} is not kept any more")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip(f"{path.name} did not decode")
    return frame


@pytest.mark.parametrize("path,expected", FRAMES, ids=lambda v: getattr(v, "stem", v))
def test_every_unobstructed_bubble_is_found(path, expected, templates):
    got = find_harvest_bubbles(load(path), templates)
    assert len(got) == expected, (
        f"{path.name}: expected {expected} bubbles, got {len(got)}: "
        f"{sorted((b.x, b.y, round(b.score, 3)) for b in got)}")


@pytest.mark.parametrize("path,x,y,what", NOT_BUBBLES)
def test_things_near_bubbles_are_not_tapped(path, x, y, what, templates):
    got = find_harvest_bubbles(load(path), templates)
    near = [b for b in got if (b.x - x) ** 2 + (b.y - y) ** 2 <= 30 ** 2]
    assert not near, f"{what} at ({x},{y}) would be tapped: {near}"


def test_every_kind_is_found_by_day(templates):
    counts = Counter(b.kind for b in find_harvest_bubbles(load(DAY), templates))
    assert set(counts) == set(HARVEST_KINDS), counts


def test_the_threshold_sits_in_the_gap():
    """Unobstructed bubbles bottom out at 0.826; the best non-clean peak is
    an obstructed bubble at 0.756 -- and the quest scroll is below that."""
    assert 0.756 < HARVEST_THRESHOLD < 0.826


def test_a_blank_frame_taps_nothing(templates):
    blank = np.zeros((862, 1533, 3), np.uint8)
    assert find_harvest_bubbles(blank, templates) == []


def test_it_runs_before_mail_and_only_on_the_way_out():
    src = (PROJECT_ROOT / "rok_farm" / "phases.py").read_text(encoding="utf-8")
    at = src.index("def _check_panels_before_quit")
    body = src[at:src.index("\n    def ", at + 10)]
    doc_end = body.index('"""', body.index('"""') + 3) + 3
    code = body[doc_end:]
    assert "_harvest_city_before_quit()" in code, "the harvest is not called"
    assert code.index("_harvest_city_before_quit()") < code.index("_mail_worth_opening"), \
        "mail runs first, and its panel would cover the bubbles"

    calls = src.count("self._harvest_city_before_quit()")
    assert calls == 1, "the harvest runs from more than the before-quit check"


def test_a_harvest_failure_cannot_stop_the_quit():
    src = (PROJECT_ROOT / "rok_farm" / "phases.py").read_text(encoding="utf-8")
    at = src.index("self._harvest_city_before_quit()")
    window = src[max(0, at - 200):at + 300]
    assert "try:" in window and "except Exception" in window
