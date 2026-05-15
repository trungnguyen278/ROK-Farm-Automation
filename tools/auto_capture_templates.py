"""
Auto-capture all missing state templates.
Requires: game open at city view, ESP32 connected.

Usage: python -m tools.auto_capture_templates [COM_PORT]

This script:
1. Connects to ESP32
2. Captures game window
3. Uses existing button templates to locate UI elements
4. Navigates to each screen via ESP32 HID clicks
5. Crops distinctive regions as state templates
6. Verifies each template matches with high confidence
7. Saves to templates/ directory
"""
import sys
import os
import time
import logging
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

from capture.screen_capture import ScreenCapture
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(message)s",
)
logger = logging.getLogger("auto_capture")

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
SKIP = "\033[96mSKIP\033[0m"

TEMPLATE_DIR = Path("templates")
SCREENSHOT_DIR = Path("tools/screenshots/auto_capture")


class AutoCapture:
    def __init__(self, port: str):
        self.port = port
        self.sc: ScreenCapture | None = None
        self.cache: TemplateCache | None = None
        self.matcher: TemplateMatcher | None = None
        self.conn = None
        self.buf = None
        self.win_w = 0
        self.win_h = 0
        self.win_left = 0
        self.win_top = 0
        self.results: dict[str, str] = {}

    def run(self):
        print("=" * 60)
        print("  Auto Template Capture")
        print("=" * 60)
        print()

        if not self._setup():
            return

        self._capture_world_map()
        self._capture_alliance_screen()
        self._capture_march_screen()
        self._capture_commander_select()
        self._capture_popups()

        self._ensure_city_view()
        self._teardown()
        self._print_report()

    def _setup(self) -> bool:
        print("--- Setup ---")

        self.sc = ScreenCapture()
        win = self.sc.find_window()
        if not win:
            print(f"  [{FAIL}] Game window not found. Open Rise of Kingdoms first.")
            return False
        self.win_left = win["left"]
        self.win_top = win["top"]
        self.win_w = win["width"]
        self.win_h = win["height"]
        print(f"  [{PASS}] Game window: {self.win_w}x{self.win_h} at ({self.win_left},{self.win_top})")

        self.cache = TemplateCache(str(TEMPLATE_DIR))
        self.matcher = TemplateMatcher(self.cache, threshold=0.5, scales=[0.8, 0.9, 1.0, 1.1, 1.2])

        frame = self.sc.grab_full()
        if frame is None:
            print(f"  [{FAIL}] Cannot capture game screen")
            return False
        print(f"  [{PASS}] Screen capture OK ({frame.shape[1]}x{frame.shape[0]})")

        SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

        from serial_comm.connection import SerialConnection
        from serial_comm.command_buffer import CommandBuffer

        self.conn = SerialConnection(port=self.port)
        if not self.conn.connect():
            print(f"  [{FAIL}] Cannot connect to ESP32 at {self.port}")
            return False

        self.buf = CommandBuffer(self.conn)
        self.buf.start()
        time.sleep(0.3)
        print(f"  [{PASS}] ESP32 connected: {self.port}")
        print()
        return True

    def _grab(self) -> np.ndarray | None:
        for _ in range(3):
            frame = self.sc.grab_full()
            if frame is not None:
                return frame
            time.sleep(0.3)
        return None

    def _find_button(self, frame: np.ndarray, btn_name: str):
        return self.matcher.match_single(frame, f"buttons/{btn_name}")

    def _to_screen(self, frame_x: int, frame_y: int) -> tuple[int, int]:
        return frame_x + self.win_left, frame_y + self.win_top

    def _click_at(self, x: int, y: int, delay_after: float = 1.5):
        sx, sy = self._to_screen(x, y)
        logger.info("Click frame(%d,%d) -> screen(%d,%d)", x, y, sx, sy)
        self.buf.send("MOVE", sx, sy, 200)
        time.sleep(0.05)
        self.buf.send("CLICK", "L", 80)
        time.sleep(delay_after)

    def _click_button(self, frame: np.ndarray, btn_name: str, delay_after: float = 2.0) -> bool:
        match = self._find_button(frame, btn_name)
        if not match:
            logger.warning("Button '%s' not found", btn_name)
            return False
        cx, cy = match.center
        logger.info("Clicking %s at (%d, %d) conf=%.3f", btn_name, cx, cy, match.confidence)
        self._click_at(cx, cy, delay_after)
        return True

    def _save_template(self, name: str, crop: np.ndarray) -> bool:
        out_path = TEMPLATE_DIR / f"{name}.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), crop)
        logger.info("Saved template: %s (%dx%d)", out_path, crop.shape[1], crop.shape[0])
        return True

    def _save_screenshot(self, label: str, frame: np.ndarray):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = SCREENSHOT_DIR / f"{ts}_{label}.png"
        cv2.imwrite(str(path), frame)

    def _verify_template(self, frame: np.ndarray, template_name: str) -> float:
        self.cache._missing.discard(template_name)
        if template_name in self.cache._cache:
            del self.cache._cache[template_name]

        match = self.matcher.match_single(frame, template_name)
        if match:
            return match.confidence
        return 0.0

    def _crop_bottom_bar(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        y1 = int(h * 0.88)
        y2 = h
        x1 = int(w * 0.15)
        x2 = int(w * 0.85)
        return frame[y1:y2, x1:x2]

    def _crop_top_area(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        y1 = 0
        y2 = int(h * 0.08)
        x1 = int(w * 0.2)
        x2 = int(w * 0.8)
        return frame[y1:y2, x1:x2]

    def _crop_center_header(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        y1 = int(h * 0.12)
        y2 = int(h * 0.22)
        x1 = int(w * 0.25)
        x2 = int(w * 0.75)
        return frame[y1:y2, x1:x2]

    def _crop_popup_header(self, frame: np.ndarray) -> np.ndarray:
        h, w = frame.shape[:2]
        y1 = int(h * 0.18)
        y2 = int(h * 0.30)
        x1 = int(w * 0.28)
        x2 = int(w * 0.72)
        return frame[y1:y2, x1:x2]

    def _press_back(self, delay: float = 1.5):
        frame = self._grab()
        if frame is None:
            self.buf.send("KEY", "Escape")
            time.sleep(delay)
            return

        h, w = frame.shape[:2]
        back_x = int(w * 0.03)
        back_y = int(h * 0.05)
        self._click_at(back_x, back_y, delay)

    def _ensure_city_view(self):
        for _ in range(3):
            frame = self._grab()
            if frame is None:
                break
            m = self.matcher.match_single(frame, "states/city_view")
            if m and m.confidence > 0.8:
                return
            if self._click_button(frame, "city_btn", 2.0):
                continue
            self._press_back(1.5)

    # ---- Screen captures ----

    def _navigate_to_world_map(self, frame: np.ndarray) -> bool:
        h, w = frame.shape[:2]
        center_sx, center_sy = self._to_screen(int(w * 0.5), int(h * 0.5))

        minimap_x = int(w * 0.93)
        minimap_y = int(h * 0.88)
        logger.info("Clicking minimap at frame(%d,%d) to enter world map", minimap_x, minimap_y)
        self._click_at(minimap_x, minimap_y, 2.0)

        for _ in range(3):
            self.buf.send("SCROLL", center_sx, center_sy, -5)
            time.sleep(0.8)

        time.sleep(1.5)

        check = self._grab()
        if check is not None:
            city_m = self.matcher.match_single(check, "states/city_view")
            if city_m and city_m.confidence > 0.8:
                logger.info("Still at city view, trying zoom out more")
                for _ in range(5):
                    self.buf.send("SCROLL", center_sx, center_sy, -5)
                    time.sleep(0.5)
                time.sleep(2.0)
        return True

    def _capture_world_map(self):
        name = "states/world_map"
        print(f"--- Capturing: {name} ---")

        if (TEMPLATE_DIR / f"{name}.png").exists():
            frame = self._grab()
            if frame:
                conf = self._verify_template(frame, name)
                if conf > 0.5:
                    print(f"  [{SKIP}] Already exists (verifiable)")
                    self.results[name] = f"SKIP (exists)"
                    return

        self._ensure_city_view()
        frame = self._grab()
        if frame is None:
            print(f"  [{FAIL}] Cannot capture screen")
            self.results[name] = "FAIL (no frame)"
            return

        self._navigate_to_world_map(frame)

        time.sleep(1.0)
        frame = self._grab()
        if frame is None:
            print(f"  [{FAIL}] Cannot capture after navigation")
            self.results[name] = "FAIL (no frame)"
            return

        self._save_screenshot("world_map_full", frame)

        city_m = self.matcher.match_single(frame, "states/city_view")
        if city_m and city_m.confidence > 0.8:
            print(f"  [{WARN}] Still at city view (conf={city_m.confidence:.3f}), trying alternative nav")
            h, w = frame.shape[:2]
            self._click_at(int(w * 0.5), int(h * 0.3), 1.0)
            cx, cy = self._to_screen(int(w * 0.5), int(h * 0.5))
            for _ in range(8):
                self.buf.send("SCROLL", cx, cy, -5)
                time.sleep(0.4)
            time.sleep(2.0)
            frame = self._grab()
            if frame is None:
                self.results[name] = "FAIL (no frame)"
                return
            self._save_screenshot("world_map_full_retry", frame)

        crop = self._crop_bottom_bar(frame)
        self._save_template(name, crop)

        conf = self._verify_template(frame, name)
        if conf >= 0.8:
            print(f"  [{PASS}] world_map template saved (conf={conf:.3f})")
            self.results[name] = f"PASS (conf={conf:.3f})"
        elif conf >= 0.5:
            print(f"  [{WARN}] world_map saved but low confidence ({conf:.3f})")
            self.results[name] = f"WARN (conf={conf:.3f})"
            self._try_alternate_crops(frame, name)
        else:
            print(f"  [{WARN}] world_map verify failed, trying alternate crops")
            self._try_alternate_crops(frame, name)

    def _capture_alliance_screen(self):
        name = "states/alliance_screen"
        print(f"\n--- Capturing: {name} ---")

        if (TEMPLATE_DIR / f"{name}.png").exists():
            print(f"  [{SKIP}] Already exists")
            self.results[name] = "SKIP (exists)"
            return

        self._ensure_city_view()
        frame = self._grab()
        if frame is None:
            print(f"  [{FAIL}] Cannot capture screen")
            self.results[name] = "FAIL (no frame)"
            return

        h, w = frame.shape[:2]

        flag_match = self._find_button(frame, "flag")
        if flag_match:
            self._click_at(flag_match.center[0], flag_match.center[1], 2.5)
        else:
            alliance_x = int(w * 0.17)
            alliance_y = int(h * 0.78)
            self._click_at(alliance_x, alliance_y, 2.5)

        time.sleep(1.0)
        frame = self._grab()
        if frame is None:
            print(f"  [{FAIL}] Cannot capture after navigation")
            self.results[name] = "FAIL (no frame)"
            return

        self._save_screenshot("alliance_full", frame)

        crop = self._crop_center_header(frame)
        self._save_template(name, crop)

        conf = self._verify_template(frame, name)
        if conf >= 0.8:
            print(f"  [{PASS}] alliance_screen saved (conf={conf:.3f})")
            self.results[name] = f"PASS (conf={conf:.3f})"
        else:
            print(f"  [{WARN}] alliance_screen conf={conf:.3f}, trying alternate crops")
            self._try_alternate_crops(frame, name)

        self._press_back(1.5)

    def _capture_march_screen(self):
        name = "states/march_screen"
        print(f"\n--- Capturing: {name} ---")

        if (TEMPLATE_DIR / f"{name}.png").exists():
            print(f"  [{SKIP}] Already exists")
            self.results[name] = "SKIP (exists)"
            return

        self._ensure_city_view()
        frame = self._grab()
        if frame is None:
            print(f"  [{FAIL}] Cannot capture screen")
            self.results[name] = "FAIL (no frame)"
            return

        self._navigate_to_world_map(frame)

        time.sleep(1.0)
        frame = self._grab()
        if frame is None:
            self.results[name] = "FAIL (no frame)"
            return

        self._save_screenshot("world_map_for_march", frame)

        h, w = frame.shape[:2]
        center_x = int(w * 0.45)
        center_y = int(h * 0.45)
        self._click_at(center_x, center_y, 2.0)

        frame = self._grab()
        if frame is not None:
            self._save_screenshot("clicked_on_map", frame)

        attack_positions = [
            (0.70, 0.75),
            (0.65, 0.80),
            (0.75, 0.70),
        ]
        for ax, ay in attack_positions:
            frame = self._grab()
            if frame is None:
                continue
            h, w = frame.shape[:2]
            self._click_at(int(w * ax), int(h * ay), 2.0)
            frame = self._grab()
            if frame is not None:
                self._save_screenshot("march_btn_attempt", frame)
                city_m = self.matcher.match_single(frame, "states/city_view")
                if not city_m or city_m.confidence < 0.7:
                    break

        frame = self._grab()
        self._save_screenshot("march_screen_attempt", frame)

        if frame is not None:
            crop = self._crop_center_header(frame)
            self._save_template(name, crop)
            conf = self._verify_template(frame, name)
            if conf >= 0.8:
                print(f"  [{PASS}] march_screen saved (conf={conf:.3f})")
                self.results[name] = f"PASS (conf={conf:.3f})"
            else:
                print(f"  [{WARN}] march_screen conf={conf:.3f} - may need re-capture later")
                self.results[name] = f"WARN (conf={conf:.3f})"
                self._try_alternate_crops(frame, name)
        else:
            self.results[name] = "FAIL (no frame)"

        self._press_back(1.0)
        self._press_back(1.0)
        self._press_back(1.0)
        self._ensure_city_view()

    def _capture_commander_select(self):
        name = "states/commander_select"
        print(f"\n--- Capturing: {name} ---")

        if (TEMPLATE_DIR / f"{name}.png").exists():
            print(f"  [{SKIP}] Already exists")
            self.results[name] = "SKIP (exists)"
            return

        self._ensure_city_view()
        frame = self._grab()
        if frame is None:
            print(f"  [{FAIL}] Cannot capture screen")
            self.results[name] = "FAIL (no frame)"
            return

        if not self._click_button(frame, "commander_btn", 2.5):
            print(f"  [{WARN}] commander_btn not found, trying P key position")
            h, w = frame.shape[:2]
            cmd_x = int(w * 0.82)
            cmd_y = int(h * 0.95)
            self._click_at(cmd_x, cmd_y, 2.5)

        time.sleep(1.0)
        frame = self._grab()
        if frame is None:
            self.results[name] = "FAIL (no frame)"
            return

        self._save_screenshot("commander_select_full", frame)

        crop = self._crop_center_header(frame)
        self._save_template(name, crop)

        conf = self._verify_template(frame, name)
        if conf >= 0.8:
            print(f"  [{PASS}] commander_select saved (conf={conf:.3f})")
            self.results[name] = f"PASS (conf={conf:.3f})"
        else:
            print(f"  [{WARN}] commander_select conf={conf:.3f}, trying alternate crops")
            self._try_alternate_crops(frame, name)

        self._press_back(1.5)

    def _capture_popups(self):
        for popup_name in ["popups/march_confirm", "popups/scout_report"]:
            print(f"\n--- Capturing: {popup_name} ---")
            if (TEMPLATE_DIR / f"{popup_name}.png").exists():
                print(f"  [{SKIP}] Already exists")
                self.results[popup_name] = "SKIP (exists)"
                continue

            print(f"  [{WARN}] Popups require in-game triggers (march confirm, scout)")
            print(f"         Will capture during live farm run if popup appears")
            self.results[popup_name] = "DEFERRED (needs game trigger)"

    def _try_alternate_crops(self, frame: np.ndarray, name: str):
        h, w = frame.shape[:2]

        crops = {
            "top": frame[0:int(h*0.10), int(w*0.1):int(w*0.9)],
            "bottom_bar": self._crop_bottom_bar(frame),
            "top_center": self._crop_top_area(frame),
            "header": self._crop_center_header(frame),
            "left_strip": frame[int(h*0.3):int(h*0.7), 0:int(w*0.12)],
        }

        best_conf = 0.0
        best_crop_name = ""

        for crop_name, crop in crops.items():
            if crop.size == 0 or crop.shape[0] < 10 or crop.shape[1] < 10:
                continue
            self._save_template(name, crop)
            conf = self._verify_template(frame, name)
            if conf > best_conf:
                best_conf = conf
                best_crop_name = crop_name

        if best_conf > 0 and best_crop_name:
            self._save_template(name, crops[best_crop_name])
            conf = self._verify_template(frame, name)
            print(f"  Best crop: '{best_crop_name}' conf={conf:.3f}")
            self.results[name] = f"AUTO ({best_crop_name}, conf={conf:.3f})"
        else:
            print(f"  [{FAIL}] No good crop found")
            self.results[name] = "FAIL (no good crop)"

    def _teardown(self):
        if self.buf:
            self.buf.stop()
        if self.conn:
            self.conn.disconnect()
        if self.sc:
            self.sc.close()

    def _print_report(self):
        print("\n" + "=" * 60)
        print("  TEMPLATE CAPTURE REPORT")
        print("=" * 60)
        for name, result in self.results.items():
            status = PASS if "PASS" in result else (WARN if "WARN" in result or "AUTO" in result else (SKIP if "SKIP" in result or "DEFER" in result else FAIL))
            print(f"  {status} {name:30s} {result}")

        existing = []
        missing = []
        all_templates = [
            "states/city_view", "states/world_map", "states/march_screen",
            "states/alliance_screen", "states/commander_select",
            "popups/march_confirm", "popups/scout_report",
        ]
        for t in all_templates:
            if (TEMPLATE_DIR / f"{t}.png").exists():
                existing.append(t)
            else:
                missing.append(t)

        print(f"\n  Templates: {len(existing)}/{len(all_templates)} present")
        if missing:
            print(f"  Missing: {', '.join(missing)}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Auto-capture game templates")
    parser.add_argument("port", nargs="?", default="COM27", help="ESP32 COM port (default: COM27)")
    args = parser.parse_args()

    app = AutoCapture(args.port)
    app.run()


if __name__ == "__main__":
    main()
