"""
Gem Farm Flow -- E2E Test via ESP32 HID

Flow per mine:
  1. From city view -> click world map button (bottom-right) -> zoom out 2x
  2. Random wander scan map for gem_icon (white diamond)
  3. Click gem icon -> game auto-zooms into mine area
  4. Click on actual gem mine structure to open gather popup
  5. Click "Thu Thập" (gather_btn)
  6. Select "New Troop" if troop panel appears, then click "March"
  7. Return to city view for next mine

Run: .venv\Scripts\python -m tools.test_gem_farm_flow --port COM27 --count 2
"""

import sys
import os
import re
import time
import math
import logging
import argparse
import random
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np

try:
    from rapidocr_onnxruntime import RapidOCR
    _ocr_engine = RapidOCR()
    _OCR_BACKEND = "rapidocr"
except ImportError:
    _ocr_engine = None
    try:
        import pytesseract
        _OCR_BACKEND = "pytesseract"
    except ImportError:
        _OCR_BACKEND = None

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.screen_capture import ScreenCapture
from capture.screen_info import get_cursor_pos
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher, Match
from vision.state_detector import StateDetector
from vision.color_filter import is_gem_icon_color, is_gem_mine_color, normalize_frame
from vision.gem_classifier import GemPatchClassifier
from anti_detection.profile_loader import ProfileLoader, DEFAULT_PROFILE
from anti_detection.timing_engine import TimingEngine
from anti_detection.session_manager import SessionManager, IdleAction
from anti_detection.mouse_humanizer import MouseHumanizer

SCREENSHOT_DIR = Path("tools/screenshots/gem_farm_test")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / f"gem_farm_test_{datetime.now():%Y%m%d_%H%M%S}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("gem_farm_test")

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
INFO = "\033[94mINFO\033[0m"

# --- Thresholds ---
ICON_ZOOM_SCROLLS = 0
GEM_ICON_THRESHOLD = 0.72
BUTTON_THRESHOLD = 0.70
GATHER_BTN_THRESHOLD = 0.65
WORLD_MAP_BTN_THRESHOLD = 0.75
GEM_MINE_THRESHOLD = 0.60
OCCUPY_ICON_PCT = 1.0
SAFE_ZONE_MARGIN = 0.08
DARK_TERRAIN_THRESH = 70
DRAG_OVERLAP = 0.20

MARCH_TEMPLATES = ["buttons/march_btn_orange", "buttons/march_btn"]
GEM_MINE_TEMPLATES = ["resources/gem_mine_close", "resources/gem_mine"]

# --- Window layout ---
TITLE_BAR_H = 40

# --- Time delays (seconds) ---
DELAY_AFTER_CLICK = 0.4
DELAY_AFTER_ESCAPE = 0.5
DELAY_AFTER_SCROLL = 1.0
DELAY_ZOOM_IN = 2.0
DELAY_MINE_CLICK = 1.0
DELAY_RECHECK = 0.8
DELAY_VERIFY = 1.2
DELAY_DRAG_SETTLE = 1.2
DELAY_WORLD_MAP = 1.5
DELAY_BETWEEN_MINES = 4.0
DELAY_DRAG_PRE = (0.15, 0.4)
DELAY_DRAG_POST = (0.5, 1.5)
DELAY_MICRO_PAUSE = (1.0, 3.0)



_SAVE_SCREENSHOTS = True


def save_screenshot(frame, name):
    if not _SAVE_SCREENSHOTS:
        return None
    ts = datetime.now().strftime("%H%M%S")
    path = SCREENSHOT_DIR / f"{name}_{ts}.png"
    cv2.imwrite(str(path), frame)
    return str(path)


def save_annotated(frame, match, name):
    ann = frame.copy()
    if match:
        cv2.rectangle(ann, (match.x, match.y),
                       (match.x + match.w, match.y + match.h), (0, 255, 0), 2)
        cv2.circle(ann, match.center, 5, (0, 0, 255), -1)
        cv2.putText(ann, f"{match.confidence:.3f}", (match.x, match.y - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    ts = datetime.now().strftime("%H%M%S")
    path = SCREENSHOT_DIR / f"{name}_{ts}.png"
    cv2.imwrite(str(path), ann)
    return str(path)


class GemFarmFlowTest:
    def __init__(self, port: str, count: int = 1, auto_learn: bool = False,
                 loop: bool = False, max_marches: int = 5):
        self.port = port
        self.count = count
        self.auto_learn = auto_learn
        self.loop = loop
        self.max_marches = max_marches
        self.sc: ScreenCapture | None = None
        self.cache: TemplateCache | None = None
        self.matcher: TemplateMatcher | None = None
        self.detector: StateDetector | None = None
        self.conn = None
        self.cmd = None
        self.win: dict | None = None
        self.results: list[dict] = []
        self.mines_completed = 0
        self.gathered_positions: list[tuple[int, int]] = []
        self._edge_gems: list[Match] = []
        self.classifier = GemPatchClassifier()
        self.classifier.load()
        self._night_logged = False
        self._raw_frame: np.ndarray | None = None
        self._cursor_scale = 1.0

        loader = ProfileLoader()
        self._profile = loader.load_random() if loader.list_profiles() else DEFAULT_PROFILE.copy()
        self.timing = TimingEngine(self._profile)
        self.session = SessionManager(self._profile)
        self.humanizer = MouseHumanizer(self._profile)

    # --- Anti-detection helpers ---

    def _wait(self, base: float, variance: float = 0.0) -> float:
        fatigue = self.timing.apply_fatigue(self.session.elapsed_minutes)
        std = max(base * 0.3, variance)
        actual = random.gauss(base, std) * fatigue
        actual = max(base * 0.4, actual)

        pause = self.timing.micro_pause()
        if pause:
            actual += pause
            logger.debug("micro-pause +%.1fs", pause)

        time.sleep(actual)
        return actual

    def _do_idle_action(self):
        action = self.session.get_idle_action()
        if action is None:
            return
        cx, cy = self._center_screen()
        if action == IdleAction.PAN_MAP:
            dx = random.randint(-150, 150)
            dy = random.randint(-100, 100)
            sx, sy = self._clamp_to_play_area(cx + dx, cy + dy)
            ex, ey = self._clamp_to_play_area(cx - dx, cy - dy)
            self._human_drag(sx, sy, ex, ey)
            self._wait(2.0, 1.0)
            logger.info("idle: pan_map")
        elif action in (IdleAction.ZOOM_IN, IdleAction.ZOOM_OUT):
            amt = 3 if action == IdleAction.ZOOM_IN else -3
            self._scroll_at_center(amt, 1)
            self._wait(1.5, 0.5)
            self._scroll_at_center(-amt, 1)
            self._wait(1.5, 0.5)
            logger.info("idle: %s (reverted)", action.value)
        else:
            pause = random.uniform(3.0, 8.0)
            time.sleep(pause)
            logger.info("idle: pause %.1fs", pause)

    _BTN_POS = {
        "bag":      (0.755, 0.953),
        "alliance": (0.803, 0.953),
        "mail":     (0.898, 0.953),
    }
    _X_CLOSE_POS = {
        "bag":      (0.865, 0.187),
        "alliance": (0.765, 0.233),
        "mail":     (0.830, 0.086),
    }
    _PANEL_ITEMS = {
        "bag": [
            (0.12, 0.187), (0.24, 0.187), (0.36, 0.187),
            (0.48, 0.187), (0.60, 0.187), (0.72, 0.187),
        ],
        "alliance": [
            (0.38, 0.52), (0.48, 0.52), (0.58, 0.52), (0.68, 0.52), (0.78, 0.52),
            (0.38, 0.72), (0.48, 0.72), (0.58, 0.72), (0.68, 0.72), (0.78, 0.72),
        ],
        "mail": [
            (0.08, 0.086), (0.18, 0.086), (0.27, 0.086),
            (0.37, 0.086), (0.46, 0.086), (0.57, 0.086),
        ],
    }

    def _click_pct(self, pct_x: float, pct_y: float, jitter_px: int = 10):
        ww, wh = self.win["width"], self.win["height"]
        sx = self.win["left"] + int(ww * pct_x) + random.randint(-jitter_px, jitter_px)
        sy = self.win["top"] + int(wh * pct_y) + random.randint(-jitter_px, jitter_px)
        self._click(sx, sy)

    def _close_panel(self, panel: str):
        x_tpl = f"ui/btn_x_close_{panel}"
        for _ in range(3):
            if panel in self._X_CLOSE_POS:
                self._click_pct(*self._X_CLOSE_POS[panel], jitter_px=5)
                time.sleep(random.uniform(0.5, 1.0))
            frame = self._grab()
            if frame is None:
                break
            m = self.matcher.match_single(frame, x_tpl)
            if not m or m.confidence < 0.80 or m.center[1] >= frame.shape[0] * 0.30:
                break
            logger.debug("close_panel: %s X still visible (conf=%.3f), retrying",
                         panel, m.confidence)

    def _collect_city_resources(self):
        frame = self._grab()
        if frame is None:
            return 0
        tpl_names = [
            "resources/city_food", "resources/city_wood",
            "resources/city_gold", "resources/city_stone",
        ]
        collected = 0
        for tpl_name in tpl_names:
            tpl = self.cache.get(tpl_name)
            if tpl is None:
                continue
            matches = [m for m in self.matcher.match_all(frame, tpl_name)
                       if m.confidence >= 0.95]
            if matches:
                best = max(matches, key=lambda m: m.confidence)
                self._click_match(best)
                time.sleep(random.uniform(0.3, 0.8))
                collected += 1
        if collected > 0:
            logger.info("Collected %d city resources", collected)
        return collected

    def _idle_while_queue_full(self):
        if not hasattr(self, '_queue_wait_start'):
            self._queue_wait_start = time.time()

        waited_min = (time.time() - self._queue_wait_start) / 60.0
        if waited_min > 20:
            self.mines_completed = max(0, self.mines_completed - 1)
            self._queue_wait_start = time.time()
            print(f"  [{INFO}] Waited {waited_min:.0f}min, assuming 1 slot freed")

        actions = (["pause"] * 20 + ["collect", "mail", "alliance", "bag", "pan"])
        pick = random.choice(actions)
        cx, cy = self._center_screen()
        ww, wh = self.win["width"], self.win["height"]

        if pick == "collect":
            n = self._collect_city_resources()
            logger.info("idle-queue: collected %d resources", n)
        elif pick in ("mail", "alliance", "bag"):
            self._click_pct(*self._BTN_POS[pick])
            time.sleep(random.uniform(2.0, 5.0))
            items = self._PANEL_ITEMS.get(pick, [])
            n_clicks = random.randint(0, min(3, len(items)))
            clicked = random.sample(items, n_clicks)
            for ix, iy in clicked:
                self._click_pct(ix, iy)
                time.sleep(random.uniform(2.0, 8.0))
            self._close_panel(pick)
            logger.info("idle-queue: browsed %s (%d items)", pick, n_clicks)
        elif pick == "pan":
            m = self._find("buttons/world_map_city_btn", threshold=WORLD_MAP_BTN_THRESHOLD)
            if not m:
                logger.debug("idle-queue: world map btn not found, skipping pan")
            else:
                self._click_match(m)
                self._wait(DELAY_WORLD_MAP)
                zoom_out = random.randint(0, 3)
                if zoom_out > 0:
                    self._scroll_at_center(-1, zoom_out)
                    time.sleep(random.uniform(0.5, 1.5))
                drags = random.randint(1, 3)
                for _ in range(drags):
                    dx = random.randint(-int(ww * 0.3), int(ww * 0.3))
                    dy = random.randint(-int(wh * 0.2), int(wh * 0.2))
                    sx, sy = self._clamp_to_play_area(cx + dx, cy + dy)
                    ex, ey = self._clamp_to_play_area(cx - dx, cy - dy)
                    self._human_drag(sx, sy, ex, ey)
                    time.sleep(random.uniform(1.0, 4.0))
                city_btn = self._find("buttons/city_btn", threshold=0.75)
                if city_btn:
                    self._click_match(city_btn)
                    self._wait(DELAY_WORLD_MAP)
                else:
                    self._press_escape()
                    self._wait(DELAY_AFTER_ESCAPE)
                logger.info("idle-queue: browsed world map (zoom=%d, drags=%d)",
                            zoom_out, drags)
        else:
            wait = random.uniform(15.0, 45.0)
            time.sleep(wait)
            logger.info("idle-queue: paused %.1fs", wait)

        time.sleep(random.uniform(5.0, 15.0))

    def _check_session(self) -> str | None:
        if self.session.should_take_break():
            return "break"
        return None

    def _detect_march_queue(self) -> tuple[int, int] | None:
        """Read march queue (e.g. '1/5') from city view via OCR. Returns (used, total) or None."""
        if _OCR_BACKEND is None:
            return None
        frame = self._grab()
        if frame is None:
            return None
        fh, fw = frame.shape[:2]
        x1 = int(fw * 0.93)
        y1 = int(fh * 0.15)
        x2 = fw
        y2 = int(fh * 0.26)
        roi = frame[y1:y2, x1:x2]

        if not hasattr(self, '_queue_roi_saved') or not self._queue_roi_saved:
            save_screenshot(roi, "queue_roi_debug")
            self._queue_roi_saved = True

        try:
            texts = []
            if _OCR_BACKEND == "rapidocr":
                result, _ = _ocr_engine(roi)
                if result:
                    sorted_r = sorted(result, key=lambda r: r[0][0][0])
                    texts = [''.join(r[1] for r in sorted_r)]
            else:
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
                binary = cv2.resize(binary, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                raw = pytesseract.image_to_string(
                    binary, config='--psm 7 -c tessedit_char_whitelist=0123456789/')
                texts = [raw.strip()]

            for text in texts:
                logger.debug("Queue OCR: '%s'", text)
                m = re.search(r'(\d)\s*/\s*(\d)', text)
                if m:
                    used, total = int(m.group(1)), int(m.group(2))
                    if 0 <= used <= total <= 9:
                        return used, total
        except Exception as e:
            logger.debug("Queue OCR error: %s", e)
        return None

    # --- Frame capture with day/night normalization ---

    def _grab(self) -> np.ndarray | None:
        frame = self.sc.grab_full()
        if frame is None:
            self._raw_frame = None
            return None
        self._raw_frame = frame
        normalized, is_night = normalize_frame(frame)
        if is_night and not self._night_logged:
            print(f"  [{INFO}] Night mode detected -- normalizing frames")
            self._night_logged = True
        return normalized

    # --- Coordinate helpers (all constrained to game window) ---

    def _screen_xy(self, frame_x: int, frame_y: int) -> tuple[int, int]:
        return frame_x + self.win["left"], frame_y + self.win["top"]

    def _center_screen(self) -> tuple[int, int]:
        return (self.win["left"] + self.win["width"] // 2,
                self.win["top"] + self.win["height"] // 2)

    @staticmethod
    def _zoom_scrolls() -> int:
        return ICON_ZOOM_SCROLLS if ICON_ZOOM_SCROLLS > 0 else 3

    def _clamp_to_window(self, sx: int, sy: int, pad: int = 5) -> tuple[int, int]:
        x = max(self.win["left"] + pad, min(self.win["left"] + self.win["width"] - pad, sx))
        top_pad = max(pad, TITLE_BAR_H)
        y = max(self.win["top"] + top_pad, min(self.win["top"] + self.win["height"] - pad, sy))
        return x, y

    def _clamp_to_play_area(self, sx: int, sy: int) -> tuple[int, int]:
        wl, wt = self.win["left"], self.win["top"]
        ww, wh = self.win["width"], self.win["height"]
        x = max(wl + int(ww * 0.12), min(wl + int(ww * 0.88), sx))
        y = max(wt + int(wh * 0.22), min(wt + int(wh * 0.70), sy))
        return x, y

    def _moveto(self, sx: int, sy: int) -> bool:
        sx, sy = self._clamp_to_window(sx, sy)
        cur_x, cur_y = get_cursor_pos()
        dx = sx - cur_x
        dy = sy - cur_y
        if abs(dx) < 3 and abs(dy) < 3:
            return True

        path = self.humanizer.humanize_move(cur_x, cur_y, sx, sy)
        path = self._apply_easing(path, "in_out")

        s = self._cursor_scale
        prev_x, prev_y = float(cur_x), float(cur_y)
        for px, py, step_ms in path:
            mdx, mdy = px - prev_x, py - prev_y
            send_dx = int(mdx / s) if s != 1.0 else int(mdx)
            send_dy = int(mdy / s) if s != 1.0 else int(mdy)
            if abs(send_dx) > 0 or abs(send_dy) > 0:
                self.cmd.send("MOVE", send_dx, send_dy, step_ms)
            prev_x, prev_y = px, py

        self._correct_position(sx, sy)
        return True

    def _correct_position(self, tx: int, ty: int, max_attempts: int = 4) -> None:
        for _ in range(max_attempts):
            time.sleep(0.03)
            cur_x, cur_y = get_cursor_pos()
            dx = tx - cur_x
            dy = ty - cur_y
            if abs(dx) < 3 and abs(dy) < 3:
                return
            send_dx = int(dx / self._cursor_scale)
            send_dy = int(dy / self._cursor_scale)
            if send_dx == 0 and send_dy == 0:
                send_dx = 1 if dx > 0 else (-1 if dx < 0 else 0)
                send_dy = 1 if dy > 0 else (-1 if dy < 0 else 0)
            dist = (send_dx**2 + send_dy**2) ** 0.5
            if dist > 15:
                steps = random.randint(2, 3)
                perp_x, perp_y = -send_dy / dist, send_dx / dist
                curve_offset = random.gauss(0, dist * 0.1)
                for s in range(1, steps + 1):
                    t = s / steps
                    frac_x = int(send_dx * t + perp_x * curve_offset * math.sin(t * math.pi))
                    frac_y = int(send_dy * t + perp_y * curve_offset * math.sin(t * math.pi))
                    seg_dx = frac_x - (int(send_dx * (s - 1) / steps) if s > 1 else 0)
                    seg_dy = frac_y - (int(send_dy * (s - 1) / steps) if s > 1 else 0)
                    seg_dur = max(20, int(dist / steps * random.uniform(0.5, 1.0)))
                    if abs(seg_dx) > 0 or abs(seg_dy) > 0:
                        self.cmd.send("MOVE", seg_dx, seg_dy, seg_dur)
                        time.sleep(0.02)
            else:
                dur = max(30, int(dist * random.uniform(0.5, 1.2)))
                self.cmd.send("MOVE", send_dx, send_dy, dur)
            time.sleep(0.03)
            new_x, new_y = get_cursor_pos()
            actual_dx = new_x - cur_x
            actual_dy = new_y - cur_y
            ref_sent = send_dx if abs(send_dx) > abs(send_dy) else send_dy
            ref_actual = actual_dx if abs(send_dx) > abs(send_dy) else actual_dy
            if abs(ref_sent) > 15 and abs(ref_actual) > 5:
                measured = ref_actual / ref_sent
                if measured > 0.1:
                    self._cursor_scale = self._cursor_scale * 0.6 + measured * 0.4

    _NO_CLICK_ZONES = [
        (0.0, 0.0, 0.70, 0.13),
    ]

    def _in_no_click_zone(self, sx: int, sy: int) -> bool:
        rx = (sx - self.win["left"]) / self.win["width"]
        ry = (sy - self.win["top"]) / self.win["height"]
        for x1, y1, x2, y2 in self._NO_CLICK_ZONES:
            if x1 <= rx <= x2 and y1 <= ry <= y2:
                return True
        return False

    def _click(self, sx: int, sy: int, hold_ms: int = 0) -> bool:
        ox, oy, h = self.humanizer.humanize_click(sx, sy)
        sx += ox
        sy += oy
        if self._in_no_click_zone(sx, sy):
            logger.debug("Click blocked: (%d,%d) in no-click zone", sx, sy)
            return False
        if not self._moveto(sx, sy):
            return False
        time.sleep(random.uniform(0.08, 0.25))
        if hold_ms <= 0:
            hold_ms = h
        ok = self.cmd.send("CLICK", "L", hold_ms)
        self.session.record_action()
        self._wait(DELAY_AFTER_CLICK, 0.4)
        return ok

    def _click_match(self, match: Match) -> bool:
        sx, sy = self._screen_xy(*match.center)
        jx = random.randint(-match.w // 6, match.w // 6)
        jy = random.randint(-match.h // 6, match.h // 6)
        return self._click(sx + jx, sy + jy)

    def _human_drag(self, sx: int, sy: int, ex: int, ey: int,
                    button: str = "L", speed_factor: float = 1.0,
                    easing: str = "in_out"):
        self._moveto(sx, sy)
        time.sleep(random.uniform(0.08, 0.2))

        path = self.humanizer.humanize_move(sx, sy, ex, ey)
        if speed_factor != 1.0:
            path = [(x, y, max(3, int(ms / speed_factor))) for x, y, ms in path]
        path = self._apply_easing(path, easing)

        self.cmd.send("MDOWN", button)
        time.sleep(random.uniform(0.01, 0.03))

        prev_x, prev_y = sx, sy
        s = self._cursor_scale
        for px, py, step_ms in path:
            dx, dy = int(px - prev_x), int(py - prev_y)
            send_dx = int(dx / s) if s != 1.0 else dx
            send_dy = int(dy / s) if s != 1.0 else dy
            if abs(send_dx) > 0 or abs(send_dy) > 0:
                self.cmd.send("MOVE", send_dx, send_dy, step_ms)
            prev_x, prev_y = px, py

        time.sleep(random.uniform(0.01, 0.03))
        self.cmd.send("MUP", button)

        time.sleep(0.03)
        actual_x, actual_y = get_cursor_pos()
        intended_dx = ex - sx
        intended_dy = ey - sy
        actual_dx = actual_x - sx
        actual_dy = actual_y - sy
        ref_i = intended_dx if abs(intended_dx) > abs(intended_dy) else intended_dy
        ref_a = actual_dx if abs(intended_dx) > abs(intended_dy) else actual_dy
        if abs(ref_i) > 50 and abs(ref_a) > 20:
            ratio = ref_a / (ref_i / s)
            if 0.2 < ratio < 5.0:
                self._cursor_scale = self._cursor_scale * 0.5 + ratio * 0.5

    def _apply_easing(self, path: list[tuple[int, int, int]],
                      mode: str = "in_out") -> list[tuple[int, int, int]]:
        n = len(path)
        result = []
        for i, (x, y, ms) in enumerate(path):
            t = i / max(n - 1, 1)
            if mode == "in":
                factor = 1.6 - t * 1.0
            else:
                factor = 0.6 + 0.8 * abs(2 * t - 1)
            result.append((x, y, max(3, int(ms * factor))))
        return result

    def _scroll_at_center(self, amount: int, count: int = 1):
        cx, cy = self._center_screen()
        cx += random.randint(-int(self.win["width"] * 0.25), int(self.win["width"] * 0.25))
        cy += random.randint(-int(self.win["height"] * 0.15), int(self.win["height"] * 0.15))
        cx, cy = self._clamp_to_play_area(cx, cy)
        self._moveto(cx, cy)
        time.sleep(random.uniform(0.15, 0.4))

        overshoot = random.random() < 0.15
        extra = random.randint(1, 2) if overshoot else 0
        total_notches = abs(amount) * (count + extra)
        direction = 1 if amount > 0 else -1
        for i in range(total_notches):
            self.cmd.send("SCROLL", direction)
            time.sleep(random.uniform(0.04, 0.12))
            if random.random() < 0.15:
                time.sleep(random.uniform(0.1, 0.3))
        if overshoot and extra > 0:
            time.sleep(random.uniform(0.4, 1.0))
            correction = max(1, int(extra * 0.6))
            for _ in range(correction):
                self.cmd.send("SCROLL", -direction)
                time.sleep(random.uniform(0.04, 0.12))

    def _press_escape(self):
        rx = random.uniform(0.20, 0.80)
        ry = random.uniform(0.22, 0.40)
        sx = self.win["left"] + int(self.win["width"] * rx)
        sy = self.win["top"] + int(self.win["height"] * ry)
        self._moveto(sx, sy)
        time.sleep(random.uniform(0.03, 0.12))
        self.cmd.send("CLICK", "L", random.randint(30, 80))

    # --- Template helpers ---

    def _find(self, template: str, threshold: float = 0.65) -> Match | None:
        frame = self._grab()
        if frame is None:
            return None
        m = self.matcher.match_single(frame, template)
        if m and m.confidence >= threshold:
            return m
        return None

    def _find_on_frame(self, frame, template: str, threshold: float = 0.65) -> Match | None:
        m = self.matcher.match_single(frame, template)
        if m and m.confidence >= threshold:
            return m
        return None

    def _find_all_gems(self, frame) -> list[Match]:
        matches = self.matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
        result = []
        edge_gems = []
        for m in matches:
            if m.confidence < GEM_ICON_THRESHOLD:
                continue
            patch = self._extract_icon_patch(frame, m)
            should, label, clf_conf = self.classifier.should_click(patch)
            if not should:
                logger.info("gem_icon classifier REJECT at %s: %s (%.2f)", m.center, label, clf_conf)
                continue
            ok, zone_info = self._is_clickable_zone(frame, m)
            if not ok:
                if zone_info.startswith("edge"):
                    logger.info("gem_icon at EDGE %s conf=%.3f -- will recenter", m.center, m.confidence)
                    edge_gems.append(m)
                else:
                    logger.info("gem_icon zone REJECT at %s conf=%.3f: %s", m.center, m.confidence, zone_info)
                continue
            logger.debug("gem_icon OK at %s: clf=%s(%.2f)", m.center, label, clf_conf)
            result.append(m)
        self._edge_gems = edge_gems
        return result

    # --- Main flow ---

    def run(self):
        for f in SCREENSHOT_DIR.glob("*.png"):
            f.unlink()

        print("=" * 60)
        print("  GEM FARM FLOW -- E2E Test (Anti-Detection ON)")
        print("=" * 60)
        print(f"  Port: {self.port}")
        if self.loop:
            print(f"  Mode: loop (max {self.max_marches} marches)")
        else:
            print(f"  Target mines: {self.count}")
        print(f"  Profile: {self._profile.get('name', 'default')}")
        print()

        try:
            if not self._setup():
                return

            pass

            i = 1
            consecutive_fails = 0
            while True:
                if not self.loop and i > self.count:
                    break

                if self.loop:
                    queue = self._detect_march_queue()
                    if queue:
                        used, total = queue
                        if used >= total:
                            print(f"\n  [{INFO}] Queue full ({used}/{total}), waiting...")
                            self._idle_while_queue_full()
                            self.mines_completed = used
                            continue
                        self.mines_completed = used
                        print(f"  [{INFO}] Queue: {used}/{total}, {total - used} slot(s) free")
                    elif self.mines_completed >= self.max_marches:
                        print(f"\n  [{INFO}] Queue likely full ({self.mines_completed}/{self.max_marches} by counter), waiting...")
                        self._idle_while_queue_full()
                        continue

                status = self._check_session()
                if status == "break":
                    dur = self.session.get_break_duration()
                    mins = dur / 60.0
                    print(f"\n  [{INFO}] Session break: {mins:.1f} min "
                          f"(after {self.session.elapsed_minutes:.0f} min active)")
                    time.sleep(dur)
                    continue

                label = f"{i}" if self.loop else f"{i}/{self.count}"
                print(f"\n{'*' * 60}")
                print(f"  *** MINE {label} ***")
                print(f"  Session: {self.session.elapsed_minutes:.0f} min | "
                      f"Fatigue: x{self.timing.apply_fatigue(self.session.elapsed_minutes):.2f}")
                print(f"{'*' * 60}")

                if not self._mine_flow(i):
                    print(f"\n  Mine {i} FAILED")
                    consecutive_fails += 1
                    if consecutive_fails >= 5:
                        print(f"  [{WARN}] {consecutive_fails} consecutive fails, stopping")
                        break
                    self._wait(random.uniform(3.0, 8.0))
                    i += 1
                    continue

                consecutive_fails = 0
                self.mines_completed += 1
                self._queue_wait_start = time.time()
                print(f"\n  Mine {i} DONE (total: {self.mines_completed})")

                self._wait(DELAY_BETWEEN_MINES, 2.0)
                if random.random() < 0.20:
                    extra = random.uniform(2.0, 8.0)
                    print(f"  [{INFO}] Extra pause {extra:.1f}s")
                    time.sleep(extra)
                self._do_idle_action()

                i += 1

        except KeyboardInterrupt:
            print("\n  Interrupted")
        except Exception as e:
            logger.exception("Error")
            self._record("ERROR", False, str(e))
        finally:
            self._teardown()
            self._print_report()

    def _mine_flow(self, idx: int) -> bool:
        tag = f"m{idx}"

        # Step 1: City view -> world map -> zoom out 2x
        if not self._step_to_world_map(tag):
            return False

        self._do_idle_action()
        self._wait(random.uniform(1.0, 3.0), 0.5)

        # Step 2+3+4: Wander scan, clicking each icon to verify gem type
        gem = self._step_scan_and_verify_gem(tag)
        if gem is None:
            self._step_return_city(tag)
            return False

        self._wait(random.uniform(1.5, 4.0), 1.0)

        # Step 5: Click "Thu Thap" (gather)
        if not self._step_click_gather(tag):
            return False

        self._wait(random.uniform(1.0, 3.0), 0.5)

        # Step 6: Select troop + click "March"
        if not self._step_click_march(tag):
            return False

        # Mark this gem as gathered
        self.gathered_positions.append(gem.center)
        print(f"  [{INFO}] Marked gem at {gem.center} as gathered ({len(self.gathered_positions)} total)")

        self._wait(random.uniform(2.0, 5.0), 1.0)

        # Step 7: Return to city view
        self._step_return_city(tag)
        return True

    # --- Setup ---

    def _setup(self) -> bool:
        print("--- Setup ---\n")

        self.sc = ScreenCapture()
        self.win = self.sc.find_window()
        if not self.win:
            print(f"  [{FAIL}] Game window not found")
            return False
        print(f"  [{PASS}] Window: {self.win['width']}x{self.win['height']}")

        self.cache = TemplateCache("templates")
        self.matcher = TemplateMatcher(self.cache, threshold=0.50)
        self.detector = StateDetector(self.matcher, min_confidence=0.80)

        key_templates = [
            "resources/gem_icon", "buttons/gather_btn",
            "buttons/new_troop_btn", "buttons/march_btn_orange",
            "buttons/march_btn", "buttons/city_btn",
            "ui/btn_mail", "ui/btn_alliance", "ui/btn_x_close",
            "ui/btn_x_close_mail", "ui/btn_x_close_alliance", "ui/btn_x_close_bag",
            "resources/city_food", "resources/city_wood",
            "resources/city_gold", "resources/city_stone",
        ]
        for t in key_templates:
            img = self.cache.get(t)
            status = PASS if img is not None else FAIL
            size = f"{img.shape[1]}x{img.shape[0]}" if img is not None else "MISSING"
            print(f"  [{status}] {t}: {size}")

        from serial_comm.connection import SerialConnection
        from serial_comm.command_buffer import CommandBuffer

        self.conn = SerialConnection(port=self.port)
        if not self.conn.connect():
            print(f"  [{FAIL}] ESP32 connect failed")
            return False
        self.cmd = CommandBuffer(self.conn)
        self.cmd.start()
        self._wait(DELAY_AFTER_CLICK)
        print(f"  [{PASS}] ESP32: {self.port}")

        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, "setup_initial")

        stats = self.classifier.get_stats()
        if stats["is_warm"]:
            print(f"  [{PASS}] Classifier: {stats['total']} samples (gem={stats['gem']}, not_gem={stats['not_gem']})")
        else:
            print(f"  [{INFO}] Classifier: cold start ({stats['total']}/{10} samples)")

        p = self._profile
        print(f"\n  --- Anti-Detection ---")
        print(f"  [{PASS}] Profile: {p.get('name', 'default')}")
        print(f"  [{INFO}] Action delay: {p['timing']['action_delay_mean']}ms "
              f"(+/-{p['timing']['action_delay_std']}ms)")
        print(f"  [{INFO}] Micro-pause: {p['timing']['micro_pause_chance']*100:.0f}% chance, "
              f"{p['timing']['micro_pause_range'][0]}-{p['timing']['micro_pause_range'][1]}ms")
        print(f"  [{INFO}] Session: farm {p['session']['farm_duration_mean']}min "
              f"-> break {p['session']['break_duration_mean']}min")
        print(f"  [{INFO}] Daily limit: {p['session']['daily_hours_max']}h, "
              f"window {p['session']['active_window'][0]}-{p['session']['active_window'][1]}")
        print(f"  [{INFO}] Mouse: overshoot {p['mouse']['overshoot_chance']*100:.0f}%, "
              f"spread +/-{p['mouse']['click_spread']}px, "
              f"hold {p['mouse']['hold_ms'][0]}-{p['mouse']['hold_ms'][1]}ms")

        if self.loop:
            if _OCR_BACKEND:
                print(f"  [{PASS}] Queue detection: {_OCR_BACKEND}")
            else:
                print(f"  [{INFO}] Queue detection: internal counter (no OCR)")
            print(f"  [{INFO}] Max marches: {self.max_marches}")

        self._record("setup", True, "OK")
        return True

    # --- Step 1: City view -> world map -> icon zoom ---

    def _step_to_world_map(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 1: City -> World Map -> Zoom out ---\n")

        # Check if already on world map at icon zoom
        frame = self._grab()
        if frame is not None:
            city_btn = self._find_on_frame(frame, "buttons/city_btn", threshold=0.75)
            if city_btn:
                gems = self._find_all_gems(frame)
                if gems:
                    print(f"  [{PASS}] Already on world map icon-zoom, {len(gems)} gem(s)")
                    self._record(f"{tag}_world", True, f"Already icon-zoom, {len(gems)} gems")
                    return True
                print(f"  [{INFO}] On world map but not icon-zoom, zooming out...")
                self._scroll_at_center(-1, self._zoom_scrolls())
                self._wait(DELAY_AFTER_SCROLL)
                self._record(f"{tag}_world", True, "World map, zoomed out")
                return True

        # From city view -> click world_map_city_btn (bottom-right)
        m = self._find("buttons/world_map_city_btn", threshold=WORLD_MAP_BTN_THRESHOLD)
        if m:
            print(f"  [{PASS}] world_map_city_btn: conf={m.confidence:.3f} at {m.center}")
            self._click_match(m)
            self._wait(DELAY_WORLD_MAP)
        else:
            print(f"  [{WARN}] world_map_city_btn not found, trying bottom-right click...")
            br_x = self.win["left"] + int(self.win["width"] * 0.95)
            br_y = self.win["top"] + int(self.win["height"] * 0.93)
            self._click(br_x, br_y)
            self._wait(DELAY_WORLD_MAP)

        # Verify we're on world map
        city_btn = self._find("buttons/city_btn", threshold=0.75)
        if not city_btn:
            print(f"  [{FAIL}] Not on world map after clicking")
            frame = self._grab()
            if frame is not None:
                save_screenshot(frame, f"{tag}_world_fail")
            self._record(f"{tag}_world", False, "World map nav failed")
            return False

        zs = self._zoom_scrolls()
        print(f"  [{PASS}] On world map, zooming out {zs}x...")

        cx, cy = self._center_screen()
        if random.random() < 0.3:
            pdx = random.randint(-80, 80)
            pdy = random.randint(-50, 50)
            self._human_drag(cx + pdx, cy + pdy, cx - pdx, cy - pdy)
            self._wait(random.uniform(0.5, 1.5))
        self._scroll_at_center(-1, zs)
        self._wait(DELAY_AFTER_SCROLL)

        # After previous mine: 2-3 smaller drags to move camera away naturally
        if self.mines_completed > 0:
            ww = self.win["width"]
            wh = self.win["height"]
            margin = 80
            base_angle = random.choice([(1, 0), (-1, 0), (0, 1), (0, -1),
                                        (1, 1), (-1, -1), (1, -1), (-1, 1)])
            num_drags = random.randint(2, 3)
            for drag_i in range(num_drags):
                if drag_i == 0:
                    dx_u, dy_u = base_angle
                else:
                    dx_u = base_angle[0] + random.choice([-1, 0, 0, 1])
                    dy_u = base_angle[1] + random.choice([-1, 0, 0, 1])
                    dx_u = max(-1, min(1, dx_u))
                    dy_u = max(-1, min(1, dy_u))
                    if dx_u == 0 and dy_u == 0:
                        dx_u, dy_u = base_angle
                dp = random.uniform(0.35, 0.7)
                sx = cx + int(dx_u * (ww // 2 - margin) * dp) + random.randint(-30, 30)
                ex = cx - int(dx_u * (ww // 2 - margin) * dp) + random.randint(-30, 30)
                s_y = cy + int(dy_u * (wh // 2 - margin) * dp) + random.randint(-30, 30)
                e_y = cy - int(dy_u * (wh // 2 - margin) * dp) + random.randint(-30, 30)
                sx, s_y = self._clamp_to_play_area(sx, s_y)
                ex, e_y = self._clamp_to_play_area(ex, e_y)
                self._human_drag(sx, s_y, ex, e_y)
                self._wait(random.uniform(1.5, 3.5), 0.8)
            print(f"  [{INFO}] Shifted camera ({num_drags} drags, base dir={base_angle})")

        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, f"{tag}_icon_zoom")

        self._record(f"{tag}_world", True, f"City -> world map -> zoom out {zs}x")
        return True

    # --- Step 2/3/4: Wander scan + click icon + verify gem type ---

    def _extract_icon_patch(self, frame, m: Match) -> np.ndarray:
        """Extract icon patch from frame for classifier input."""
        fh, fw = frame.shape[:2]
        x1 = max(0, m.x)
        y1 = max(0, m.y)
        x2 = min(fw, m.x + m.w)
        y2 = min(fh, m.y + m.h)
        return frame[y1:y2, x1:x2].copy()

    def _is_clickable_zone(self, frame, m: Match) -> tuple[bool, str]:
        """Check if icon is in a clickable area (not edge/fog/dark terrain)."""
        fh, fw = frame.shape[:2]
        cx, cy = m.center

        margin_x = int(fw * SAFE_ZONE_MARGIN)
        margin_y = int(fh * SAFE_ZONE_MARGIN)
        if cx < margin_x or cx > fw - margin_x or cy < margin_y or cy > fh - margin_y:
            return False, f"edge({cx},{cy})"

        pad = max(m.w, m.h) * 2
        y1 = max(0, cy - pad)
        y2 = min(fh, cy + pad)
        x1 = max(0, cx - pad)
        x2 = min(fw, cx + pad)
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty"

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        ir = max(m.w, m.h) // 2
        mask = np.ones(gray.shape, dtype=bool)
        ly, lx = cy - y1, cx - x1
        mask[max(0, ly - ir):min(gray.shape[0], ly + ir),
             max(0, lx - ir):min(gray.shape[1], lx + ir)] = False
        terrain = gray[mask]
        if terrain.size == 0:
            return False, "no_terrain"

        med = float(np.median(terrain))
        if med < DARK_TERRAIN_THRESH:
            return False, f"dark({med:.0f})"

        return True, f"ok({med:.0f})"

    def _find_all_icons(self, frame) -> list[Match]:
        """Find all resource icons (gem_icon template) on frame, sorted by confidence desc."""
        matches = self.matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
        result = []
        edge_gems = []
        for m in matches:
            if m.confidence < GEM_ICON_THRESHOLD:
                continue
            patch = self._extract_icon_patch(frame, m)
            should_click, label, clf_conf = self.classifier.should_click(patch)
            if not should_click:
                print(f"  [ -- ] Classifier reject at {m.center} conf={m.confidence:.3f}: {label} ({clf_conf:.2f})")
                continue
            is_gem_color, color_info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            if not is_gem_color:
                print(f"  [ -- ] Color reject at {m.center} conf={m.confidence:.3f}: {color_info.get('reason','')}")
                continue
            ok, zone_info = self._is_clickable_zone(frame, m)
            if not ok:
                if zone_info.startswith("edge"):
                    print(f"  [{INFO}] Edge gem at {m.center} conf={m.confidence:.3f} -- will recenter")
                    edge_gems.append(m)
                else:
                    print(f"  [ -- ] Zone reject icon at {m.center} conf={m.confidence:.3f}: {zone_info}")
                continue
            if label != "unknown":
                print(f"  [{INFO}] Classifier: {label} ({clf_conf:.2f}) at {m.center}")
            result.append(m)
        self._edge_gems = edge_gems
        return sorted(result, key=lambda m: -m.confidence)

    def _recenter_edge_gem(self, edge_match: Match) -> list[Match]:
        """Drag map to roughly center an edge gem, then re-scan."""
        cx, cy = self._center_screen()
        mx, my = edge_match.center
        sx, sy = self._screen_xy(mx, my)

        dx = cx - sx + random.randint(-60, 60)
        dy = cy - sy + random.randint(-40, 40)

        self._human_drag(cx, cy, cx + dx, cy + dy)
        self._wait(DELAY_DRAG_SETTLE, 1.0)

        frame = self._grab()
        if frame is None:
            return []
        return self._find_all_icons(frame)

    def _has_march_line(self, frame, icon: Match) -> tuple[bool, str]:
        """Detect march lines converging on an icon (troops en-route).

        Multi-color detection:
        1. White/bright lines (V>200, S<50)
        2. Teal/cyan lines (H 75-105) -- player's own marches
        3. Green lines (H 50-84) -- gathering marches

        A valid march line must be long (>2x icon) and have an endpoint
        near the icon center.
        """
        fh, fw = frame.shape[:2]
        cx, cy = icon.center
        icon_r = max(icon.w, icon.h)

        pad = icon_r * 5
        y1 = max(cy - pad, 0)
        y2 = min(cy + pad, fh)
        x1 = max(cx - pad, 0)
        x2 = min(cx + pad, fw)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty"

        icon_lx = cx - x1
        icon_ly = cy - y1
        min_len = icon_r * 3
        near_r = icon_r * 2

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        white_mask = (
            (hsv[:, :, 2] > 200) & (hsv[:, :, 1] < 50)
        ).astype(np.uint8) * 255

        cyan_mask = (
            (hsv[:, :, 0] >= 75) & (hsv[:, :, 0] <= 105) &
            (hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 130)
        ).astype(np.uint8) * 255

        green_mask = (
            (hsv[:, :, 0] >= 50) & (hsv[:, :, 0] <= 74) &
            (hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 130)
        ).astype(np.uint8) * 255

        combined = cv2.bitwise_or(white_mask, cv2.bitwise_or(cyan_mask, green_mask))

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        closed = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=1)

        lines = cv2.HoughLinesP(closed, 1, np.pi / 180,
                                threshold=35, minLineLength=min_len, maxLineGap=15)
        if lines is None:
            return False, "no lines"

        for line in lines:
            lx1, ly1, lx2, ly2 = line[0]
            length = np.sqrt((lx2 - lx1) ** 2 + (ly2 - ly1) ** 2)
            if length < min_len:
                continue

            angle = abs(np.degrees(np.arctan2(ly2 - ly1, lx2 - lx1)))
            if angle < 15 or angle > 165 or (75 < angle < 105):
                continue

            d1 = np.sqrt((lx1 - icon_lx) ** 2 + (ly1 - icon_ly) ** 2)
            d2 = np.sqrt((lx2 - icon_lx) ** 2 + (ly2 - icon_ly) ** 2)
            if min(d1, d2) > near_r:
                continue

            # Identify which color matched for logging
            ep_x = lx1 if d1 < d2 else lx2
            ep_y = ly1 if d1 < d2 else ly2
            ep_x = max(0, min(ep_x, roi.shape[1] - 1))
            ep_y = max(0, min(ep_y, roi.shape[0] - 1))
            h_val = hsv[ep_y, ep_x, 0]
            s_val = hsv[ep_y, ep_x, 1]
            color_tag = "white" if s_val < 50 else ("cyan" if h_val >= 75 else "green")

            info = f"{color_tag} len={length:.0f} endpt={min(d1,d2):.0f} angle={angle:.0f}"
            return True, info

        return False, "no march lines"

    def _check_icon_occupied(self, frame, icon: Match) -> tuple[bool, str]:
        """Check for march lines converging on the icon at icon-zoom level."""
        has_line, line_info = self._has_march_line(frame, icon)
        if has_line:
            return True, f"march_line({line_info})"
        return False, "free"

    def _is_mine_occupied(self, frame, mine_match: Match) -> tuple[bool, str]:
        """Check for gathering icon above the mine (colored circle with pickaxe).

        Finds compact bright blobs matching icon size (~20-45px diameter).
        Trees are diffuse/large; the gathering icon is a small circle.
        """
        mine_cx, mine_cy = mine_match.center
        fh, fw = frame.shape[:2]
        mh = mine_match.h

        y1 = max(0, mine_cy - mh * 3)
        y2 = max(0, mine_cy - mh // 3)
        x1 = max(0, mine_cx - mh)
        x2 = min(fw, mine_cx + mh)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty ROI"

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        sat_bright = (hsv[:, :, 1] > 150) & (hsv[:, :, 2] > 150)

        green_mask = sat_bright & (hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 85)
        red_mask = sat_bright & ((hsv[:, :, 0] < 10) | (hsv[:, :, 0] > 170))
        blue_mask = sat_bright & (hsv[:, :, 0] >= 90) & (hsv[:, :, 0] <= 135)

        combined = (green_mask | red_mask | blue_mask).astype(np.uint8) * 255
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        min_area = 15 * 15
        max_area = 45 * 45
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            if max(w, h) > 48:
                continue
            aspect = max(w, h) / max(min(w, h), 1)
            if aspect > 1.8:
                continue
            fill = area / max(w * h, 1)
            if fill < 0.55:
                continue
            cx_blob = x + w // 2
            cy_blob = y + h // 2
            h_val = hsv[cy_blob, cx_blob, 0]
            color = "green" if 35 <= h_val <= 85 else ("red" if h_val < 10 or h_val > 170 else "blue")
            info = f"icon {color} area={area} size={w}x{h}"
            return True, info

        return False, "no icon"

    def _has_incoming_march(self, frame, mine_match: Match) -> tuple[bool, str]:
        """Detect march lines pointing toward the mine using HoughLinesP.

        Color-percentage approach fails because map terrain (grass, water)
        shares hue ranges with march lines. Instead we:
        1. Build color masks for march-line colors (white/cyan/green)
        2. Use HoughLinesP to find actual line segments
        3. Only flag lines that have an endpoint near the mine center
        """
        mine_cx, mine_cy = mine_match.center
        fh, fw = frame.shape[:2]
        mine_r = max(mine_match.w, mine_match.h)
        pad = mine_r * 4

        y1 = max(0, mine_cy - pad)
        y2 = min(fh, mine_cy + pad)
        x1 = max(0, mine_cx - pad)
        x2 = min(fw, mine_cx + pad)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty"

        mine_lx = mine_cx - x1
        mine_ly = mine_cy - y1
        min_len = mine_r * 2
        near_r = mine_r * 2

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        white_mask = (
            (hsv[:, :, 2] > 200) & (hsv[:, :, 1] < 50)
        ).astype(np.uint8) * 255

        cyan_mask = (
            (hsv[:, :, 0] >= 75) & (hsv[:, :, 0] <= 115) &
            (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 150)
        ).astype(np.uint8) * 255

        green_mask = (
            (hsv[:, :, 0] >= 50) & (hsv[:, :, 0] <= 74) &
            (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 150)
        ).astype(np.uint8) * 255

        combined = cv2.bitwise_or(white_mask, cv2.bitwise_or(cyan_mask, green_mask))

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        cleaned = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=1)

        lines = cv2.HoughLinesP(cleaned, 1, np.pi / 180,
                                threshold=30, minLineLength=int(min_len), maxLineGap=20)
        if lines is None:
            return False, "no lines"

        for line in lines:
            lx1, ly1, lx2, ly2 = line[0]
            length = np.sqrt((lx2 - lx1) ** 2 + (ly2 - ly1) ** 2)
            if length < min_len:
                continue

            d1 = np.sqrt((lx1 - mine_lx) ** 2 + (ly1 - mine_ly) ** 2)
            d2 = np.sqrt((lx2 - mine_lx) ** 2 + (ly2 - mine_ly) ** 2)
            if min(d1, d2) > near_r:
                continue

            ep_x = lx1 if d1 < d2 else lx2
            ep_y = ly1 if d1 < d2 else ly2
            ep_x = max(0, min(ep_x, roi.shape[1] - 1))
            ep_y = max(0, min(ep_y, roi.shape[0] - 1))
            h_val = hsv[ep_y, ep_x, 0]
            s_val = hsv[ep_y, ep_x, 1]
            color_tag = "white" if s_val < 50 else ("cyan" if h_val >= 75 else "green")

            info = f"{color_tag} len={length:.0f} endpt={min(d1,d2):.0f}"
            return True, info

        return False, "no march lines"

    def _click_icon_and_verify(self, icon: Match, tag: str, attempt: int, icon_frame=None) -> bool:
        """Click an icon, wait for zoom-in, verify it's a gem mine. Returns True if gem popup opens."""
        sx, sy = self._screen_xy(*icon.center)
        print(f"  [{INFO}] [{attempt}] Clicking icon conf={icon.confidence:.3f} at {icon.center} -> screen ({sx},{sy})")

        # Save icon patch for classifier labeling
        if icon_frame is not None:
            icon_patch = self._extract_icon_patch(icon_frame, icon)
        else:
            icon_patch = None

        self._click(sx, sy)
        self._wait(DELAY_ZOOM_IN)

        frame = self._grab()
        if frame is None:
            return False
        save_screenshot(frame, f"{tag}_attempt_{attempt:02d}")

        # Find best mine structure match (reuse for gem check + occupation check)
        mine = None
        for tpl in GEM_MINE_TEMPLATES:
            m = self._find_on_frame(frame, tpl, threshold=GEM_MINE_THRESHOLD)
            if m and (mine is None or m.confidence > mine.confidence):
                mine = m

        is_gem = mine is not None
        g_raw = self.matcher.match_single(frame, "buttons/gather_btn")
        g_conf = g_raw.confidence if g_raw else 0.0
        g = g_raw if g_conf >= GATHER_BTN_THRESHOLD else None
        print(f"  [{INFO}] [{attempt}] gather_btn conf={g_conf:.3f} (threshold={GATHER_BTN_THRESHOLD}, pass={g is not None})")

        if self.auto_learn and icon_patch is not None and icon_patch.size > 0:
            n = self.classifier.add_sample(icon_patch, is_gem)
            label_str = "gem" if is_gem else "not_gem"
            stats = self.classifier.get_stats()
            print(f"  [LEARN] Added {label_str} sample #{n}, total={stats['total']} (gem={stats['gem']}, not_gem={stats['not_gem']})")

        # Check occupation before proceeding (bright green march/mining indicators)
        if is_gem:
            occupied, occ_info = self._is_mine_occupied(frame, mine)
            if occupied:
                save_screenshot(frame, f"{tag}_occupied_{attempt:02d}")
                print(f"  [{WARN}] [{attempt}] Mine occupied ({occ_info}) -- skipping")
                return False

            raw = self._raw_frame if self._raw_frame is not None else frame
            has_line, line_info = self._has_incoming_march(raw, mine)
            if has_line:
                save_screenshot(frame, f"{tag}_march_line_{attempt:02d}")
                print(f"  [{WARN}] [{attempt}] Incoming march at mine ({line_info}) -- skipping")
                return False

            is_gem_color, color_info = is_gem_mine_color(frame, mine.x, mine.y, mine.w, mine.h)
            if not is_gem_color:
                save_screenshot(frame, f"{tag}_mine_color_warn_{attempt:02d}")
                print(f"  [{WARN}] [{attempt}] Mine color suspect ({color_info}) -- continuing (icon filter passed)")
            else:
                print(f"  [{INFO}] [{attempt}] Mine color OK ({color_info})")

        if g and is_gem:
            print(f"  [{PASS}] [{attempt}] Gem mine confirmed + popup open (gather conf={g.confidence:.3f})")
            return True

        if g and not is_gem:
            print(f"  [{WARN}] [{attempt}] Popup open but NOT gem -- dismissing")
            self._press_escape()
            self._wait(DELAY_AFTER_ESCAPE)
            return False

        if is_gem and not g:
            self._wait(DELAY_RECHECK)
            frame_recheck = self._grab()
            if frame_recheck is not None:
                save_screenshot(frame_recheck, f"{tag}_recheck_{attempt:02d}")
                g_re_raw = self.matcher.match_single(frame_recheck, "buttons/gather_btn")
                g_re_conf = g_re_raw.confidence if g_re_raw else 0.0
                print(f"  [{INFO}] [{attempt}] re-check gather_btn conf={g_re_conf:.3f}")
                if g_re_conf >= GATHER_BTN_THRESHOLD:
                    print(f"  [{PASS}] [{attempt}] Popup detected on re-check (conf={g_re_conf:.3f})")
                    return True

            print(f"  [{INFO}] [{attempt}] Gem confirmed, clicking mine structure...")
            msx, msy = self._screen_xy(*mine.center)
            msx += mine.w // 5
            msy -= mine.h // 5
            self._click(msx, msy)
            self._wait(DELAY_MINE_CLICK)
            frame2 = self._grab()
            if frame2 is not None:
                save_screenshot(frame2, f"{tag}_after_mine_click_{attempt:02d}")
                g2_raw = self.matcher.match_single(frame2, "buttons/gather_btn")
                g2_conf = g2_raw.confidence if g2_raw else 0.0
                print(f"  [{INFO}] [{attempt}] after mine click gather_btn conf={g2_conf:.3f}")
                if g2_conf >= GATHER_BTN_THRESHOLD:
                    print(f"  [{PASS}] [{attempt}] Popup opened after mine click!")
                    return True
            print(f"  [{WARN}] [{attempt}] Gem confirmed but popup won't open")
            return False

        # Neither gem structure nor popup -- not a gem mine
        print(f"  [{WARN}] [{attempt}] Not a gem mine")
        return False

    def _return_to_icon_zoom(self):
        """After a failed icon click, zoom back to icon level."""
        self._scroll_at_center(-1, self._zoom_scrolls())
        self._wait(DELAY_AFTER_SCROLL)

    def _step_scan_and_verify_gem(self, tag: str) -> Match | None:
        print(f"\n--- [{tag}] Step 2: Scan + verify gem mines ---\n")

        ww = self.win["width"]
        wh = self.win["height"]
        margin = 80
        cx, cy = self._center_screen()

        spiral_angle = random.uniform(0, 2 * math.pi)
        scans_per_rev = random.uniform(5, 8)
        spiral_step = 2 * math.pi / scans_per_rev
        scan_count = 0
        scan_speed = random.uniform(3.6, 5.0)
        _speed_target = random.uniform(3.6, 7.0)
        max_scans = 60
        max_attempts = 10
        empty_streak = 0
        max_empty_streak = 12
        max_icons_per_frame = 2
        attempt = 0
        SKIP_RADIUS = 80
        clicked_positions: list[tuple[int, int, int]] = []
        cam_offset = [0.0, 0.0]
        visited_cells: set[tuple[int, int]] = {(0, 0)}

        print(f"  [{INFO}] Wander scan (margin={margin})")

        # Check current frame first
        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, f"{tag}_scan_00")
            icons = self._find_all_icons(frame)
            if not icons and self._edge_gems:
                print(f"  [{INFO}] {len(self._edge_gems)} edge gem(s) on initial frame, recentering...")
                icons = self._recenter_edge_gem(self._edge_gems[0])
            tried_this_frame = 0
            for icon in icons:
                if attempt >= max_attempts or tried_this_frame >= max_icons_per_frame:
                    break
                if any(abs(icon.center[0]-px) < r and abs(icon.center[1]-py) < r
                       for px, py, r in clicked_positions):
                    continue
                raw = self._raw_frame if self._raw_frame is not None else frame
                occupied, occ_info = self._check_icon_occupied(raw, icon)
                if occupied:
                    print(f"  [{WARN}] Icon at {icon.center} occupied ({occ_info}) -- skip")
                    clicked_positions.append((*icon.center, SKIP_RADIUS))
                    continue
                attempt += 1
                tried_this_frame += 1
                clicked_positions.append((*icon.center, SKIP_RADIUS))
                if self._click_icon_and_verify(icon, tag, attempt, icon_frame=frame):
                    self._record(f"{tag}_find", True, f"Gem found at attempt {attempt} (no drag)")
                    return icon
                self._return_to_icon_zoom()

        # Random wander scan (human-like, not spiral)
        while scan_count < max_scans and attempt < max_attempts:
            scan_count += 1

            if self._check_session() == "break":
                dur = self.session.get_break_duration()
                print(f"  [{INFO}] Mid-scan break: {dur/60:.1f} min")
                time.sleep(dur)

            dist_pct = random.uniform(2.0, 3.0)

            angle = spiral_angle + random.gauss(0, 0.2)
            dx_f = math.cos(angle)
            dy_f = math.sin(angle)

            target_cell = (round(cam_offset[0] + dx_f * dist_pct),
                           round(cam_offset[1] + dy_f * dist_pct))
            if target_cell in visited_cells:
                for nudge in [0.5, -0.5, 1.0, -1.0]:
                    alt = spiral_angle + nudge
                    adx, ady = math.cos(alt), math.sin(alt)
                    ac = (round(cam_offset[0] + adx * dist_pct),
                          round(cam_offset[1] + ady * dist_pct))
                    if ac not in visited_cells:
                        dx_f, dy_f = adx, ady
                        break

            spiral_angle += spiral_step + random.gauss(0, 0.12)

            jx = random.randint(-45, 45)
            jy = random.randint(-35, 35)
            half_x = int((ww // 2 - margin) * dist_pct)
            half_y = int((wh // 2 - margin) * dist_pct)
            sx = cx + int(dx_f * half_x) + jx
            sy = cy + int(dy_f * half_y) + jy
            ex = cx - int(dx_f * half_x) + jx
            ey = cy - int(dy_f * half_y) + jy
            sx, sy = self._clamp_to_play_area(sx, sy)
            ex, ey = self._clamp_to_play_area(ex, ey)

            if random.random() < 0.12:
                _speed_target = random.uniform(3.6, 7.0)
            scan_speed += (_speed_target - scan_speed) * random.uniform(0.08, 0.15)
            self._human_drag(sx, sy, ex, ey, speed_factor=scan_speed, easing="in")
            time.sleep(random.uniform(0.3, 0.8))

            cam_offset[0] += dx_f * dist_pct
            cam_offset[1] += dy_f * dist_pct
            visited_cells.add((round(cam_offset[0]), round(cam_offset[1])))

            if random.random() < 0.10:
                time.sleep(random.uniform(1.0, 2.5))

            frame = self._grab()
            if frame is None:
                continue

            save_screenshot(frame, f"{tag}_scan_{scan_count:02d}")

            icons = self._find_all_icons(frame)

            if not icons and self._edge_gems:
                print(f"  [{INFO}] Scan {scan_count:2d}: {len(self._edge_gems)} edge gem(s), recentering...")
                icons = self._recenter_edge_gem(self._edge_gems[0])

            if not icons:
                empty_streak += 1
                print(f"  [ -- ] Scan {scan_count:2d}/{max_scans}: no icons "
                      f"(spd={scan_speed:.1f}x, cells={len(visited_cells)}, empty={empty_streak})")
                if empty_streak >= max_empty_streak:
                    print(f"  [{WARN}] {max_empty_streak} consecutive empty scans -- zoom likely wrong, restarting from city")
                    return None
                continue

            empty_streak = 0
            print(f"  [{INFO}] Scan {scan_count:2d}/{max_scans}: {len(icons)} icon(s)")
            tried_this_frame = 0
            for icon in icons:
                if attempt >= max_attempts or tried_this_frame >= max_icons_per_frame:
                    break
                if any(abs(icon.center[0]-px) < r and abs(icon.center[1]-py) < r
                       for px, py, r in clicked_positions):
                    print(f"  [ -- ] Skip already-clicked icon at {icon.center}")
                    continue
                raw = self._raw_frame if self._raw_frame is not None else frame
                occupied, occ_info = self._check_icon_occupied(raw, icon)
                if occupied:
                    print(f"  [{WARN}] Icon at {icon.center} occupied ({occ_info}) -- skip")
                    clicked_positions.append((*icon.center, SKIP_RADIUS))
                    continue
                attempt += 1
                tried_this_frame += 1
                clicked_positions.append((*icon.center, SKIP_RADIUS))
                if self._click_icon_and_verify(icon, tag, attempt, icon_frame=frame):
                    self._record(f"{tag}_find", True, f"Gem at attempt {attempt}, scan {scan_count}")
                    return icon
                self._return_to_icon_zoom()

        print(f"  [{FAIL}] No gem mine after {scan_count} scans, {attempt} icons checked")
        self._record(f"{tag}_find", False, f"{attempt} icons checked, none were gem")
        return None

    # --- Step: Click gather button ---

    def _step_click_gather(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 5: Click Gather ---\n")

        for attempt in range(5):
            frame = self._grab()
            if frame is None:
                self._wait(DELAY_RECHECK)
                continue

            m_raw = self.matcher.match_single(frame, "buttons/gather_btn")
            m_conf = m_raw.confidence if m_raw else 0.0
            m = m_raw if m_conf >= GATHER_BTN_THRESHOLD else None

            if m:
                print(f"  [{PASS}] gather_btn: conf={m.confidence:.3f}")
                save_annotated(frame, m, f"{tag}_gather_found")

                if self._click_match(m):
                    print(f"  [{PASS}] Gather clicked!")
                    self._wait(DELAY_VERIFY)
                    frame2 = self._grab()
                    if frame2 is not None:
                        save_screenshot(frame2, f"{tag}_after_gather")
                    self._record(f"{tag}_gather", True, f"conf={m.confidence:.3f}")
                    return True

            print(f"  [{INFO}] gather_btn not found (attempt {attempt+1}/5)")
            self._wait(DELAY_RECHECK)

        print(f"  [{FAIL}] gather_btn not found")
        self._record(f"{tag}_gather", False, "Not found")
        return False

    # --- Step: Click march ---

    def _find_march_btn(self, frame) -> Match | None:
        """Find march button via template matching."""
        for tpl in MARCH_TEMPLATES:
            m = self._find_on_frame(frame, tpl, threshold=0.65)
            if m:
                return m
        return None

    def _is_troop_panel_open(self, frame) -> bool:
        """Check if troop selection panel is still visible."""
        m = self._find_on_frame(frame, "buttons/new_troop_btn", threshold=0.85)
        return m is not None

    def _step_click_march(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 6: Troop + March ---\n")

        selected_new_troop = False

        for attempt in range(6):
            frame = self._grab()
            if frame is None:
                self._wait(DELAY_RECHECK)
                continue

            # Try "New Troop" button first (troop selection panel)
            if not selected_new_troop:
                m = self._find_on_frame(frame, "buttons/new_troop_btn", threshold=BUTTON_THRESHOLD)
                if m:
                    print(f"  [{PASS}] new_troop_btn: conf={m.confidence:.3f}")
                    if self._click_match(m):
                        selected_new_troop = True
                        print(f"  [{PASS}] New troop selected")
                        self._wait(DELAY_VERIFY)
                        continue

            # Try template matching for march button
            march = self._find_march_btn(frame)
            if march:
                print(f"  [{INFO}] March btn found: {march.name} conf={march.confidence:.3f} at {march.center}")
                sx, sy = self._screen_xy(*march.center)
                self._click(sx, sy)
            else:
                sx = self.win["left"] + int(self.win["width"] * 0.66)
                sy = self.win["top"] + int(self.win["height"] * 0.76)
                print(f"  [{INFO}] March btn not found, fallback click ({sx},{sy}) (attempt {attempt+1}/6)")
                self._click(sx, sy)

            self._wait(DELAY_VERIFY * 2)

            frame2 = self._grab()
            if frame2 is not None:
                save_screenshot(frame2, f"{tag}_after_march_{attempt:02d}")
                if not self._is_troop_panel_open(frame2):
                    print(f"  [{PASS}] March clicked! (troop panel gone)")
                    self._record(f"{tag}_march", True, f"attempt={attempt+1}")
                    return True
                print(f"  [{WARN}] Troop panel still open (attempt {attempt+1}/6)")

            self._wait(DELAY_RECHECK)

        print(f"  [{FAIL}] March button not clicked")
        self._record(f"{tag}_march", False, "Not found")
        return False

    # --- Step 7: Return to city view ---

    def _step_return_city(self, tag: str):
        print(f"\n--- [{tag}] Step 7: Return to city ---\n")

        # Try city_btn first (visible on world map)
        m = self._find("buttons/city_btn", threshold=0.75)
        if m:
            print(f"  [{INFO}] Clicking city_btn...")
            self._click_match(m)
            self._wait(DELAY_WORLD_MAP)
        else:
            self._press_escape()
            self._wait(DELAY_AFTER_ESCAPE)
            self._press_escape()
            self._wait(DELAY_AFTER_SCROLL)

        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, f"{tag}_return_city")

        self._record(f"{tag}_return", True, "Returned to city")

    # --- Helpers ---

    def _record(self, step: str, ok: bool, note: str):
        self.results.append({"step": step, "success": ok, "note": note})

    def _teardown(self):
        print("\n--- Teardown ---")
        ss = self.session.session_stats()
        print(f"  Session: {ss['session_minutes']:.1f} min active, "
              f"{ss['action_count']} actions, "
              f"fatigue x{self.timing.apply_fatigue(ss['session_minutes']):.2f}")
        if self.auto_learn and self.classifier.sample_count > 0:
            self.classifier.save()
            stats = self.classifier.get_stats()
            print(f"  Classifier saved: {stats['total']} samples (gem={stats['gem']}, not_gem={stats['not_gem']})")
        if self.cmd:
            self.cmd.send("RESET")
            self.cmd.stop()
        if self.conn:
            self.conn.disconnect()
        if self.sc:
            self.sc.close()

    def _print_report(self):
        print(f"\n{'=' * 60}")
        print("  GEM FARM FLOW REPORT")
        print(f"{'=' * 60}")
        if self.loop:
            print(f"  Mode: loop | Max: {self.max_marches} | Completed: {self.mines_completed}")
        else:
            print(f"  Target: {self.count} | Completed: {self.mines_completed}")

        for r in self.results:
            s = PASS if r["success"] else FAIL
            print(f"  [{s}] {r['step']:25s} -- {r['note']}")

        print()
        if self.mines_completed == self.count:
            print(f"  [{PASS}] *** ALL {self.count} MINES COMPLETE! ***")
        elif self.mines_completed > 0:
            print(f"  [{WARN}] {self.mines_completed}/{self.count} mines done")
        else:
            print(f"  [{FAIL}] No mines completed")
        print(f"\n  Screenshots: {SCREENSHOT_DIR}\n")


def main():
    parser = argparse.ArgumentParser(description="Gem Farm Flow E2E Test")
    parser.add_argument("--port", default="COM27")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--find-only", action="store_true",
                        help="Vision-only scan: capture current frame, run template match + color filter, no ESP32")
    parser.add_argument("--auto-learn", action="store_true",
                        help="Enable auto-labeling for classifier (default: OFF)")
    parser.add_argument("--loop", action="store_true",
                        help="Loop until march queue is full (uses --max-marches as limit)")
    parser.add_argument("--max-marches", type=int, default=5,
                        help="Max march slots (default: 5)")
    parser.add_argument("--no-screenshots", action="store_true",
                        help="Disable saving screenshots (for overnight runs)")
    parser.add_argument("--zoom-scrolls", type=int, default=None,
                        help="Override ICON_ZOOM_SCROLLS (default: random 2-3)")
    args = parser.parse_args()

    if args.no_screenshots:
        global _SAVE_SCREENSHOTS
        _SAVE_SCREENSHOTS = False

    if args.zoom_scrolls is not None:
        global ICON_ZOOM_SCROLLS
        ICON_ZOOM_SCROLLS = args.zoom_scrolls
    if args.find_only:
        _run_find_only()
    else:
        test = GemFarmFlowTest(
            port=args.port, count=args.count, auto_learn=args.auto_learn,
            loop=args.loop, max_marches=args.max_marches,
        )
        test.run()


def _run_find_only():
    print("=" * 60)
    print("  GEM FARM -- Find-Only (vision scan, no ESP32)")
    print("=" * 60)
    print()

    sc = ScreenCapture()
    win = sc.find_window()
    if not win:
        print(f"  [{FAIL}] Game window not found")
        return
    print(f"  [{PASS}] Window: {win['width']}x{win['height']}")

    cache = TemplateCache("templates")
    matcher = TemplateMatcher(cache, threshold=0.50)

    tpl = cache.get("resources/gem_icon")
    if tpl is None:
        print(f"  [{FAIL}] gem_icon template MISSING")
        return
    print(f"  [{PASS}] gem_icon template: {tpl.shape[1]}x{tpl.shape[0]}")

    frame = sc.grab_full()
    if frame is None:
        print(f"  [{FAIL}] Screen capture failed")
        return
    print(f"  [{PASS}] Frame: {frame.shape[1]}x{frame.shape[0]}")

    ts = datetime.now().strftime("%H%M%S")
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(SCREENSHOT_DIR / f"find_only_{ts}.png"), frame)

    all_matches = matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
    print(f"\n  Raw matches (any conf): {len(all_matches)}")
    for m in sorted(all_matches, key=lambda x: -x.confidence):
        print(f"    conf={m.confidence:.3f} at {m.center} ({m.w}x{m.h})")

    above_thresh = [m for m in all_matches if m.confidence >= GEM_ICON_THRESHOLD]
    print(f"\n  Above threshold ({GEM_ICON_THRESHOLD}): {len(above_thresh)}")

    gems = []
    for m in sorted(above_thresh, key=lambda x: -x.confidence):
        is_gem, info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
        status = PASS if is_gem else FAIL
        print(f"    [{status}] conf={m.confidence:.3f} at {m.center} color={info}")
        if is_gem:
            gems.append(m)

    # Draw annotated frame
    ann = frame.copy()
    for m in all_matches:
        if m.confidence < GEM_ICON_THRESHOLD:
            color = (128, 128, 128)  # gray: below threshold
        elif m in gems:
            color = (0, 255, 0)  # green: gem confirmed
        else:
            color = (0, 0, 255)  # red: color rejected
        cv2.rectangle(ann, (m.x, m.y), (m.x + m.w, m.y + m.h), color, 2)
        cv2.putText(ann, f"{m.confidence:.2f}", (m.x, m.y - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    ann_path = SCREENSHOT_DIR / f"find_only_annotated_{ts}.png"
    cv2.imwrite(str(ann_path), ann)

    print(f"\n{'=' * 60}")
    if gems:
        print(f"  [{PASS}] Found {len(gems)} gem icon(s) on current frame")
    else:
        print(f"  [{WARN}] No gem icons on current frame (may need to be on world map at icon-zoom)")
    print(f"  Annotated: {ann_path}")
    print(f"{'=' * 60}")

    sc.close()


if __name__ == "__main__":
    main()
