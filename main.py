import sys
import os
import logging
import threading
import time
from queue import Queue, Empty, Full

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import Config
from vision.state_detector import GameScreen
from anti_detection.profile_loader import ProfileLoader
from anti_detection.mouse_humanizer import MouseHumanizer
from anti_detection.timing_engine import TimingEngine
from anti_detection.session_manager import SessionManager

logger = logging.getLogger(__name__)

VISION_QUEUE_MAX = 8
ACTION_QUEUE_MAX = 32


class Orchestrator:
    def __init__(self, config: Config):
        self.config = config
        self.vision_queue: Queue[GameScreen | None] = Queue(maxsize=VISION_QUEUE_MAX)
        self.action_queue: Queue[dict] = Queue(maxsize=ACTION_QUEUE_MAX)
        self.state_queue: Queue[str] = Queue(maxsize=16)

        self._running = threading.Event()
        self._paused = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._logic_thread: threading.Thread | None = None

        self._state_machine = None
        self._scheduler = None
        self._strategy = None
        self._screen_capture = None
        self._state_detector = None

        self._cmd_buffer = None
        self._template_matcher = None

        self._profile_loader = ProfileLoader(config.anti_detection.profile_dir)
        self._profile: dict = {}
        self._humanizer: MouseHumanizer | None = None
        self._timing: TimingEngine | None = None
        self._session: SessionManager | None = None
        self._action_executor = None

    def start(self, strategy_name: str):
        from logic.state_machine import StateMachine
        from logic.task_scheduler import TaskScheduler
        from logic.farm_strategies import FarmStrategy

        self._state_machine = StateMachine(
            unknown_state_timeout=self.config.logic.unknown_state_timeout,
        )
        self._scheduler = TaskScheduler(max_queue=self.config.logic.max_task_queue)
        self._strategy = FarmStrategy(strategy_name)

        profile_name = self.config.anti_detection.profile
        if profile_name == "random":
            self._profile = self._profile_loader.load_random()
        else:
            self._profile = self._profile_loader.load(profile_name)
        self._humanizer = MouseHumanizer(self._profile)
        self._timing = TimingEngine(self._profile)
        self._session = SessionManager(self._profile)
        logger.info("Anti-detection loaded: profile=%s", self._profile.get("name"))

        self._state_machine.add_listener(self._on_state_change)

        self._running.set()
        self._paused.clear()

        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True, name="capture",
        )
        self._logic_thread = threading.Thread(
            target=self._logic_loop, daemon=True, name="logic",
        )
        self._capture_thread.start()
        self._logic_thread.start()

        if self._cmd_buffer and self._screen_capture and self._template_matcher:
            from logic.action_executor import ActionExecutor
            self._action_executor = ActionExecutor(
                action_queue=self.action_queue,
                cmd_buffer=self._cmd_buffer,
                screen_capture=self._screen_capture,
                template_matcher=self._template_matcher,
                humanizer=self._humanizer,
                timing=self._timing,
            )
            self._action_executor.start()
            logger.info("ActionExecutor started")
        else:
            logger.warning("ActionExecutor not started: missing cmd_buffer/capture/matcher")

        logger.info("Orchestrator started: strategy=%s", strategy_name)

    def stop(self):
        self._running.clear()
        self._paused.clear()
        if self._action_executor:
            self._action_executor.stop()
            self._action_executor = None
        if self._capture_thread:
            self._capture_thread.join(timeout=3.0)
        if self._logic_thread:
            self._logic_thread.join(timeout=3.0)
        if self._scheduler:
            self._scheduler.clear()
        if self._strategy:
            self._strategy.reset()
        if self._session:
            self._session.reset()
        logger.info("Orchestrator stopped")

    def pause(self):
        self._paused.set()

    def resume(self):
        self._paused.clear()

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    @property
    def state_machine(self):
        return self._state_machine

    @property
    def scheduler(self):
        return self._scheduler

    @property
    def strategy(self):
        return self._strategy

    @property
    def humanizer(self):
        return self._humanizer

    @property
    def timing(self):
        return self._timing

    @property
    def session(self):
        return self._session

    def set_screen_capture(self, sc):
        self._screen_capture = sc

    def set_state_detector(self, sd):
        self._state_detector = sd

    def set_command_buffer(self, cb):
        self._cmd_buffer = cb

    def set_template_matcher(self, tm):
        self._template_matcher = tm

    def _on_state_change(self, old, new):
        try:
            self.state_queue.put_nowait(new.value)
        except Full:
            pass

    def _capture_loop(self):
        interval = 1.0 / self.config.capture.fps
        consecutive_errors = 0
        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.2)
                continue

            try:
                screen = None
                if self._screen_capture and self._state_detector:
                    frame = self._screen_capture.grab_full()
                    if frame is not None:
                        screen = self._state_detector.detect(frame)

                try:
                    self.vision_queue.put_nowait(screen)
                except Full:
                    pass
                consecutive_errors = 0
            except Exception:
                consecutive_errors += 1
                if consecutive_errors <= 3 or consecutive_errors % 50 == 0:
                    logger.exception("Capture loop error (count=%d)", consecutive_errors)
                time.sleep(min(consecutive_errors * 0.5, 5.0))

            time.sleep(interval)

    def _logic_loop(self):
        interval = 1.0 / self.config.logic.decision_rate
        consecutive_errors = 0
        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.2)
                continue

            try:
                screen: GameScreen | None = GameScreen.UNKNOWN
                try:
                    screen = self.vision_queue.get_nowait()
                except Empty:
                    pass

                if self._state_machine:
                    self._state_machine.update(screen)
                    state = self._state_machine.state
                else:
                    time.sleep(interval)
                    continue

                if self._session and self._session.should_stop_daily():
                    logger.info("Daily limit reached, stopping")
                    self._running.clear()
                    break

                if self._session and self._session.should_take_break():
                    time.sleep(1.0)
                    continue

                if self._strategy and self._scheduler:
                    new_tasks = self._strategy.generate_tasks(state)
                    for task in new_tasks:
                        self._scheduler.add(task)

                    task = self._scheduler.next()
                    if task:
                        if self._timing:
                            delay = self._timing.action_delay()
                            fatigue = self._timing.apply_fatigue(
                                self._session.elapsed_minutes if self._session else 0,
                            )
                            time.sleep(delay * fatigue)

                            pause = self._timing.micro_pause()
                            if pause is not None:
                                time.sleep(pause)

                        action = {
                            "task_id": task.id,
                            "type": task.type.value,
                            "params": task.params,
                            "state": state.value,
                        }

                        if self._humanizer and "x" in task.params and "y" in task.params:
                            ox, oy, hold = self._humanizer.humanize_click(
                                task.params["x"], task.params["y"],
                            )
                            action["click_offset"] = (ox, oy)
                            action["hold_ms"] = hold

                        if self._session:
                            idle = self._session.get_idle_action()
                            if idle is not None:
                                action["idle_action"] = idle.value
                            self._session.record_action()

                        try:
                            self.action_queue.put_nowait(action)
                        except Full:
                            logger.warning("Action queue full, retrying task %s", task.id)
                            self._scheduler.retry(task)

                consecutive_errors = 0
            except Exception:
                consecutive_errors += 1
                if consecutive_errors <= 3 or consecutive_errors % 50 == 0:
                    logger.exception("Logic loop error (count=%d)", consecutive_errors)
                time.sleep(min(consecutive_errors * 0.5, 5.0))

            time.sleep(interval)


def main():
    config = Config.load()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"Config error: {e}")
        sys.exit(1)

    from logging_setup import setup_from_config
    setup_from_config(config.logging)

    from ui.app import run
    run(config)


if __name__ == "__main__":
    main()
