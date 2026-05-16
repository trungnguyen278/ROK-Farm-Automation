"""
Gem Mine Detection Tool — capture current screen and test gem template matching
at multiple zoom levels.

Run: .venv\Scripts\python -m tools.detect_gem_mine [--port COM27] [--capture-template]

Modes:
  (default)            Detect gem mines on current screen, show all matches
  --capture-template   Crop the best match region and save as a new template
  --zoom-test          Zoom out step by step, test detection at each level
"""

import sys
import os
import time
import argparse
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.screen_capture import ScreenCapture
from capture.screen_info import screen_to_hid, get_screen_resolution
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher

SCREENSHOT_DIR = Path("tools/screenshots/gem_detect")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"
INFO = "\033[94mINFO\033[0m"

GEM_TEMPLATES = [
    "resources/gem_mine_close",
    "resources/gem_mine_red",
    "resources/gem_mine",
]


def save_annotated(frame, matches, name):
    annotated = frame.copy()
    for m in matches:
        cv2.rectangle(annotated, (m.x, m.y), (m.x + m.w, m.y + m.h), (0, 255, 0), 2)
        cv2.circle(annotated, m.center, 5, (0, 0, 255), -1)
        cv2.putText(annotated, f"{m.name} ({m.confidence:.3f})",
                    (m.x, m.y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
    ts = datetime.now().strftime("%H%M%S")
    path = SCREENSHOT_DIR / f"{name}_{ts}.png"
    cv2.imwrite(str(path), annotated)
    print(f"  [{INFO}] Saved: {path}")
    return str(path)


def detect_on_frame(matcher, frame, label="current"):
    """Try all gem templates on a frame, print results."""
    print(f"\n  --- Detection at zoom: {label} ---")
    h, w = frame.shape[:2]
    print(f"  [{INFO}] Frame size: {w}x{h}")

    all_matches = []
    for tpl_name in GEM_TEMPLATES:
        match = matcher.match_single(frame, tpl_name)
        if match is None:
            print(f"  [ -- ] {tpl_name:30s}: not found")
            continue

        # Play area check
        x, y = match.center
        in_play = (int(w * 0.10) <= x <= int(w * 0.92) and
                   int(h * 0.08) <= y <= int(h * 0.86))

        status = PASS if match.confidence >= 0.70 else WARN
        area_tag = "play-area" if in_play else "UI-zone"
        print(f"  [{status}] {tpl_name:30s}: conf={match.confidence:.3f} "
              f"center=({x},{y}) size=({match.w}x{match.h}) [{area_tag}]")
        all_matches.append(match)

    if all_matches:
        save_annotated(frame, all_matches, f"detect_{label}")
    else:
        ts = datetime.now().strftime("%H%M%S")
        path = SCREENSHOT_DIR / f"detect_{label}_none_{ts}.png"
        cv2.imwrite(str(path), frame)
        print(f"  [{WARN}] No matches. Raw frame saved: {path}")

    return all_matches


def main():
    parser = argparse.ArgumentParser(description="Gem Mine Detection Tool")
    parser.add_argument("--port", default=None, help="ESP32 COM port (needed for --zoom-test)")
    parser.add_argument("--capture-template", action="store_true",
                        help="Capture best match region as new template")
    parser.add_argument("--zoom-test", action="store_true",
                        help="Test detection at multiple zoom levels (needs ESP32)")
    args = parser.parse_args()

    print("=" * 60)
    print("  GEM MINE DETECTION TOOL")
    print("=" * 60)

    # Setup vision
    sc = ScreenCapture()
    win = sc.find_window()
    if not win:
        print(f"  [{FAIL}] Game window not found")
        return
    print(f"  [{PASS}] Window: {win['width']}x{win['height']} at ({win['left']},{win['top']})")

    res_w, res_h = get_screen_resolution()
    print(f"  [{INFO}] Screen: {res_w}x{res_h}")

    cache = TemplateCache("templates")
    matcher = TemplateMatcher(cache, threshold=0.50)  # low threshold to see all matches

    # Show loaded template sizes
    for tpl_name in GEM_TEMPLATES:
        img = cache.get(tpl_name)
        if img is not None:
            print(f"  [{INFO}] Template {tpl_name}: {img.shape[1]}x{img.shape[0]}px")
        else:
            print(f"  [{WARN}] Template {tpl_name}: MISSING")

    # Detect at current zoom
    frame = sc.grab_full()
    if frame is None:
        print(f"  [{FAIL}] Cannot capture screen")
        return

    matches = detect_on_frame(matcher, frame, "current")

    # Capture template mode
    if args.capture_template and matches:
        best = max(matches, key=lambda m: m.confidence)
        print(f"\n  Capturing template from best match: {best.name} conf={best.confidence:.3f}")

        # Crop with padding
        pad = 10
        x1 = max(0, best.x - pad)
        y1 = max(0, best.y - pad)
        x2 = min(frame.shape[1], best.x + best.w + pad)
        y2 = min(frame.shape[0], best.y + best.h + pad)
        crop = frame[y1:y2, x1:x2]

        ts = datetime.now().strftime("%H%M%S")
        crop_path = SCREENSHOT_DIR / f"gem_template_crop_{ts}.png"
        cv2.imwrite(str(crop_path), crop)
        print(f"  [{PASS}] Template crop saved: {crop_path}")
        print(f"  [{INFO}] Size: {crop.shape[1]}x{crop.shape[0]}px")
        print(f"  [{INFO}] To use: copy to templates/resources/gem_mine_close.png")

    # Zoom test mode
    if args.zoom_test:
        if args.port is None:
            print(f"\n  [{FAIL}] --zoom-test requires --port (ESP32 needed for scroll)")
            return

        from serial_comm.connection import SerialConnection
        from serial_comm.command_buffer import CommandBuffer

        conn = SerialConnection(port=args.port)
        if not conn.connect():
            print(f"  [{FAIL}] Cannot connect to ESP32")
            return

        cmd = CommandBuffer(conn)
        cmd.start()
        time.sleep(0.3)

        # Click center of window first (focus game)
        cx = win["left"] + win["width"] // 2
        cy = win["top"] + win["height"] // 2
        hid_cx, hid_cy = screen_to_hid(cx, cy)
        cmd.send("MOVETO", hid_cx, hid_cy)
        time.sleep(0.1)
        cmd.send("CLICK", "L", 50)
        time.sleep(0.5)

        # Test zoom out levels: 1, 2, 3, 5, 8 scroll-out steps
        zoom_levels = [1, 2, 3, 5, 8]
        cumulative = 0

        for steps in zoom_levels:
            delta = steps - cumulative
            if delta > 0:
                for _ in range(delta):
                    cmd.send("SCROLL", -5)
                    time.sleep(0.15)
                cumulative = steps
                time.sleep(1.5)

            frame = sc.grab_full()
            if frame is not None:
                detect_on_frame(matcher, frame, f"zoom_out_{steps}")

        # Zoom back in to original
        print(f"\n  [{INFO}] Zooming back in {cumulative} steps...")
        for _ in range(cumulative):
            cmd.send("SCROLL", 5)
            time.sleep(0.15)
        time.sleep(1.0)

        cmd.send("RESET")
        cmd.stop()
        conn.disconnect()

    sc.close()
    print(f"\n  Screenshots: {SCREENSHOT_DIR}")


if __name__ == "__main__":
    main()
