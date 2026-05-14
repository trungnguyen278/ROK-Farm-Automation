"""Tests for Phase 3: config, state machine, task scheduler, farm strategies."""
from __future__ import annotations

import time
import unittest

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestConfig(unittest.TestCase):
    def test_load_defaults(self):
        from config import Config
        cfg = Config()
        self.assertEqual(cfg.serial.baud, 115200)
        self.assertEqual(cfg.logic.strategy, "basic_gather")
        self.assertEqual(cfg.vision.match_threshold, 0.8)

    def test_load_from_yaml(self):
        from config import Config
        cfg = Config.load("config.yaml")
        self.assertEqual(cfg.serial.port, "COM3")
        self.assertEqual(cfg.capture.window_title, "Rise of Kingdoms")
        self.assertEqual(cfg.logic.decision_rate, 10)
        self.assertIn("top_bar", cfg.capture.roi)

    def test_validate_ok(self):
        from config import Config
        cfg = Config.load("config.yaml")
        errors = cfg.validate()
        self.assertEqual(errors, [])

    def test_validate_bad_baud(self):
        from config import Config
        cfg = Config()
        cfg.serial.baud = 12345
        errors = cfg.validate()
        self.assertTrue(any("baud" in e for e in errors))

    def test_validate_bad_threshold(self):
        from config import Config
        cfg = Config()
        cfg.vision.match_threshold = 1.5
        errors = cfg.validate()
        self.assertTrue(any("threshold" in e for e in errors))

    def test_missing_file_returns_defaults(self):
        from config import Config
        cfg = Config.load("nonexistent_config_xyz.yaml")
        self.assertEqual(cfg.serial.baud, 115200)


class TestGameState(unittest.TestCase):
    def test_enum_values(self):
        from logic.state_machine import GameState
        self.assertEqual(GameState.INIT.value, "init")
        self.assertEqual(GameState.CITY_VIEW.value, "city_view")
        self.assertEqual(GameState.ERROR.value, "error")


class TestStateMachine(unittest.TestCase):
    def setUp(self):
        from logic.state_machine import StateMachine
        self.sm = StateMachine(unknown_state_timeout=1.0)

    def test_initial_state(self):
        from logic.state_machine import GameState
        self.assertEqual(self.sm.state, GameState.INIT)

    def test_transition_city_view(self):
        from logic.state_machine import GameState
        from vision.state_detector import GameScreen
        self.sm.update(GameScreen.CITY_VIEW)
        self.assertEqual(self.sm.state, GameState.CITY_VIEW)

    def test_transition_world_map(self):
        from logic.state_machine import GameState
        from vision.state_detector import GameScreen
        self.sm.update(GameScreen.WORLD_MAP)
        self.assertEqual(self.sm.state, GameState.WORLD_MAP)

    def test_city_to_world(self):
        from logic.state_machine import GameState
        from vision.state_detector import GameScreen
        self.sm.update(GameScreen.CITY_VIEW)
        self.sm.update(GameScreen.WORLD_MAP)
        self.assertEqual(self.sm.state, GameState.WORLD_MAP)
        self.assertEqual(self.sm.previous_state, GameState.CITY_VIEW)

    def test_popup_overlay(self):
        from logic.state_machine import GameState
        from vision.state_detector import GameScreen
        self.sm.update(GameScreen.CITY_VIEW)
        self.sm.update(GameScreen.POPUP_DIALOG)
        self.assertEqual(self.sm.state, GameState.POPUP)
        self.assertEqual(self.sm.previous_state, GameState.CITY_VIEW)

    def test_none_means_disconnected(self):
        from logic.state_machine import GameState
        from vision.state_detector import GameScreen
        self.sm.update(GameScreen.CITY_VIEW)
        self.sm.update(None)
        self.assertEqual(self.sm.state, GameState.DISCONNECTED)

    def test_unknown_timeout_to_error(self):
        from logic.state_machine import GameState
        from vision.state_detector import GameScreen
        self.sm.update(GameScreen.CITY_VIEW)
        self.sm.update(GameScreen.UNKNOWN)
        self.assertEqual(self.sm.state, GameState.CITY_VIEW)
        self.sm._unknown_since = time.monotonic() - 2.0
        self.sm.update(GameScreen.UNKNOWN)
        self.assertEqual(self.sm.state, GameState.ERROR)

    def test_force_state(self):
        from logic.state_machine import GameState
        self.sm.force_state(GameState.IDLE)
        self.assertEqual(self.sm.state, GameState.IDLE)

    def test_time_in_state(self):
        self.assertGreaterEqual(self.sm.time_in_state(), 0.0)

    def test_listener_called(self):
        from vision.state_detector import GameScreen
        transitions = []
        self.sm.add_listener(lambda old, new: transitions.append((old, new)))
        self.sm.update(GameScreen.CITY_VIEW)
        self.assertEqual(len(transitions), 1)

    def test_same_state_no_transition(self):
        from logic.state_machine import GameState
        from vision.state_detector import GameScreen
        self.sm.update(GameScreen.CITY_VIEW)
        transitions = []
        self.sm.add_listener(lambda old, new: transitions.append((old, new)))
        self.sm.update(GameScreen.CITY_VIEW)
        self.assertEqual(len(transitions), 0)

    def test_commander_select(self):
        from logic.state_machine import GameState
        from vision.state_detector import GameScreen
        self.sm.update(GameScreen.CITY_VIEW)
        self.sm.update(GameScreen.COMMANDER_SELECT)
        self.assertEqual(self.sm.state, GameState.COMMANDER_SELECT)


class TestTaskScheduler(unittest.TestCase):
    def _make_task(self, task_id="t1", priority=5):
        from logic.task_scheduler import Task, TaskType
        return Task(id=task_id, type=TaskType.GATHER_RESOURCE, priority=priority)

    def test_add_and_next(self):
        from logic.task_scheduler import TaskScheduler
        s = TaskScheduler()
        t = self._make_task()
        self.assertTrue(s.add(t))
        self.assertEqual(s.pending_count, 1)
        got = s.next()
        self.assertIsNotNone(got)
        self.assertEqual(got.id, "t1")
        self.assertEqual(s.pending_count, 0)

    def test_priority_order(self):
        from logic.task_scheduler import TaskScheduler
        s = TaskScheduler()
        s.add(self._make_task("low", priority=10))
        s.add(self._make_task("high", priority=1))
        s.add(self._make_task("med", priority=5))
        self.assertEqual(s.next().id, "high")
        self.assertEqual(s.next().id, "med")
        self.assertEqual(s.next().id, "low")

    def test_no_duplicates(self):
        from logic.task_scheduler import TaskScheduler
        s = TaskScheduler()
        s.add(self._make_task("t1"))
        self.assertFalse(s.add(self._make_task("t1")))

    def test_retry_with_backoff(self):
        from logic.task_scheduler import TaskScheduler
        s = TaskScheduler()
        t = self._make_task("t1")
        s.add(t)
        t = s.next()
        self.assertTrue(s.retry(t))
        self.assertEqual(t.retry_count, 1)
        self.assertGreater(t.next_retry_at, 0)
        self.assertEqual(s.pending_count, 1)

    def test_max_retries_exceeded(self):
        from logic.task_scheduler import TaskScheduler
        s = TaskScheduler()
        t = self._make_task("t1")
        t.retry_count = 3
        t.max_retries = 3
        self.assertFalse(s.retry(t))

    def test_queue_full(self):
        from logic.task_scheduler import TaskScheduler
        s = TaskScheduler(max_queue=2)
        s.add(self._make_task("t1"))
        s.add(self._make_task("t2"))
        self.assertFalse(s.add(self._make_task("t3")))

    def test_clear(self):
        from logic.task_scheduler import TaskScheduler
        s = TaskScheduler()
        s.add(self._make_task("t1"))
        s.add(self._make_task("t2"))
        s.clear()
        self.assertEqual(s.pending_count, 0)
        self.assertIsNone(s.next())

    def test_deferred_task_not_returned(self):
        from logic.task_scheduler import TaskScheduler
        s = TaskScheduler()
        t = self._make_task("future")
        t.next_retry_at = time.time() + 9999
        s.add(t)
        self.assertIsNone(s.next())
        self.assertEqual(s.pending_count, 1)


class TestFarmStrategies(unittest.TestCase):
    def test_basic_gather_exists(self):
        from logic.farm_strategies import STRATEGIES
        self.assertIn("basic_gather", STRATEGIES)
        self.assertIn("war_prep", STRATEGIES)
        self.assertIn("alliance_focus", STRATEGIES)

    def test_generate_tasks_city_view(self):
        from logic.farm_strategies import FarmStrategy
        from logic.state_machine import GameState
        strat = FarmStrategy("basic_gather")
        tasks = strat.generate_tasks(GameState.CITY_VIEW)
        self.assertGreater(len(tasks), 0)
        types = {t.type.value for t in tasks}
        self.assertIn("collect", types)

    def test_generate_tasks_popup(self):
        from logic.farm_strategies import FarmStrategy
        from logic.state_machine import GameState
        strat = FarmStrategy("basic_gather")
        tasks = strat.generate_tasks(GameState.POPUP)
        types = {t.type.value for t in tasks}
        self.assertIn("dismiss", types)

    def test_interval_throttle(self):
        from logic.farm_strategies import FarmStrategy
        from logic.state_machine import GameState
        strat = FarmStrategy("basic_gather")
        tasks1 = strat.generate_tasks(GameState.CITY_VIEW)
        tasks2 = strat.generate_tasks(GameState.CITY_VIEW)
        self.assertGreater(len(tasks1), len(tasks2))

    def test_unknown_strategy_fallback(self):
        from logic.farm_strategies import FarmStrategy
        strat = FarmStrategy("nonexistent_strategy")
        self.assertEqual(strat.name, "basic_gather")

    def test_reset(self):
        from logic.farm_strategies import FarmStrategy
        from logic.state_machine import GameState
        strat = FarmStrategy("basic_gather")
        strat.generate_tasks(GameState.CITY_VIEW)
        strat.reset()
        tasks = strat.generate_tasks(GameState.CITY_VIEW)
        self.assertGreater(len(tasks), 0)

    def test_available_strategies(self):
        from logic.farm_strategies import FarmStrategy
        names = FarmStrategy.available_strategies()
        self.assertIn("basic_gather", names)

    def test_no_tasks_for_error_state(self):
        from logic.farm_strategies import FarmStrategy
        from logic.state_machine import GameState
        strat = FarmStrategy("basic_gather")
        tasks = strat.generate_tasks(GameState.ERROR)
        self.assertEqual(len(tasks), 0)

    def test_no_tasks_for_loading_state(self):
        from logic.farm_strategies import FarmStrategy
        from logic.state_machine import GameState
        strat = FarmStrategy("basic_gather")
        tasks = strat.generate_tasks(GameState.LOADING)
        self.assertEqual(len(tasks), 0)


if __name__ == "__main__":
    unittest.main()
