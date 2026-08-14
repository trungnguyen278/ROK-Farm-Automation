"""Layer 1, locked against the numbers measured on the live client.

Measured 2026-08-14 at 1533x863 (logs/state_signals.json):

    state        liveness min   dim ratio   city_btn   world_map_city_btn
    world map        0.867         1.064      0.777          0.742
    city             0.504         1.178      0.612          0.958
    bag panel        0.008         4.971      0.482          0.444

These tests exist so a later threshold change has to face the real data. The
most important one is `test_open_panel_is_not_mistaken_for_a_frozen_client`: a
panel is as static as a crash, and treating that as a dead client would restart
the game every time a panel is opened.

No screenshots are committed -- the frames here are synthetic, and the measured
values are fed in directly.
"""

import numpy as np
import pytest

from rok_farm import config as cfg
from rok_farm.state_probe import ScreenState, StateProbeMixin, dim_ratio

# --- measured fixtures -------------------------------------------------------

MEASURED = {
    "world": {"live_min": 0.867, "dim": 1.064, "city_btn": 0.777, "wmcb": 0.742},
    "city": {"live_min": 0.504, "dim": 1.178, "city_btn": 0.612, "wmcb": 0.958},
    "panel": {"live_min": 0.008, "dim": 4.971, "city_btn": 0.482, "wmcb": 0.444},
}


def frame_with_ratio(ratio: float, border: int = 120, size=(863, 1533)):
    """A synthetic frame whose centre/border brightness is exactly `ratio`."""
    h, w = size
    frame = np.full((h, w, 3), border, dtype=np.uint8)
    centre = min(255, int(border * ratio))
    frame[int(h * 0.22):int(h * 0.78), int(w * 0.28):int(w * 0.72)] = centre
    return frame


class StubProbe(StateProbeMixin):
    """StateProbeMixin with its two dependencies stubbed out."""

    def __init__(self, state: str, activity: float | None):
        m = MEASURED[state]
        self._frame = frame_with_ratio(m["dim"])
        self._raw_frame = self._frame
        self._confidences = {
            "buttons/world_map_city_btn": m["wmcb"],
            "buttons/city_btn": m["city_btn"],
        }
        self._activity_samples = [] if activity is None else [activity] * 3
        self._quiet_streak = 0

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


# --- the measured states classify correctly ----------------------------------

def test_clean_world_map():
    state = StubProbe("world", activity=MEASURED["world"]["live_min"])._probe_state()
    assert state.overlay == "none"
    assert state.view == "world_map"
    assert state.alive is True


def test_clean_city():
    state = StubProbe("city", activity=MEASURED["city"]["live_min"])._probe_state()
    assert state.overlay == "none"
    assert state.view == "city"
    assert state.alive is True


def test_open_panel_reads_as_modal():
    state = StubProbe("panel", activity=MEASURED["panel"]["live_min"])._probe_state()
    assert state.overlay == "modal"
    assert state.blocked is True


def test_open_panel_is_not_mistaken_for_a_frozen_client():
    """The whole reason liveness and the dim ratio are combined.

    A panel is as static as a crashed client (measured 0.008). If stillness
    alone decided, opening the bag would restart the game.
    """
    probe = StubProbe("panel", activity=0.0)
    for _ in range(cfg.LIVENESS_QUIET_STREAK + 3):
        state = probe._probe_state()
    assert state.alive is True, "a covered screen must never read as frozen"
    assert state.overlay == "modal"


def test_a_still_uncovered_screen_does_read_as_frozen():
    probe = StubProbe("city", activity=0.0)
    for _ in range(cfg.LIVENESS_QUIET_STREAK):
        state = probe._probe_state()
    assert state.alive is False


def test_one_quiet_sample_is_not_enough():
    state = StubProbe("city", activity=0.0)._probe_state()
    assert state.alive is True, "a single quiet window must not condemn the client"


def test_no_activity_samples_yet_means_alive():
    state = StubProbe("city", activity=None)._probe_state()
    assert state.alive is True


# --- the thresholds still separate the measured states -----------------------

def test_modal_threshold_sits_between_clean_and_covered():
    clean = max(MEASURED["world"]["dim"], MEASURED["city"]["dim"])
    covered = MEASURED["panel"]["dim"]
    assert clean < cfg.MODAL_RATIO_MIN < covered


def test_liveness_threshold_sits_below_every_live_reading():
    live_floor = min(MEASURED["world"]["live_min"], MEASURED["city"]["live_min"])
    assert cfg.LIVENESS_MIN_DIFF < live_floor


def test_city_gate_separates_the_two_views():
    """The old margin comparison gave 0.035 on the world map; the absolute
    world_map_city_btn score gives 0.216. Keep using the wider one."""
    assert MEASURED["world"]["wmcb"] < cfg.CITY_WMCB_MIN <= MEASURED["city"]["wmcb"]
    old_margin = abs(MEASURED["world"]["city_btn"] - MEASURED["world"]["wmcb"])
    new_margin = MEASURED["city"]["wmcb"] - MEASURED["world"]["wmcb"]
    assert new_margin > old_margin * 5


def test_no_frame_is_reported_not_guessed():
    probe = StubProbe("city", activity=1.0)
    probe._grab = lambda: None
    state = probe._probe_state()
    assert isinstance(state, ScreenState)
    assert state.view == "unknown" and state.confidence == 0.0
