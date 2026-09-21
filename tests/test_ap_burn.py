"""Spending action points on barbarians, and the rules around it.

The operator asked for this on 2026-09-21 and was explicit that the points
themselves hardly matter -- "dai dai di". What matters is that an account
which gathers sixty deposits a day and does nothing else is a strange shape,
and none of the anti-cheat letters has been explained by anything smaller.

Their three constraints, each with a test here:
  * only when the bar is near full, 80% is fine;
  * the auto errors if pressed within two or three minutes of the client
    starting, because it is a VIP feature;
  * closing the client stops the run and sends the troops home -- which is the
    brake, not a problem.
"""

import time

import cv2
import numpy as np
import pytest

from rok_farm import ap_burn


def frame_with_arc(px: int):
    """A black client frame with `px` bright-green pixels in the arc band."""
    im = np.zeros((862, 1533, 3), np.uint8)
    y1, y2, x1, x2 = ap_burn.AP_ARC_BAND
    # Written straight into the frame: reshaping a non-contiguous slice hands
    # back a COPY, so filling that leaves the picture black and the first cut
    # of this test "proved" a full bar reads empty.
    ys, xs = np.divmod(np.arange(px), x2 - x1)
    im[y1 + ys, x1 + xs] = (60, 230, 60)   # BGR green, saturated and bright
    return im


def test_a_full_arc_reads_full():
    assert ap_burn.arc_fill(frame_with_arc(139)) == pytest.approx(1.0, abs=0.02)


def test_a_flat_arc_reads_empty():
    assert ap_burn.arc_fill(frame_with_arc(0)) == 0.0


def test_the_threshold_matches_what_was_asked_for():
    """They said 90%, then that 80% was fine too."""
    assert 0.75 <= ap_burn.AP_BURN_AT <= 0.92


def test_a_half_full_bar_is_left_alone(monkeypatch):
    monkeypatch.setattr(ap_burn, "last_burn", lambda: 0.0)
    assert not ap_burn.due(0.5, gap=2400.0)


def test_a_near_full_bar_is_due(monkeypatch):
    monkeypatch.setattr(ap_burn, "last_burn", lambda: 0.0)
    assert ap_burn.due(0.85, gap=2400.0)


def test_it_does_not_run_twice_in_a_row(monkeypatch):
    """A second attempt a minute later would be a loop, not a decision."""
    monkeypatch.setattr(ap_burn, "last_burn", lambda: time.time() - 60)
    assert not ap_burn.due(1.0, gap=2400.0)


def test_it_may_try_again_within_the_hour(monkeypatch):
    """Six hours was the first guess and it was wrong twice: the operator
    refills the bar from a potion, and a run cut short spends almost nothing,
    so the bar is still full and the wait forbade exactly the retry that was
    wanted."""
    monkeypatch.setattr(ap_burn, "last_burn", lambda: time.time() - 3000)
    assert ap_burn.due(1.0, gap=2400.0)


def test_the_gap_is_not_a_fixed_number():
    lo, hi = ap_burn.AP_MIN_GAP_S
    assert lo < hi, "a fixed spacing between visits is its own pattern"
    assert 1800 <= lo and hi <= 7200


def test_a_run_that_changed_nothing_is_noticed(tmp_path, monkeypatch):
    """If the bar is where it was, the auto found no free march slot."""
    state = tmp_path / "ap.json"
    monkeypatch.setattr(ap_burn, "AP_STATE", state)
    ap_burn.note_burn(1.0)
    assert ap_burn.spent_nothing(0.99)
    assert not ap_burn.spent_nothing(0.40)


def test_nothing_is_claimed_before_the_first_run(tmp_path, monkeypatch):
    monkeypatch.setattr(ap_burn, "AP_STATE", tmp_path / "none.json")
    assert not ap_burn.spent_nothing(1.0)


def test_the_warmup_matches_the_operators_warning():
    """"doi 2 3 phut sau khi vao game thi nhan moi co the su dung"."""
    assert 120 <= ap_burn.AP_WARMUP_S <= 240


def test_the_client_is_shut_long_enough_for_troops_to_walk_back():
    """They put it at about five minutes."""
    lo, hi = ap_burn.AP_AWAY_S
    assert lo >= 240 and hi <= 600


def test_the_dwell_is_random_and_long_enough_to_matter():
    """Two to five minutes was the first guess and the operator rejected it:
    the farm can spare one march slot, so the auto sends one army at a time
    and a few minutes barely touches the bar. Twenty-odd is their number."""
    lo, hi = ap_burn.AP_DWELL_S
    assert lo < hi, "a fixed dwell is a fingerprint"
    assert lo >= 600, "too short to spend anything with a single march slot"
    assert hi <= 2100, "the client is online for all of this"


def test_the_panel_open_check_separates_the_two_states():
    """The search panel does not dim the map, so the usual modal signal is no
    help; the auto button's own blue disc is the tell."""
    open_ = np.zeros((862, 1533, 3), np.uint8)
    h, w = open_.shape[:2]
    x, y = int(w * ap_burn.AUTO_BTN_PCT[0]), int(h * ap_burn.AUTO_BTN_PCT[1])
    cv2.circle(open_, (x, y), 17, (235, 140, 30), -1)     # BGR blue
    assert ap_burn.auto_button_visible(open_)
    assert not ap_burn.auto_button_visible(np.zeros((862, 1533, 3), np.uint8))


def test_the_tab_check_tells_active_from_inactive():
    """Measured: the active tab reads saturation 78, the inactive one 38."""
    assert 38 < ap_burn.TAB_ACTIVE_SAT < 78


def test_the_flow_ends_by_quitting_the_client():
    """Their warning is the brake: closing the client stops the run and sends
    the troops home, so no arithmetic about how many points to spend is needed."""
    import ast
    import inspect

    import rok_farm.phases as ph

    src = inspect.getsource(ph.PhasesMixin._maybe_burn_ap)
    code = ast.unparse(ast.parse(src.lstrip()))
    assert "_restart_game" in code, "it never ends the run"
    assert "note_burn" in code, "it never records that it ran"
    assert "_ensure_game_focused" in code, "it would click into another window"


def test_reading_the_bar_and_spending_it_are_separate():
    """They happen in different places, and that is the whole point.

    The arc is legible only in the CITY, and the barbarian auto can only send
    an army when a march slot is FREE -- which is never true in the city
    phase, because that phase is reached exactly when the queue filled up.
    The first cut had them in one place and would have pressed BAT DAU with
    nowhere to send troops, every single time. The operator caught it: "hang
    cho day sao xa ap duoc".
    """
    import ast
    import inspect

    import rok_farm.phases as ph
    import rok_farm.runner as rn

    city = ast.unparse(ast.parse(
        inspect.getsource(ph.PhasesMixin._phase_city_idle).lstrip()))
    assert "_note_ap_bar" in city, "the city phase no longer reads the bar"
    assert "_maybe_burn_ap" not in city, (
        "the city phase acts on the bar again -- the queue is full there"
    )

    loop = inspect.getsource(rn.GemFarmRunner.run)
    assert "_maybe_burn_ap" in loop, (
        "nothing spends the bar where a march slot is actually free"
    )
    assert "slot(s) free" in loop, "the hook moved away from the free slot"


def test_the_burn_refuses_when_nothing_is_pending():
    """Without a reading from the city it must not act on a guess."""
    import ast
    import inspect

    import rok_farm.phases as ph

    code = ast.unparse(ast.parse(
        inspect.getsource(ph.PhasesMixin._maybe_burn_ap).lstrip()))
    assert "_ap_pending" in code, "it no longer waits to be told"
