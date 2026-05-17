from __future__ import annotations

import logging
import threading
import time
from queue import Queue, Empty

from capture.screen_info import screen_to_hid
from vision.color_filter import is_gem_icon_color
from vision.gem_classifier import GemPatchClassifier
from vision.state_detector import GameScreen, StateDetector

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from capture.screen_capture import ScreenCapture
    from serial_comm.command_buffer import CommandBuffer
    from vision.template_matcher import Match, TemplateMatcher
    from anti_detection.mouse_humanizer import MouseHumanizer
    from anti_detection.timing_engine import TimingEngine

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
VERIFY_DELAY = 1.0
CLICK_SETTLE = 0.05
VERIFY_SETTLE = 0.15
WORLD_MAP_SCROLL_STEPS = 5
WORLD_MAP_ZOOM_IN_RECOVERY_STEPS = 3

ACTION_MIN_CONFIDENCE = {
    "resources/gem_mine_close": 0.60,
    "resources/gem_mine_red": 0.60,
    "resources/gem_mine": 0.60,
    "buttons/world_map_btn": 0.75,
    "buttons/world_map_city_btn": 0.75,
    "buttons/city_btn": 0.75,
    "buttons/gather_btn": 0.65,
    "buttons/new_troop_btn": 0.70,
    "buttons/march_btn_orange": 0.70,
    "buttons/march_btn": 0.70,
}

GEM_TEMPLATES = [
    "resources/gem_mine_close",
    "resources/gem_mine_red",
    "resources/gem_mine",
]

RESOURCE_TEMPLATE_MAP = {
    "gem": GEM_TEMPLATES,
    "food": ["resources/farm_node"],
    "wood": ["resources/wood_node"],
    "stone": ["resources/stone_node"],
    "gold": ["resources/gold_node"],
}

RESOURCE_TEMPLATES = set(tpl for templates in RESOURCE_TEMPLATE_MAP.values() for tpl in templates)

MARCH_TEMPLATES = ["buttons/march_btn_orange", "buttons/march_btn"]

GEM_ICON_TEMPLATE = "resources/gem_icon"
GEM_ICON_THRESHOLD = 0.68
GEM_MINE_VERIFY_THRESHOLD = 0.60
ICON_ZOOM_SCROLLS = 2


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
        self._classifier = GemPatchClassifier()
        self._classifier.load()

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
        if self._classifier.sample_count > 0:
            self._classifier.save()
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
            "train": self._handle_train_troops,
            "heal": self._handle_heal_troops,
            "gather": self._handle_gather_resource,
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

    def _click_at_window_relative(self, rx: float, ry: float) -> bool:
        win = self._capture.window
        if win is None:
            return False
        sx = win["left"] + int(win["width"] * rx)
        sy = win["top"] + int(win["height"] * ry)

        if self._humanizer:
            ox, oy, hold = self._humanizer.humanize_click(sx, sy)
            sx += ox
            sy += oy
        else:
            hold = 50

        self._apply_timing()
        return self._click_at_screen(sx, sy, hold)

    def _match_is_actionable(self, template_name: str, match: Match, frame) -> bool:
        min_conf = ACTION_MIN_CONFIDENCE.get(template_name)
        if min_conf is not None and match.confidence < min_conf:
            logger.debug(
                "Reject %s: confidence %.3f below %.2f",
                template_name, match.confidence, min_conf,
            )
            return False

        if template_name in RESOURCE_TEMPLATES:
            h, w = frame.shape[:2]
            x, y = match.center
            in_play_area = (
                int(w * 0.10) <= x <= int(w * 0.92)
                and int(h * 0.08) <= y <= int(h * 0.86)
            )
            if not in_play_area:
                logger.debug("Reject %s: center %s outside play area", template_name, match.center)
                return False

        return True

    def _find_template(self, template_name: str, actionable: bool = False) -> Match | None:
        frame = self._capture.grab_full()
        if frame is None:
            return None
        return self._find_template_in_frame(frame, template_name, actionable=actionable)

    def _find_template_in_frame(
        self, frame, template_name: str, actionable: bool = False
    ) -> Match | None:
        match = self._matcher.match_single(frame, template_name)
        if match is None:
            return None
        if actionable and not self._match_is_actionable(template_name, match, frame):
            return None
        return match

    def _find_first_template(
        self, template_names: list[str], actionable: bool = False
    ) -> Match | None:
        frame = self._capture.grab_full()
        if frame is None:
            return None
        return self._find_first_template_in_frame(frame, template_names, actionable=actionable)

    def _find_first_template_in_frame(
        self, frame, template_names: list[str], actionable: bool = False
    ) -> Match | None:
        for template_name in template_names:
            match = self._find_template_in_frame(frame, template_name, actionable=actionable)
            if match is not None:
                return match
        return None

    def _extract_icon_patch(self, frame, m: Match):
        fh, fw = frame.shape[:2]
        x1 = max(0, m.x)
        y1 = max(0, m.y)
        x2 = min(fw, m.x + m.w)
        y2 = min(fh, m.y + m.h)
        return frame[y1:y2, x1:x2].copy()

    def _find_gem_icons_filtered(self, frame) -> list[Match]:
        """Find gem_icon matches filtered by HSV color + k-NN classifier."""
        matches = self._matcher.match_all(frame, GEM_ICON_TEMPLATE, overlap_thresh=0.3)
        result = []
        for m in matches:
            if m.confidence < GEM_ICON_THRESHOLD:
                continue
            is_gem, info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            if not is_gem:
                logger.debug("gem_icon color reject at %s conf=%.3f: %s",
                             m.center, m.confidence, info)
                continue
            patch = self._extract_icon_patch(frame, m)
            should_click, label, clf_conf = self._classifier.should_click(patch)
            if not should_click:
                logger.debug("gem_icon classifier reject at %s: %s (%.2f)",
                             m.center, label, clf_conf)
                continue
            result.append(m)
        return sorted(result, key=lambda m: -m.confidence)

    def _find_template_near(
        self, template_name: str, frame_center: tuple[int, int], radius: int = 300
    ) -> Match | None:
        match = self._find_template(template_name, actionable=True)
        if match is None:
            return None
        dx = abs(match.center[0] - frame_center[0])
        dy = abs(match.center[1] - frame_center[1])
        if dx <= radius and dy <= radius:
            return match
        logger.debug(
            "%s at (%d,%d) too far from target (%d,%d)",
            template_name, match.center[0], match.center[1],
            frame_center[0], frame_center[1],
        )
        return None

    def _click_match_verified(self, template_name: str, match: Match) -> bool:
        frame_x, frame_y = match.center
        screen_x, screen_y = self._frame_to_screen(frame_x, frame_y)

        if self._humanizer:
            ox, oy, hold = self._humanizer.humanize_click(screen_x, screen_y)
            screen_x += ox
            screen_y += oy
        else:
            hold = 50

        self._apply_timing()

        frame = self._capture.grab_full()
        if frame is not None and not self._match_is_actionable(template_name, match, frame):
            return False

        hid_x, hid_y = screen_to_hid(screen_x, screen_y)
        if not self._cmd.send("MOVETO", hid_x, hid_y):
            return False

        time.sleep(VERIFY_SETTLE)

        frame = self._capture.grab_full()
        if frame is not None:
            v = self._matcher.match_single(frame, template_name)
            if v is None:
                logger.warning("Verify failed: %s gone after MOVETO", template_name)
                return False
            if not self._match_is_actionable(template_name, v, frame):
                logger.warning("Verify failed: %s match not actionable", template_name)
                return False
            if abs(v.center[0] - frame_x) > 20 or abs(v.center[1] - frame_y) > 20:
                logger.info("Target %s shifted, re-aiming", template_name)
                new_sx, new_sy = self._frame_to_screen(v.center[0], v.center[1])
                hid_x, hid_y = screen_to_hid(new_sx, new_sy)
                if not self._cmd.send("MOVETO", hid_x, hid_y):
                    return False
                time.sleep(CLICK_SETTLE)

        return self._cmd.send("CLICK", "L", hold)

    def _click_template_verified(
        self, template_name: str,
    ) -> tuple[bool, tuple[int, int] | None]:
        match = self._find_template(template_name, actionable=True)
        if match is None:
            logger.debug("Template not found: %s", template_name)
            return False, None
        ok = self._click_match_verified(template_name, match)
        return ok, match.center if ok else None

    def _press_escape(self) -> bool:
        return self._cmd.send("KEY", 27)

    def _press_space(self) -> bool:
        return self._cmd.send("KEY", 32)

    def _recover_unknown_screen(self) -> GameScreen:
        logger.info("Current screen unknown; trying Space/Escape recovery via ESP32")
        self._press_space()
        time.sleep(VERIFY_DELAY * 2)

        current = self._detect_current_screen()
        if current != GameScreen.UNKNOWN:
            return current

        for _ in range(3):
            self._press_escape()
            time.sleep(VERIFY_DELAY * 0.8)
            current = self._detect_current_screen()
            if current != GameScreen.UNKNOWN:
                return current

        return current

    def _looks_like_world_map(self, frame=None) -> bool:
        if frame is None:
            frame = self._capture.grab_full()
        if frame is None:
            return False
        return self._find_template_in_frame(frame, "buttons/city_btn", actionable=True) is not None

    def _navigate_to_city(self, timeout: float = 5.0) -> bool:
        if self._detect_current_screen() == GameScreen.CITY_VIEW:
            return True

        if self._click_template("buttons/city_btn"):
            if self._wait_for_screen(GameScreen.CITY_VIEW, timeout):
                return True

        for _ in range(3):
            self._press_escape()
            time.sleep(VERIFY_DELAY)
            if self._detect_current_screen() == GameScreen.CITY_VIEW:
                return True

        return False

    def _navigate_to_world_map(self, timeout: float = 5.0) -> bool:
        current = self._detect_current_screen()
        if current == GameScreen.WORLD_MAP:
            return True
        if current == GameScreen.UNKNOWN and self._looks_like_world_map():
            return True
        if current == GameScreen.UNKNOWN:
            current = self._recover_unknown_screen()
            if current == GameScreen.WORLD_MAP:
                return True
            if current == GameScreen.UNKNOWN and self._looks_like_world_map():
                return True

        for template_name in ("buttons/world_map_btn", "buttons/world_map_city_btn"):
            ok, _ = self._click_template_verified(template_name)
            if ok:
                if self._wait_for_screen(GameScreen.WORLD_MAP, timeout):
                    return True
                if self._looks_like_world_map():
                    return True

        self._click_center_of_screen()
        time.sleep(CLICK_SETTLE)
        for _ in range(WORLD_MAP_SCROLL_STEPS):
            self._cmd.send("SCROLL", -5)
            time.sleep(0.15)
        time.sleep(1.0)

        current = self._detect_current_screen()
        if current == GameScreen.WORLD_MAP:
            return True
        if current == GameScreen.UNKNOWN:
            self._click_center_of_screen()
            for _ in range(WORLD_MAP_ZOOM_IN_RECOVERY_STEPS):
                self._cmd.send("SCROLL", 5)
                time.sleep(0.15)
            time.sleep(1.0)

        return True

    def _prepare_resource_search_state(self, template_names: list[str]) -> bool:
        frame = self._capture.grab_full()
        if frame is None:
            return False

        visible = self._find_first_template_in_frame(frame, template_names, actionable=True)
        if visible is not None:
            logger.info(
                "Resource target already visible: %s at %s (conf=%.3f)",
                visible.name, visible.center, visible.confidence,
            )
            return True

        current = self._detector.detect(frame)
        if current == GameScreen.UNKNOWN and self._looks_like_world_map(frame):
            current = GameScreen.WORLD_MAP
        elif current == GameScreen.UNKNOWN:
            current = self._recover_unknown_screen()

        if current != GameScreen.WORLD_MAP:
            if not self._navigate_to_world_map():
                return False

        frame = self._capture.grab_full()
        if frame is None:
            return False
        if self._find_first_template_in_frame(frame, template_names, actionable=True) is not None:
            return True

        current = self._detector.detect(frame)
        return current in (GameScreen.WORLD_MAP, GameScreen.UNKNOWN)

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

        claimed = 0
        for _ in range(5):
            if self._click_template("buttons/claim_btn"):
                claimed += 1
                time.sleep(VERIFY_DELAY * 0.5)
            elif claimed == 0:
                # Fallback: claim buttons sit on the right side of quest rows
                if self._click_at_window_relative(0.75, 0.35):
                    claimed += 1
                    time.sleep(VERIFY_DELAY * 0.5)
                break
            else:
                break

        self._press_escape()
        time.sleep(VERIFY_DELAY)

        if self._wait_for_screen(GameScreen.CITY_VIEW, timeout=3.0):
            return True

        self._press_escape()
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

        self._press_escape()
        time.sleep(VERIFY_DELAY)

        return self._wait_for_screen(GameScreen.CITY_VIEW, timeout=3.0)

    def _handle_train_troops(self, action: dict) -> bool:
        if not self._navigate_to_city():
            logger.debug("Cannot navigate to city for training")
            return False

        clicked = self._click_template("buildings/barracks")
        if not clicked:
            clicked = self._click_at_window_relative(0.35, 0.55)
        if not clicked:
            logger.debug("Failed to click training building")
            return False

        time.sleep(VERIFY_DELAY * 1.5)

        trained = False
        for _ in range(MAX_RETRIES):
            if self._click_template("buttons/train_btn"):
                time.sleep(VERIFY_DELAY)
                self._click_template("buttons/train_btn")
                trained = True
                break
            if self._click_at_window_relative(0.5, 0.75):
                trained = True
                break
            time.sleep(VERIFY_DELAY * 0.5)

        time.sleep(VERIFY_DELAY)
        self._press_escape()
        time.sleep(VERIFY_DELAY)
        self._press_escape()
        time.sleep(VERIFY_DELAY)

        self._navigate_to_city()
        return trained

    def _handle_heal_troops(self, action: dict) -> bool:
        if not self._navigate_to_city():
            logger.debug("Cannot navigate to city for healing")
            return False

        clicked = self._click_template("buildings/hospital")
        if not clicked:
            clicked = self._click_at_window_relative(0.65, 0.55)
        if not clicked:
            logger.debug("Failed to click hospital")
            return False

        time.sleep(VERIFY_DELAY * 1.5)

        healed = False
        for _ in range(MAX_RETRIES):
            if self._click_template("buttons/heal_btn"):
                healed = True
                break
            if self._click_at_window_relative(0.5, 0.75):
                healed = True
                break
            time.sleep(VERIFY_DELAY * 0.5)

        time.sleep(VERIFY_DELAY)
        self._press_escape()
        time.sleep(VERIFY_DELAY)
        self._press_escape()
        time.sleep(VERIFY_DELAY)

        self._navigate_to_city()
        return healed

    def _scan_for_template(
        self, template_name: str, max_drags: int = 8
    ) -> bool:
        return self._scan_for_any_template([template_name], max_drags=max_drags) is not None

    def _scan_for_any_template(
        self, template_names: list[str], max_drags: int = 8
    ) -> Match | None:
        frame = self._capture.grab_full()
        if frame is not None:
            match = self._find_first_template_in_frame(frame, template_names, actionable=True)
            if match is not None:
                return match

        win = self._capture.window
        if win is None:
            return None
        cx = win["left"] + win["width"] // 2
        cy = win["top"] + win["height"] // 2
        drag_dist = win["width"] // 3

        directions = [
            (drag_dist, 0), (0, drag_dist),
            (-drag_dist, 0), (0, -drag_dist),
            (drag_dist, drag_dist), (-drag_dist, -drag_dist),
            (-drag_dist, drag_dist), (drag_dist, -drag_dist),
        ]

        for i in range(min(max_drags, len(directions))):
            dx, dy = directions[i]
            self._drag_map(cx, cy, cx + dx, cy + dy)
            time.sleep(VERIFY_DELAY)

            frame = self._capture.grab_full()
            if frame is None:
                continue
            match = self._find_first_template_in_frame(frame, template_names, actionable=True)
            if match is not None:
                logger.info("Found %s after %d drags", match.name, i + 1)
                return match

        return None

    def _drag_map(
        self, from_x: int, from_y: int, to_x: int, to_y: int, duration_ms: int = 500
    ):
        hx1, hy1 = screen_to_hid(from_x, from_y)
        hx2, hy2 = screen_to_hid(to_x, to_y)
        dx = hx2 - hx1
        dy = hy2 - hy1
        self._cmd.send("MOVETO", hx1, hy1)
        time.sleep(CLICK_SETTLE)
        self._cmd.send("DRAG", 0, 0, dx, dy, duration_ms)
        time.sleep(0.3)

    def _scroll_at_center(self, amount: int, count: int = 1):
        win = self._capture.window
        if win is None:
            return
        cx = win["left"] + win["width"] // 2
        cy = win["top"] + win["height"] // 2
        hx, hy = screen_to_hid(cx, cy)
        self._cmd.send("MOVETO", hx, hy)
        time.sleep(CLICK_SETTLE)
        for _ in range(count):
            self._cmd.send("SCROLL", amount)
            time.sleep(0.15)

    def _return_to_icon_zoom(self):
        self._click_center_of_screen()
        time.sleep(0.5)
        self._scroll_at_center(-5, ICON_ZOOM_SCROLLS)
        time.sleep(1.0)

    def _verify_gem_after_icon_click(
        self, icon: Match, icon_frame=None,
    ) -> tuple[bool, tuple[int, int] | None]:
        """Click a gem icon, zoom in, verify it's really a gem mine.

        Returns (is_gem, mine_center_in_frame) where mine_center is the
        frame-relative position to use for gather popup search.
        """
        icon_patch = None
        if icon_frame is not None:
            icon_patch = self._extract_icon_patch(icon_frame, icon)

        screen_x, screen_y = self._frame_to_screen(*icon.center)
        self._click_at_screen(screen_x, screen_y)
        time.sleep(2.5)

        frame = self._capture.grab_full()
        if frame is None:
            return False, None

        gem_confirmed = False
        mine_match = None
        for tpl in GEM_TEMPLATES:
            m = self._find_template_in_frame(frame, tpl)
            if m and m.confidence >= GEM_MINE_VERIFY_THRESHOLD:
                gem_confirmed = True
                if mine_match is None or m.confidence > mine_match.confidence:
                    mine_match = m
                break

        # Auto-label for classifier
        if icon_patch is not None and icon_patch.size > 0:
            self._classifier.add_sample(icon_patch, gem_confirmed)
            label_str = "gem" if gem_confirmed else "not_gem"
            stats = self._classifier.get_stats()
            logger.info(
                "[LEARN] Added %s sample #%d (gem=%d, not_gem=%d)",
                label_str, stats["total"], stats["gem"], stats["not_gem"],
            )

        gather = self._find_template_in_frame(frame, "buttons/gather_btn")
        gather_visible = gather is not None and gather.confidence >= 0.65

        if gather_visible and gem_confirmed:
            logger.info("Gem mine confirmed + gather popup open")
            return True, (mine_match or gather).center

        if gather_visible and not gem_confirmed:
            logger.info("Gather popup but NOT gem -- dismissing")
            self._press_escape()
            time.sleep(0.5)
            return False, None

        if gem_confirmed and mine_match is not None:
            mine_sx, mine_sy = self._frame_to_screen(*mine_match.center)
            self._click_at_screen(mine_sx, mine_sy)
            time.sleep(2.0)
            frame2 = self._capture.grab_full()
            if frame2 is not None:
                g2 = self._find_template_in_frame(frame2, "buttons/gather_btn")
                if g2 and g2.confidence >= 0.65:
                    logger.info("Gather popup opened after mine click")
                    return True, mine_match.center
            self._click_center_of_screen()
            time.sleep(2.0)
            frame3 = self._capture.grab_full()
            if frame3 is not None:
                g3 = self._find_template_in_frame(frame3, "buttons/gather_btn")
                if g3 and g3.confidence >= 0.65:
                    return True, mine_match.center
            logger.info("Gem confirmed but gather popup won't open")
            self._press_escape()
            time.sleep(0.5)
            return False, None

        self._press_escape()
        time.sleep(0.5)
        return False, None

    def _scan_gem_icons(self, max_scans: int = 24) -> tuple[Match | None, tuple[int, int] | None]:
        """Spiral scan for gem icons with color filter + two-step verify.

        Returns (icon_match, mine_center_in_frame) on success, (None, None) on failure.
        """
        win = self._capture.window
        if win is None:
            return None, None

        ww, wh = win["width"], win["height"]
        drag_x = min(int(ww * 0.80), ww // 2 - 30)
        drag_y = min(int(wh * 0.80), wh // 2 - 30)
        cx = win["left"] + ww // 2
        cy = win["top"] + wh // 2

        directions = [(1, 0), (0, 1), (-1, 0), (0, -1)]
        leg = 1
        dir_idx = 0
        turns = 0
        scan_count = 0
        clicked_positions: list[tuple[int, int]] = []

        frame = self._capture.grab_full()
        if frame is not None:
            icons = self._find_gem_icons_filtered(frame)
            for icon in icons:
                clicked_positions.append(icon.center)
                is_gem, mine_pos = self._verify_gem_after_icon_click(icon, icon_frame=frame)
                if is_gem:
                    return icon, mine_pos
                self._return_to_icon_zoom()

        while scan_count < max_scans:
            dx_u, dy_u = directions[dir_idx % 4]
            for _ in range(leg):
                if scan_count >= max_scans:
                    break
                scan_count += 1

                dx = dx_u * drag_x
                dy = dy_u * drag_y
                from_x, from_y = cx, cy
                to_x, to_y = cx - dx, cy - dy
                self._drag_map(from_x, from_y, to_x, to_y)
                time.sleep(1.2)

                frame = self._capture.grab_full()
                if frame is None:
                    continue

                icons = self._find_gem_icons_filtered(frame)
                for icon in icons:
                    if any(abs(icon.center[0] - px) < 80 and abs(icon.center[1] - py) < 80
                           for px, py in clicked_positions):
                        continue
                    clicked_positions.append(icon.center)
                    is_gem, mine_pos = self._verify_gem_after_icon_click(icon, icon_frame=frame)
                    if is_gem:
                        return icon, mine_pos
                    self._return_to_icon_zoom()

            dir_idx += 1
            turns += 1
            if turns % 2 == 0:
                leg += 1

        return None, None

    def _handle_gather_gem(self, action: dict) -> bool:
        """Gem-specific gather: icon scan + color filter + two-step verify."""
        if not self._navigate_to_world_map():
            logger.debug("Cannot navigate to world map for gem search")
            return False

        self._click_center_of_screen()
        time.sleep(0.3)
        self._scroll_at_center(-5, ICON_ZOOM_SCROLLS)
        time.sleep(1.0)

        icon, mine_pos = self._scan_gem_icons()
        if icon is None or mine_pos is None:
            logger.debug("No gem mine found during scan")
            self._navigate_to_city()
            return False

        time.sleep(VERIFY_DELAY * 1.5)

        gathered = False
        for _ in range(MAX_RETRIES):
            match = self._find_template_near("buttons/gather_btn", mine_pos)
            if match is None:
                match = self._find_template("buttons/gather_btn")
            if match is not None and self._click_match_verified("buttons/gather_btn", match):
                gathered = True
                break
            time.sleep(VERIFY_DELAY * 0.5)

        if not gathered:
            logger.debug("Gather button not found for gem")
            self._press_escape()
            self._navigate_to_city()
            return False

        time.sleep(VERIFY_DELAY)

        selected_new_troop = False
        for _ in range(MAX_RETRIES):
            for march_template in MARCH_TEMPLATES:
                ok, _ = self._click_template_verified(march_template)
                if ok:
                    time.sleep(VERIFY_DELAY * 2)
                    return self._navigate_to_city()

            if not selected_new_troop:
                new_troop = self._find_template("buttons/new_troop_btn", actionable=True)
                if new_troop is not None and self._click_match_verified("buttons/new_troop_btn", new_troop):
                    selected_new_troop = True
                    time.sleep(VERIFY_DELAY)
                    continue

            time.sleep(VERIFY_DELAY * 0.5)

        logger.debug("March button not found for gem")
        self._press_escape()
        self._navigate_to_city()
        return False

    def _handle_gather_resource(self, action: dict) -> bool:
        params = action.get("params", {})
        resource_type = params.get("resource_type", "food")

        if resource_type == "gem":
            return self._handle_gather_gem(action)

        templates = RESOURCE_TEMPLATE_MAP.get(resource_type, [])
        if not templates:
            logger.debug("No resource templates configured for: %s", resource_type)
            return False

        if not self._prepare_resource_search_state(templates):
            logger.debug("Cannot prepare search state for gathering")
            return False

        resource_match = self._scan_for_any_template(templates)
        mine_pos = None
        if resource_match is not None and self._click_match_verified(resource_match.name, resource_match):
            mine_pos = resource_match.center

        if mine_pos is None:
            logger.debug("Resource node not found: %s", resource_type)
            self._navigate_to_city()
            return False

        # Step 2: Wait for action popup (appears relative to mine position)
        time.sleep(VERIFY_DELAY * 1.5)

        # Step 3: Find gather button near mine, verify, then click
        gathered = False
        for _ in range(MAX_RETRIES):
            match = self._find_template_near("buttons/gather_btn", mine_pos)
            if match is None:
                match = self._find_template("buttons/gather_btn")
            if match is not None and self._click_match_verified("buttons/gather_btn", match):
                gathered = True
                break
            time.sleep(VERIFY_DELAY * 0.5)

        if not gathered:
            logger.debug("Gather button not found for %s", resource_type)
            self._press_escape()
            self._navigate_to_city()
            return False

        # Step 4: March confirmation (centered dialog, full-frame search)
        time.sleep(VERIFY_DELAY)

        selected_new_troop = False
        for _ in range(MAX_RETRIES):
            for march_template in MARCH_TEMPLATES:
                ok, _ = self._click_template_verified(march_template)
                if ok:
                    time.sleep(VERIFY_DELAY * 2)
                    return self._navigate_to_city()

            if not selected_new_troop:
                new_troop = self._find_template("buttons/new_troop_btn", actionable=True)
                if new_troop is not None and self._click_match_verified("buttons/new_troop_btn", new_troop):
                    selected_new_troop = True
                    time.sleep(VERIFY_DELAY)
                    continue

            time.sleep(VERIFY_DELAY * 0.5)

        logger.debug("March button not found")
        self._press_escape()
        self._navigate_to_city()
        return False
