"""Night on this map is a colour shift, not a dimming.

The bot has had a night path for months -- lift brightness, desaturate the
cast, drop the icon gate from 0.72 to 0.70 -- gated on median brightness below
90. Measured over 58 scan frames spanning many runs, night frames read 128-159
brightness, exactly like day. The path never ran once, so a day-captured gem
template faced a 0.72 gate while matching 0.65-0.71 under the cast, and real
mines went unrecognised for hours.

Hue separates what brightness cannot: day 20-39, night 90-99, and not one frame
in between.
"""

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from vision.color_filter import (NIGHT_HUE_HI, NIGHT_HUE_LO, has_night_cast,
                                 normalize_frame, terrain_hue_sat)


def frame_with(hue, sat=120, val=140):
    """A full frame of one HSV colour, as the terrain band would read."""
    hsv = np.zeros((862, 1533, 3), dtype=np.uint8)
    hsv[:, :, 0] = hue
    hsv[:, :, 1] = sat
    hsv[:, :, 2] = val
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)


def test_the_cyan_cast_of_night_is_detected():
    """Night frames measured on this map sit at hue 90-99."""
    for hue in (90, 92, 95, 99):
        assert has_night_cast(frame_with(hue)), f"hue {hue}"


def test_day_terrain_is_not_night():
    """Day frames measured on this map sit at hue 20-39."""
    for hue in (20, 28, 35, 39):
        assert not has_night_cast(frame_with(hue)), f"hue {hue}"


def test_brightness_alone_would_have_missed_every_one():
    """The whole reason this exists: night is just as bright as day here."""
    from vision.color_filter import NIGHT_BRIGHTNESS_THRESH
    night = frame_with(92, val=140)
    from vision.color_filter import estimate_terrain_brightness
    assert estimate_terrain_brightness(night) >= NIGHT_BRIGHTNESS_THRESH, \
        "this fixture is not reproducing the bug"
    assert has_night_cast(night), "hue must catch what brightness cannot"


def test_a_warm_map_is_not_mistaken_for_night():
    """Desert and autumn terrain sit LOW on the hue scale, not high.

    A rule of "hue above 70" would have been fine here and wrong on a map the
    bot has not seen yet, which is why the check is a band.
    """
    for hue in (5, 12, 18, 25):
        assert not has_night_cast(frame_with(hue)), f"warm hue {hue}"


def test_a_greyscale_frame_has_no_meaningful_hue():
    """Hue is noise when there is no colour; do not act on it."""
    assert not has_night_cast(frame_with(90, sat=5))


def test_the_band_sits_inside_the_measured_gap():
    """Bounds must not be tuned to an edge: day topped out at 39, night began
    at 90, and the band has to sit clear of both."""
    assert 39 < NIGHT_HUE_LO, "the low bound crowds the day cluster"
    assert NIGHT_HUE_HI > 99, "the high bound crowds the night cluster"


def test_normalising_a_night_frame_reports_it_as_night():
    out, is_night = normalize_frame(frame_with(92))
    assert is_night
    assert terrain_hue_sat(out)[1] < terrain_hue_sat(frame_with(92))[1], \
        "the cast should be desaturated, that is the point"


def test_a_day_frame_passes_through_untouched():
    day = frame_with(30)
    out, is_night = normalize_frame(day)
    assert not is_night
    assert out is day, "day frames must not be copied or altered"
