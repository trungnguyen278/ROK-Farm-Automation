"""
Gem Farm Flow -- E2E Test via ESP32 HID

Flow per mine:
  1. From city view -> click world map button (bottom-right) -> zoom out 2x
  2. Spiral scan map for gem_icon (white diamond), minimal frame overlap
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
from capture.screen_info import screen_to_hid
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher, Match
from vision.state_detector import StateDetector
from vision.color_filter import is_gem_icon_color, is_gem_mine_color
from vision.gem_classifier import GemPatchClassifier

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

ICON_ZOOM_SCROLLS = 2
GEM_ICON_THRESHOLD = 0.68
BUTTON_THRESHOLD = 0.80
WORLD_MAP_BTN_THRESHOLD = 0.75
CLICK_SETTLE = 0.1
VERIFY_DELAY = 1.5
DRAG_OVERLAP = 0.20
DRAG_SETTLE = 2.5

MARCH_TEMPLATES = ["buttons/march_btn_orange", "buttons/march_btn"]
GEM_MINE_TEMPLATES = ["resources/gem_mine_close", "resources/gem_mine"]
GEM_MINE_THRESHOLD = 0.60
OCCUPY_GREEN_PCT = 4.0
MARCH_LINE_PCT = 0.15
SAFE_ZONE_MARGIN = 0.08
DARK_TERRAIN_THRESH = 70


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
        self.classifier = GemPatchClassifier()
        self.classifier.load()

    # --- Coordinate helpers (all constrained to game window) ---

    def _screen_xy(self, frame_x: int, frame_y: int) -> tuple[int, int]:
        return frame_x + self.win["left"], frame_y + self.win["top"]

    def _center_screen(self) -> tuple[int, int]:
        return (self.win["left"] + self.win["width"] // 2,
                self.win["top"] + self.win["height"] // 2)

    def _clamp_to_window(self, sx: int, sy: int, pad: int = 5) -> tuple[int, int]:
        x = max(self.win["left"] + pad, min(self.win["left"] + self.win["width"] - pad, sx))
        y = max(self.win["top"] + pad, min(self.win["top"] + self.win["height"] - pad, sy))
        return x, y

    def _moveto(self, sx: int, sy: int) -> bool:
        sx, sy = self._clamp_to_window(sx, sy)
        hx, hy = screen_to_hid(sx, sy)
        return self.cmd.send("MOVETO", hx, hy)

    def _click(self, sx: int, sy: int, hold_ms: int = 0) -> bool:
        sx += random.randint(-3, 3)
        sy += random.randint(-3, 3)
        if not self._moveto(sx, sy):
            return False
        time.sleep(random.uniform(0.06, 0.14))
        if hold_ms <= 0:
            hold_ms = random.randint(60, 120)
        return self.cmd.send("CLICK", "L", hold_ms)

    def _click_match(self, match: Match) -> bool:
        sx, sy = self._screen_xy(*match.center)
        jx = random.randint(-match.w // 6, match.w // 6)
        jy = random.randint(-match.h // 6, match.h // 6)
        return self._click(sx + jx, sy + jy)

    def _scroll_at_center(self, amount: int, count: int = 1):
        cx, cy = self._center_screen()
        cx += random.randint(-15, 15)
        cy += random.randint(-15, 15)
        self._moveto(cx, cy)
        time.sleep(random.uniform(0.06, 0.15))
        for _ in range(count):
            self.cmd.send("SCROLL", amount)
            time.sleep(random.uniform(0.10, 0.25))

    def _press_escape(self):
        self.cmd.send("KEY", 27)

    # --- Template helpers ---

    def _find(self, template: str, threshold: float = 0.65) -> Match | None:
        frame = self.sc.grab_full()
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
        for m in matches:
            if m.confidence < GEM_ICON_THRESHOLD:
                continue
            ok, zone_info = self._is_clickable_zone(frame, m)
            if not ok:
                logger.info("gem_icon zone REJECT at %s conf=%.3f: %s", m.center, m.confidence, zone_info)
                continue
            is_gem, info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            if not is_gem:
                logger.info("gem_icon color REJECT at %s conf=%.3f: %s", m.center, m.confidence, info)
                continue
            patch = self._extract_icon_patch(frame, m)
            should, label, clf_conf = self.classifier.should_click(patch)
            if not should:
                logger.info("gem_icon classifier REJECT at %s: %s (%.2f)", m.center, label, clf_conf)
                continue
            logger.debug("gem_icon OK at %s: color=%s, clf=%s(%.2f)", m.center, info, label, clf_conf)
            result.append(m)
        return result

    # --- Main flow ---

    def run(self):
        for f in SCREENSHOT_DIR.glob("*.png"):
            f.unlink()

        print("=" * 60)
        print("  GEM FARM FLOW -- E2E Test")
        print("=" * 60)
        print(f"  Port: {self.port}")
        print(f"  Target mines: {self.count}")
        print()

        try:
            if not self._setup():
                return

            for i in range(1, self.count + 1):
                print(f"\n{'*' * 60}")
                print(f"  *** MINE {i}/{self.count} ***")
                print(f"{'*' * 60}")

                if not self._mine_flow(i):
                    print(f"\n  Mine {i} FAILED")
                    break

                self.mines_completed += 1
                print(f"\n  Mine {i} DONE ({self.mines_completed}/{self.count})")

                if i < self.count:
                    print(f"  Waiting 3s before next mine...")
                    time.sleep(3.0)

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

        # Step 2+3+4: Spiral scan, clicking each icon to verify gem type
        gem = self._step_scan_and_verify_gem(tag)
        if gem is None:
            self._step_return_city(tag)
            return False

        # Step 5: Click "Thu Thap" (gather)
        if not self._step_click_gather(tag):
            return False

        # Step 6: Select troop + click "March"
        if not self._step_click_march(tag):
            return False

        # Mark this gem as gathered
        self.gathered_positions.append(gem.center)
        print(f"  [{INFO}] Marked gem at {gem.center} as gathered ({len(self.gathered_positions)} total)")

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
        time.sleep(0.3)
        print(f"  [{PASS}] ESP32: {self.port}")

        frame = self.sc.grab_full()
        if frame is not None:
            save_screenshot(frame, "setup_initial")

        stats = self.classifier.get_stats()
        if stats["is_warm"]:
            print(f"  [{PASS}] Classifier: {stats['total']} samples (gem={stats['gem']}, not_gem={stats['not_gem']})")
        else:
            print(f"  [{INFO}] Classifier: cold start ({stats['total']}/{10} samples)")

        self._record("setup", True, "OK")
        return True

    # --- Step 1: City view -> world map -> icon zoom ---

    def _step_to_world_map(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 1: City -> World Map -> Zoom out ---\n")

        # Check if already on world map at icon zoom
        frame = self.sc.grab_full()
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
                time.sleep(0.3)
                self._scroll_at_center(-5, ICON_ZOOM_SCROLLS)
                time.sleep(1.0)
                self._record(f"{tag}_world", True, "World map, zoomed out")
                return True

        # From city view -> click world_map_city_btn (bottom-right)
        m = self._find("buttons/world_map_city_btn", threshold=WORLD_MAP_BTN_THRESHOLD)
        if m:
            print(f"  [{PASS}] world_map_city_btn: conf={m.confidence:.3f} at {m.center}")
            self._click_match(m)
            time.sleep(2.0)
        else:
            print(f"  [{WARN}] world_map_city_btn not found, trying bottom-right click...")
            br_x = self.win["left"] + int(self.win["width"] * 0.95)
            br_y = self.win["top"] + int(self.win["height"] * 0.93)
            self._click(br_x, br_y)
            time.sleep(2.0)

        # Verify we're on world map
        city_btn = self._find("buttons/city_btn", threshold=0.75)
        if not city_btn:
            print(f"  [{FAIL}] Not on world map after clicking")
            frame = self.sc.grab_full()
            if frame is not None:
                save_screenshot(frame, f"{tag}_world_fail")
            self._record(f"{tag}_world", False, "World map nav failed")
            return False

        print(f"  [{PASS}] On world map, zooming out {ICON_ZOOM_SCROLLS}x...")

        # Click center for focus, then zoom out exactly 2
        cx, cy = self._center_screen()
        self._click(cx, cy)
        time.sleep(0.3)
        self._scroll_at_center(-5, ICON_ZOOM_SCROLLS)
        time.sleep(1.0)

        # After previous mine: drag camera away to avoid re-finding same mine
        if self.mines_completed > 0:
            ww = self.win["width"]
            margin = 80
            angle = random.choice([(1, 0), (-1, 0), (0, 1), (0, -1),
                                   (1, 1), (-1, -1), (1, -1), (-1, 1)])
            dp = random.uniform(0.7, 1.0)
            sx = cx + int(angle[0] * (ww // 2 - margin) * dp) + random.randint(-20, 20)
            ex = cx - int(angle[0] * (ww // 2 - margin) * dp) + random.randint(-20, 20)
            s_y = cy + int(angle[1] * (ww // 2 - margin) * dp) + random.randint(-20, 20)
            e_y = cy - int(angle[1] * (ww // 2 - margin) * dp) + random.randint(-20, 20)
            sx, s_y = self._clamp_to_window(sx, s_y, pad=40)
            ex, e_y = self._clamp_to_window(ex, e_y, pad=40)
            hx1, hy1 = screen_to_hid(sx, s_y)
            hx2, hy2 = screen_to_hid(ex, e_y)
            self.cmd.send("MOVETO", hx1, hy1)
            time.sleep(random.uniform(0.05, 0.15))
            self.cmd.send("DRAG", 0, 0, hx2 - hx1, hy2 - hy1, random.randint(400, 600), timeout=3.0)
            time.sleep(random.uniform(2.0, 3.2))
            print(f"  [{INFO}] Shifted camera (dir={angle})")

        frame = self.sc.grab_full()
        if frame is not None:
            save_screenshot(frame, f"{tag}_icon_zoom")

        self._record(f"{tag}_world", True, f"City -> world map -> zoom out {ICON_ZOOM_SCROLLS}x")
        return True

    # --- Step 2/3/4: Spiral scan + click icon + verify gem type ---

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
        for m in matches:
            if m.confidence < GEM_ICON_THRESHOLD:
                continue
            ok, zone_info = self._is_clickable_zone(frame, m)
            if not ok:
                print(f"  [ -- ] Zone reject icon at {m.center} conf={m.confidence:.3f}: {zone_info}")
                continue
            is_gem, info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            if not is_gem:
                print(f"  [ -- ] Color reject icon at {m.center} conf={m.confidence:.3f}: {info}")
                continue
            patch = self._extract_icon_patch(frame, m)
            should_click, label, clf_conf = self.classifier.should_click(patch)
            if not should_click:
                print(f"  [ -- ] Classifier reject at {m.center} conf={m.confidence:.3f}: {label} ({clf_conf:.2f})")
                continue
            if label != "unknown":
                print(f"  [{INFO}] Classifier: {label} ({clf_conf:.2f}) at {m.center}")
            result.append(m)
        return sorted(result, key=lambda m: -m.confidence)

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
        """Check for occupation indicators at icon-zoom level (before clicking).

        Detects:
        1. Colored UI overlays near the icon (gathering circles)
        2. March lines converging on the icon (troops en-route)
        """
        fh, fw = frame.shape[:2]

        # ROI: icon area + 1.5x padding for indicators above/below/around
        pad_x = icon.w
        pad_y = int(icon.h * 1.5)
        y1 = max(icon.y - pad_y, 0)
        y2 = min(icon.y + icon.h + pad_y, fh)
        x1 = max(icon.x - pad_x // 2, 0)
        x2 = min(icon.x + icon.w + pad_x // 2, fw)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty"

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        total = hsv.shape[0] * hsv.shape[1]
        sat_bright = (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 100)

        red_mask = sat_bright & ((hsv[:, :, 0] < 10) | (hsv[:, :, 0] > 170))
        blue_mask = sat_bright & (hsv[:, :, 0] >= 85) & (hsv[:, :, 0] <= 130)
        green_mask = sat_bright & (hsv[:, :, 0] >= 50) & (hsv[:, :, 0] <= 84)

        red_pct = np.sum(red_mask) / total * 100
        blue_pct = np.sum(blue_mask) / total * 100
        green_pct = np.sum(green_mask) / total * 100

        info = f"R={red_pct:.1f}% B={blue_pct:.1f}% G={green_pct:.1f}%"
        circle_occupied = (red_pct >= OCCUPY_GREEN_PCT or
                           blue_pct >= OCCUPY_GREEN_PCT)

        if circle_occupied:
            return True, info

        has_line, line_info = self._has_march_line(frame, icon)
        if has_line:
            return True, f"march_line({line_info}) {info}"

        return False, info

    def _is_mine_occupied(self, frame, mine_match: Match) -> tuple[bool, str]:
        """Post-zoom backup: check occupation after zoom-in (wider ROI around mine)."""
        mine_cx, mine_cy = mine_match.center
        h, w = frame.shape[:2]

        pad = max(mine_match.w, mine_match.h)
        y1 = max(mine_cy - pad, 0)
        y2 = min(mine_cy + pad + 60, h)
        x1 = max(mine_cx - pad, 0)
        x2 = min(mine_cx + pad, w)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty ROI"

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        total = hsv.shape[0] * hsv.shape[1]
        sat_bright = (hsv[:, :, 1] > 100) & (hsv[:, :, 2] > 100)

        red_mask = sat_bright & ((hsv[:, :, 0] < 10) | (hsv[:, :, 0] > 170))
        blue_mask = sat_bright & (hsv[:, :, 0] >= 85) & (hsv[:, :, 0] <= 130)
        green_mask = sat_bright & (hsv[:, :, 0] >= 50) & (hsv[:, :, 0] <= 84)

        red_pct = np.sum(red_mask) / total * 100
        blue_pct = np.sum(blue_mask) / total * 100
        green_pct = np.sum(green_mask) / total * 100

        info = f"R={red_pct:.1f}% B={blue_pct:.1f}% G={green_pct:.1f}%"
        occupied = red_pct >= OCCUPY_GREEN_PCT or blue_pct >= OCCUPY_GREEN_PCT
        return occupied, info

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
        time.sleep(2.5)

        frame = self.sc.grab_full()
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
        g = self._find_on_frame(frame, "buttons/gather_btn", threshold=0.70)

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
                time.sleep(0.5)
                return False

            has_line, line_info = self._has_march_line(frame, mine)
            if has_line:
                save_screenshot(frame, f"{tag}_march_line_{attempt:02d}")
                print(f"  [{WARN}] [{attempt}] March line at zoomed mine ({line_info}) -- skipping")
                self._press_escape()
                time.sleep(0.5)
                return False

            is_gem_color, color_info = is_gem_mine_color(frame, mine.x, mine.y, mine.w, mine.h)
            if not is_gem_color:
                save_screenshot(frame, f"{tag}_not_gem_mine_{attempt:02d}")
                print(f"  [{WARN}] [{attempt}] Mine color check failed ({color_info}) -- not gem")
                self._press_escape()
                time.sleep(0.5)
                return False
            print(f"  [{INFO}] [{attempt}] Mine color OK ({color_info})")

        if g and is_gem:
            print(f"  [{PASS}] [{attempt}] Gem mine confirmed + popup open (gather conf={g.confidence:.3f})")
            return True

        if g and not is_gem:
            print(f"  [{WARN}] [{attempt}] Popup open but NOT gem -- dismissing")
            self._press_escape()
            time.sleep(0.5)
            return False

        if is_gem and not g:
            # Popup might be rendering slowly -- re-check before clicking mine again
            time.sleep(1.0)
            frame_recheck = self.sc.grab_full()
            if frame_recheck is not None:
                g_late = self._find_on_frame(frame_recheck, "buttons/gather_btn", threshold=0.65)
                if g_late:
                    print(f"  [{PASS}] [{attempt}] Popup found on re-check (conf={g_late.confidence:.3f})")
                    return True

            # Popup not open -- click mine structure to open it
            print(f"  [{INFO}] [{attempt}] Gem confirmed, clicking mine structure...")
            msx, msy = self._screen_xy(*mine.center)
            self._click(msx, msy)
            time.sleep(2.0)
            frame2 = self.sc.grab_full()
            if frame2 is not None:
                g2 = self._find_on_frame(frame2, "buttons/gather_btn", threshold=0.70)
                if g2:
                    print(f"  [{PASS}] [{attempt}] Popup opened after mine click!")
                    save_screenshot(frame2, f"{tag}_gem_popup_{attempt:02d}")
                    return True
            print(f"  [{WARN}] [{attempt}] Gem confirmed but popup won't open")
            self._press_escape()
            time.sleep(0.5)
            return False

        # Neither gem structure nor popup -- not a gem mine
        print(f"  [{WARN}] [{attempt}] Not a gem mine -- dismissing")
        self._press_escape()
        time.sleep(0.5)
        return False

    def _return_to_icon_zoom(self):
        """After a failed icon click, dismiss and zoom back to icon level."""
        # Click outside to dismiss any leftover popup
        cx, cy = self._center_screen()
        self._click(cx, cy)
        time.sleep(0.5)
        # Zoom out back to icon level
        self._scroll_at_center(-5, ICON_ZOOM_SCROLLS)
        time.sleep(1.0)

    def _step_scan_and_verify_gem(self, tag: str) -> Match | None:
        print(f"\n--- [{tag}] Step 2: Scan + verify gem mines ---\n")

        ww = self.win["width"]
        wh = self.win["height"]
        margin = 80
        cx, cy = self._center_screen()

        all_dirs = [(1, 0), (0, 1), (-1, 0), (0, -1)]
        start_rot = random.randint(0, 3)
        directions = all_dirs[start_rot:] + all_dirs[:start_rot]
        leg = 1
        dir_idx = 0
        turns = 0
        scan_count = 0
        max_scans = 100
        max_attempts = 20
        max_icons_per_frame = 2
        relocate_after = 8
        attempt = 0
        clicked_positions: list[tuple[int, int]] = []
        relocate_dirs = [(1, 1), (-1, -1), (1, -1), (-1, 1)]
        random.shuffle(relocate_dirs)
        relocate_count = 0

        step_x = ww - 2 * margin
        step_y = wh - 2 * margin
        print(f"  [{INFO}] Drag: ~{step_x}x{step_y}px (margin={margin}, rot={start_rot})")

        # Check current frame first
        frame = self.sc.grab_full()
        if frame is not None:
            save_screenshot(frame, f"{tag}_scan_00")
            icons = self._find_all_icons(frame)
            tried_this_frame = 0
            for icon in icons:
                if attempt >= max_attempts or tried_this_frame >= max_icons_per_frame:
                    break
                if any(abs(icon.center[0]-px) < 80 and abs(icon.center[1]-py) < 80
                       for px, py in clicked_positions):
                    continue
                occupied, occ_info = self._check_icon_occupied(frame, icon)
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

        # Spiral scan
        while scan_count < max_scans and attempt < max_attempts:
            dx_u, dy_u = directions[dir_idx % 4]
            for _ in range(leg):
                if scan_count >= max_scans or attempt >= max_attempts:
                    break
                scan_count += 1

                dist_pct = random.uniform(0.78, 1.0)
                jx = random.randint(-30, 30)
                jy = random.randint(-30, 30)
                if dx_u != 0:
                    half = int((ww // 2 - margin) * dist_pct)
                    sx = cx + dx_u * half + jx
                    ex = cx - dx_u * half + jx
                    sy = ey = cy + jy
                else:
                    half = int((wh // 2 - margin) * dist_pct)
                    sx = ex = cx + jx
                    sy = cy + dy_u * half + jy
                    ey = cy - dy_u * half + jy
                sx, sy = self._clamp_to_window(sx, sy, pad=40)
                ex, ey = self._clamp_to_window(ex, ey, pad=40)
                hx1, hy1 = screen_to_hid(sx, sy)
                hx2, hy2 = screen_to_hid(ex, ey)

                self.cmd.send("MOVETO", hx1, hy1)
                time.sleep(random.uniform(0.05, 0.15))
                drag_ms = random.randint(380, 650)
                self.cmd.send("DRAG", 0, 0, hx2 - hx1, hy2 - hy1, drag_ms, timeout=3.0)
                time.sleep(random.uniform(1.8, 3.2))

                if random.random() < 0.12:
                    time.sleep(random.uniform(0.5, 1.5))

                frame = self.sc.grab_full()
                if frame is None:
                    continue

                save_screenshot(frame, f"{tag}_scan_{scan_count:02d}")

                icons = self._find_all_icons(frame)
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
                    occupied, occ_info = self._check_icon_occupied(frame, icon)
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

            dir_idx += 1
            turns += 1
            if turns == 2:
                leg += 1
                turns = 0

            # Relocate camera after N failed attempts to search a new area
            if (attempt > 0 and attempt >= (relocate_count + 1) * relocate_after
                    and relocate_count < len(relocate_dirs)):
                rd = relocate_dirs[relocate_count]
                relocate_count += 1
                rp = random.uniform(0.75, 1.0)
                drag_sx = cx + int(rd[0] * (ww // 2 - margin) * rp) + random.randint(-25, 25)
                drag_sy = cy + int(rd[1] * (wh // 2 - margin) * rp) + random.randint(-25, 25)
                drag_ex = cx - int(rd[0] * (ww // 2 - margin) * rp) + random.randint(-25, 25)
                drag_ey = cy - int(rd[1] * (wh // 2 - margin) * rp) + random.randint(-25, 25)
                drag_sx, drag_sy = self._clamp_to_window(drag_sx, drag_sy, pad=40)
                drag_ex, drag_ey = self._clamp_to_window(drag_ex, drag_ey, pad=40)
                hx1, hy1 = screen_to_hid(drag_sx, drag_sy)
                hx2, hy2 = screen_to_hid(drag_ex, drag_ey)
                self.cmd.send("MOVETO", hx1, hy1)
                time.sleep(random.uniform(0.05, 0.15))
                self.cmd.send("DRAG", 0, 0, hx2 - hx1, hy2 - hy1, random.randint(450, 700), timeout=3.0)
                time.sleep(random.uniform(2.0, 3.5))
                print(f"  [{INFO}] Relocated camera (attempt {attempt}, direction {rd})")
                leg = 1
                dir_idx = 0
                turns = 0

        print(f"  [{FAIL}] No gem mine after {scan_count} scans, {attempt} icons checked")
        self._record(f"{tag}_find", False, f"{attempt} icons checked, none were gem")
        return None

    # --- Step: Click gather button ---

    def _step_click_gather(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 5: Click Gather ---\n")

        for attempt in range(5):
            m = self._find("buttons/gather_btn", threshold=BUTTON_THRESHOLD)
            if m:
                print(f"  [{PASS}] gather_btn: conf={m.confidence:.3f}")
                save_annotated(self.sc.grab_full(), m, f"{tag}_gather_found")

                if self._click_match(m):
                    print(f"  [{PASS}] Gather clicked!")
                    time.sleep(VERIFY_DELAY)
                    frame = self.sc.grab_full()
                    if frame is not None:
                        save_screenshot(frame, f"{tag}_after_gather")
                    self._record(f"{tag}_gather", True, f"conf={m.confidence:.3f}")
                    return True

            print(f"  [{INFO}] gather_btn not found (attempt {attempt+1}/5)")
            time.sleep(1.0)

        print(f"  [{FAIL}] gather_btn not found")
        self._record(f"{tag}_gather", False, "Not found")
        return False

    # --- Step: Click march ---

    def _step_click_march(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 6: Troop + March ---\n")

        selected_new_troop = False

        for attempt in range(5):
            # Try march buttons first
            for march_tpl in MARCH_TEMPLATES:
                m = self._find(march_tpl, threshold=BUTTON_THRESHOLD)
                if m:
                    print(f"  [{PASS}] {march_tpl}: conf={m.confidence:.3f}")
                    if self._click_match(m):
                        print(f"  [{PASS}] March clicked!")
                        time.sleep(VERIFY_DELAY * 2)
                        frame = self.sc.grab_full()
                        if frame is not None:
                            save_screenshot(frame, f"{tag}_after_march")
                        self._record(f"{tag}_march", True, march_tpl)
                        return True

            # Try "New Troop" button (troop selection panel)
            if not selected_new_troop:
                m = self._find("buttons/new_troop_btn", threshold=BUTTON_THRESHOLD)
                if m:
                    print(f"  [{PASS}] new_troop_btn: conf={m.confidence:.3f}")
                    if self._click_match(m):
                        selected_new_troop = True
                        print(f"  [{PASS}] New troop selected")
                        time.sleep(VERIFY_DELAY)
                        continue

            print(f"  [{INFO}] March not found (attempt {attempt+1}/5)")
            time.sleep(1.0)

        print(f"  [{FAIL}] March button not found")
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
            time.sleep(2.0)
        else:
            # Fallback: Escape twice to dismiss overlays
            self._press_escape()
            time.sleep(0.8)
            self._press_escape()
            time.sleep(1.0)

        frame = self.sc.grab_full()
        if frame is not None:
            save_screenshot(frame, f"{tag}_return_city")

        self._record(f"{tag}_return", True, "Returned to city")

    # --- Helpers ---

    def _record(self, step: str, ok: bool, note: str):
        self.results.append({"step": step, "success": ok, "note": note})

    def _teardown(self):
        print("\n--- Teardown ---")
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
