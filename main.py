import sys
import os
import logging
import threading
import time
from queue import Queue, Empty

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

        self._profile_loader = ProfileLoader(config.anti_detection.profile_dir)
        self._profile: dict = {}
        self._humanizer: MouseHumanizer | None = None
        self._timing: TimingEngine | None = None
        self._session: SessionManager | None = None

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
        logger.info("Orchestrator started: strategy=%s", strategy_name)

    def stop(self):
        self._running.clear()
        self._paused.clear()
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

    def _on_state_change(self, old, new):
        try:
            self.state_queue.put_nowait(new.value)
        except Exception:
            pass

    def _capture_loop(self):
        interval = 1.0 / self.config.capture.fps
        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.2)
                continue

            screen = None
            if self._screen_capture and self._state_detector:
                frame = self._screen_capture.grab_full()
                if frame is not None:
                    screen = self._state_detector.detect(frame)
                else:
                    screen = None

            try:
                self.vision_queue.put_nowait(screen)
            except Exception:
                pass

            time.sleep(interval)

    def _logic_loop(self):
        interval = 1.0 / self.config.logic.decision_rate
        while self._running.is_set():
            if self._paused.is_set():
                time.sleep(0.2)
                continue

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
                    except Exception:
                        self._scheduler.retry(task)

            time.sleep(interval)


def main():
    config = Config.load()
    errors = config.validate()
    if errors:
        for e in errors:
            print(f"Config error: {e}")
        sys.exit(1)

    from ui.app import run
    run(config)


if __name__ == "__main__":
    main()
