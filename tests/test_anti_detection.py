"""Tests for Phase 4: anti-detection engine."""
from __future__ import annotations

import math
import time
import unittest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


SAMPLE_PROFILE = {
    "name": "test",
    "mouse": {
        "bezier_control_points": 3,
        "speed_base": 400,
        "speed_variance": 150,
        "overshoot_chance": 0.15,
        "overshoot_distance": [5, 15],
        "misclick_chance": 0.01,
        "click_spread": 8,
        "hold_ms": [50, 150],
        "jitter_px": 2,
    },
    "timing": {
        "action_delay_mean": 1200,
        "action_delay_std": 400,
        "micro_pause_chance": 0.2,
        "micro_pause_range": [2000, 5000],
        "typing_delay": [30, 120],
    },
    "session": {
        "farm_duration_mean": 25,
        "farm_duration_std": 8,
        "break_duration_mean": 8,
        "break_duration_std": 3,
        "daily_hours_max": 6,
        "active_window": ["00:00", "23:59"],
        "idle_action_chance": 0.08,
    },
}


# ── ProfileLoader ──

class TestProfileLoader(unittest.TestCase):
    def test_load_default_profile(self):
        from anti_detection.profile_loader import ProfileLoader
        loader = ProfileLoader("profiles/")
        profile = loader.load("default")
        self.assertEqual(profile["name"], "default")
        self.assertIn("mouse", profile)
        self.assertIn("timing", profile)
        self.assertIn("session", profile)

    def test_load_cautious_profile(self):
        from anti_detection.profile_loader import ProfileLoader
        loader = ProfileLoader("profiles/")
        profile = loader.load("cautious")
        self.assertEqual(profile["name"], "cautious")
        self.assertGreater(profile["timing"]["action_delay_mean"], 1200)

    def test_load_aggressive_profile(self):
        from anti_detection.profile_loader import ProfileLoader
        loader = ProfileLoader("profiles/")
        profile = loader.load("aggressive")
        self.assertEqual(profile["name"], "aggressive")
        self.assertLess(profile["timing"]["action_delay_mean"], 1200)

    def test_load_missing_falls_back(self):
        from anti_detection.profile_loader import ProfileLoader
        loader = ProfileLoader("profiles/")
        profile = loader.load("nonexistent_xyz")
        self.assertIn("mouse", profile)
        self.assertIn("timing", profile)

    def test_list_profiles(self):
        from anti_detection.profile_loader import ProfileLoader
        loader = ProfileLoader("profiles/")
        names = loader.list_profiles()
        self.assertIn("default", names)
        self.assertIn("cautious", names)
        self.assertIn("aggressive", names)

    def test_load_random(self):
        from anti_detection.profile_loader import ProfileLoader
        loader = ProfileLoader("profiles/")
        profile = loader.load_random()
        self.assertIn("mouse", profile)
        self.assertIn(profile["name"], ["default", "cautious", "aggressive"])

    def test_deep_merge_fills_missing_keys(self):
        from anti_detection.profile_loader import ProfileLoader
        loader = ProfileLoader("profiles/")
        profile = loader.load("default")
        self.assertIn("bezier_control_points", profile["mouse"])
        self.assertIn("micro_pause_range", profile["timing"])
        self.assertIn("idle_action_chance", profile["session"])


# ── MouseHumanizer ──

class TestMouseHumanizer(unittest.TestCase):
    def setUp(self):
        from anti_detection.mouse_humanizer import MouseHumanizer
        self.h = MouseHumanizer(SAMPLE_PROFILE)

    def test_humanize_move_returns_path(self):
        path = self.h.humanize_move(100, 100, 500, 400)
        self.assertGreater(len(path), 3)
        for x, y, ms in path:
            self.assertIsInstance(x, int)
            self.assertIsInstance(y, int)
            self.assertIsInstance(ms, int)

    def test_path_starts_near_origin(self):
        path = self.h.humanize_move(0, 0, 1000, 1000)
        fx, fy, _ = path[0]
        self.assertLess(abs(fx), 200)
        self.assertLess(abs(fy), 200)

    def test_path_ends_near_target(self):
        path = self.h.humanize_move(0, 0, 500, 500)
        lx, ly, _ = path[-1]
        dist = math.hypot(lx - 500, ly - 500)
        self.assertLess(dist, 50)

    def test_short_move(self):
        path = self.h.humanize_move(100, 100, 101, 100)
        self.assertGreaterEqual(len(path), 1)

    def test_zero_distance(self):
        path = self.h.humanize_move(200, 200, 200, 200)
        self.assertEqual(len(path), 1)
        self.assertEqual(path[0], (200, 200, 0))

    def test_humanize_click_offset(self):
        offsets = [self.h.humanize_click(500, 500) for _ in range(50)]
        ox_vals = [o[0] for o in offsets]
        oy_vals = [o[1] for o in offsets]
        hold_vals = [o[2] for o in offsets]
        self.assertTrue(any(v != 0 for v in ox_vals), "Offsets should have variance")
        for h in hold_vals:
            self.assertGreaterEqual(h, 50)
            self.assertLessEqual(h, 150)

    def test_overshoot_probabilistic(self):
        results = [self.h.should_overshoot() for _ in range(1000)]
        rate = sum(results) / len(results)
        self.assertGreater(rate, 0.05)
        self.assertLess(rate, 0.35)

    def test_misclick_rare(self):
        results = [self.h.should_misclick() for _ in range(1000)]
        rate = sum(results) / len(results)
        self.assertLess(rate, 0.05)

    def test_different_profiles_different_speed(self):
        from anti_detection.mouse_humanizer import MouseHumanizer
        slow_profile = {**SAMPLE_PROFILE, "mouse": {**SAMPLE_PROFILE["mouse"], "speed_base": 100}}
        fast_profile = {**SAMPLE_PROFILE, "mouse": {**SAMPLE_PROFILE["mouse"], "speed_base": 800}}
        h_slow = MouseHumanizer(slow_profile)
        h_fast = MouseHumanizer(fast_profile)
        path_slow = h_slow.humanize_move(0, 0, 500, 500)
        path_fast = h_fast.humanize_move(0, 0, 500, 500)
        total_slow = sum(ms for _, _, ms in path_slow)
        total_fast = sum(ms for _, _, ms in path_fast)
        self.assertGreater(total_slow, total_fast)


# ── TimingEngine ──

class TestTimingEngine(unittest.TestCase):
    def setUp(self):
        from anti_detection.timing_engine import TimingEngine
        self.t = TimingEngine(SAMPLE_PROFILE)

    def test_action_delay_positive(self):
        delays = [self.t.action_delay() for _ in range(100)]
        for d in delays:
            self.assertGreater(d, 0)

    def test_action_delay_in_range(self):
        delays = [self.t.action_delay() for _ in range(200)]
        mean = sum(delays) / len(delays)
        self.assertGreater(mean, 0.5)
        self.assertLess(mean, 3.0)

    def test_micro_pause_sometimes_none(self):
        results = [self.t.micro_pause() for _ in range(100)]
        nones = sum(1 for r in results if r is None)
        non_nones = sum(1 for r in results if r is not None)
        self.assertGreater(nones, 10)
        self.assertGreater(non_nones, 5)

    def test_micro_pause_range(self):
        pauses = [self.t.micro_pause() for _ in range(500)]
        actual = [p for p in pauses if p is not None]
        for p in actual:
            self.assertGreater(p, 1.0)
            self.assertLess(p, 10.0)

    def test_typing_delay_range(self):
        delays = [self.t.typing_delay() for _ in range(100)]
        for d in delays:
            self.assertGreaterEqual(d, 0.030)
            self.assertLessEqual(d, 0.120)

    def test_fatigue_at_zero(self):
        self.assertAlmostEqual(self.t.apply_fatigue(0), 1.0)

    def test_fatigue_at_30_min(self):
        f = self.t.apply_fatigue(30)
        self.assertAlmostEqual(f, 1.25)

    def test_fatigue_at_60_min(self):
        f = self.t.apply_fatigue(60)
        self.assertAlmostEqual(f, 1.5)

    def test_fatigue_caps_at_60(self):
        f = self.t.apply_fatigue(120)
        self.assertAlmostEqual(f, 1.5)


# ── SessionManager ──

class TestSessionManager(unittest.TestCase):
    def test_no_break_initially(self):
        from anti_detection.session_manager import SessionManager
        sm = SessionManager(SAMPLE_PROFILE)
        self.assertFalse(sm.should_take_break())

    def test_daily_not_exceeded_initially(self):
        from anti_detection.session_manager import SessionManager
        sm = SessionManager(SAMPLE_PROFILE)
        self.assertFalse(sm.should_stop_daily())

    def test_session_stats(self):
        from anti_detection.session_manager import SessionManager
        sm = SessionManager(SAMPLE_PROFILE)
        stats = sm.session_stats()
        self.assertIn("session_minutes", stats)
        self.assertIn("daily_active_hours", stats)
        self.assertIn("on_break", stats)
        self.assertIn("action_count", stats)
        self.assertEqual(stats["action_count"], 0)

    def test_record_action(self):
        from anti_detection.session_manager import SessionManager
        sm = SessionManager(SAMPLE_PROFILE)
        sm.record_action()
        sm.record_action()
        sm.record_action()
        self.assertEqual(sm.session_stats()["action_count"], 3)

    def test_idle_action_sometimes_none(self):
        from anti_detection.session_manager import SessionManager
        sm = SessionManager(SAMPLE_PROFILE)
        results = [sm.get_idle_action() for _ in range(200)]
        nones = sum(1 for r in results if r is None)
        non_nones = sum(1 for r in results if r is not None)
        self.assertGreater(nones, 50)
        self.assertGreater(non_nones, 3)

    def test_idle_action_valid_enum(self):
        from anti_detection.session_manager import SessionManager, IdleAction
        sm = SessionManager(SAMPLE_PROFILE)
        for _ in range(100):
            action = sm.get_idle_action()
            if action is not None:
                self.assertIsInstance(action, IdleAction)

    def test_reset(self):
        from anti_detection.session_manager import SessionManager
        sm = SessionManager(SAMPLE_PROFILE)
        sm.record_action()
        sm.record_action()
        sm.reset()
        self.assertEqual(sm.session_stats()["action_count"], 0)

    def test_elapsed_minutes(self):
        from anti_detection.session_manager import SessionManager
        sm = SessionManager(SAMPLE_PROFILE)
        self.assertGreaterEqual(sm.elapsed_minutes, 0)
        self.assertLess(sm.elapsed_minutes, 1)

    def test_active_window_all_day(self):
        from anti_detection.session_manager import SessionManager
        profile = {**SAMPLE_PROFILE, "session": {**SAMPLE_PROFILE["session"],
                   "active_window": ["00:00", "23:59"]}}
        sm = SessionManager(profile)
        self.assertFalse(sm.should_stop_daily())

    def test_break_with_short_farm_duration(self):
        from anti_detection.session_manager import SessionManager
        profile = {**SAMPLE_PROFILE, "session": {**SAMPLE_PROFILE["session"],
                   "farm_duration_mean": 1, "farm_duration_std": 0.001}}
        sm = SessionManager(profile)
        sm._session_start = time.monotonic() - 90
        self.assertTrue(sm.should_take_break())


# ── Integration: Humanized vs Raw ──

class TestHumanizedVsRaw(unittest.TestCase):
    def test_path_has_variance(self):
        from anti_detection.mouse_humanizer import MouseHumanizer
        h = MouseHumanizer(SAMPLE_PROFILE)
        paths = [h.humanize_move(0, 0, 500, 500) for _ in range(5)]
        all_x = [[s[0] for s in p] for p in paths]
        self.assertFalse(all(x == all_x[0] for x in all_x),
                         "Paths should differ between runs")

    def test_click_has_variance(self):
        from anti_detection.mouse_humanizer import MouseHumanizer
        h = MouseHumanizer(SAMPLE_PROFILE)
        clicks = [h.humanize_click(500, 500) for _ in range(20)]
        ox_vals = set(c[0] for c in clicks)
        self.assertGreater(len(ox_vals), 3, "Click offsets should vary")

    def test_timing_has_variance(self):
        from anti_detection.timing_engine import TimingEngine
        t = TimingEngine(SAMPLE_PROFILE)
        delays = [t.action_delay() for _ in range(20)]
        self.assertGreater(len(set(round(d, 4) for d in delays)), 5,
                           "Delays should vary")


if __name__ == "__main__":
    unittest.main()
