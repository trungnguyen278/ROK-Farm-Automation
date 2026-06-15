r"""
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
import json
import time
import math
import hashlib
import logging
import argparse
import random
import threading
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

import ctypes
ctypes.windll.user32.SetProcessDPIAware()

from capture.screen_capture import ScreenCapture
from capture.screen_info import get_cursor_pos, screen_to_hid, get_screen_resolution
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher, Match
from vision.state_detector import StateDetector
from vision.color_filter import is_gem_icon_color, is_gem_mine_color, normalize_frame
from vision.gem_classifier import GemPatchClassifier
from anti_detection.profile_loader import ProfileLoader, DEFAULT_PROFILE
from anti_detection.timing_engine import TimingEngine
from anti_detection.session_manager import SessionManager
from anti_detection.mouse_humanizer import MouseHumanizer
from anti_detection.player_actions import PlayerActions

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

# --- Time delays (center, spread) --- focused-player speed ---
DELAY_AFTER_CLICK = (0.15, 0.06)
DELAY_AFTER_ESCAPE = (0.18, 0.07)
DELAY_AFTER_SCROLL = (0.30, 0.10)
DELAY_ZOOM_IN = (1.5, 0.3)
DELAY_MINE_CLICK = (0.30, 0.10)
DELAY_RECHECK = (0.25, 0.08)
DELAY_VERIFY = (0.35, 0.12)
DELAY_DRAG_SETTLE = (0.40, 0.12)
DELAY_WORLD_MAP = (1.5, 0.5)
DELAY_BETWEEN_MINES = (1.0, 0.4)
DELAY_DRAG_PRE = (0.08, 0.04)
DELAY_DRAG_POST = (0.25, 0.10)
DELAY_MICRO_PAUSE = (0.40, 0.15)



_SAVE_SCREENSHOTS = True


def save_screenshot(frame, name):
    if not _SAVE_SCREENSHOTS:
        return None
    ts_offset = random.randint(-30, 30)
    fake_ts = datetime.now().timestamp() + ts_offset
    ts = datetime.fromtimestamp(fake_ts).strftime("%H%M%S")
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
                 loop: bool = False, max_marches: int = 5,
                 account_id: str = "default",
                 actions_override: list[str] | None = None):
        self.port = port
        self.count = count
        self.auto_learn = auto_learn
        self.loop = loop
        self.max_marches = max_marches
        self._account_id = account_id
        self._burst_counter: int = random.choices(
            [3, 4, 5, 6, 7, 8], weights=[10, 20, 30, 20, 12, 8])[0]
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
        self._has_moveto = False
        self._mouse_scale = 1.0

        loader = ProfileLoader()
        self._profile = loader.load_random() if loader.list_profiles() else DEFAULT_PROFILE.copy()

        self._persona = self._load_or_create_persona()
        self._apply_persona()

        self.timing = TimingEngine(self._profile)
        self.session = SessionManager(self._profile)
        self.humanizer = MouseHumanizer(self._profile)
        self._actions = PlayerActions(self, self._persona)
        if actions_override:
            self._actions._preferred = list(actions_override)

        self._scroll_overshoot_chance = self._jitter(
            self._persona["scroll_overshoot"], 0.08)

    # --- Persistent persona ---

    def _persona_path(self) -> Path:
        base = Path(os.environ.get("APPDATA", Path.home())) / ".rok_data"
        base.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(self._account_id.encode()).hexdigest()[:12]
        return base / f"{h}.dat"

    def _load_or_create_persona(self) -> dict:
        path = self._persona_path()
        if path.exists():
            try:
                with open(path, "r") as f:
                    persona = json.load(f)
                persona.setdefault("session_count", 0)
                persona["session_count"] += 1
                if persona["session_count"] % 20 == 0:
                    persona["speed_base"] = max(1200, min(2000,
                        persona["speed_base"] + random.randint(-30, 30)))
                    persona["curve_spread"] = max(0.03, min(0.10,
                        persona["curve_spread"] + random.uniform(-0.01, 0.01)))
                with open(path, "w") as f:
                    json.dump(persona, f, indent=2)
                logger.info("Loaded persona: %s (session #%d)", path.name,
                            persona["session_count"])
                return persona
            except Exception as e:
                logger.warning("Failed to load persona %s: %s", path, e)

        persona = {
            "speed_base": random.randint(1300, 1800),
            "speed_variance": random.randint(50, 120),
            "curve_spread": round(random.uniform(0.03, 0.08), 3),
            "overshoot_chance": round(random.uniform(0.02, 0.06), 3),
            "click_bias_x": round(random.gauss(0, 0.015), 4),
            "click_bias_y": round(random.gauss(0, 0.012), 4),
            "scroll_overshoot": round(random.uniform(0.08, 0.25), 3),
            "hesitation_level": round(random.uniform(0.02, 0.12), 3),
            "fatigue_sensitivity": round(random.uniform(0.7, 1.3), 2),
            "afk_frequency": round(random.uniform(0.02, 0.08), 3),
            "bezier_points": 2,
            "jitter_px": 0,
            "preferred_idle": PlayerActions.focused_farmer_preferred(),
            "session_count": 1,
            "created": datetime.now().isoformat(),
        }
        try:
            with open(path, "w") as f:
                json.dump(persona, f, indent=2)
            logger.info("Created new persona: %s", path.name)
        except Exception as e:
            logger.warning("Failed to save persona: %s", e)
        return persona

    @staticmethod
    def _jitter(value: float, pct: float = 0.06) -> float:
        return value * random.uniform(1 - pct, 1 + pct)

    def _apply_persona(self):
        p = self._persona
        self._profile.setdefault("mouse", {})
        self._profile["mouse"]["speed_base"] = int(self._jitter(p["speed_base"]))
        self._profile["mouse"]["speed_variance"] = int(self._jitter(p["speed_variance"]))
        self._profile["mouse"]["bezier_control_points"] = p["bezier_points"]
        self._profile["mouse"]["jitter_px"] = p["jitter_px"]
        self._profile["mouse"]["curve_spread"] = self._jitter(p["curve_spread"])
        self._profile["mouse"]["overshoot_chance"] = self._jitter(p["overshoot_chance"])

    # --- Anti-detection helpers ---

    def _wait(self, spec, variance: float = 0.0) -> float:
        if isinstance(spec, tuple):
            center, spread = spec[0], spec[1] if len(spec) > 1 else spec[0] * 0.15
        else:
            center = float(spec)
            spread = center * 0.15
        if spread > 0:
            sigma = spread / center if center > 0 else 0.15
        else:
            sigma = 0.12
        raw = random.lognormvariate(0, sigma)
        actual = max(0.05, center * raw)
        time.sleep(actual)
        return actual

    def _tab_away(self):
        raw = random.lognormvariate(3.8, 0.7)
        away = max(5.0, min(600.0, raw))
        logger.info("tab away %.0fs", away)
        print(f"  [{INFO}] Alt-tab away {away:.0f}s")
        self.cmd.send("IDLE", "1")
        hold = random.randint(50, 120)
        self.cmd.send("COMBO", "ALT", "TAB", hold)
        time.sleep(away)

    def _tab_back(self):
        hold = random.randint(50, 120)
        self.cmd.send("COMBO", "ALT", "TAB", hold)
        self.cmd.send("IDLE", "0")
        time.sleep(random.uniform(1.5, 3.0))
        self._refresh_window()
        if self._check_reconnect_popup():
            logger.info("tab_back: dismissed reconnect popup")
            time.sleep(random.uniform(2.0, 4.0))
        warmup = random.lognormvariate(0.5, 0.6)
        time.sleep(max(0.5, min(8.0, warmup)))
        if random.random() < 0.5:
            cx, cy = self._center_screen()
            dx, dy = random.randint(-60, 60), random.randint(-40, 40)
            self._human_drag(cx + dx, cy + dy, cx - dx, cy - dy)
            time.sleep(random.uniform(0.3, 1.2))

    _BTN_POS = {
        "bag":      (0.755, 0.953),
        "alliance": (0.803, 0.953),
        "mail":     (0.898, 0.953),
    }
    _X_CLOSE_POS = {
        "bag":      (0.865, 0.187),
        "alliance": (0.765, 0.233),
        "mail":     (0.817, 0.086),
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

    _X_SEARCH_REGION = {
        "bag":      (0.78, 0.10, 0.95, 0.28),
        "alliance": (0.68, 0.14, 0.85, 0.32),
        "mail":     (0.74, 0.05, 0.92, 0.18),
    }
    _X_BUTTON_THRESHOLD = {
        "mail":     0.75,
        "alliance": 0.70,
        "bag":      0.70,
    }

    def _find_x_button(self, frame, panel: str):
        """Detect X close button in a small region around expected position."""
        region = self._X_SEARCH_REGION.get(panel)
        if region is None:
            return None
        fh, fw = frame.shape[:2]
        rx1, ry1, rx2, ry2 = region
        x1, y1 = int(fw * rx1), int(fh * ry1)
        x2, y2 = int(fw * rx2), int(fh * ry2)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        threshold = self._X_BUTTON_THRESHOLD.get(panel, 0.60)
        for tpl_name in [f"ui/btn_x_close_{panel}", "ui/btn_x_close"]:
            m = self.matcher.match_single(crop, tpl_name)
            if m and m.confidence >= threshold:
                ax, ay = m.x + x1, m.y + y1
                return Match(m.name, ax, ay, m.w, m.h, m.confidence,
                             (ax + m.w // 2, ay + m.h // 2))
        return None

    def _close_panel(self, panel: str):
        if panel in self._X_CLOSE_POS:
            self._click_pct(*self._X_CLOSE_POS[panel], jitter_px=3)
            time.sleep(random.uniform(0.4, 0.8))

    def _dismiss_popups(self):
        """Detect and close any open panel popup."""
        frame = self._grab()
        if frame is None:
            return
        for panel in ("alliance", "mail", "bag"):
            m = self._find_x_button(frame, panel)
            if m:
                logger.debug("dismiss_popups: %s detected (conf=%.3f), closing", panel, m.confidence)
                self._close_panel(panel)
                return

    def _idle_while_queue_full(self):
        if not hasattr(self, '_queue_wait_start'):
            self._queue_wait_start = time.time()

        waited_min = (time.time() - self._queue_wait_start) / 60.0
        if waited_min > 20:
            self.mines_completed = max(0, self.mines_completed - 1)
            self._queue_wait_start = time.time()
            print(f"  [{INFO}] Waited {waited_min:.0f}min, assuming 1 slot freed")

        self._tab_away()
        self._tab_back()

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

    def _start_capture_thread(self):
        self._capture_running = True
        self._frame_lock = threading.Lock()
        self._bg_frame = None
        self._bg_back = None
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

    def _stop_capture_thread(self):
        self._capture_running = False
        if hasattr(self, '_capture_thread') and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)

    def _capture_loop(self):
        win_refresh_interval = 10.0
        last_win_refresh = time.monotonic()
        while self._capture_running:
            frame = self.sc.grab_full()
            if frame is not None:
                with self._frame_lock:
                    self._bg_back = self._bg_frame
                    self._bg_frame = frame
            now = time.monotonic()
            if now - last_win_refresh > win_refresh_interval:
                self._refresh_window()
                last_win_refresh = now
            time.sleep(random.uniform(0.03, 0.15))

    def _grab(self) -> np.ndarray | None:
        with self._frame_lock:
            if self._bg_frame is None:
                self._raw_frame = None
                return None
            frame = self._bg_frame
            self._bg_frame = self._bg_back
        self._raw_frame = frame
        normalized, is_night = normalize_frame(frame)
        if is_night and not self._night_logged:
            print(f"  [{INFO}] Night mode detected -- normalizing frames")
            self._night_logged = True
        return normalized

    def _check_reconnect_popup(self) -> bool:
        """Check and dismiss network disconnect popup. Call when flow seems stuck."""
        frame = self.sc.grab_full()
        if frame is None:
            return False
        m = self.matcher.match_single(frame, "ui/btn_confirm_reconnect")
        if m and m.confidence >= 0.75:
            roll = random.random()
            if roll < 0.30:
                time.sleep(random.uniform(1.0, 5.0))
            elif roll < 0.60:
                delay = random.uniform(30, 120)
                logger.info("Reconnect: delayed %.0fs (brief AFK)", delay)
                time.sleep(delay)
            elif roll < 0.80:
                delay = random.uniform(300, 900)
                logger.info("Reconnect: long delay %.0fs (extended AFK)", delay)
                time.sleep(delay)
                frame = self.sc.grab_full()
                m = self.matcher.match_single(frame, "ui/btn_confirm_reconnect") if frame is not None else None
                if not m or m.confidence < 0.75:
                    return False
            else:
                delay = random.uniform(900, 1800)
                logger.info("Reconnect: very long delay %.0fs (simulating player left)", delay)
                time.sleep(delay)
                frame = self.sc.grab_full()
                m = self.matcher.match_single(frame, "ui/btn_confirm_reconnect") if frame is not None else None
                if not m or m.confidence < 0.75:
                    return False
            print(f"  [{WARN}] Network disconnect popup (conf={m.confidence:.3f}), clicking confirm...")
            self._click_match(m)
            time.sleep(random.uniform(3.0, 8.0))
            return True
        return False

    def _attempt_recovery(self):
        """Try to recover from stuck state by dismissing popups.
        Click empty map area instead of ESC (ESC opens profile when nothing is open)."""
        rx = random.uniform(0.82, 0.92)
        ry = random.uniform(0.35, 0.55)
        self._click_pct(rx, ry, jitter_px=8)
        time.sleep(random.uniform(0.5, 1.0))
        cx, cy = self._center_screen()
        self._click(cx, cy)
        time.sleep(random.uniform(0.5, 1.0))
        self._click_pct(random.uniform(0.82, 0.92), random.uniform(0.35, 0.55), jitter_px=8)
        time.sleep(random.uniform(1.0, 2.0))
        if self._check_reconnect_popup():
            print(f"  [{WARN}] Recovery: dismissed reconnect popup")
            time.sleep(random.uniform(3.0, 6.0))

    # --- Coordinate helpers (all constrained to game window) ---

    def _refresh_window(self):
        w = self.sc.find_window()
        if w:
            self.win = w

    def _screen_xy(self, frame_x: int, frame_y: int) -> tuple[int, int]:
        raw = self._raw_frame
        if raw is not None:
            fh, fw = raw.shape[:2]
            ww, wh = self.win["width"], self.win["height"]
            if fw > 0 and fh > 0 and (fw != ww or fh != wh):
                frame_x = int(frame_x * ww / fw)
                frame_y = int(frame_y * wh / fh)
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

    def _probe_moveto(self) -> bool:
        """Send MOVETO and verify cursor arrives near the expected screen position.

        Probes at the center of the game window so the cursor stays in-place
        rather than jumping to an arbitrary screen location.
        """
        if not self.win:
            return False
        res_w, res_h = get_screen_resolution()
        target_sx = self.win["left"] + self.win["width"] // 2
        target_sy = self.win["top"] + self.win["height"] // 2
        target_hid_x = int(target_sx * 32767 / res_w)
        target_hid_y = int(target_sy * 32767 / res_h)
        if not self.cmd.send("MOVETO", target_hid_x, target_hid_y):
            return False
        time.sleep(0.4)
        cx, cy = get_cursor_pos()
        err = max(abs(cx - target_sx), abs(cy - target_sy))
        ok = err < 80
        if not ok:
            logger.warning("MOVETO inaccurate: cursor=(%d,%d) expected=(%d,%d) err=%d",
                           cx, cy, target_sx, target_sy, err)
        return ok

    def _calibrate_mouse_scale(self) -> float:
        """Measure Windows mouse acceleration by sending known MOVE deltas."""
        scales = []
        for test_dx in [80, -80, 120, -120]:
            time.sleep(0.15)
            bx, _ = get_cursor_pos()
            self.cmd.send("MOVE", test_dx, 0, 50)
            time.sleep(0.15)
            ax, _ = get_cursor_pos()
            actual = ax - bx
            if abs(test_dx) > 5 and abs(actual) > 5:
                scales.append(actual / test_dx)
        for test_dy in [80, -80]:
            time.sleep(0.15)
            _, by = get_cursor_pos()
            self.cmd.send("MOVE", 0, test_dy, 50)
            time.sleep(0.15)
            _, ay = get_cursor_pos()
            actual = ay - by
            if abs(test_dy) > 5 and abs(actual) > 5:
                scales.append(actual / test_dy)
        if scales:
            avg = sum(abs(s) for s in scales) / len(scales)
            return max(0.5, min(3.0, avg))
        return 1.0

    def _restore_cursor_to_window(self):
        """Move cursor back to game window center using relative MOVE with correction."""
        tx = self.win["left"] + self.win["width"] // 2
        ty = self.win["top"] + self.win["height"] // 2
        sc = self._mouse_scale
        for _ in range(5):
            cx, cy = get_cursor_pos()
            dx, dy = tx - cx, ty - cy
            if abs(dx) <= 5 and abs(dy) <= 5:
                break
            send_dx = int(dx / sc) if sc != 1.0 else dx
            send_dy = int(dy / sc) if sc != 1.0 else dy
            dur = max(abs(send_dx), abs(send_dy)) * 2
            self.cmd.send("MOVE", send_dx, send_dy, max(dur, 50))
            time.sleep(0.15)

    def _path_to_hid(self, path: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
        """Convert screen-coord path to HID waypoints, clamped to game window."""
        waypoints = []
        for px, py, ms in path:
            cx, cy = self._clamp_to_window(int(px), int(py))
            hx, hy = screen_to_hid(cx, cy)
            waypoints.append((hx, hy, ms))
        return waypoints

    def _send_path(self, waypoints: list[tuple[int, int, int]], drag: bool = False) -> bool:
        """Send path via PATH commands (ESP32 hardware timing) with fallback."""
        ok = self.cmd.send_path(waypoints, drag=drag)
        if ok:
            return True
        # Fallback: send one by one
        logger.debug("PATH command failed, falling back to sequential MOVETO")
        if drag:
            self.cmd.send("MDOWN", "L")
            time.sleep(0.015)
        for hx, hy, ms in waypoints:
            self.cmd.send("MOVETO", hx, hy)
            time.sleep(max(0.004, ms / 1000.0))
        if drag:
            time.sleep(0.015)
            self.cmd.send("MUP", "L")
        return True

    def _moveto(self, sx: int, sy: int) -> bool:
        sx, sy = self._clamp_to_window(sx, sy)
        cur_x, cur_y = get_cursor_pos()
        dx = sx - cur_x
        dy = sy - cur_y
        if abs(dx) < 3 and abs(dy) < 3:
            return True

        # The humanizer already shapes the velocity envelope (accel -> cruise
        # -> decel); don't re-time the path here or it distorts that profile.
        path = self.humanizer.humanize_move(cur_x, cur_y, sx, sy)

        if self._has_moveto:
            waypoints = self._path_to_hid([(cur_x, cur_y, 0), *path])
            self._send_path(waypoints)
            hx, hy = screen_to_hid(sx, sy)
            self.cmd.send("MOVETO", hx, hy)
        else:
            sc = self._mouse_scale
            for px, py, step_ms in path:
                ax, ay = get_cursor_pos()
                mdx = px - ax
                mdy = py - ay
                send_dx = int(mdx / sc) if sc != 1.0 else int(mdx)
                send_dy = int(mdy / sc) if sc != 1.0 else int(mdy)
                if abs(send_dx) > 0 or abs(send_dy) > 0:
                    dur = max(step_ms, max(abs(send_dx), abs(send_dy)))
                    self.cmd.send("MOVE", send_dx, send_dy, dur)
            for _ in range(4):
                time.sleep(0.03)
                ax, ay = get_cursor_pos()
                err_x, err_y = sx - ax, sy - ay
                if abs(err_x) <= 3 and abs(err_y) <= 3:
                    break
                send_ex = int(err_x / sc) if sc != 1.0 else err_x
                send_ey = int(err_y / sc) if sc != 1.0 else err_y
                dur = max(abs(send_ex), abs(send_ey)) * 2
                self.cmd.send("MOVE", send_ex, send_ey, max(dur, 30))
        return True

    _NO_CLICK_ZONES = [
        (0.0, 0.0, 0.70, 0.13),
        (0.0, 0.80, 0.45, 1.0),
    ]

    def _in_no_click_zone(self, sx: int, sy: int) -> bool:
        rx = (sx - self.win["left"]) / self.win["width"]
        ry = (sy - self.win["top"]) / self.win["height"]
        in_zone = False
        for x1, y1, x2, y2 in self._NO_CLICK_ZONES:
            if x1 <= rx <= x2 and y1 <= ry <= y2:
                in_zone = True
                break
        if in_zone and random.random() < 0.05:
            return False
        return in_zone

    def _click(self, sx: int, sy: int, hold_ms: int = 0) -> bool:
        ox, oy, h = self.humanizer.humanize_click(sx, sy)
        sx += ox
        sy += oy
        if self._in_no_click_zone(sx, sy):
            logger.debug("Click blocked: (%d,%d) in no-click zone", sx, sy)
            return False
        if not self._moveto(sx, sy):
            return False
        perceive = random.lognormvariate(-0.5, 0.4)
        time.sleep(max(0.15, min(2.0, perceive)))
        if random.random() < 0.015:
            miss_dx = random.randint(-40, 40)
            miss_dy = random.randint(-30, 30)
            self._moveto(sx + miss_dx, sy + miss_dy)
            time.sleep(random.uniform(0.05, 0.15))
            self.cmd.send("CLICK", "L", random.randint(30, 60))
            time.sleep(random.uniform(0.2, 0.6))
            self._moveto(sx, sy)
            time.sleep(random.uniform(0.1, 0.3))
        if hold_ms <= 0:
            hold_ms = h
            if random.random() < 0.08:
                hold_ms = random.randint(200, 400)
        ok = self.cmd.send("CLICK", "L", hold_ms)
        self.session.record_action()
        self._wait(DELAY_AFTER_CLICK)
        return ok

    def _click_match(self, match: Match) -> bool:
        sx, sy = self._screen_xy(*match.center)
        jx = int(random.gauss(0, match.w / 8))
        jy = int(random.gauss(0, match.h / 8))
        jx = max(-match.w // 3, min(match.w // 3, jx))
        jy = max(-match.h // 3, min(match.h // 3, jy))
        return self._click(sx + jx, sy + jy)

    def _human_drag(self, sx: int, sy: int, ex: int, ey: int,
                    button: str = "L", speed_factor: float = 1.0,
                    easing: str = "in_out"):
        # `easing` is accepted for call-site compatibility but ignored: the
        # humanizer now owns the acceleration profile. `speed_factor` still
        # scales the overall duration (e.g. fast camera pans).
        sx, sy = self._clamp_to_window(sx, sy)
        ex, ey = self._clamp_to_window(ex, ey)
        self._moveto(sx, sy)
        time.sleep(random.uniform(0.08, 0.2))

        path = self.humanizer.humanize_move(sx, sy, ex, ey)
        if speed_factor != 1.0:
            path = [(x, y, max(3, int(ms / speed_factor))) for x, y, ms in path]

        if self._has_moveto:
            waypoints = self._path_to_hid([(sx, sy, 0), *path])
            self._send_path(waypoints, drag=True)
        else:
            sc = self._mouse_scale
            self.cmd.send("MDOWN", button)
            time.sleep(random.uniform(0.01, 0.03))
            prev_x, prev_y = float(sx), float(sy)
            for px, py, step_ms in path:
                cx, cy = self._clamp_to_window(int(px), int(py))
                mdx = cx - prev_x
                mdy = cy - prev_y
                send_dx = int(mdx / sc) if sc != 1.0 else int(mdx)
                send_dy = int(mdy / sc) if sc != 1.0 else int(mdy)
                if abs(send_dx) > 0 or abs(send_dy) > 0:
                    self.cmd.send("MOVE", send_dx, send_dy, step_ms)
                prev_x, prev_y = float(cx), float(cy)
            time.sleep(random.uniform(0.01, 0.03))
            self.cmd.send("MUP", button)

    def _scroll_at_center(self, amount: int, count: int = 1):
        cx, cy = self._center_screen()
        cx += random.randint(-int(self.win["width"] * 0.25), int(self.win["width"] * 0.25))
        cy += random.randint(-int(self.win["height"] * 0.15), int(self.win["height"] * 0.15))
        cx, cy = self._clamp_to_play_area(cx, cy)
        self._moveto(cx, cy)
        time.sleep(random.uniform(0.15, 0.4))

        overshoot = random.random() < self._scroll_overshoot_chance
        extra = random.randint(1, 2) if overshoot else 0
        total_notches = abs(amount) * (count + extra)
        direction = 1 if amount > 0 else -1
        for i in range(total_notches):
            self.cmd.send("SCROLL", direction)
            if random.random() < 0.3:
                time.sleep(random.uniform(0.15, 0.5))
            else:
                time.sleep(random.uniform(0.04, 0.12))
            if random.random() < 0.08:
                time.sleep(random.uniform(0.3, 1.5))
        if overshoot and extra > 0:
            time.sleep(random.uniform(0.4, 1.0))
            correction = max(1, int(extra * 0.6))
            for _ in range(correction):
                self.cmd.send("SCROLL", -direction)
                if random.random() < 0.3:
                    time.sleep(random.uniform(0.15, 0.5))
                else:
                    time.sleep(random.uniform(0.04, 0.12))

    def _press_escape(self):
        rx = random.uniform(0.82, 0.92)
        ry = random.uniform(0.35, 0.55)
        sx = self.win["left"] + int(self.win["width"] * rx)
        sy = self.win["top"] + int(self.win["height"] * ry)
        self._moveto(sx, sy)
        time.sleep(random.uniform(0.03, 0.12))
        self.cmd.send("CLICK", "L", random.randint(30, 80))
        logger.debug("dismiss_panel: click empty area (%.2f, %.2f)", rx, ry)

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
                logger.info("Classifier REJECT at %s: %s (%.2f)", m.center, label, clf_conf)
                continue
            is_gem_color, color_info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            if not is_gem_color:
                logger.info("color REJECT at %s conf=%.3f: %s", m.center, m.confidence, color_info.get("reason",""))
                continue
            ok, zone_info = self._is_clickable_zone(frame, m)
            if not ok:
                if zone_info.startswith("edge"):
                    logger.info("gem_icon at EDGE %s conf=%.3f -- will recenter", m.center, m.confidence)
                    edge_gems.append(m)
                else:
                    logger.info("gem_icon zone REJECT at %s conf=%.3f: %s", m.center, m.confidence, zone_info)
                continue
            logger.debug("gem_icon OK at %s: color=%s clf=%s(%.2f)", m.center, color_info.get("reason",""), label, clf_conf)
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
                    logger.info("Taking break for %.0fs", dur)
                    print(f"\n  [{INFO}] Session break: {dur / 60:.1f} min")
                    self._tab_away()
                    time.sleep(dur)
                    self._tab_back()
                    continue

                label = f"{i}" if self.loop else f"{i}/{self.count}"
                print(f"\n{'*' * 60}")
                print(f"  *** MINE {label} ***")
                print(f"  Session: {self.session.elapsed_minutes:.0f} min")
                print(f"{'*' * 60}")

                if not self._mine_flow(i):
                    print(f"\n  Mine {i} FAILED")
                    consecutive_fails += 1
                    if consecutive_fails >= 3:
                        print(f"  [{WARN}] {consecutive_fails} consecutive fails, attempting recovery...")
                        self._attempt_recovery()
                    if consecutive_fails >= 8:
                        print(f"  [{WARN}] {consecutive_fails} consecutive fails, taking long break before retry")
                        self._tab_away()
                        time.sleep(random.uniform(120, 300))
                        self._tab_back()
                        consecutive_fails = 0
                    self._wait(random.uniform(1.0, 3.0))
                    i += 1
                    continue

                consecutive_fails = 0
                self.mines_completed += 1
                self._queue_wait_start = time.time()
                print(f"\n  Mine {i} DONE (total: {self.mines_completed})")

                self._burst_counter -= 1
                if self._burst_counter <= 0:
                    self._tab_away()
                    self._tab_back()
                    self._burst_counter = random.choices(
                        [3, 4, 5, 6, 7, 8], weights=[10, 20, 30, 20, 12, 8])[0]
                else:
                    self._wait(DELAY_BETWEEN_MINES)

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

        self._actions.maybe_distract("before_next")

        # Step 1: Get to world map at icon-zoom level
        # If already on world map (from previous mine), skip city detour
        if not self._step_to_world_map(tag):
            return False

        self._actions.maybe_distract("after_world")

        # Step 2+3+4: Wander scan, clicking each icon to verify gem type
        gem = self._step_scan_and_verify_gem(tag)
        if gem is None:
            # Failed to find gem -- only return city if needed for queue check
            if self.loop and random.random() < 0.6:
                self._step_return_city(tag)
            return False

        # Step 5: Click "Thu Thap" (gather)
        if not self._step_click_gather(tag):
            return False

        self._actions.maybe_distract("after_gather")

        # Step 6: Select troop + click "March"
        if not self._step_click_march(tag):
            return False

        self.gathered_positions.append(gem.center)
        print(f"  [{INFO}] Marked gem at {gem.center} as gathered ({len(self.gathered_positions)} total)")

        self._actions.maybe_distract("after_march")

        # Step 7: Stay on world map, zoom back to icon level for next mine
        # Only return to city occasionally (queue check, or like a real player)
        if not hasattr(self, '_city_return_interval'):
            self._city_return_interval = random.randint(2, 4)
        need_city = self.loop and (self.mines_completed + 1) % self._city_return_interval == 0
        if need_city:
            self._city_return_interval = random.randint(2, 4)
            self._step_return_city(tag)
        else:
            self._step_stay_and_rezoom(tag)
        return True

    def _step_stay_and_rezoom(self, tag: str):
        """After march, stay on world map and zoom back out to icon level."""
        print(f"\n--- [{tag}] Step 7: Stay on world map, re-zoom ---\n")

        # After march, game often zooms in on marching troops -- wait for it
        self._wait(random.uniform(1.0, 2.5))

        # Escape any march animation overlay
        self._press_escape()
        self._wait(DELAY_AFTER_ESCAPE)

        # Verify still on world map
        city_btn = self._find("buttons/city_btn", threshold=0.70)
        if not city_btn:
            print(f"  [{WARN}] Not on world map after march, falling back to city")
            self._step_return_city(tag)
            return

        # Shift camera away from just-gathered mine so we scan new area
        cx, cy = self._center_screen()
        ww, wh = self.win["width"], self.win["height"]
        margin = 80
        angle = random.uniform(0, 2 * math.pi)
        for _ in range(random.randint(1, 2)):
            dist = random.uniform(0.20, 0.30)
            dx = int(math.cos(angle) * (ww // 2 - margin) * dist)
            dy = int(math.sin(angle) * (wh // 2 - margin) * dist)
            sx, sy = self._clamp_to_play_area(cx + dx, cy + dy)
            ex, ey = self._clamp_to_play_area(cx - dx, cy - dy)
            self._human_drag(sx, sy, ex, ey, speed_factor=random.uniform(3.0, 5.0))
            self._wait(random.uniform(0.3, 0.8))
            angle += random.gauss(0, 0.3)

        # Zoom out to icon level
        self._scroll_at_center(-1, self._zoom_scrolls())
        self._wait(DELAY_AFTER_SCROLL)

        self._record(f"{tag}_rezoom", True, "Stayed on world map, re-zoomed")

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
            "resources/gem_icon", "resources/gem_mine_close",
            "buttons/gather_btn", "buttons/world_map_city_btn",
            "buttons/new_troop_btn", "buttons/march_btn_orange",
            "buttons/march_btn", "buttons/city_btn",
            "ui/btn_mail", "ui/btn_alliance",
            "ui/btn_x_close_mail", "ui/btn_x_close_alliance", "ui/btn_x_close_bag",
            "ui/city_food", "ui/city_wood",
        ]
        for t in key_templates:
            img = self.cache.get(t)
            status = PASS if img is not None else FAIL
            size = f"{img.shape[1]}x{img.shape[0]}" if img is not None else "MISSING"
            print(f"  [{status}] {t}: {size}")

        optional_templates = ["ui/btn_confirm_reconnect"]
        for t in optional_templates:
            img = self.cache.get(t)
            status = PASS if img is not None else WARN
            size = f"{img.shape[1]}x{img.shape[0]}" if img is not None else "MISSING (optional)"
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
        self._has_moveto = self._probe_moveto()
        if self._has_moveto:
            print(f"  [{PASS}] ESP32: {self.port} (MOVETO verified)")
        else:
            self._mouse_scale = self._calibrate_mouse_scale()
            print(f"  [{WARN}] ESP32: {self.port} (MOVETO unavailable, using relative MOVE, scale={self._mouse_scale:.2f}x)")

        self._start_capture_thread()
        time.sleep(0.2)

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

        # Dismiss any open panel/popup before starting
        self._dismiss_popups()

        # Check if already on world map at icon zoom
        frame = self._grab()
        if frame is not None:
            city_btn = self._find_on_frame(frame, "buttons/city_btn", threshold=0.70)
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
            if self._check_reconnect_popup():
                m = self._find("buttons/world_map_city_btn", threshold=WORLD_MAP_BTN_THRESHOLD)
                if m:
                    self._click_match(m)
                    self._wait(DELAY_WORLD_MAP)
                else:
                    print(f"  [{WARN}] world_map_city_btn not found after reconnect")
            else:
                print(f"  [{WARN}] world_map_city_btn not found, trying bottom-right click...")
                br_x = self.win["left"] + int(self.win["width"] * 0.95)
                br_y = self.win["top"] + int(self.win["height"] * 0.93)
                self._click(br_x, br_y)
                self._wait(DELAY_WORLD_MAP)

        # Verify we're on world map (retry — transition animation takes time)
        city_btn = None
        for retry in range(4):
            city_btn = self._find("buttons/city_btn", threshold=0.70)
            if city_btn:
                break
            time.sleep(1.0)
        if not city_btn:
            # May have toggled wrong direction — try clicking Space again
            m2 = self._find("buttons/world_map_city_btn", threshold=WORLD_MAP_BTN_THRESHOLD)
            if m2:
                print(f"  [{WARN}] Toggled wrong, clicking Space again...")
                self._click_match(m2)
                self._wait(DELAY_WORLD_MAP)
                city_btn = self._find("buttons/city_btn", threshold=0.70)
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
        noticed = [m for m in result if random.random() > 0.08]
        if len(noticed) < len(result):
            logger.debug("Missed %d icon(s) (simulated inattention)", len(result) - len(noticed))
        return sorted(noticed, key=lambda m: -m.confidence)

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

    def _recenter_to_safe_zone(self, icon: Match) -> Match | None:
        """If icon is in no-click zone, drag map to move it to center."""
        sx, sy = self._screen_xy(*icon.center)
        if not self._in_no_click_zone(sx, sy):
            return icon
        cx, cy = self._center_screen()
        drag_dy = sy - cy
        drag_dx = sx - cx
        print(f"  [{INFO}] Icon at ({sx},{sy}) in no-click zone, dragging map to recenter")
        self._human_drag(cx - drag_dx // 3, cy - drag_dy // 3,
                         cx + drag_dx, cy + drag_dy)
        time.sleep(random.uniform(0.3, 0.6))
        frame = self._grab()
        if frame is None:
            return None
        icons = self._find_all_icons(frame)
        if icons:
            return icons[0]
        return None

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

        wander_heading = getattr(self, '_wander_heading', random.uniform(0, 2 * math.pi))
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

        distraction_interval = random.randint(8, 15)

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
                icon = self._recenter_to_safe_zone(icon)
                if icon is None:
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
                return None

            if scan_count > 1 and scan_count % distraction_interval == 0:
                self._actions.maybe_distract("during_scan")

            turn = random.gauss(0, 0.4)
            if random.random() < 0.15:
                turn = random.uniform(-math.pi / 2, math.pi / 2)
            if random.random() < 0.05:
                turn = random.uniform(-math.pi, math.pi)
            wander_heading += turn

            dx_f = math.cos(wander_heading)
            dy_f = math.sin(wander_heading)

            if random.random() < 0.12:
                _speed_target = random.uniform(3.6, 7.0)
            scan_speed += (_speed_target - scan_speed) * random.uniform(0.08, 0.15)

            num_swipes = 2
            for _sw in range(num_swipes):
                dist_pct = random.uniform(0.20, 0.30)
                jx = random.randint(-25, 25)
                jy = random.randint(-20, 20)
                half_x = int((ww // 2 - margin) * dist_pct)
                half_y = int((wh // 2 - margin) * dist_pct)
                sx = cx + int(dx_f * half_x) + jx
                sy = cy + int(dy_f * half_y) + jy
                ex = cx - int(dx_f * half_x) + jx
                ey = cy - int(dy_f * half_y) + jy
                sx, sy = self._clamp_to_play_area(sx, sy)
                ex, ey = self._clamp_to_play_area(ex, ey)
                self._human_drag(sx, sy, ex, ey, speed_factor=scan_speed, easing="in")
                time.sleep(random.uniform(0.25, 0.55))
                turn_adj = random.gauss(0, 0.15)
                wander_heading += turn_adj

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
                      f"(spd={scan_speed:.1f}x, empty={empty_streak})")
                if empty_streak >= max_empty_streak:
                    if self._check_reconnect_popup():
                        empty_streak = 0
                        continue
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
                icon = self._recenter_to_safe_zone(icon)
                if icon is None:
                    continue
                attempt += 1
                tried_this_frame += 1
                clicked_positions.append((*icon.center, SKIP_RADIUS))
                if self._click_icon_and_verify(icon, tag, attempt, icon_frame=frame):
                    self._wander_heading = wander_heading
                    self._record(f"{tag}_find", True, f"Gem at attempt {attempt}, scan {scan_count}")
                    return icon
                self._return_to_icon_zoom()

        self._wander_heading = wander_heading
        print(f"  [{FAIL}] No gem mine after {scan_count} scans, {attempt} icons checked")
        self._record(f"{tag}_find", False, f"{attempt} icons checked, none were gem")
        return None

    # --- Step: Click gather button ---

    def _step_click_gather(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 5: Click Gather ---\n")

        max_retries = random.randint(3, 6)
        for attempt in range(max_retries):
            frame = self._grab()
            if frame is None:
                self._wait(DELAY_RECHECK)
                continue
            if random.random() < 0.1:
                time.sleep(random.uniform(1.0, 3.0))

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

        if self._check_reconnect_popup():
            return self._step_click_gather(tag)
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

            self._wait(DELAY_VERIFY[0] * 2)

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
        self._stop_capture_thread()
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
        if SCREENSHOT_DIR.exists():
            cutoff = time.time() - 3600
            for f in SCREENSHOT_DIR.glob("*.png"):
                try:
                    if f.stat().st_mtime < cutoff:
                        f.unlink()
                except Exception:
                    pass

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
    parser.add_argument("--account-id", type=str, default="default",
                        help="Account identifier for persistent persona (default: 'default')")
    parser.add_argument("--actions", type=str, default=None,
                        help="Override distraction action pool (comma-separated, e.g. alt_tab,chat,mail)")
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
        actions_list = args.actions.split(",") if args.actions else None
        test = GemFarmFlowTest(
            port=args.port, count=args.count, auto_learn=args.auto_learn,
            loop=args.loop, max_marches=args.max_marches,
            account_id=args.account_id,
            actions_override=actions_list,
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
