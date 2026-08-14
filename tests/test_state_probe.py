"""Layer 1, locked against the numbers measured on the live client.

Measured 2026-08-14/15 at 1533x863 (logs/state_signals.json):

    state                 frame activity   dim ratio   city_btn   wmcb
    world map (near)          0.867           1.064      0.777    0.742
    city                      0.504           1.178      0.612    0.958
    gather popup              0.088           1.188      0.908    0.618
    alliance panel            0.021           4.775      0.586    0.367
    bag panel                 0.008           4.971      0.482    0.444
    world map (icon zoom)     0.001           1.131      0.787    0.754

The activity column is kept here as evidence, not as an input: it is why this
module has no frame-motion "client froze" detector. The icon-zoom world map is
where the bot spends most of its time and it reads 0.001 -- a healthy screen
indistinguishable from a dead one. See the note in config.py.

No screenshots are committed; the frames here are synthetic and the measured
values are fed in directly.
"""

import numpy as np
import pytest

from rok_farm import config as cfg
from rok_farm.state_probe import ScreenState, StateProbeMixin, dim_ratio

MEASURED = {
    "world_near": {"activity": 0.867, "dim": 1.064, "city_btn": 0.777, "wmcb": 0.742},
    "city": {"activity": 0.504, "dim": 1.178, "city_btn": 0.612, "wmcb": 0.958},
    "gather": {"activity": 0.088, "dim": 1.188, "city_btn": 0.908, "wmcb": 0.618},
    "alliance": {"activity": 0.021, "dim": 4.775, "city_btn": 0.586, "wmcb": 0.367},
    "bag": {"activity": 0.008, "dim": 4.971, "city_btn": 0.482, "wmcb": 0.444},
    "world_icon": {"activity": 0.001, "dim": 1.131, "city_btn": 0.787, "wmcb": 0.754},
    # Nothing matches: the case that escalates to layer 2.
    "murky": {"activity": 0.5, "dim": 1.05, "city_btn": 0.30, "wmcb": 0.25},
}

UNCOVERED = ("world_near", "city", "gather", "world_icon")
COVERED = ("alliance", "bag")
WORLD = ("world_near", "gather", "world_icon")


def frame_with_ratio(ratio: float, border: int = 120, size=(863, 1533)):
    """A synthetic frame whose centre/border brightness is exactly `ratio`."""
    h, w = size
    frame = np.full((h, w, 3), border, dtype=np.uint8)
    frame[int(h * 0.22):int(h * 0.78), int(w * 0.28):int(w * 0.72)] = \
        min(255, int(border * ratio))
    return frame


class StubProbe(StateProbeMixin):
    """StateProbeMixin with its two dependencies stubbed out."""

    def __init__(self, state: str):
        m = MEASURED[state]
        self._frame = frame_with_ratio(m["dim"])
        self._raw_frame = self._frame
        self._confidences = {"buttons/world_map_city_btn": m["wmcb"],
                             "buttons/city_btn": m["city_btn"]}

    def _grab(self):
        return self._frame

    def _find_on_frame(self, frame, template, threshold=0.65):
        conf = self._confidences.get(template, 0.0)

        class M:
            confidence = conf
        return M() if conf >= threshold else None


# --- dim_ratio ---------------------------------------------------------------

def test_dim_ratio_of_a_flat_frame_is_one():
    assert dim_ratio(np.full((863, 1533, 3), 120, dtype=np.uint8)) == pytest.approx(1.0)


def test_dim_ratio_tracks_the_requested_ratio():
    assert dim_ratio(frame_with_ratio(2.0)) == pytest.approx(2.0, rel=0.02)


def test_dim_ratio_survives_a_black_frame():
    assert dim_ratio(np.zeros((863, 1533, 3), dtype=np.uint8)) == 0.0


# --- every measured state classifies correctly -------------------------------

@pytest.mark.parametrize("state", COVERED)
def test_every_measured_modal_is_detected(state):
    assert StubProbe(state)._probe_state().overlay == "modal"


@pytest.mark.parametrize("state", UNCOVERED)
def test_no_uncovered_screen_is_called_a_modal(state):
    assert StubProbe(state)._probe_state().overlay == "none"


@pytest.mark.parametrize("state", WORLD)
def test_world_views_are_recognised(state):
    assert StubProbe(state)._probe_state().view == "world_map"


def test_city_is_recognised():
    assert StubProbe("city")._probe_state().view == "city"


def test_no_frame_is_reported_not_guessed():
    probe = StubProbe("city")
    probe._grab = lambda: None
    state = probe._probe_state()
    assert isinstance(state, ScreenState)
    assert state.view == "unknown" and state.confidence == 0.0


# --- the thresholds still separate the measured states -----------------------

def test_modal_threshold_sits_in_the_gap_between_every_measured_state():
    """Uncovered screens land at 1.06-1.19, full modals at 4.78-4.97."""
    highest_uncovered = max(MEASURED[s]["dim"] for s in UNCOVERED)
    lowest_covered = min(MEASURED[s]["dim"] for s in COVERED)
    assert highest_uncovered < cfg.MODAL_RATIO_MIN < lowest_covered


def test_city_gate_separates_the_two_views():
    """The old margin comparison gave 0.035 on the world map; the absolute
    world_map_city_btn score gives 0.216. Keep using the wider one."""
    worst_world_wmcb = max(MEASURED[s]["wmcb"] for s in WORLD)
    assert worst_world_wmcb < cfg.CITY_WMCB_MIN <= MEASURED["city"]["wmcb"]

    old_margin = abs(MEASURED["world_near"]["city_btn"]
                     - MEASURED["world_near"]["wmcb"])
    new_margin = MEASURED["city"]["wmcb"] - MEASURED["world_near"]["wmcb"]
    assert new_margin > old_margin * 5


def test_there_is_no_frame_motion_health_check():
    """Regression guard for a removed feature, not a style rule.

    Frame motion was tried as a "client froze" signal and measured out of
    existence: the icon-zoom world map reads 0.001 while perfectly healthy, and
    the action on a frozen verdict is to restart the game. Two thresholds were
    tried and both were falsified by the next state measured. If this ever comes
    back it needs a signal that is guaranteed to move -- and the HUD clock is
    not one, it is hidden in the compact mode used at icon zoom.
    """
    assert not hasattr(StateProbeMixin, "_activity")
    assert not hasattr(ScreenState, "alive")
    assert min(MEASURED[s]["activity"] for s in UNCOVERED) < \
        max(MEASURED[s]["activity"] for s in COVERED), \
        "a healthy uncovered screen is quieter than a covered one: no signal exists"
