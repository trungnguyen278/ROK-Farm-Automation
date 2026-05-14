"""Tests for vision system: template_cache, template_matcher, state_detector."""

import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vision.template_cache import TemplateCache
from vision.template_matcher import Match, TemplateMatcher
from vision.state_detector import GameScreen, StateDetector


@pytest.fixture
def template_dir(tmp_path):
    """Create a temp dir with synthetic template images."""
    buttons_dir = tmp_path / "buttons"
    buttons_dir.mkdir()
    states_dir = tmp_path / "states"
    states_dir.mkdir()

    red_btn = np.zeros((40, 80, 3), dtype=np.uint8)
    red_btn[:] = (0, 0, 200)
    cv2.rectangle(red_btn, (5, 5), (75, 35), (255, 255, 255), 2)
    cv2.imwrite(str(buttons_dir / "ok.png"), red_btn)

    blue_icon = np.zeros((50, 50, 3), dtype=np.uint8)
    cv2.circle(blue_icon, (25, 25), 20, (200, 100, 0), -1)
    cv2.imwrite(str(states_dir / "city_view.png"), blue_icon)

    green_icon = np.zeros((50, 50, 3), dtype=np.uint8)
    cv2.circle(green_icon, (25, 25), 20, (0, 180, 0), -1)
    cv2.imwrite(str(states_dir / "world_map.png"), green_icon)

    return tmp_path


@pytest.fixture
def cache(template_dir):
    return TemplateCache(str(template_dir), max_size=10)


@pytest.fixture
def matcher(cache):
    return TemplateMatcher(cache, threshold=0.8, scales=[1.0])


# === TemplateCache ===

class TestTemplateCache:
    def test_load_existing(self, cache):
        img = cache.get("buttons/ok")
        assert img is not None
        assert img.shape == (40, 80, 3)

    def test_load_missing(self, cache):
        img = cache.get("buttons/nonexistent")
        assert img is None

    def test_cache_hit(self, cache):
        cache.get("buttons/ok")
        cache.get("buttons/ok")
        assert cache.size == 1

    def test_preload(self, cache):
        cache.preload(["buttons/ok", "states/city_view"])
        assert cache.size == 2

    def test_clear(self, cache):
        cache.get("buttons/ok")
        cache.clear()
        assert cache.size == 0

    def test_eviction(self, template_dir):
        small_cache = TemplateCache(str(template_dir), max_size=2)
        small_cache.get("buttons/ok")
        small_cache.get("states/city_view")
        small_cache.get("states/world_map")
        assert small_cache.size == 2


# === TemplateMatcher ===

class TestTemplateMatcher:
    def _make_frame_with_template(self, cache, name, pos=(100, 80)):
        """Create a 640x480 frame with a template pasted at pos."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (50, 50, 50)  # gray background
        tpl = cache.get(name)
        x, y = pos
        h, w = tpl.shape[:2]
        frame[y : y + h, x : x + w] = tpl
        return frame

    def test_match_single_found(self, matcher, cache):
        frame = self._make_frame_with_template(cache, "buttons/ok", (200, 150))
        m = matcher.match_single(frame, "buttons/ok")
        assert m is not None
        assert m.confidence > 0.95
        assert abs(m.x - 200) < 5
        assert abs(m.y - 150) < 5

    def test_match_single_not_found(self, matcher):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        m = matcher.match_single(frame, "buttons/ok")
        assert m is None

    def test_match_single_missing_template(self, matcher):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        m = matcher.match_single(frame, "buttons/nonexistent")
        assert m is None

    def test_match_all_multiple(self, matcher, cache):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (50, 50, 50)
        tpl = cache.get("buttons/ok")
        h, w = tpl.shape[:2]
        frame[50 : 50 + h, 50 : 50 + w] = tpl
        frame[50 : 50 + h, 300 : 300 + w] = tpl
        results = matcher.match_all(frame, "buttons/ok")
        assert len(results) >= 2

    def test_match_best(self, matcher, cache):
        frame = self._make_frame_with_template(cache, "states/city_view", (100, 100))
        m = matcher.match_best(frame, ["states/city_view", "states/world_map"])
        assert m is not None
        assert m.name == "states/city_view"

    def test_match_returns_named_tuple(self, matcher, cache):
        frame = self._make_frame_with_template(cache, "buttons/ok")
        m = matcher.match_single(frame, "buttons/ok")
        assert hasattr(m, "name")
        assert hasattr(m, "center")
        assert isinstance(m.center, tuple)


# === StateDetector ===

class TestStateDetector:
    def test_detect_city_view(self, matcher, cache):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (50, 50, 50)
        tpl = cache.get("states/city_view")
        frame[100:150, 100:150] = tpl
        detector = StateDetector(matcher)
        state = detector.detect(frame)
        assert state == GameScreen.CITY_VIEW

    def test_detect_unknown(self, matcher):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        detector = StateDetector(matcher)
        state = detector.detect(frame)
        assert state == GameScreen.UNKNOWN

    def test_detect_with_match(self, matcher, cache):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = (50, 50, 50)
        tpl = cache.get("states/city_view")
        frame[100:150, 100:150] = tpl
        detector = StateDetector(matcher)
        state, match = detector.detect_with_match(frame)
        assert state == GameScreen.CITY_VIEW
        assert match is not None
        assert match.confidence > 0.9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
