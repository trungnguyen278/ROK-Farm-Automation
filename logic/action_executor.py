from __future__ import annotations

import logging
import threading
import time
from queue import Queue, Empty

from capture.screen_info import screen_to_hid
from vision.state_detector import GameScreen, StateDetector

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from capture.screen_capture import ScreenCapture
    from serial_comm.command_buffer import CommandBuffer
    from vision.template_matcher import TemplateMatcher
    from anti_detection.mouse_humanizer import MouseHumanizer
    from anti_detection.timing_engine import TimingEngine

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
VERIFY_DELAY = 1.0
CLICK_SETTLE = 0.05


class ActionExecutor:
    def __init__(
        self,
        action_queue: Queue,
        cmd_buffer: CommandBuffer,
        screen_capture: ScreenCapture,
        template_matcher: TemplateMatcher,
        humanizer: MouseHumanizer | None = None,
        timing: TimingEngine | None = None,
    ):
        self._queue = action_queue
        self._cmd = cmd_buffer
        self._capture = screen_capture
        self._matcher = template_matcher
        self._humanizer = humanizer
        self._timing = timing
        self._detector = StateDetector(template_matcher)

        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._elapsed_minutes = 0.0
        self._start_time = 0.0

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._start_time = time.monotonic()
        self._thread = threading.Thread(
            target=self._executor_loop, daemon=True, name="action-executor",
        )
        self._thread.start()

    def stop(self):
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _executor_loop(self):
        while self._running.is_set():
            try:
                action = self._queue.get(timeout=0.5)
            except Empty:
                continue

            self._elapsed_minutes = (time.monotonic() - self._start_time) / 60.0
            action_type = action.get("type", "")

            handler = self._get_handler(action_type)
            if handler is None:
                logger.warning("No handler for action type: %s", action_type)
                continue

            try:
                success = handler(action)
                if success:
                    logger.info("Action %s completed", action_type)
                else:
                    logger.warning("Action %s failed", action_type)
            except Exception:
                logger.exception("Action %s error", action_type)

    def _get_handler(self, action_type: str):
        handlers = {
            "dismiss": self._handle_dismiss_popup,
            "collect": self._handle_collect_rewards,
            "help": self._handle_alliance_help,
        }
        return handlers.get(action_type)

    # --- Core helpers ---

    def _frame_to_screen(self, frame_x: int, frame_y: int) -> tuple[int, int]:
        win = self._capture.window
        if win is None:
            raise RuntimeError("Game window not found")
        return frame_x + win["left"], frame_y + win["top"]

    def _apply_timing(self):
        if not self._timing:
            return
        delay = self._timing.action_delay()
        fatigue = self._timing.apply_fatigue(self._elapsed_minutes)
        time.sleep(delay * fatigue)
        pause = self._timing.micro_pause()
        if pause is not None:
            time.sleep(pause)

    def _click_at_screen(self, screen_x: int, screen_y: int, hold_ms: int = 50) -> bool:
        hid_x, hid_y = screen_to_hid(screen_x, screen_y)
        ok = self._cmd.send("MOVETO", hid_x, hid_y)
        if not ok:
            logger.warning("MOVETO failed at (%d, %d)", screen_x, screen_y)
            return False
        time.sleep(CLICK_SETTLE)
        ok = self._cmd.send("CLICK", "L", hold_ms)
        if not ok:
            logger.warning("CLICK failed")
            return False
        return True

    def _click_template(self, template_name: str) -> bool:
        frame = self._capture.grab_full()
        if frame is None:
            return False

        match = self._matcher.match_single(frame, template_name)
        if match is None:
            logger.debug("Template not found: %s", template_name)
            return False

        screen_x, screen_y = self._frame_to_screen(match.center[0], match.center[1])

        if self._humanizer:
            ox, oy, hold = self._humanizer.humanize_click(screen_x, screen_y)
            screen_x += ox
            screen_y += oy
        else:
            hold = 50

        self._apply_timing()
        return self._click_at_screen(screen_x, screen_y, hold)

    def _detect_current_screen(self) -> GameScreen:
        frame = self._capture.grab_full()
        if frame is None:
            return GameScreen.UNKNOWN
        return self._detector.detect(frame)

    def _wait_for_screen(self, target: GameScreen, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._detect_current_screen() == target:
                return True
            time.sleep(0.3)
        return False

    def _wait_not_screen(self, avoid: GameScreen, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._detect_current_screen() != avoid:
                return True
            time.sleep(0.3)
        return False

    def _click_center_of_screen(self) -> bool:
        win = self._capture.window
        if win is None:
            return False
        cx = win["left"] + win["width"] // 2
        cy = win["top"] + win["height"] // 2
        return self._click_at_screen(cx, cy)

    # --- Task handlers ---

    def _handle_dismiss_popup(self, action: dict) -> bool:
        for attempt in range(MAX_RETRIES):
            if not self._click_template("buttons/close_btn"):
                self._click_center_of_screen()

            time.sleep(VERIFY_DELAY)

            if self._wait_not_screen(GameScreen.POPUP_DIALOG, timeout=2.0):
                return True

            logger.debug("Popup still visible, retry %d/%d", attempt + 1, MAX_RETRIES)

        return False

    def _handle_collect_rewards(self, action: dict) -> bool:
        current = self._detect_current_screen()
        if current != GameScreen.CITY_VIEW:
            logger.debug("Not in city view for collect, current=%s", current)
            return False

        if not self._click_template("buttons/quest_btn"):
            logger.debug("Quest button not found")
            return False

        time.sleep(VERIFY_DELAY)

        for _ in range(5):
            if not self._click_template("buttons/claim_btn"):
                break
            time.sleep(VERIFY_DELAY * 0.5)

        self._cmd.send("KEY", 27)  # Escape
        time.sleep(VERIFY_DELAY)

        if self._wait_for_screen(GameScreen.CITY_VIEW, timeout=3.0):
            return True

        self._cmd.send("KEY", 27)
        return self._wait_for_screen(GameScreen.CITY_VIEW, timeout=2.0)

    def _handle_alliance_help(self, action: dict) -> bool:
        current = self._detect_current_screen()
        if current != GameScreen.CITY_VIEW:
            return False

        if not self._click_template("buttons/flag"):
            logger.debug("Alliance flag not found")
            return False

        time.sleep(VERIFY_DELAY * 1.5)

        self._click_template("buttons/help_all_btn")
        time.sleep(VERIFY_DELAY)

        self._cmd.send("KEY", 27)
        time.sleep(VERIFY_DELAY)

        return self._wait_for_screen(GameScreen.CITY_VIEW, timeout=3.0)
