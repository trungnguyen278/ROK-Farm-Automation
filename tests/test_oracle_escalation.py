"""The escalation gate: layer 2 is only asked when layer 1 cannot tell.

The point of the whole design is that the model is rare. These tests hold that
line -- a confident local verdict must never spend a call.
"""

import numpy as np
import pytest

from rok_farm import config as cfg
from rok_farm.state_probe import ScreenState, StateProbeMixin
from rok_farm.vision_llm import MockProvider, VisionOracle

MEASURED = {
    "world": {"dim": 1.064, "city_btn": 0.777, "wmcb": 0.742},
    "city": {"dim": 1.178, "city_btn": 0.612, "wmcb": 0.958},
    "panel": {"dim": 4.971, "city_btn": 0.482, "wmcb": 0.444},
    "murky": {"dim": 1.05, "city_btn": 0.30, "wmcb": 0.25},   # nothing matches
}


def frame_with_ratio(ratio, border=120, size=(863, 1533)):
    h, w = size
    frame = np.full((h, w, 3), border, dtype=np.uint8)
    frame[int(h * 0.22):int(h * 0.78), int(w * 0.28):int(w * 0.72)] = \
        min(255, int(border * ratio))
    return frame


class StubRunner(StateProbeMixin):
    def __init__(self, state, oracle=None):
        m = MEASURED[state]
        self._frame = frame_with_ratio(m["dim"])
        self._raw_frame = self._frame
        self._confidences = {"buttons/world_map_city_btn": m["wmcb"],
                             "buttons/city_btn": m["city_btn"]}
        self._activity_samples = [1.0, 1.0, 1.0]
        self._quiet_streak = 0
        self.oracle = oracle

    def _grab(self):
        return self._frame

    def _find_on_frame(self, frame, template, threshold=0.65):
        conf = self._confidences.get(template, 0.0)

        class M:
            confidence = conf
        return M() if conf >= threshold else None


@pytest.fixture
def mock_oracle():
    mock = MockProvider(
        '{"view":"world_map","overlay":"none","covers_hud":false}')
    oracle = VisionOracle([mock])
    oracle._budget.min_gap_s = 0
    return oracle, mock


# --- when the oracle must NOT be called --------------------------------------

def test_confident_city_does_not_escalate(mock_oracle):
    oracle, mock = mock_oracle
    state = StubRunner("city", oracle)._resolve_state()
    assert state.view == "city"
    assert mock.calls == 0, "a confident local verdict must not spend a call"


def test_confident_world_map_does_not_escalate(mock_oracle):
    oracle, mock = mock_oracle
    state = StubRunner("world", oracle)._resolve_state()
    assert state.view == "world_map"
    assert mock.calls == 0


def test_open_panel_does_not_escalate(mock_oracle):
    """A dimmed screen is unambiguous locally; no need to pay for an answer."""
    oracle, mock = mock_oracle
    state = StubRunner("panel", oracle)._resolve_state()
    assert state.overlay == "modal"
    assert mock.calls == 0


# --- when it must ------------------------------------------------------------

def test_unrecognised_screen_escalates(mock_oracle):
    oracle, mock = mock_oracle
    runner = StubRunner("murky", oracle)
    assert runner._probe_state().view == "unknown", "precondition"
    state = runner._resolve_state()
    assert mock.calls == 1
    assert state.view == "world_map", "the model's answer replaces 'unknown'"


def test_escalation_keeps_the_local_alive_verdict(mock_oracle):
    """The model sees one frame; whether the client is animating is not its call."""
    oracle, _ = mock_oracle
    runner = StubRunner("murky", oracle)
    runner._activity_samples = [0.0, 0.0, 0.0]
    for _ in range(cfg.LIVENESS_QUIET_STREAK):
        state = runner._resolve_state()
    assert state.alive is False


def test_no_oracle_configured_falls_back_to_local():
    state = StubRunner("murky", oracle=None)._resolve_state()
    assert isinstance(state, ScreenState)
    assert state.view == "unknown"


def test_disabled_oracle_is_not_called():
    oracle = VisionOracle([])          # no providers -> disabled
    state = StubRunner("murky", oracle)._resolve_state()
    assert state.view == "unknown"


def test_oracle_failure_leaves_the_local_verdict_intact():
    oracle = VisionOracle([MockProvider(fail=True)])
    oracle._budget.min_gap_s = 0
    state = StubRunner("murky", oracle)._resolve_state()
    assert state.view == "unknown", "a failed call must not invent an answer"


def test_oracle_can_report_a_blocking_overlay(mock_oracle):
    oracle, _ = mock_oracle
    oracle._providers[0].reply = (
        '{"view":"city","overlay":"event_popup","covers_hud":true}')
    state = StubRunner("murky", oracle)._resolve_state()
    assert state.blocked is True
    assert state.overlay == "modal"
