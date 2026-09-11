"""Where the gather button is, checked before what it says.

The text guard alone let two combat marches through -- 178.000 and 29.921
troops sent onto ground that was not a gem mine. Both times the wrong button
read as UNREADABLE, and unreadable passes on purpose, so that an OCR hiccup
does not cost a mine.

Position separates them where text cannot. Measured from the log:

    9 clicks that produced normal ~1.000-troop marches   y = 518..534
    2 clicks that sent armies                            y = 257 and 451

on an 862-high window. The popup lands in the same place every time because
clicking a mine centres the camera on it.
"""

import pytest

from rok_farm.config import GATHER_BTN_MAX_Y_OFFSET, GATHER_BTN_Y_PCT

H = 862  # the client height every one of these numbers was measured at

GOOD_Y = [518, 528, 523, 534, 524, 529, 522, 518, 529]
ARMY_Y = [257, 451]


def off(y):
    return abs(y / H - GATHER_BTN_Y_PCT)


@pytest.mark.parametrize("y", GOOD_Y)
def test_every_real_gather_click_is_accepted(y):
    assert off(y) <= GATHER_BTN_MAX_Y_OFFSET, (
        f"y={y} produced a normal march and would now be refused; the guard "
        f"would cost real mines")


@pytest.mark.parametrize("y", ARMY_Y)
def test_the_clicks_that_sent_armies_are_refused(y):
    assert off(y) > GATHER_BTN_MAX_Y_OFFSET, (
        f"y={y} sent a combat march and is still allowed")


def test_the_window_has_real_margin_either_side():
    """Tight to the data on one side and loose on the other is a trap.

    The band must clear the observed spread comfortably, or ordinary jitter
    starts costing mines; and it must still exclude the nearest bad click, or
    it buys nothing.
    """
    worst_good = max(off(y) for y in GOOD_Y)
    best_bad = min(off(y) for y in ARMY_Y)
    assert worst_good < GATHER_BTN_MAX_Y_OFFSET * 0.6, (
        "the furthest legitimate click is close to the limit; jitter will "
        "start refusing real gathers")
    assert best_bad > GATHER_BTN_MAX_Y_OFFSET * 1.2, (
        "the nearest army click is barely outside; the separation is not real")


def test_x_is_not_checked():
    """Legitimate clicks use two different x positions, so checking x would
    refuse half of them."""
    from rok_farm import config
    assert not hasattr(config, "GATHER_BTN_X_PCT"), (
        "an x check was added; measured clicks cluster at about 509 AND 1021, "
        "so the popup flips side and half the gathers would be refused")
