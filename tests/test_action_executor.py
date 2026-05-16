"""Tests for ActionExecutor handlers (Phase 7)."""
from __future__ import annotations

import sys
import os
import time
import unittest
from collections import namedtuple
from queue import Queue
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision.state_detector import GameScreen

Match = namedtuple("Match", ["name", "x", "y", "w", "h", "confidence", "center"])

WINDOW = {"left": 100, "top": 50, "width": 1920, "height": 1080}


def _make_executor(template_hits=None, screen_seq=None,
                    fallback_screen=GameScreen.CITY_VIEW,
                    match_all_hits=None):
    """Build an ActionExecutor with mocked dependencies.

    Args:
        template_hits: dict of template_name -> Match (or None for miss)
        screen_seq: list of GameScreen values returned by successive detect() calls
        fallback_screen: screen returned after screen_seq is exhausted
        match_all_hits: dict of template_name -> list[Match] for match_all calls
    """
    from logic.action_executor import ActionExecutor

    queue = Queue()
    cmd = MagicMock()
    cmd.send = MagicMock(return_value=True)

    capture = MagicMock()
    capture.window = dict(WINDOW)
    import numpy as np
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    capture.grab_full = MagicMock(return_value=frame)

    matcher = MagicMock()
    hits = template_hits or {}
    all_hits = match_all_hits or {}

    def match_single(frame, name):
        return hits.get(name)

    def match_best(frame, names):
        for n in names:
            if n in hits:
                return hits[n]
        return None

    def match_all(frame, name, overlap_thresh=0.5):
        return all_hits.get(name, [])

    matcher.match_single = MagicMock(side_effect=match_single)
    matcher.match_best = MagicMock(side_effect=match_best)
    matcher.match_all = MagicMock(side_effect=match_all)

    ex = ActionExecutor(
        action_queue=queue,
        cmd_buffer=cmd,
        screen_capture=capture,
        template_matcher=matcher,
    )

    if screen_seq is not None:
        seq = list(screen_seq)
        fb = fallback_screen
        def detect_side(frame):
            if seq:
                return seq.pop(0)
            return fb
        ex._detector = MagicMock()
        ex._detector.detect = MagicMock(side_effect=detect_side)

    return ex, cmd, matcher, capture


def _match_at(name, cx, cy):
    return Match(name=name, x=cx - 10, y=cy - 10, w=20, h=20,
                 confidence=0.95, center=(cx, cy))


class TestGetHandler(unittest.TestCase):
    def test_all_handlers_registered(self):
        ex, *_ = _make_executor()
        for action_type in ("dismiss", "collect", "help", "train", "heal", "gather"):
            self.assertIsNotNone(ex._get_handler(action_type), f"Missing handler: {action_type}")

    def test_unknown_handler(self):
        ex, *_ = _make_executor()
        self.assertIsNone(ex._get_handler("nonexistent"))


class TestHelpers(unittest.TestCase):
    @patch("logic.action_executor.time.sleep")
    def test_click_at_window_relative(self, _sleep):
        ex, cmd, *_ = _make_executor()
        result = ex._click_at_window_relative(0.5, 0.5)
        self.assertTrue(result)
        calls = [c for c in cmd.send.call_args_list if c[0][0] == "MOVETO"]
        self.assertEqual(len(calls), 1)

    @patch("logic.action_executor.time.sleep")
    def test_press_escape(self, _sleep):
        ex, cmd, *_ = _make_executor()
        result = ex._press_escape()
        self.assertTrue(result)
        cmd.send.assert_called_with("KEY", 27)

    @patch("logic.action_executor.time.sleep")
    def test_navigate_to_city_already_there(self, _sleep):
        ex, *_ = _make_executor(screen_seq=[GameScreen.CITY_VIEW])
        self.assertTrue(ex._navigate_to_city())

    @patch("logic.action_executor.time.sleep")
    def test_navigate_to_city_via_escape(self, _sleep):
        # detect consumes: [0]=WM (initial), [1]=WM, [2]=WM, [3]=CV (escape loop)
        screens = [GameScreen.WORLD_MAP] * 3 + [GameScreen.CITY_VIEW] * 3
        ex, *_ = _make_executor(screen_seq=screens)
        self.assertTrue(ex._navigate_to_city())

    @patch("logic.action_executor.time.sleep")
    def test_navigate_to_city_fails(self, _sleep):
        screens = [GameScreen.WORLD_MAP] * 30
        ex, *_ = _make_executor(screen_seq=screens)
        self.assertFalse(ex._navigate_to_city(timeout=0.1))

    @patch("logic.action_executor.time.sleep")
    def test_navigate_to_world_map_already_there(self, _sleep):
        ex, *_ = _make_executor(screen_seq=[GameScreen.WORLD_MAP])
        self.assertTrue(ex._navigate_to_world_map())

    @patch("logic.action_executor.time.sleep")
    def test_navigate_to_world_map_via_button(self, _sleep):
        hits = {"buttons/world_map_btn": _match_at("buttons/world_map_btn", 100, 50)}
        screens = [GameScreen.CITY_VIEW, GameScreen.WORLD_MAP] * 3
        ex, *_ = _make_executor(template_hits=hits, screen_seq=screens)
        self.assertTrue(ex._navigate_to_world_map())


class TestDismissPopup(unittest.TestCase):
    @patch("logic.action_executor.time.sleep")
    def test_dismiss_with_close_btn(self, _sleep):
        hits = {"buttons/close_btn": _match_at("buttons/close_btn", 500, 200)}
        screens = [GameScreen.POPUP_DIALOG, GameScreen.CITY_VIEW]
        ex, cmd, *_ = _make_executor(template_hits=hits, screen_seq=screens)
        self.assertTrue(ex._handle_dismiss_popup({}))

    @patch("logic.action_executor.time.sleep")
    def test_dismiss_fallback_center_click(self, _sleep):
        screens = [GameScreen.POPUP_DIALOG, GameScreen.CITY_VIEW]
        ex, cmd, *_ = _make_executor(screen_seq=screens)
        self.assertTrue(ex._handle_dismiss_popup({}))

    @patch("logic.action_executor.time.sleep")
    def test_dismiss_fails_after_retries(self, _sleep):
        screens = [GameScreen.POPUP_DIALOG] * 30
        ex, *_ = _make_executor(screen_seq=screens,
                                fallback_screen=GameScreen.POPUP_DIALOG)
        self.assertFalse(ex._handle_dismiss_popup({}))


class TestCollectRewards(unittest.TestCase):
    @patch("logic.action_executor.time.sleep")
    def test_collect_with_templates(self, _sleep):
        hits = {
            "buttons/quest_btn": _match_at("buttons/quest_btn", 800, 100),
            "buttons/claim_btn": _match_at("buttons/claim_btn", 700, 300),
        }
        screens = [GameScreen.CITY_VIEW] * 20
        ex, cmd, *_ = _make_executor(template_hits=hits, screen_seq=screens)
        self.assertTrue(ex._handle_collect_rewards({}))

    @patch("logic.action_executor.time.sleep")
    def test_collect_with_fallback(self, _sleep):
        hits = {"buttons/quest_btn": _match_at("buttons/quest_btn", 800, 100)}
        screens = [GameScreen.CITY_VIEW] * 20
        ex, cmd, *_ = _make_executor(template_hits=hits, screen_seq=screens)
        result = ex._handle_collect_rewards({})
        self.assertTrue(result)

    @patch("logic.action_executor.time.sleep")
    def test_collect_wrong_screen(self, _sleep):
        screens = [GameScreen.WORLD_MAP] * 5
        ex, *_ = _make_executor(screen_seq=screens)
        self.assertFalse(ex._handle_collect_rewards({}))

    @patch("logic.action_executor.time.sleep")
    def test_collect_no_quest_btn(self, _sleep):
        screens = [GameScreen.CITY_VIEW] * 5
        ex, *_ = _make_executor(screen_seq=screens)
        self.assertFalse(ex._handle_collect_rewards({}))


class TestAllianceHelp(unittest.TestCase):
    @patch("logic.action_executor.time.sleep")
    def test_help_success(self, _sleep):
        hits = {
            "buttons/flag": _match_at("buttons/flag", 200, 300),
            "buttons/help_all_btn": _match_at("buttons/help_all_btn", 500, 400),
        }
        screens = [GameScreen.CITY_VIEW] * 20
        ex, cmd, *_ = _make_executor(template_hits=hits, screen_seq=screens)
        self.assertTrue(ex._handle_alliance_help({}))

    @patch("logic.action_executor.time.sleep")
    def test_help_no_flag(self, _sleep):
        screens = [GameScreen.CITY_VIEW] * 5
        ex, *_ = _make_executor(screen_seq=screens)
        self.assertFalse(ex._handle_alliance_help({}))


class TestTrainTroops(unittest.TestCase):
    @patch("logic.action_executor.time.sleep")
    def test_train_with_templates(self, _sleep):
        hits = {
            "buildings/barracks": _match_at("buildings/barracks", 400, 500),
            "buttons/train_btn": _match_at("buttons/train_btn", 500, 600),
        }
        screens = [GameScreen.CITY_VIEW] * 20
        ex, cmd, *_ = _make_executor(template_hits=hits, screen_seq=screens)
        self.assertTrue(ex._handle_train_troops({}))

    @patch("logic.action_executor.time.sleep")
    def test_train_with_fallback_positions(self, _sleep):
        screens = [GameScreen.CITY_VIEW] * 20
        ex, cmd, *_ = _make_executor(screen_seq=screens)
        result = ex._handle_train_troops({})
        self.assertTrue(result)

    @patch("logic.action_executor.time.sleep")
    def test_train_not_in_city(self, _sleep):
        screens = [GameScreen.WORLD_MAP] * 30
        ex, *_ = _make_executor(screen_seq=screens)
        self.assertFalse(ex._handle_train_troops({}))

    @patch("logic.action_executor.time.sleep")
    def test_train_sends_escape_to_close(self, _sleep):
        screens = [GameScreen.CITY_VIEW] * 20
        ex, cmd, *_ = _make_executor(screen_seq=screens)
        ex._handle_train_troops({})
        key_calls = [c for c in cmd.send.call_args_list if c[0] == ("KEY", 27)]
        self.assertGreaterEqual(len(key_calls), 2)


class TestHealTroops(unittest.TestCase):
    @patch("logic.action_executor.time.sleep")
    def test_heal_with_templates(self, _sleep):
        hits = {
            "buildings/hospital": _match_at("buildings/hospital", 600, 500),
            "buttons/heal_btn": _match_at("buttons/heal_btn", 500, 600),
        }
        screens = [GameScreen.CITY_VIEW] * 20
        ex, cmd, *_ = _make_executor(template_hits=hits, screen_seq=screens)
        self.assertTrue(ex._handle_heal_troops({}))

    @patch("logic.action_executor.time.sleep")
    def test_heal_with_fallback_positions(self, _sleep):
        screens = [GameScreen.CITY_VIEW] * 20
        ex, cmd, *_ = _make_executor(screen_seq=screens)
        result = ex._handle_heal_troops({})
        self.assertTrue(result)

    @patch("logic.action_executor.time.sleep")
    def test_heal_not_in_city(self, _sleep):
        screens = [GameScreen.WORLD_MAP] * 30
        ex, *_ = _make_executor(screen_seq=screens)
        self.assertFalse(ex._handle_heal_troops({}))

    @patch("logic.action_executor.time.sleep")
    def test_heal_sends_escape_to_close(self, _sleep):
        screens = [GameScreen.CITY_VIEW] * 20
        ex, cmd, *_ = _make_executor(screen_seq=screens)
        ex._handle_heal_troops({})
        key_calls = [c for c in cmd.send.call_args_list if c[0] == ("KEY", 27)]
        self.assertGreaterEqual(len(key_calls), 2)


class TestGatherResource(unittest.TestCase):
    @patch("logic.action_executor.is_gem_icon_color", return_value=(True, {"green_pct": 80, "white_pct": 50, "bright_pct": 100, "max_hue": 39, "reason": "green"}))
    @patch("logic.action_executor.time.sleep")
    def test_gather_full_flow(self, _sleep, _color):
        gem_icon = _match_at("resources/gem_icon", 400, 300)
        hits = {
            "resources/gem_mine_close": _match_at("resources/gem_mine_close", 400, 300),
            "buttons/gather_btn": _match_at("buttons/gather_btn", 500, 450),
            "buttons/march_btn": _match_at("buttons/march_btn", 700, 500),
            "buttons/city_btn": _match_at("buttons/city_btn", 1400, 900),
        }
        screens = (
            [GameScreen.WORLD_MAP] * 2
            + [GameScreen.CITY_VIEW] * 15
        )
        ex, cmd, *_ = _make_executor(
            template_hits=hits, screen_seq=screens,
            match_all_hits={"resources/gem_icon": [gem_icon]},
        )
        action = {"type": "gather", "params": {"resource_type": "gem"}}
        self.assertTrue(ex._handle_gather_resource(action))

    @patch("logic.action_executor.is_gem_icon_color", return_value=(True, {"green_pct": 80, "white_pct": 50, "bright_pct": 100, "max_hue": 39, "reason": "green"}))
    @patch("logic.action_executor.time.sleep")
    def test_gather_node_not_found(self, _sleep, _color):
        screens = (
            [GameScreen.WORLD_MAP] * 60
            + [GameScreen.CITY_VIEW] * 10
        )
        ex, *_ = _make_executor(screen_seq=screens)
        action = {"type": "gather", "params": {"resource_type": "gem"}}
        self.assertFalse(ex._handle_gather_resource(action))

    @patch("logic.action_executor.is_gem_icon_color", return_value=(True, {"green_pct": 80, "white_pct": 50, "bright_pct": 100, "max_hue": 39, "reason": "green"}))
    @patch("logic.action_executor.time.sleep")
    def test_gather_no_gather_btn(self, _sleep, _color):
        gem_icon = _match_at("resources/gem_icon", 400, 300)
        hits = {
            "resources/gem_mine_close": _match_at("resources/gem_mine_close", 400, 300),
        }
        screens = (
            [GameScreen.WORLD_MAP] * 15
            + [GameScreen.CITY_VIEW] * 10
        )
        ex, *_ = _make_executor(
            template_hits=hits, screen_seq=screens,
            match_all_hits={"resources/gem_icon": [gem_icon]},
        )
        action = {"type": "gather", "params": {"resource_type": "gem"}}
        self.assertFalse(ex._handle_gather_resource(action))

    @patch("logic.action_executor.is_gem_icon_color", return_value=(True, {"green_pct": 80, "white_pct": 50, "bright_pct": 100, "max_hue": 39, "reason": "green"}))
    @patch("logic.action_executor.time.sleep")
    def test_gather_no_march_btn(self, _sleep, _color):
        gem_icon = _match_at("resources/gem_icon", 400, 300)
        hits = {
            "resources/gem_mine_close": _match_at("resources/gem_mine_close", 400, 300),
            "buttons/gather_btn": _match_at("buttons/gather_btn", 500, 450),
        }
        screens = (
            [GameScreen.WORLD_MAP] * 2
            + [GameScreen.CITY_VIEW] * 15
        )
        ex, *_ = _make_executor(
            template_hits=hits, screen_seq=screens,
            match_all_hits={"resources/gem_icon": [gem_icon]},
        )
        action = {"type": "gather", "params": {"resource_type": "gem"}}
        self.assertFalse(ex._handle_gather_resource(action))

    @patch("logic.action_executor.time.sleep")
    def test_gather_cannot_reach_world_map(self, _sleep):
        screens = [GameScreen.CITY_VIEW] * 30
        ex, *_ = _make_executor(screen_seq=screens)
        action = {"type": "gather", "params": {}}
        self.assertFalse(ex._handle_gather_resource(action))

    @patch("logic.action_executor.time.sleep")
    def test_gather_default_resource_food(self, _sleep):
        screens = (
            [GameScreen.WORLD_MAP] * 20
            + [GameScreen.CITY_VIEW] * 10
        )
        ex, cmd, matcher, *_ = _make_executor(screen_seq=screens)
        action = {"type": "gather", "params": {}}
        ex._handle_gather_resource(action)
        farm_calls = [c for c in matcher.match_single.call_args_list
                      if c[0][1] == "resources/farm_node"]
        self.assertGreater(len(farm_calls), 0)


class TestVerifiedClick(unittest.TestCase):
    @patch("logic.action_executor.time.sleep")
    def test_find_template(self, _sleep):
        hits = {"buttons/gather_btn": _match_at("buttons/gather_btn", 500, 300)}
        ex, *_ = _make_executor(template_hits=hits)
        match = ex._find_template("buttons/gather_btn")
        self.assertIsNotNone(match)
        self.assertEqual(match.center, (500, 300))

    @patch("logic.action_executor.time.sleep")
    def test_find_template_missing(self, _sleep):
        ex, *_ = _make_executor()
        self.assertIsNone(ex._find_template("buttons/gather_btn"))

    @patch("logic.action_executor.time.sleep")
    def test_find_template_near_in_range(self, _sleep):
        hits = {"buttons/gather_btn": _match_at("buttons/gather_btn", 500, 350)}
        ex, *_ = _make_executor(template_hits=hits)
        match = ex._find_template_near("buttons/gather_btn", (400, 300), radius=300)
        self.assertIsNotNone(match)

    @patch("logic.action_executor.time.sleep")
    def test_find_template_near_out_of_range(self, _sleep):
        hits = {"buttons/gather_btn": _match_at("buttons/gather_btn", 1500, 800)}
        ex, *_ = _make_executor(template_hits=hits)
        match = ex._find_template_near("buttons/gather_btn", (400, 300), radius=200)
        self.assertIsNone(match)

    @patch("logic.action_executor.time.sleep")
    def test_click_match_verified_success(self, _sleep):
        hits = {"buttons/gather_btn": _match_at("buttons/gather_btn", 500, 300)}
        ex, cmd, *_ = _make_executor(template_hits=hits)
        match = _match_at("buttons/gather_btn", 500, 300)
        self.assertTrue(ex._click_match_verified("buttons/gather_btn", match))
        moveto = [c for c in cmd.send.call_args_list if c[0][0] == "MOVETO"]
        click = [c for c in cmd.send.call_args_list if c[0][0] == "CLICK"]
        self.assertGreaterEqual(len(moveto), 1)
        self.assertGreaterEqual(len(click), 1)

    @patch("logic.action_executor.time.sleep")
    def test_click_match_verified_template_gone(self, _sleep):
        ex, cmd, *_ = _make_executor()
        match = _match_at("buttons/gather_btn", 500, 300)
        self.assertFalse(ex._click_match_verified("buttons/gather_btn", match))
        moveto = [c for c in cmd.send.call_args_list if c[0][0] == "MOVETO"]
        click = [c for c in cmd.send.call_args_list if c[0][0] == "CLICK"]
        self.assertGreaterEqual(len(moveto), 1)
        self.assertEqual(len(click), 0)

    @patch("logic.action_executor.time.sleep")
    def test_click_match_verified_re_aims_on_shift(self, _sleep):
        shifted = _match_at("buttons/gather_btn", 550, 350)
        original = _match_at("buttons/gather_btn", 500, 300)
        hits = {"buttons/gather_btn": shifted}
        ex, cmd, *_ = _make_executor(template_hits=hits)
        self.assertTrue(ex._click_match_verified("buttons/gather_btn", original))
        moveto = [c for c in cmd.send.call_args_list if c[0][0] == "MOVETO"]
        self.assertGreaterEqual(len(moveto), 2)

    @patch("logic.action_executor.time.sleep")
    def test_click_template_verified_success(self, _sleep):
        hits = {"buttons/march_btn": _match_at("buttons/march_btn", 700, 500)}
        ex, *_ = _make_executor(template_hits=hits)
        ok, pos = ex._click_template_verified("buttons/march_btn")
        self.assertTrue(ok)
        self.assertEqual(pos, (700, 500))

    @patch("logic.action_executor.time.sleep")
    def test_click_template_verified_not_found(self, _sleep):
        ex, *_ = _make_executor()
        ok, pos = ex._click_template_verified("buttons/march_btn")
        self.assertFalse(ok)
        self.assertIsNone(pos)


class TestGatherGem(unittest.TestCase):
    @patch("logic.action_executor.is_gem_icon_color", return_value=(True, {"green_pct": 80, "white_pct": 50, "bright_pct": 100, "max_hue": 39, "reason": "green"}))
    @patch("logic.action_executor.time.sleep")
    def test_gather_gem_verifies_with_mine_close(self, _sleep, _color):
        """After icon click, verify gem type with gem_mine_close template."""
        gem_icon = _match_at("resources/gem_icon", 400, 300)
        hits = {
            "resources/gem_mine_close": _match_at("resources/gem_mine_close", 400, 300),
            "buttons/gather_btn": _match_at("buttons/gather_btn", 500, 450),
            "buttons/march_btn": _match_at("buttons/march_btn", 700, 500),
            "buttons/city_btn": _match_at("buttons/city_btn", 1400, 900),
        }
        screens = (
            [GameScreen.WORLD_MAP] * 2
            + [GameScreen.CITY_VIEW] * 15
        )
        ex, cmd, matcher, *_ = _make_executor(
            template_hits=hits, screen_seq=screens,
            match_all_hits={"resources/gem_icon": [gem_icon]},
        )
        action = {"type": "gather", "params": {"resource_type": "gem"}}
        self.assertTrue(ex._handle_gather_resource(action))
        close_calls = [c for c in matcher.match_single.call_args_list
                       if c[0][1] == "resources/gem_mine_close"]
        self.assertGreater(len(close_calls), 0)

    @patch("logic.action_executor.is_gem_icon_color", return_value=(True, {"green_pct": 80, "white_pct": 50, "bright_pct": 100, "max_hue": 39, "reason": "green"}))
    @patch("logic.action_executor.time.sleep")
    def test_gather_gem_falls_back_to_gem_mine(self, _sleep, _color):
        """Falls back to gem_mine template if gem_mine_close not found."""
        gem_icon = _match_at("resources/gem_icon", 400, 300)
        hits = {
            "resources/gem_mine": _match_at("resources/gem_mine", 500, 350),
            "buttons/gather_btn": _match_at("buttons/gather_btn", 500, 450),
            "buttons/march_btn": _match_at("buttons/march_btn", 700, 500),
            "buttons/city_btn": _match_at("buttons/city_btn", 1400, 900),
        }
        screens = (
            [GameScreen.WORLD_MAP] * 2
            + [GameScreen.CITY_VIEW] * 15
        )
        ex, cmd, matcher, *_ = _make_executor(
            template_hits=hits, screen_seq=screens,
            match_all_hits={"resources/gem_icon": [gem_icon]},
        )
        action = {"type": "gather", "params": {"resource_type": "gem"}}
        self.assertTrue(ex._handle_gather_resource(action))

    @patch("logic.action_executor.is_gem_icon_color", return_value=(True, {"green_pct": 80, "white_pct": 50, "bright_pct": 100, "max_hue": 39, "reason": "green"}))
    @patch("logic.action_executor.time.sleep")
    def test_gather_gem_sends_drag_for_scan(self, _sleep, _color):
        """Spiral scan sends DRAG commands to explore the map."""
        screens = (
            [GameScreen.WORLD_MAP] * 60
            + [GameScreen.CITY_VIEW] * 10
        )
        ex, cmd, *_ = _make_executor(screen_seq=screens)
        action = {"type": "gather", "params": {"resource_type": "gem"}}
        ex._handle_gather_resource(action)
        drag_calls = [c for c in cmd.send.call_args_list if c[0][0] == "DRAG"]
        self.assertGreater(len(drag_calls), 0)

    @patch("logic.action_executor.is_gem_icon_color", return_value=(True, {"green_pct": 80, "white_pct": 50, "bright_pct": 100, "max_hue": 39, "reason": "green"}))
    @patch("logic.action_executor.time.sleep")
    def test_gather_gem_zooms_out_to_icon_level(self, _sleep, _color):
        """Gem flow always zooms out to icon level before scanning."""
        gem_icon = _match_at("resources/gem_icon", 400, 300)
        hits = {
            "resources/gem_mine_close": _match_at("resources/gem_mine_close", 400, 300),
            "buttons/gather_btn": _match_at("buttons/gather_btn", 500, 450),
            "buttons/march_btn": _match_at("buttons/march_btn", 700, 500),
            "buttons/city_btn": _match_at("buttons/city_btn", 1400, 900),
        }
        screens = (
            [GameScreen.WORLD_MAP] * 2
            + [GameScreen.CITY_VIEW] * 15
        )
        ex, cmd, *_ = _make_executor(
            template_hits=hits, screen_seq=screens,
            match_all_hits={"resources/gem_icon": [gem_icon]},
        )
        action = {"type": "gather", "params": {"resource_type": "gem"}}
        self.assertTrue(ex._handle_gather_resource(action))
        scroll_calls = [c for c in cmd.send.call_args_list if c[0][0] == "SCROLL"]
        self.assertGreater(len(scroll_calls), 0)

    @patch("logic.action_executor.is_gem_icon_color", return_value=(False, {"green_pct": 5, "white_pct": 10, "bright_pct": 50, "max_hue": 15, "reason": "reject"}))
    @patch("logic.action_executor.time.sleep")
    def test_gather_gem_color_filter_rejects_non_gem(self, _sleep, _color):
        """Color filter rejects icons that don't look like gems."""
        gem_icon = _match_at("resources/gem_icon", 400, 300)
        hits = {
            "buttons/gather_btn": _match_at("buttons/gather_btn", 500, 450),
            "buttons/march_btn": _match_at("buttons/march_btn", 700, 500),
        }
        screens = (
            [GameScreen.WORLD_MAP] * 60
            + [GameScreen.CITY_VIEW] * 10
        )
        ex, *_ = _make_executor(
            template_hits=hits, screen_seq=screens,
            match_all_hits={"resources/gem_icon": [gem_icon]},
        )
        action = {"type": "gather", "params": {"resource_type": "gem"}}
        self.assertFalse(ex._handle_gather_resource(action))

    @patch("logic.action_executor.time.sleep")
    def test_prepare_gem_search_unknown_uses_esp32_keyboard_recovery(self, _sleep):
        screens = [
            GameScreen.UNKNOWN, GameScreen.UNKNOWN, GameScreen.CITY_VIEW,
            GameScreen.CITY_VIEW, GameScreen.WORLD_MAP, GameScreen.WORLD_MAP,
        ]
        ex, cmd, *_ = _make_executor(screen_seq=screens, fallback_screen=GameScreen.WORLD_MAP)
        self.assertTrue(ex._prepare_resource_search_state(["resources/gem_mine_close"]))
        key_calls = [c[0] for c in cmd.send.call_args_list if c[0][0] == "KEY"]
        self.assertIn(("KEY", 32), key_calls)
        self.assertIn(("KEY", 27), key_calls)

    @patch("logic.action_executor.time.sleep")
    def test_prepare_gem_search_unknown_world_map_cue_skips_keyboard_recovery(self, _sleep):
        hits = {"buttons/city_btn": _match_at("buttons/city_btn", 1420, 820)}
        screens = [GameScreen.UNKNOWN] * 5
        ex, cmd, *_ = _make_executor(template_hits=hits, screen_seq=screens,
                                     fallback_screen=GameScreen.UNKNOWN)
        self.assertTrue(ex._prepare_resource_search_state(["resources/gem_mine_close"]))
        key_calls = [c for c in cmd.send.call_args_list if c[0][0] == "KEY"]
        self.assertEqual(key_calls, [])


class TestGemFarmStrategy(unittest.TestCase):
    def test_gem_farm_strategy_exists(self):
        from logic.farm_strategies import FarmStrategy
        self.assertIn("gem_farm", FarmStrategy.available_strategies())

    def test_gem_farm_generates_gather_gem(self):
        from logic.farm_strategies import FarmStrategy
        from logic.state_machine import GameState
        strategy = FarmStrategy("gem_farm")
        tasks = strategy.generate_tasks(GameState.CITY_VIEW)
        gather_tasks = [t for t in tasks if t.type.value == "gather"]
        self.assertGreater(len(gather_tasks), 0)
        self.assertEqual(gather_tasks[0].params.get("resource_type"), "gem")

    def test_gem_farm_includes_side_tasks(self):
        from logic.farm_strategies import FarmStrategy
        from logic.state_machine import GameState
        strategy = FarmStrategy("gem_farm")
        tasks = strategy.generate_tasks(GameState.CITY_VIEW)
        task_types = {t.type.value for t in tasks}
        self.assertIn("gather", task_types)
        self.assertIn("collect", task_types)
        self.assertIn("help", task_types)

    def test_gem_farm_gather_highest_priority(self):
        from logic.farm_strategies import FarmStrategy
        from logic.state_machine import GameState
        strategy = FarmStrategy("gem_farm")
        tasks = strategy.generate_tasks(GameState.CITY_VIEW)
        gather_tasks = [t for t in tasks if t.type.value == "gather"]
        other_tasks = [t for t in tasks if t.type.value != "gather"]
        if gather_tasks and other_tasks:
            self.assertLess(gather_tasks[0].priority, min(t.priority for t in other_tasks))


class TestExecutorLoop(unittest.TestCase):
    @patch("logic.action_executor.time.sleep")
    def test_loop_dispatches_action(self, _sleep):
        screens = [GameScreen.POPUP_DIALOG, GameScreen.CITY_VIEW] * 5
        ex, cmd, *_ = _make_executor(screen_seq=screens)
        ex._queue.put({"type": "dismiss"})
        ex.start()
        time.sleep(0.3)
        ex.stop()
        moveto_or_key_calls = [c for c in cmd.send.call_args_list
                               if c[0][0] in ("MOVETO", "CLICK", "KEY")]
        self.assertGreater(len(moveto_or_key_calls), 0)

    @patch("logic.action_executor.time.sleep")
    def test_loop_skips_unknown_action(self, _sleep):
        ex, cmd, *_ = _make_executor()
        ex._queue.put({"type": "nonexistent_action"})
        ex.start()
        time.sleep(0.3)
        ex.stop()


if __name__ == "__main__":
    unittest.main()
