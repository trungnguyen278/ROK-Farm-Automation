"""A badge threshold must not care how bright the frame is.

The mask asked for R>150 and G<100 and B<100. Measured on the same mail badge
in two frames from 2026-09-13:

    by day    R 226-236   G 0-7     B 0-4      passes easily
    at night  R 255       G 101     B 101      fails G<100 by ONE unit

ROK's night lighting lifts the whole frame, so an absolute floor ends up
sitting a single value away from a real reading. That is the same mistake as
the 12-scan empty streak (cutting 6.9% of real finds) and the 8-attempt
circling alert (firing on a healthy mine): a threshold pinned to the observed
ceiling measures the ceiling.

Swept over 597 saved frames, the relative test finds a badge on 166 the
absolute one missed and misses 4 it found -- all four 4x15 or 37x22 slivers,
not badges. So the mail button's badge was invisible on 28% of frames, which
is a second reason "checking mail" kept finding nothing.
"""

import cv2
import numpy as np
import pytest

from anti_detection.player_actions import (BADGE_RED_MARGIN, _badge_red,
                                           mail_badge_count)
from rok_farm import PROJECT_ROOT

REFS = PROJECT_ROOT / "screenshots" / "keep" / "feature_refs"


def patch(r, g, b, n=8):
    return np.full((n, n, 3), (b, g, r), dtype=np.uint8)


def test_the_night_badge_passes():
    """R=255 G=101 B=101 -- verbatim, and one unit under the old floor."""
    assert _badge_red(patch(255, 101, 101)).all()


def test_the_day_badge_passes():
    assert _badge_red(patch(230, 3, 2)).all()


def test_plain_bright_ground_does_not():
    """Whiteish and greyish pixels are equally red, green and blue."""
    for v in (60, 120, 200, 255):
        assert not _badge_red(patch(v, v, v)).any(), f"grey {v} reads as badge red"


def test_the_margin_clears_both_readings_by_a_lot():
    """Not fitted to an edge: the two real readings are 154 and 219 apart."""
    assert BADGE_RED_MARGIN < 154 * 0.6, (
        f"{BADGE_RED_MARGIN} is close to the night reading of 154; a threshold "
        f"near a real value is what broke the absolute one")


@pytest.mark.parametrize("name,expected", [
    ("MAPID_S2465_065019.png", 63),
    ("city_idle_return_city_192158.png", 12),
    ("city_idle_return_city_193505.png", 16),
])
def test_the_number_on_the_badge_reads(name, expected):
    """MAPID is the night frame the operator pointed at: it says 63."""
    path = REFS / name
    if not path.is_file():
        pytest.skip(f"{name} is not kept any more")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip(f"{name} did not decode")
    assert mail_badge_count(frame) == expected


def test_a_covered_button_reads_nothing_rather_than_guessing():
    """With the mail panel open the button is behind it. None, not a number."""
    for name in ("MAIL_NO_TAB_BADGES_130505.png", "MAIL_NO_TAB_BADGES_180640.png"):
        path = REFS / name
        if not path.is_file():
            continue
        frame = cv2.imread(str(path))
        if frame is not None:
            assert mail_badge_count(frame) is None, name
