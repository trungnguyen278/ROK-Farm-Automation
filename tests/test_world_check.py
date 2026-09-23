"""World map or not: the castle glyph's measured gate, and a fresh frame.

2026-09-24 01:41:40, a relaunched client still loading (12%): "Game world is
up (oracle: world_map)" -- the local probe matched the buttons on the stale
raw frame of the session before the quit -- then the castle glyph scored
0.723 on the loading screen against a 0.70 gate, and the mine scanned a
loading screen and a city (m5_scan_00_014146, m5_NO_CANDIDATES_014137).
tools/dev/castle_scores.py: 1162 real world verdicts at 0.95-1.00, 160 false
ones at 0.719-0.783, none between.
"""

import numpy as np

from rok_farm.config import SPACE_CASTLE_MIN
from rok_farm.detect import DetectMixin
from rok_farm.state_probe import StateProbeMixin
from vision.template_matcher import Match


def test_the_gate_sits_in_the_measured_gap():
    assert 0.783 < SPACE_CASTLE_MIN < 0.95


class Matcher:
    def __init__(self, castle, space_map):
        self.scores = {"buttons/space_castle": castle,
                       "buttons/space_map": space_map}

    def match_single(self, crop, name):
        c = self.scores[name]
        return Match(name, 5, 5, 20, 20, c, (15, 15)) if c else None


class Screen(DetectMixin):
    def __init__(self, castle, space_map):
        self.matcher = Matcher(castle, space_map)
        self._raw_frame = np.zeros((863, 1534, 3), np.uint8)

    def _grab(self):
        return self._raw_frame


def test_the_loading_screen_is_not_the_world_map():
    assert not Screen(0.723, 0.0)._on_world_map()      # 01:41:45
    assert not Screen(0.783, 0.0)._on_world_map()      # the highest false one


def test_the_world_map_still_is():
    assert Screen(0.99, 0.0)._on_world_map()
    assert Screen(0.95, 0.0)._on_world_map()           # the lowest real one


def test_the_city_is_not_the_world_map():
    assert not Screen(0.64, 0.85)._on_world_map()


class Probe(StateProbeMixin):
    """Records which frame each button match was run on."""

    def __init__(self, stale):
        self._raw_frame = stale
        self.seen = []

    def _find_on_frame(self, frame, name, threshold=0.0):
        self.seen.append(frame)
        return None


def test_a_frame_handed_in_is_the_frame_judged():
    stale = np.full((90, 160, 3), 200, np.uint8)       # the old world map
    fresh = np.full((90, 160, 3), 90, np.uint8)        # the loading screen
    p = Probe(stale)
    p._probe_state(fresh)
    assert p.seen and all(f is fresh for f in p.seen)
