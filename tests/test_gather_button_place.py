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

import ast

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


# --- out of band is not the same as "not a mine" (2026-09-13) -------------

def flow_source():
    from rok_farm import PROJECT_ROOT
    return (PROJECT_ROOT / "rok_farm" / "flow_steps.py").read_text(
        encoding="utf-8")


def out_of_band_branch():
    """The `if y_off > GATHER_BTN_MAX_Y_OFFSET:` block, as a syntax tree.

    These tests used to take 1800 characters from the `if` and search them.
    On 2026-09-14 a comment was added inside the refusal and pushed its
    `return False` past the window -- the test failed while the code it
    guards had not changed. The tree holds the structure and no comments.
    """
    for node in ast.walk(ast.parse(flow_source())):
        if (isinstance(node, ast.If)
                and ast.unparse(node.test) == "y_off > GATHER_BTN_MAX_Y_OFFSET"):
            return node
    raise AssertionError("the out-of-band branch is gone")


def test_position_no_longer_refuses_on_its_own():
    """Position is a proxy, and it conflates two different things.

    Photographed the same evening, both out of the gem band:

        y=0.296  "Chua bi chiem dong" -- an EMPTY TILE offering DICH CHUYEN
                 and HANH QUAN, with no gather button at all. The template
                 matched "Hanh quan" at 0.880, higher than most real gem
                 mines. This is the 178.000-troop catastrophe, caught.
        y=0.738  "Trai xe go Cap do 7", reserve 1.417.500, gather button
                 plainly there. A mine -- just not a gem one.

    0.478 and 0.523 sit between them from opposite camps, so no threshold
    separates the two. The words do, and they have already been read by the
    time this branch runs.
    """
    assert "verdict == 'gather'" in ast.unparse(out_of_band_branch()), \
        "the position check still refuses without asking what the button says"

    # and the text must be read BEFORE the position is judged, or there is
    # nothing to ask
    flow = flow_source()
    assert flow.index("verdict = button_verdict(words)") < \
        flow.index("if y_off > GATHER_BTN_MAX_Y_OFFSET:"), \
        "the button text is read after the position check, so the position " \
        "branch cannot consult it"


def test_out_of_band_and_unreadable_still_refuses():
    """Two signals wrong is not the moment to take a chance.

    This guard is the only thing between a 0.880 match on "Hanh quan" and an
    army marched onto bare ground, so silence does not earn the benefit of
    the doubt here the way it does in the band.
    """
    inner = next((n for n in ast.walk(out_of_band_branch())
                  if isinstance(n, ast.If)
                  and ast.unparse(n.test) == "verdict == 'gather'"), None)
    assert inner is not None, "the branch no longer asks what the button says"
    refusal = "\n".join(ast.unparse(s) for s in inner.orelse)
    assert "return False" in refusal, \
        "an out-of-band button that does not read as Gather is allowed through"
    assert "WRONG_PLACE" in refusal


def test_the_accepted_case_leaves_a_frame():
    """It is a deliberate relaxation; the rate it happens at has to be
    visible, or nobody can tell whether it was the right call."""
    from rok_farm import PROJECT_ROOT

    assert "OFFBAND_GATHER" in ast.unparse(out_of_band_branch())

    runner = (PROJECT_ROOT / "rok_farm" / "runner.py").read_text(
        encoding="utf-8")
    assert "OFFBAND_GATHER" in runner, "the frame is swept after three hours"
