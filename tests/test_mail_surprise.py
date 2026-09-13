"""Open the mailbox for mail the farm did not cause, not for mail.

The badge is a COUNT, and most of what lands in it is the farm's own doing --
every gather sends back one "Bao cao thu gom". Asking "is there mail" is why
the old rule opened the mailbox on all 125 calls it was ever given.

The operator's rule, 2026-09-13: compare how much the badge GREW against how
many gathers finished in the same stretch, and open when the difference is
bigger than routine. Their worked example was a badge of 63 against about 40
returns -- 23 unexplained, plainly worth a look.

Their arithmetic assumes the badge was cleared at the previous check, which is
what reading the mail does. The implementation works from the DELTA instead,
so it gives the same answer when the read worked and a sensible one when it
did not.
"""

import pytest

import rok_farm.phases as ph
from rok_farm.config import MAIL_SURPRISE
from rok_farm.phases import PhasesMixin


class Fake(PhasesMixin):
    visible = True          # is there any red on the mail button?

    def _grab(self):
        return "frame"

    def _mail_badge_visible(self, frame):
        return self.visible


@pytest.fixture
def rig(monkeypatch):
    seq = []
    monkeypatch.setattr(ph, "mail_badge_count", lambda frame: seq.pop(0))
    f = Fake()

    def check(badge, gathers):
        seq.append(badge)
        f._gathers_started = gathers
        return f._mail_worth_opening()

    return check


def test_the_first_look_always_happens(rig):
    look, why = rig(5, 0)
    assert look and "first look" in why


def test_mail_the_farm_caused_is_not_worth_opening_for(rig):
    """Five gathers, five reports. Nothing arrived that we did not send."""
    rig(5, 0)
    look, why = rig(10, 5)
    assert not look, why
    assert "0 unexplained" in why


def test_the_operators_example_opens(rig):
    """Badge 63 against about 40 gathers."""
    rig(10, 5)
    look, why = rig(63, 45)
    assert look, why
    assert "13 unexplained" in why


def test_one_gather_one_report_is_routine_however_big_the_badge(rig):
    """The badge being large is not itself a reason -- only its GROWTH is.

    Without this, a mailbox nobody ever reads would open every single time.
    """
    rig(63, 45)
    look, why = rig(64, 46)
    assert not look, why


def test_a_badge_that_fell_re_baselines_instead_of_opening(rig):
    """The account owner reads mail on their phone. That is not a surprise."""
    rig(64, 46)
    look, why = rig(20, 47)
    assert not look
    assert "re-baselining" in why
    # and the new baseline is the lower number, so the next check is sane
    look, why = rig(21, 48)
    assert not look, why


def test_an_unreadable_badge_falls_back_to_opening(rig):
    """Being unable to count is not evidence that nothing is there.

    Failing closed here would let one OCR miss stop the mail being read at
    all, which is the outcome this whole feature exists to prevent.
    """
    rig(10, 5)
    look, why = rig(None, 6)
    assert look and "did not read" in why, why


def test_an_unreadable_badge_does_not_move_the_baseline(rig):
    """Otherwise a miss would be recorded as "the badge is 0" and the next
    real reading would look like an enormous jump."""
    rig(10, 5)
    rig(None, 6)
    look, why = rig(12, 7)
    assert "10->12" in why, why


def test_the_threshold_is_a_knob_not_a_constant_of_nature():
    """Battle reports land in the same tab and the farm does not generate
    them, so some unexplained mail is routine and nobody has measured how
    much. Every check logs its arithmetic so the value can be set from data."""
    assert 3 <= MAIL_SURPRISE <= 30
    src = (ph.__file__)
    body = open(src, encoding="utf-8").read()
    at = body.index("def _mail_worth_opening")
    fn = body[at:body.index("\n    def ", at + 10)]
    assert "unexplained vs" in fn, \
        "the check does not log the arithmetic it used, so the threshold can " \
        "only ever be guessed at"


def test_no_badge_at_all_is_not_called_unreadable(monkeypatch):
    """Live 2026-09-14 01:02: the log said "badge unreadable, falling back",
    and act_mail's own check then found red_px=0 -- no badge it could see.
    Whatever the reason (an empty mailbox, or -- likelier, as it turned out --
    a panel a harvest tap had opened), "unreadable" was the wrong word, and
    the threshold is meant to be tuned from that log.
    """
    monkeypatch.setattr(ph, "mail_badge_count", lambda frame: None)
    f = Fake()
    f.visible = False
    f._gathers_started = 3
    look, why = f._mail_worth_opening()
    assert not look
    assert "no badge" in why and "unreadable" not in why, why


def test_no_badge_does_not_move_the_baseline(monkeypatch):
    """The button may be covered rather than empty, and the saved frames hold
    no example that separates the two yet. Writing 0 while covered would make
    the next real reading look like a jump."""
    seq = [29, None, 31]
    monkeypatch.setattr(ph, "mail_badge_count", lambda frame: seq.pop(0))
    f = Fake()
    f._gathers_started = 0
    f._mail_worth_opening()
    f.visible = False
    f._gathers_started = 1
    f._mail_worth_opening()
    f.visible = True
    f._gathers_started = 2
    look, why = f._mail_worth_opening()
    assert "29->31" in why, why


def test_a_covered_screen_is_not_called_an_empty_mailbox(monkeypatch):
    """Live 2026-09-14 01:52: a harvest tap had opened the road plot's info
    panel, and the check logged "no badge on the mail button". The badge was
    under the panel, not gone -- and a look through a panel must not move the
    baseline either."""
    import numpy as np

    import rok_farm.state_probe as probe

    monkeypatch.setattr(ph, "mail_badge_count", lambda frame: 29)
    monkeypatch.setattr(probe, "dim_ratio", lambda frame: 5.18)

    class Covered(Fake):
        def _grab(self):
            return np.zeros((862, 1533, 3), np.uint8)

    f = Covered()
    f._gathers_started = 0
    look, why = f._mail_worth_opening()
    assert not look
    assert "covers the game" in why, why
    assert f._mail_last_count is None, "a look through a panel moved the baseline"
