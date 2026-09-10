"""When the deploy gate refuses the chain, it must leave something to look at.

This gate has refused four times across the whole log and not one refusal left
a frame, so the cause is still unknown. Guessing at it is the trap: the obvious
theory is that 4.0s is too tight, and the log refutes that outright -- over 229
successes the panel opened in 2.30s at worst.

Driven with a stub rather than the real runner: no ESP32, no game, no capture.
"""

import numpy as np
import pytest

import rok_farm.flow_steps as fs
from rok_farm.flow_steps import GemFlowMixin


class NeverOpens(GemFlowMixin):
    """The panel that stays shut, which is the case being tested."""

    fast_matcher = None

    def __init__(self):
        self.grabs = 0

    def _wait(self, *a, **k):
        pass

    def _grab(self):
        self.grabs += 1
        return np.zeros((862, 1533, 3), dtype=np.uint8)

    def _match_verify(self, *a, **k):
        return None                      # never matches -> always times out


@pytest.fixture
def saved(monkeypatch):
    calls = []
    monkeypatch.setattr(fs, "save_screenshot",
                        lambda frame, name: calls.append((name, frame)))
    return calls


def test_a_refused_deploy_leaves_a_frame(saved):
    r = NeverOpens()
    assert r._wait_for_troop_panel(timeout=0.3, tag="m7") is False
    assert saved, "the gate refused the chain and saved nothing to look at"
    name, frame = saved[0]
    assert "m7" in name and "TIMEOUT" in name, f"unhelpful name {name!r}"
    assert frame is not None


def test_the_frame_is_named_even_without_a_tag(saved):
    r = NeverOpens()
    assert r._wait_for_troop_panel(timeout=0.3) is False
    assert saved and "TIMEOUT" in saved[0][0]


def test_nothing_is_saved_when_the_panel_opens(saved, monkeypatch):
    """Evidence on refusal only -- a frame per march would bury the log."""
    class Opens(NeverOpens):
        def _match_verify(self, *a, **k):
            class M:
                confidence = 0.99
                center = (int(fs.NEW_TROOP_BTN_PCT[0] * 1533),
                          int(fs.NEW_TROOP_BTN_PCT[1] * 862))
            return M()

    assert Opens()._wait_for_troop_panel(timeout=2.0, tag="m7") is True
    assert not saved
