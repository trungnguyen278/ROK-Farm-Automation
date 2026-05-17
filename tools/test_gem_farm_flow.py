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
import time
import logging
import argparse
import random
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.screen_capture import ScreenCapture
from capture.screen_info import screen_to_hid, screen_delta_to_hid
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
ICON_ZOOM_SCROLLS = 2
GEM_ICON_THRESHOLD = 0.68
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

# --- Time delays (seconds) -- human-realistic ranges ---
DELAY_AFTER_CLICK = 1.0         # sau click thuong
DELAY_AFTER_ESCAPE = 1.5        # sau ESC
DELAY_AFTER_SCROLL = 2.5        # sau scroll zoom
DELAY_ZOOM_IN = 3.0             # cho game zoom vao mine
DELAY_MINE_CLICK = 2.0          # cho popup sau click mine
DELAY_RECHECK = 2.5             # cho truoc recheck
DELAY_VERIFY = 3.0              # cho verify sau action
DELAY_DRAG_SETTLE = 3.0         # cho map on dinh sau drag
DELAY_WORLD_MAP = 3.0           # cho chuyen sang world map
DELAY_BETWEEN_MINES = 12.0      # nghi giua cac mine (base, actual = 8-25s)
DELAY_DRAG_PRE = (0.3, 0.8)     # random truoc drag
DELAY_DRAG_POST = (1.5, 4.0)    # random sau drag scan
DELAY_MICRO_PAUSE = (3.0, 8.0)  # random micro pause



def save_screenshot(frame, name):
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
    def __init__(self, port: str, count: int = 1, auto_learn: bool = False):
        self.port = port
        self.count = count
        self.auto_learn = auto_learn
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
        self._last_hid: tuple[int, int] | None = None

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
            sx, sy = self._clamp_to_window(cx + dx, cy + dy)
            ex, ey = self._clamp_to_window(cx - dx, cy - dy)
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

    def _check_session(self) -> str | None:
        if self.session.should_stop_daily():
            return "daily_limit"
        if self.session.should_take_break():
            return "break"
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

    def _clamp_to_window(self, sx: int, sy: int, pad: int = 5) -> tuple[int, int]:
        x = max(self.win["left"] + pad, min(self.win["left"] + self.win["width"] - pad, sx))
        top_pad = max(pad, TITLE_BAR_H)
        y = max(self.win["top"] + top_pad, min(self.win["top"] + self.win["height"] - pad, sy))
        return x, y

    def _moveto(self, sx: int, sy: int) -> bool:
        sx, sy = self._clamp_to_window(sx, sy)
        hx, hy = screen_to_hid(sx, sy)
        if self._last_hid is None:
            ok = self.cmd.send("MOVETO", hx, hy)
        else:
            dx = hx - self._last_hid[0]
            dy = hy - self._last_hid[1]
            dist = (dx**2 + dy**2) ** 0.5
            if dist < 10:
                ok = True
            else:
                dur = max(50, int(dist / 32767 * random.uniform(600, 1200)))
                ok = self.cmd.send("MOVE", dx, dy, dur)
        if ok:
            self._last_hid = (hx, hy)
        return ok

    def _click(self, sx: int, sy: int, hold_ms: int = 0) -> bool:
        ox, oy, h = self.humanizer.humanize_click(sx, sy)
        sx += ox
        sy += oy
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

    def _human_drag(self, sx: int, sy: int, ex: int, ey: int, button: str = "L"):
        self._moveto(sx, sy)
        time.sleep(random.uniform(0.08, 0.2))

        path = self.humanizer.humanize_move(sx, sy, ex, ey)
        path = self._apply_easing(path)

        self.cmd.send("MDOWN", button)
        time.sleep(random.uniform(0.01, 0.03))

        prev_x, prev_y = sx, sy
        for px, py, step_ms in path:
            dx, dy = px - prev_x, py - prev_y
            hid_dx, hid_dy = screen_delta_to_hid(int(dx), int(dy))
            if abs(hid_dx) > 0 or abs(hid_dy) > 0:
                self.cmd.send("MOVE", hid_dx, hid_dy, step_ms)
            prev_x, prev_y = px, py

        time.sleep(random.uniform(0.01, 0.03))
        self.cmd.send("MUP", button)
        self._last_hid = screen_to_hid(*self._clamp_to_window(ex, ey))

    def _apply_easing(self, path: list[tuple[int, int, int]]) -> list[tuple[int, int, int]]:
        n = len(path)
        result = []
        for i, (x, y, ms) in enumerate(path):
            t = i / max(n - 1, 1)
            factor = 0.6 + 0.8 * abs(2 * t - 1)
            result.append((x, y, max(5, int(ms * factor))))
        return result

    def _scroll_at_center(self, amount: int, count: int = 1):
        cx, cy = self._center_screen()
        cx += random.randint(-25, 25)
        cy += random.randint(-25, 25)
        self._moveto(cx, cy)
        time.sleep(random.uniform(0.15, 0.4))
        for _ in range(count):
            self.cmd.send("SCROLL", amount)
            time.sleep(random.uniform(0.3, 0.7))

    def _press_escape(self):
        self.cmd.send("KEY", 27)

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
        print(f"  Target mines: {self.count}")
        print(f"  Profile: {self._profile.get('name', 'default')}")
        print()

        try:
            if not self._setup():
                return

            if self.session.should_stop_daily():
                print(f"  [{WARN}] Outside active window or daily limit -- aborting")
                return

            i = 1
            while i <= self.count:
                status = self._check_session()
                if status == "daily_limit":
                    print(f"\n  [{WARN}] Daily limit reached -- stopping")
                    break
                if status == "break":
                    dur = self.session.get_break_duration()
                    mins = dur / 60.0
                    print(f"\n  [{INFO}] Session break: {mins:.1f} min "
                          f"(after {self.session.elapsed_minutes:.0f} min active)")
                    time.sleep(dur)
                    continue

                print(f"\n{'*' * 60}")
                print(f"  *** MINE {i}/{self.count} ***")
                print(f"  Session: {self.session.elapsed_minutes:.0f} min | "
                      f"Fatigue: x{self.timing.apply_fatigue(self.session.elapsed_minutes):.2f}")
                print(f"{'*' * 60}")

                if not self._mine_flow(i):
                    print(f"\n  Mine {i} FAILED")
                    break

                self.mines_completed += 1
                print(f"\n  Mine {i} DONE ({self.mines_completed}/{self.count})")

                if i < self.count:
                    self._wait(DELAY_BETWEEN_MINES, 5.0)
                    if random.random() < 0.35:
                        extra = random.uniform(5.0, 20.0)
                        print(f"  [{INFO}] Extra pause {extra:.1f}s (human hesitation)")
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
                cx, cy = self._center_screen()
                self._click(cx, cy)
                self._wait(DELAY_AFTER_CLICK)
                self._scroll_at_center(-5, ICON_ZOOM_SCROLLS)
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

        print(f"  [{PASS}] On world map, zooming out {ICON_ZOOM_SCROLLS}x...")

        # Click center for focus, then zoom out exactly 2
        cx, cy = self._center_screen()
        self._click(cx, cy)
        self._wait(DELAY_AFTER_CLICK)
        self._scroll_at_center(-5, ICON_ZOOM_SCROLLS)
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
                sx, s_y = self._clamp_to_window(sx, s_y, pad=40)
                ex, e_y = self._clamp_to_window(ex, e_y, pad=40)
                self._human_drag(sx, s_y, ex, e_y)
                self._wait(random.uniform(1.5, 3.5), 0.8)
            print(f"  [{INFO}] Shifted camera ({num_drags} drags, base dir={base_angle})")

        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, f"{tag}_icon_zoom")

        self._record(f"{tag}_world", True, f"City -> world map -> zoom out {ICON_ZOOM_SCROLLS}x")
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
        max_area = 50 * 50
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            aspect = max(w, h) / max(min(w, h), 1)
            if aspect > 2.0:
                continue
            fill = area / max(w * h, 1)
            if fill < 0.5:
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
                self._press_escape()
                self._wait(DELAY_AFTER_ESCAPE)
                return False

            raw = self._raw_frame if self._raw_frame is not None else frame
            has_line, line_info = self._has_incoming_march(raw, mine)
            if has_line:
                save_screenshot(frame, f"{tag}_march_line_{attempt:02d}")
                print(f"  [{WARN}] [{attempt}] Incoming march at mine ({line_info}) -- skipping")
                self._press_escape()
                self._wait(DELAY_AFTER_ESCAPE)
                return False

            is_gem_color, color_info = is_gem_mine_color(frame, mine.x, mine.y, mine.w, mine.h)
            if not is_gem_color:
                save_screenshot(frame, f"{tag}_not_gem_mine_{attempt:02d}")
                print(f"  [{WARN}] [{attempt}] Mine color check failed ({color_info}) -- not gem")
                self._press_escape()
                self._wait(DELAY_AFTER_ESCAPE)
                return False
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
                print(f"  [{INFO}] [{attempt}] Popup not found -- retrying mine click (toggle recovery)...")
                self._click(msx, msy)
                self._wait(DELAY_MINE_CLICK)
                frame3 = self._grab()
                if frame3 is not None:
                    save_screenshot(frame3, f"{tag}_retry_mine_{attempt:02d}")
                    g3_raw = self.matcher.match_single(frame3, "buttons/gather_btn")
                    g3_conf = g3_raw.confidence if g3_raw else 0.0
                    print(f"  [{INFO}] [{attempt}] retry gather_btn conf={g3_conf:.3f}")
                    if g3_conf >= GATHER_BTN_THRESHOLD:
                        print(f"  [{PASS}] [{attempt}] Popup opened on retry!")
                        return True
            print(f"  [{WARN}] [{attempt}] Gem confirmed but popup won't open")
            self._press_escape()
            self._wait(DELAY_AFTER_ESCAPE)
            return False

        # Neither gem structure nor popup -- not a gem mine
        print(f"  [{WARN}] [{attempt}] Not a gem mine -- dismissing")
        self._press_escape()
        self._wait(DELAY_AFTER_ESCAPE)
        return False

    def _return_to_icon_zoom(self):
        """After a failed icon click, dismiss and zoom back to icon level."""
        cx, cy = self._center_screen()
        self._click(cx, cy)
        self._wait(DELAY_AFTER_ESCAPE)
        self._scroll_at_center(-5, ICON_ZOOM_SCROLLS)
        self._wait(DELAY_AFTER_SCROLL)

    def _step_scan_and_verify_gem(self, tag: str) -> Match | None:
        print(f"\n--- [{tag}] Step 2: Scan + verify gem mines ---\n")

        ww = self.win["width"]
        wh = self.win["height"]
        margin = 80
        cx, cy = self._center_screen()

        wander_dirs = [
            (1, 0), (-1, 0), (0, 1), (0, -1),
            (1, 1), (1, -1), (-1, 1), (-1, -1),
        ]
        last_dir = random.choice(wander_dirs)
        scan_count = 0
        max_scans = 35
        max_attempts = 10
        max_icons_per_frame = 2
        attempt = 0
        clicked_positions: list[tuple[int, int]] = []

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
                if any(abs(icon.center[0]-px) < 80 and abs(icon.center[1]-py) < 80
                       for px, py in clicked_positions):
                    continue
                raw = self._raw_frame if self._raw_frame is not None else frame
                occupied, occ_info = self._check_icon_occupied(raw, icon)
                if occupied:
                    print(f"  [{WARN}] Icon at {icon.center} occupied ({occ_info}) -- skip")
                    clicked_positions.append(icon.center)
                    continue
                attempt += 1
                tried_this_frame += 1
                clicked_positions.append(icon.center)
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

            # Pick direction: 45% continue roughly same way, 35% random, 20% backtrack
            r = random.random()
            if r < 0.45:
                same_ish = [d for d in wander_dirs
                            if d[0] * last_dir[0] >= 0 and d[1] * last_dir[1] >= 0]
                dx_u, dy_u = random.choice(same_ish) if same_ish else random.choice(wander_dirs)
            elif r < 0.80:
                dx_u, dy_u = random.choice(wander_dirs)
            else:
                dx_u, dy_u = -last_dir[0], -last_dir[1]
            last_dir = (dx_u, dy_u)

            # Vary drag distance: 30-100% of available space
            dist_pct = random.uniform(0.30, 1.0)
            jx = random.randint(-45, 45)
            jy = random.randint(-45, 45)
            half_x = int((ww // 2 - margin) * dist_pct)
            half_y = int((wh // 2 - margin) * dist_pct)
            sx = cx + dx_u * half_x + jx
            sy = cy + dy_u * half_y + jy
            ex = cx - dx_u * half_x + jx
            ey = cy - dy_u * half_y + jy
            sx, sy = self._clamp_to_window(sx, sy, pad=40)
            ex, ey = self._clamp_to_window(ex, ey, pad=40)
            self._human_drag(sx, sy, ex, ey)
            self._wait(random.uniform(*DELAY_DRAG_POST), 1.0)

            if random.random() < 0.25:
                self._wait(random.uniform(*DELAY_MICRO_PAUSE), 2.0)

            self._do_idle_action()

            frame = self._grab()
            if frame is None:
                continue

            save_screenshot(frame, f"{tag}_scan_{scan_count:02d}")

            icons = self._find_all_icons(frame)

            if not icons and self._edge_gems:
                print(f"  [{INFO}] Scan {scan_count:2d}: {len(self._edge_gems)} edge gem(s), recentering...")
                icons = self._recenter_edge_gem(self._edge_gems[0])

            if not icons:
                print(f"  [ -- ] Scan {scan_count:2d}/{max_scans}: no icons")
                continue

            print(f"  [{INFO}] Scan {scan_count:2d}/{max_scans}: {len(icons)} icon(s)")
            tried_this_frame = 0
            for icon in icons:
                if attempt >= max_attempts or tried_this_frame >= max_icons_per_frame:
                    break
                if any(abs(icon.center[0]-px) < 80 and abs(icon.center[1]-py) < 80
                       for px, py in clicked_positions):
                    print(f"  [ -- ] Skip already-clicked icon at {icon.center}")
                    continue
                raw = self._raw_frame if self._raw_frame is not None else frame
                occupied, occ_info = self._check_icon_occupied(raw, icon)
                if occupied:
                    print(f"  [{WARN}] Icon at {icon.center} occupied ({occ_info}) -- skip")
                    clicked_positions.append(icon.center)
                    continue
                attempt += 1
                tried_this_frame += 1
                clicked_positions.append(icon.center)
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
    args = parser.parse_args()

    if args.find_only:
        _run_find_only()
    else:
        test = GemFarmFlowTest(port=args.port, count=args.count, auto_learn=args.auto_learn)
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
