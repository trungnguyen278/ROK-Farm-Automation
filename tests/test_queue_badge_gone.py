"""No badge on screen means nothing is out -- when the picture says so.

2026-09-29 12:31: every troop was home, the game had hidden the "N/5"
badge, the OCR read nothing, and the farm's burst counter said 5/5. It quit
for 18 minutes and then sat a 15-minute toast vigil with all five slots
free. An empty read is not enough on its own (178 of 205 in September had
troops out), so the blue icon beside the badge decides, on two looks, on a
plain view.
"""

import cv2
import numpy as np
import pytest

import rok_farm.queue_ocr as q
from rok_farm import PROJECT_ROOT
from rok_farm.queue_ocr import QueueMixin

ICON = cv2.imread(str(PROJECT_ROOT / "templates" / "ui" / "queue_badge_icon.png"))


def frame(with_icon: bool):
    """A 1533x862 map-green frame, the icon pasted where the game draws it."""
    f = np.zeros((862, 1533, 3), np.uint8)
    f[:] = (60, 140, 90)
    if with_icon:
        f[122:122 + ICON.shape[0], 1442:1442 + ICON.shape[1]] = ICON
    return f


def test_the_template_is_there():
    assert ICON is not None and ICON.shape[:2] == (26, 25)


def test_the_icon_scores_where_it_sits():
    assert q.badge_icon_score(frame(True)) > 0.95
    assert q.badge_icon_score(frame(False)) < q.BADGE_ABSENT_MAX


def test_the_line_sits_between_the_measurements():
    """0 out scored at most 0.38; troops out on a plain view 0.60 and up."""
    assert 0.38 < q.BADGE_ABSENT_MAX < 0.60


class Reader(QueueMixin):
    def __init__(self, frames, view="world", total=5):
        self.frames = list(frames)
        self.view = view
        if total:
            self._queue_total = total

    def _grab(self):
        return self.frames.pop(0) if len(self.frames) > 1 else self.frames[0]

    def _space_view(self, frame):
        return self.view


@pytest.fixture(autouse=True)
def no_text(monkeypatch):
    """The OCR reads nothing at all, as it does with the badge hidden."""
    monkeypatch.setattr(q, "_OCR_BACKEND", "rapidocr")
    monkeypatch.setattr(q, "_ocr_engine", lambda roi: (None, None))
    monkeypatch.setattr(q.time, "sleep", lambda s: None)
    monkeypatch.setattr(q, "save_screenshot", lambda *a, **k: "x.png")


def test_no_icon_on_a_plain_view_is_nothing_out():
    assert Reader([frame(False)])._detect_march_queue() == (0, 5)


def test_an_icon_that_is_there_keeps_it_unknown():
    """Troops out and the text unreadable: the old answer, no reading."""
    assert Reader([frame(True)])._detect_march_queue() is None


@pytest.mark.parametrize("late", [1, 2])
def test_a_panel_still_sliding_in_is_looked_at_again(late):
    """11:49: the city's right-hand panel half in, no icon yet, five out.
    Any of the three looks finding the icon keeps it unknown."""
    looks = [frame(False)] * 3
    looks[late] = frame(True)
    frames = [frame(False)] * 3 + looks          # three OCR tries, then looks
    assert Reader(frames)._detect_march_queue() is None


def test_a_loading_screen_or_a_notice_is_not_nothing_out():
    """Neither Space glyph: not a view the badge is drawn on."""
    assert Reader([frame(False)], view=None)._detect_march_queue() is None


def test_a_panel_over_the_game_is_not_nothing_out(monkeypatch):
    monkeypatch.setattr(q, "dim_ratio", lambda f: 5.0)       # the bag open: 4.97
    assert Reader([frame(False)])._detect_march_queue() is None


def test_the_city_counts_as_plain():
    assert Reader([frame(False)], view="city")._detect_march_queue() == (0, 5)


def test_without_a_known_total_it_says_nothing():
    assert Reader([frame(False)], total=None)._detect_march_queue() is None


def test_a_good_read_remembers_the_total(monkeypatch):
    monkeypatch.setattr(q, "_ocr_engine",
                        lambda roi: ([[[[0, 0]], "KF53/5", 0.9]], None))
    r = Reader([frame(True)], total=None)
    assert r._detect_march_queue() == (3, 5) and r._queue_total == 5
