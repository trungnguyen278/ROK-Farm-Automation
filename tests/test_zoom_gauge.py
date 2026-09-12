"""The game tells you the zoom; the farm used to guess it from the detector.

"No gem visible" cannot separate barren ground from the wrong zoom, and both
rules built on that guess failed in turn -- zooming out on it walked the view
to 0.35x template scale over a night, and then leaving the zoom alone let a
mine inherit the zoom-in a gather had left behind.

At icon zoom ROK hides the power/resource bar; closer in it puts the power
counter back in front of the coordinates and shoves the badge to the right.
Every text and box below is verbatim from a measurement over the 386 scan
frames saved on the night of 2026-09-13: 356 at icon zoom, 30 close in, with
nothing between 0.19 and 0.52 of the crop width.
"""

import pytest

from rok_farm.queue_ocr import (ICON_ZOOM_BADGE_MAX, badge_left_frac,
                                zoom_verdict)

# POS_ROI spans 0.02..0.26 of a 1533px-wide window.
ROI_W = (0.26 - 0.02) * 1533


def det(left, text, width=120):
    return ([[left, 0], [left + width, 0], [left + width, 30], [left, 30]],
            text, 0.95)


# Left edge in pixels, and the mine it came from. The four mines listed here
# are every mine in that run whose scan frames ever read in the high group --
# and all four failed: m8 and m28 gave up with NOT ONE candidate in 10 scans,
# m33 bailed on "fog" over plain ground, m17 ran its whole 18-scan streak out.
CLOSE_ZOOM_PX = [193, 194, 195]
ICON_ZOOM_PX = [15, 25, 33, 35, 36, 42, 70]


@pytest.mark.parametrize("left", CLOSE_ZOOM_PX)
def test_the_power_counter_pushes_the_badge_right(left):
    """Verbatim: '27.025.422 #S11465X:561Y:460 Q' -- the bar is on screen."""
    boxes = [det(0, "27.025.422", 150), det(left, "#S11465X:561Y:460")]
    assert zoom_verdict(badge_left_frac(boxes, ROI_W)) == "close"


@pytest.mark.parametrize("left", ICON_ZOOM_PX)
def test_at_icon_zoom_the_badge_is_flush_left(left):
    boxes = [det(left, "#S11465X:360Y:488")]
    assert zoom_verdict(badge_left_frac(boxes, ROI_W)) == "icon"


def test_the_threshold_sits_in_the_gap_not_on_an_edge():
    """A threshold touching either group is a threshold fitted to noise."""
    assert max(ICON_ZOOM_PX) / ROI_W < ICON_ZOOM_BADGE_MAX
    assert min(CLOSE_ZOOM_PX) / ROI_W > ICON_ZOOM_BADGE_MAX
    # The gap is a third of the crop wide; nothing was observed inside it.
    assert min(CLOSE_ZOOM_PX) / ROI_W - max(ICON_ZOOM_PX) / ROI_W > 0.3


def test_no_badge_box_means_no_verdict():
    """Six of 386 frames returned no box with a '#' in it.

    The caller must leave the zoom alone there, which is what it already did
    before the gauge existed -- an unreadable gauge is never worse than none.
    """
    assert badge_left_frac([det(10, "27.025.422")], ROI_W) is None
    assert badge_left_frac([], ROI_W) is None
    assert badge_left_frac(None, ROI_W) is None
    assert zoom_verdict(None) is None


def test_a_letter_prefixed_id_without_the_hash_still_counts():
    """OCR drops the '#' sometimes; 'S11465' is still plainly the badge."""
    assert zoom_verdict(badge_left_frac([det(195, "S11465X:336Y:479")],
                                        ROI_W)) == "close"


def test_the_leftmost_matching_box_wins():
    """The badge can split; the gauge is about where it STARTS."""
    boxes = [det(195, "#S11465X:336"), det(300, "Y:479")]
    assert badge_left_frac(boxes, ROI_W) == pytest.approx(195 / ROI_W)


def test_a_zero_width_crop_does_not_divide_by_zero():
    assert badge_left_frac([det(195, "#S11465")], 0) is None


def test_the_gem_counter_is_not_this_signal():
    """Why geometry and not "is the gem total readable".

    On 9 of the 386 frames the gem crop "read" 6, 8, 31, 33 at icon zoom --
    deposit level numbers showing through, not a gem total. Those frames all
    sit in the icon group by geometry, so the gauge is right where a
    gem-counter test would have been wrong.
    """
    for left in ICON_ZOOM_PX:
        boxes = [det(left, "#S11465X:334Y:478")]
        assert zoom_verdict(badge_left_frac(boxes, ROI_W)) == "icon"
