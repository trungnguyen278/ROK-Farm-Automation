"""What the farm DOES once it can read the zoom.

Four of the 35 mines in the run of 2026-09-13 failed for one cause -- the
camera sitting at a closer zoom than the icon templates were captured at --
and it showed up as three different-looking failures:

    m8, m28   10 scans, NOT ONE candidate, gave up and walked back to the city
    m33       "FOG (out of kingdom)" over ordinary grass, and a PERMANENT
              wall written into the map book at a place that has none
    m17       the full 18-scan empty streak

All four started, or drifted into, frames whose badge read in the close group
(see test_zoom_gauge). None of the three code paths involved could tell the
wrong zoom from bad luck, because none of them asked.
"""

import re

import pytest

from rok_farm import PROJECT_ROOT
from rok_farm.flow_steps import GemFlowMixin, ZOOM_FIX_ROUNDS

FLOW = (PROJECT_ROOT / "rok_farm" / "flow_steps.py").read_text(encoding="utf-8")


def step1_tail():
    """The branch that runs when we were ALREADY on the world map."""
    start = FLOW.index("def _step_to_world_map")
    end = FLOW.index("def _step_stay_and_rezoom")
    body = FLOW[start:end]
    return body[body.index("if toggled_from_city:"):]


# --- fog: featureless close up is not the map void ------------------------

class FakeFlow(GemFlowMixin):
    """Only what _fog_confirmed touches."""

    def __init__(self, gauge):
        self.gauge = gauge
        self.grabs = 0

    def _is_fog(self, frame):
        return True                      # both frames say featureless

    def _wait(self, _):
        pass

    def _grab(self):
        self.grabs += 1
        return object()

    def read_zoom_gauge(self, frame=None):
        return self.gauge


def test_featureless_at_close_zoom_is_not_fog():
    """m33: plain ground has no features close up. Bailing cost the mine AND
    wrote a wall that no expiry ever removes."""
    assert FakeFlow("close")._fog_confirmed(object()) is False


@pytest.mark.parametrize("gauge", ["icon", None])
def test_featureless_at_icon_zoom_is_still_fog(gauge):
    """The guard must not disarm the detector it is guarding.

    An unreadable gauge keeps the old behaviour: two featureless frames in a
    row at icon zoom are the map void, and that is still worth retreating
    from.
    """
    assert FakeFlow(gauge)._fog_confirmed(object()) is True


def test_one_clear_frame_still_ends_it_before_the_gauge_is_consulted():
    """The mid-load re-check predates this and must keep working."""
    class Loading(FakeFlow):
        def _is_fog(self, frame):
            return self.grabs == 0       # first frame only

    f = Loading("icon")
    assert f._fog_confirmed(object()) is False


# --- step 1: correct the zoom instead of leaving it alone -----------------

def test_step_one_asks_the_hud_instead_of_the_detector():
    tail = step1_tail()
    assert "read_zoom_gauge()" in tail, \
        "step 1 still decides the zoom without measuring it"
    assert "leaving the zoom alone" in tail, \
        "there must still be a do-nothing path for an unreadable gauge"


def test_the_correction_is_bounded_and_re_reads_between_rounds():
    """Unbounded "zoom out until it looks right" is the 0.35x ratchet."""
    tail = step1_tail()
    loop = tail[tail.index("for _ in range(ZOOM_FIX_ROUNDS)"):]
    assert ZOOM_FIX_ROUNDS <= 3
    body = loop[:loop.index("if gauge == \"close\":")]
    assert body.count("read_zoom_gauge()") >= 1, \
        "the loop scrolls without re-measuring, so it cannot know when to stop"
    assert 'if gauge != "close"' in body, "the loop has no exit on success"


def test_the_zoom_in_flag_is_cleared_on_every_path():
    """Leaving it set undid the same zoom-in twice and landed at 121 KM."""
    tail = step1_tail()
    # Twelve spaces of indent: directly in the "already on the world map"
    # branch, not nested inside one of its arms, so no arm can skip it.
    mark = "\n            self._zoomed_in_by_click = False\n"
    assert mark in tail, \
        "the paired-undo flag is not cleared for every arm of the branch"
    assert tail.index(mark) > tail.rindex("_scroll_at_center"), \
        "the flag is cleared before the last scroll, so a correction can " \
        "still leave a second undo armed"


def test_a_stuck_zoom_leaves_a_frame_behind():
    tail = step1_tail()
    assert "ZOOM_STUCK" in tail, \
        "if the scroll does not fix it there is nothing to look at afterwards"


# --- the give-up: fix it here, not by walking back to the city ------------

def scan_giveup():
    start = FLOW.index("def _step_scan_and_verify_gem")
    body = FLOW[start:]
    at = body.index("no_candidate_floor >= NO_CANDIDATE_GIVEUP")
    return body[at:at + 2200]


def test_the_giveup_measures_the_zoom_before_blaming_the_map():
    branch = scan_giveup()
    assert "read_zoom_gauge()" in branch
    assert "zoom gauge" in branch, \
        "the give-up log must say what the gauge read, or the next run is as " \
        "blind as this one"


def test_the_in_place_fix_happens_at_most_once_per_mine():
    """Otherwise a mine that cannot be fixed scrolls out forever."""
    branch = scan_giveup()
    assert "_zoom_fixed_this_mine" in branch
    start = FLOW.index("def _step_scan_and_verify_gem")
    head = FLOW[start:start + 1400]
    assert "_zoom_fixed_this_mine = False" in head, \
        "the once-per-mine flag is never reset, so only the first mine of a " \
        "session can be corrected"


def test_the_giveup_clock_restarts_after_a_correction():
    """Scrolling out on scan 10 and giving up on scan 11 fixes nothing."""
    branch = scan_giveup()
    assert "no_candidate_floor = scan_count" in branch
    start = FLOW.index("def _step_scan_and_verify_gem")
    assert "no_candidate_floor = 0" in FLOW[start:start + 1400]


# --- step 7: stop the leak into the next mine ----------------------------

def rezoom_body():
    start = FLOW.index("def _return_to_icon_zoom")
    return FLOW[start:FLOW.index("\n    def ", start + 10)]


def test_the_post_march_rezoom_checks_that_it_landed():
    """Two of the first seven mines after the gauge shipped arrived zoomed in.

    Step 1 catches that, but only after running its gem check at the wrong
    level -- and the camera had already panned a "full screen" that was a
    fraction of one.
    """
    at = FLOW.index("def _step_stay_and_rezoom")
    step7 = FLOW[at:FLOW.index("\n    def ", at + 10)]
    assert "_return_to_icon_zoom(verify=True)" in step7, \
        "the post-march re-zoom does not check whether it worked"


def test_the_check_happens_before_the_pan():
    """The pan is sized in screen fractions; at the wrong zoom it under-runs.

    Its whole job is to put the just-marched mine out of view, and the same
    mine being clicked again was measured on 2 of 18 mid-burst transitions.
    """
    body = rezoom_body()
    assert body.index("read_zoom_gauge") < body.index("_human_drag"), \
        "the zoom is verified after the pan, so the pan ran at the wrong zoom"


def test_the_scan_loop_path_does_not_pay_for_it():
    """The dud-icon caller fires many times per mine; an OCR each is not free."""
    body = rezoom_body()
    assert "verify: bool = False" in body, \
        "verification is on by default, so the scan loop now pays an OCR per dud"
    at = FLOW.index("def _step_scan_and_verify_gem")
    scan = FLOW[at:FLOW.index("\n    def ", at + 10)]
    for call in re.findall(r"_return_to_icon_zoom\([^)]*\)", scan):
        assert "verify" not in call, \
            f"the scan loop asks for verification on every dud icon: {call}"


def test_that_correction_is_bounded_too():
    body = rezoom_body()
    loop = body[body.index("if verify:"):]
    assert "range(ZOOM_FIX_ROUNDS)" in loop, \
        "the post-march correction can scroll without limit"


def test_a_full_queue_still_undoes_the_zoom():
    """The branch that skipped step 7 entirely.

    "Queue full after march -- skip re-zoom, heading to city next" skipped the
    zoom-out along with the pan, so the camera stayed at the gather's close
    zoom through the city trip, the alt-tab, and into the next mine. Measured
    2026-09-13: mine 16 arrived at close zoom straight after this branch ran
    on mine 15.
    """
    at = FLOW.index("Queue full ({queue[0]}/{queue[1]}) after march")
    branch = FLOW[at:at + 1400]
    end = branch.index("return True")
    assert "_return_to_icon_zoom" in branch[:end], \
        "a full queue still leaves the gather's zoom-in in place for the " \
        "next mine to inherit"
    assert "pan=False" in branch[:end], \
        "the pan is the wasted motion here, and it is no longer skipped"


def test_skipping_the_pan_does_not_skip_the_zoom():
    """pan=False must return AFTER the scroll-out, not before it."""
    body = rezoom_body()
    assert "if not pan:" in body
    assert body.index("_scroll_at_center") < body.index("if not pan:"), \
        "pan=False returns before the zoom-out, so it does nothing at all"
    assert body.index("read_zoom_gauge") < body.index("if not pan:"), \
        "pan=False returns before the verification, so a stuck zoom is missed"
