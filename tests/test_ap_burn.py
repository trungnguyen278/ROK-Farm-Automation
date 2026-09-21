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
from pathlib import Path

import cv2
import numpy as np
import pytest

from rok_farm import ap_burn
from rok_farm import phases as ph
from rok_farm.phases import PhasesMixin


KEEP = Path(__file__).resolve().parents[1] / "screenshots" / "keep" / "ap_arc"


def kept(name):
    """A frame saved out of a live session. Skipped rather than failed when it
    is gone: screenshots/ is not in the repo, so a fresh clone has none."""
    path = KEEP / name
    if not path.exists():
        pytest.skip(f"{name} is not kept any more")
    im = cv2.imread(str(path))
    if im is None:
        pytest.skip(f"{name} did not decode")
    return im


def drawn_arc(fraction: float, value: int = 230):
    """A black client frame with the arc drawn `fraction` of the way round.

    Drawn on the fitted circle rather than as a block of pixels: the measure
    is an angle now, and a rectangle of green is exactly the thing it is
    supposed to refuse.
    """
    im = np.zeros((862, 1533, 3), np.uint8)
    cx, cy = ap_burn.AP_ARC_CENTRE
    empty, full = ap_burn.AP_ARC_SWEEP
    if fraction > 0:
        cv2.ellipse(im, (int(round(cx)), int(round(cy))), (34, 34), 0.0,
                    empty - (empty - full) * fraction, empty,
                    (60, value, 60), 3)
    return im


def test_a_full_arc_reads_full():
    assert ap_burn.arc_fill(drawn_arc(1.0)) == pytest.approx(1.0, abs=0.05)


def test_a_flat_arc_reads_unreadable():
    """No arc is not the same as an empty one, and both mean do not spend."""
    assert ap_burn.arc_fill(drawn_arc(0.0)) == -1.0


def test_the_arc_reads_the_same_on_the_frames_the_operator_called_full():
    """The bug this measure exists for.

    On 2026-09-21 three city frames scored 99%, 67% and 67% by pixel count and
    the operator said all three looked full. Drawing the masks settled it: the
    arcs are the same length, and the two "67%" frames were simply lit
    dimmer, so the old S>150 V>180 gate dropped half their pixels. The
    threshold that decides whether to spend sits at 80%, right between the
    two answers.
    """
    readings = [ap_burn.arc_fill(kept(n)) for n in (
        "city_idle_return_city_143910.png",
        "city_idle_return_city_145339.png",
        "city_idle_return_city_145621.png")]
    assert min(readings) >= 0.90, readings
    assert max(readings) - min(readings) <= 0.10, readings


def test_dimming_the_arc_does_not_move_the_reading():
    """The defect itself, with no saved frame needed to catch it.

    The same arc drawn dim and bright. The old measure counted pixels above a
    fixed brightness, so it read these two as 67% and 99% -- one side of the
    spend threshold each.
    """
    dim = ap_burn.arc_fill(drawn_arc(1.0, value=140))
    bright = ap_burn.arc_fill(drawn_arc(1.0, value=230))
    assert dim == pytest.approx(bright, abs=0.05), (dim, bright)


def test_dimming_a_whole_saved_frame_does_not_move_the_reading():
    """Same thing against a real city frame, lighting taken out of all of it."""
    im = kept("city_idle_return_city_142533.png")
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
    hsv[:, :, 2] = (hsv[:, :, 2] * 0.75).astype(np.uint8)
    dim = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    assert ap_burn.arc_fill(dim) == pytest.approx(ap_burn.arc_fill(im), abs=0.05)


def test_a_partly_spent_arc_reads_part():
    """12:01 on 2026-09-21: the left arm stops a quarter of the way round."""
    assert 0.15 <= ap_burn.arc_fill(kept("city_idle_return_city_120143.png")) <= 0.40


def test_grass_is_not_a_full_bar():
    """On the world map that corner holds terrain, and the count used to read
    it as 44%, 96%, even 152% of a full bar."""
    for name in sorted(p.name for p in KEEP.glob("NOT_AN_ARC_*.png")):
        assert ap_burn.arc_fill(kept(name)) == -1.0, name


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


# --- Watching the queue through the auto run -------------------------------
#
# The operator corrected the arithmetic on 2026-09-21: the auto does not send
# one march, it sends as many as there are free slots, "kha dung bao nhieu
# march da setup truoc do se dung bay nhieu", depending on the queue and on
# how many troops there are. That makes a single sample taken with one slot
# free useless as a rate, and it makes a blind sleep through the dwell the
# wrong shape -- their log has a gathering march coming home every four or
# five minutes, and the auto takes each slot as it frees.

class FakeClock:
    """Time that only moves when something sleeps.

    The first cut of these tests let the fake return from its sleep instantly
    while the dwell measured the real wall clock, so the loop never ran down
    and pytest hung. The stub has to own the clock, not just the sleeping.
    """

    def __init__(self):
        self.now = 1_000_000.0

    def time(self):
        return self.now


class DwellFake(PhasesMixin):
    """A runner that only knows how to sleep and read a queue."""

    def __init__(self, readings, wake_after=None):
        self.readings = list(readings)
        self.wake_after = wake_after
        self.slept = []
        self.clock = FakeClock()

    def _sleep_until_woken(self, seconds, reason):
        self.slept.append(seconds)
        self.clock.now += seconds
        if self.wake_after is not None and len(self.slept) >= self.wake_after:
            return False
        return True

    def _detect_march_queue(self, retries=3):
        return self.readings.pop(0) if self.readings else None

    def dwell(self, seconds, monkeypatch):
        monkeypatch.setattr(ph.time, "time", self.clock.time)
        return self._ap_dwell(seconds)


def test_the_dwell_reads_the_queue_instead_of_sleeping_blind(monkeypatch):
    fake = DwellFake([(4, 5), (5, 5), (5, 5)])
    seen = fake.dwell(300.0, monkeypatch)
    assert seen, "the dwell recorded nothing about the queue"
    assert [u for _, u, _ in seen] == [4, 5, 5]


def test_the_dwell_never_probes_on_a_fixed_beat(monkeypatch):
    """A fixed interval is the fingerprint that drew the warning before."""
    fake = DwellFake([(4, 5)] * 20)
    fake.dwell(1500.0, monkeypatch)
    assert len(set(fake.slept[:-1])) > 1, fake.slept


def test_the_dwell_still_adds_up_to_the_time_it_was_given(monkeypatch):
    fake = DwellFake([(4, 5)] * 40)
    fake.dwell(900.0, monkeypatch)
    assert sum(fake.slept) == pytest.approx(900.0, abs=1.0)


def test_a_wake_request_cuts_the_dwell_short(monkeypatch):
    fake = DwellFake([(4, 5)] * 20, wake_after=2)
    fake.dwell(1800.0, monkeypatch)
    assert sum(fake.slept) < 1800.0


def test_the_dwell_survives_a_queue_that_never_reads(monkeypatch):
    """Queue OCR fails often enough that it cannot be a precondition."""
    fake = DwellFake([])
    assert fake.dwell(200.0, monkeypatch) == []
