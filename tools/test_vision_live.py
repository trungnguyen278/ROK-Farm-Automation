"""
Phase 6 — Live Vision Pipeline Test
Captures game window in real-time, runs state detection, shows result overlay.
Run: python -m tools.test_vision_live

Controls:
  q / ESC  — quit
  s        — save current frame as screenshot
  d        — toggle debug overlay (match rectangles + confidence)
  t        — run template scan on current frame (all templates)
  SPACE    — pause/resume capture

Output:
  - Console: detected state, confidence, FPS
  - Window: game frame with detection overlay
  - Screenshots saved to tools/screenshots/
"""
import sys
import os
import time
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

from capture.screen_capture import ScreenCapture
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from vision.state_detector import StateDetector, GameScreen, SCREEN_TEMPLATES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_vision_live")

SCREENSHOT_DIR = Path("tools/screenshots")

STATE_COLORS = {
    GameScreen.UNKNOWN: (128, 128, 128),
    GameScreen.CITY_VIEW: (0, 255, 0),
    GameScreen.WORLD_MAP: (255, 200, 0),
    GameScreen.MARCH_SCREEN: (0, 100, 255),
    GameScreen.POPUP_DIALOG: (0, 255, 255),
    GameScreen.COMMANDER_SELECT: (255, 0, 255),
    GameScreen.ALLIANCE_SCREEN: (255, 128, 0),
}


def draw_overlay(frame: np.ndarray, state: GameScreen, match, fps: float,
                 debug: bool, frame_count: int) -> np.ndarray:
    overlay = frame.copy()
    h, w = overlay.shape[:2]

    color = STATE_COLORS.get(state, (255, 255, 255))

    cv2.rectangle(overlay, (0, 0), (w, 40), (0, 0, 0), -1)

    state_text = f"State: {state.value}"
    cv2.putText(overlay, state_text, (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

    conf_text = f"Conf: {match.confidence:.3f}" if match else "Conf: N/A"
    cv2.putText(overlay, conf_text, (300, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    fps_text = f"FPS: {fps:.1f}"
    cv2.putText(overlay, fps_text, (550, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2)

    frame_text = f"#{frame_count}"
    cv2.putText(overlay, frame_text, (w - 120, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1)

    if debug and match:
        x, y, mw, mh = match.x, match.y, match.w, match.h
        cv2.rectangle(overlay, (x, y + 40), (x + mw, y + mh + 40), color, 2)
        label = f"{match.name} ({match.confidence:.2f})"
        cv2.putText(overlay, label, (x, y + 35), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    return overlay


def scan_all_templates(frame: np.ndarray, matcher: TemplateMatcher):
    print("\n  --- Full Template Scan ---")
    for screen, templates in SCREEN_TEMPLATES.items():
        match = matcher.match_best(frame, templates)
        if match:
            print(f"    {screen.value:20s}  conf={match.confidence:.3f}  "
                  f"at=({match.x},{match.y})  template={match.name}")
        else:
            print(f"    {screen.value:20s}  no match")
    print()


def save_screenshot(frame: np.ndarray, state: GameScreen):
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = SCREENSHOT_DIR / f"{ts}_{state.value}.png"
    cv2.imwrite(str(filename), frame)
    print(f"  Screenshot saved: {filename}")


def main():
    print("=" * 60)
    print("  Live Vision Pipeline Test — Phase 6")
    print("=" * 60)

    sc = ScreenCapture()
    print("\n  Looking for game window...")
    win = sc.find_window()
    if not win:
        print("  Game window not found. Make sure Rise of Kingdoms is running.")
        print("  Tip: Window title must contain 'Rise of Kingdoms'")
        return

    print(f"  Found: {win['width']}x{win['height']} at ({win['left']},{win['top']})")

    templates_dir = Path("templates")
    if not templates_dir.exists():
        print(f"  Templates directory not found: {templates_dir}")
        return

    cache = TemplateCache(str(templates_dir))
    matcher = TemplateMatcher(cache, threshold=0.8)
    detector = StateDetector(matcher, min_confidence=0.8)

    template_count = 0
    for screen, tpls in SCREEN_TEMPLATES.items():
        for t in tpls:
            if cache.get(t) is not None:
                template_count += 1
    print(f"  Templates loaded: {template_count}")

    print("\n  Controls: q=quit  s=screenshot  d=debug  t=template_scan  SPACE=pause")
    print("  Starting capture...\n")

    paused = False
    debug = True
    frame_count = 0
    fps = 0.0
    fps_frames = 0
    fps_start = time.monotonic()
    last_state = GameScreen.UNKNOWN
    state_change_count = 0

    while True:
        if not paused:
            frame = sc.grab_full()
            if frame is None:
                time.sleep(0.5)
                continue

            frame_count += 1
            fps_frames += 1

            now = time.monotonic()
            dt = now - fps_start
            if dt >= 1.0:
                fps = fps_frames / dt
                fps_frames = 0
                fps_start = now

            state, match = detector.detect_with_match(frame)

            if state != last_state:
                state_change_count += 1
                conf_str = f"{match.confidence:.3f}" if match else "N/A"
                print(f"  State change #{state_change_count}: {last_state.value} -> {state.value} "
                      f"(conf={conf_str})")
                last_state = state

            display = draw_overlay(frame, state, match, fps, debug, frame_count)

            scale = min(1.0, 1280 / display.shape[1], 720 / display.shape[0])
            if scale < 1.0:
                display = cv2.resize(display, None, fx=scale, fy=scale)

            cv2.imshow("Vision Pipeline Test", display)

        key = cv2.waitKey(33) & 0xFF

        if key in (ord('q'), 27):  # q or ESC
            break
        elif key == ord('s'):
            if frame is not None:
                save_screenshot(frame, last_state)
        elif key == ord('d'):
            debug = not debug
            print(f"  Debug overlay: {'ON' if debug else 'OFF'}")
        elif key == ord('t'):
            if frame is not None:
                scan_all_templates(frame, matcher)
        elif key == ord(' '):
            paused = not paused
            print(f"  {'PAUSED' if paused else 'RESUMED'}")

    cv2.destroyAllWindows()
    sc.close()

    print(f"\n  Session summary:")
    print(f"    Frames captured: {frame_count}")
    print(f"    State changes: {state_change_count}")
    print(f"    Final state: {last_state.value}")
    print(f"    Avg FPS: {fps:.1f}")


if __name__ == "__main__":
    main()
