"""The farm's own parameters have to move, or the distribution is the tell.

Randomness with fixed parameters is still a fixed fingerprint: a lognormal
click pause with constant mu and sigma is, over nine thousand samples, MORE
identifiable than a constant, because the parameters can be estimated to
several decimal places.

Measured on this farm's logs, 2026-09-22: the daily median click gap ran 4.99s
to 8.70s across fourteen days. That looks like healthy variation until the
sequence is read -- it falls almost monotonically from 8.70 in early September
to 4.99 today, because the code kept changing underneath it. A development
artefact, not drift, and it stops when the code settles.
"""

import datetime
import json

import pytest

from rok_farm import mood


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(mood, "STATE", tmp_path / "mood.json")


def days(n, account="acct", start=datetime.date(2026, 1, 1)):
    return [mood.today(account, start + datetime.timedelta(days=i))
            for i in range(n)]


def test_a_mood_is_stable_within_the_day():
    """A farm restarted six times must not re-roll its character six times."""
    d = datetime.date(2026, 5, 5)
    first = mood.today("acct", d)
    for _ in range(5):
        assert mood.today("acct", d) == first


def test_it_actually_moves_between_days():
    vals = [m["pace"] for m in days(20)]
    assert len(set(vals)) > 10, vals
    assert max(vals) - min(vals) > 0.05, vals


def test_consecutive_days_resemble_each_other():
    """A walk, not a re-roll. A person tired on Tuesday is often tired on
    Wednesday; independent draws would have no such memory."""
    vals = [m["pace"] for m in days(40)]
    steps = [abs(vals[i] - vals[i - 1]) for i in range(1, len(vals))]
    spread = max(vals) - min(vals)
    assert max(steps) < spread, (
        "a single day can jump the whole range, so this is re-rolling rather "
        "than walking")


def test_it_stays_inside_its_bounds():
    """Drift is a behaviour, not a licence to wander anywhere."""
    lo, hi = mood.BOUNDS
    for m in days(400):
        for dial in mood.DIALS:
            assert lo <= m[dial] <= hi, m


def test_two_accounts_do_not_share_a_mood():
    a = [m["pace"] for m in days(10, "one")]
    b = [m["pace"] for m in days(10, "two")]
    assert a != b


def test_the_dials_are_independent():
    ms = days(30)
    pace = [m["pace"] for m in ms]
    rest = [m["restless"] for m in ms]
    assert pace != rest, "one dial driving both is one dial"


def test_the_safety_limits_are_not_on_a_dial():
    """Drifting a detector threshold or a warm-up turns an anti-detection
    feature into a fault generator."""
    import inspect
    src = inspect.getsource(mood)
    for forbidden in ("WARMUP", "RUN_WINDOW", "BURN_AT", "GIVEUP",
                      "MAINTENANCE", "THRESHOLD"):
        assert forbidden not in src, f"mood reaches for {forbidden}"


def test_the_click_pause_and_the_quit_rhythm_are_on_one():
    """The two that shape what an observer can measure."""
    import inspect
    from rok_farm.input_hid import HidInputMixin
    from rok_farm.phases import PhasesMixin

    assert "mood" in inspect.getsource(HidInputMixin._click)
    assert "mood" in inspect.getsource(PhasesMixin._may_quit_again)
