"""
Quick recovery: close current panel, go to city, then navigate to world map
and capture a fresh gem mine template with proper zoom level.

Run: .venv\\Scripts\\python tools/recover_and_recapture.py
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from pathlib import Path
from capture.screen_capture import ScreenCapture
from capture.screen_info import screen_to_hid, get_screen_resolution
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from vision.state_detector import StateDetector, GameScreen
from serial_comm.connection import SerialConnection
from serial_comm.command_buffer import CommandBuffer

SCREENSHOT_DIR = Path("tools/screenshots/recapture")
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

def main():
    sc = ScreenCapture()
    win = sc.find_window()
    if not win:
        print("Game window not found!")
        return
    print(f"Window: {win['width']}x{win['height']} at ({win['left']},{win['top']})")

    conn = SerialConnection(port="COM27")
    if not conn.connect():
        print("ESP32 not connected!")
        return
    print("ESP32 connected")

    cmd = CommandBuffer(conn)
    cmd.start()
    time.sleep(0.3)

    cache = TemplateCache("templates")
    matcher = TemplateMatcher(cache, threshold=0.65)
    detector = StateDetector(matcher, min_confidence=0.8)

    # Step 1: Close any open panel — press Escape multiple times
    print("\n1. Closing panels (Escape x5)...")
    for i in range(5):
        cmd.send("KEY", 27)  # Escape
        time.sleep(0.8)

    frame = sc.grab_full()
    if frame is not None:
        state = detector.detect(frame)
        print(f"   State after Escape: {state.value}")
        cv2.imwrite(str(SCREENSHOT_DIR / "after_escape.png"), frame)

    # Step 2: Go to city via Space key
    print("\n2. Going to city (Space key)...")
    cmd.send("KEY", 32)  # Space
    time.sleep(2.0)

    frame = sc.grab_full()
    if frame is not None:
        state = detector.detect(frame)
        print(f"   State: {state.value}")
        cv2.imwrite(str(SCREENSHOT_DIR / "after_space.png"), frame)

    if state != GameScreen.CITY_VIEW:
        print("   Not in city view, trying click + zoom in...")
        cx = win["left"] + win["width"] // 2
        cy = win["top"] + win["height"] // 2
        hid_x, hid_y = screen_to_hid(cx, cy)
        cmd.send("MOVETO", hid_x, hid_y)
        time.sleep(0.1)
        for _ in range(10):
            cmd.send("SCROLL", 5)  # zoom IN
            time.sleep(0.15)
        time.sleep(2.0)
        frame = sc.grab_full()
        if frame is not None:
            state = detector.detect(frame)
            print(f"   State after zoom in: {state.value}")
            cv2.imwrite(str(SCREENSHOT_DIR / "after_zoom_in.png"), frame)

    # Step 3: Zoom out to world map (controlled)
    print("\n3. Zooming out to world map (6 scroll steps)...")
    cx = win["left"] + win["width"] // 2
    cy = win["top"] + win["height"] // 2
    hid_x, hid_y = screen_to_hid(cx, cy)
    cmd.send("MOVETO", hid_x, hid_y)
    time.sleep(0.1)
    cmd.send("CLICK", "L", 50)
    time.sleep(0.3)

    for step in range(8):
        cmd.send("SCROLL", -3)  # gentle zoom out
        time.sleep(0.2)

        if step in (3, 5, 7):  # check at certain points
            time.sleep(0.5)
            frame = sc.grab_full()
            if frame is not None:
                state = detector.detect(frame)
                cv2.imwrite(str(SCREENSHOT_DIR / f"zoom_out_step{step}_{state.value}.png"), frame)
                print(f"   Step {step}: state={state.value}")
                if state == GameScreen.WORLD_MAP:
                    print(f"   ✅ Reached world map at step {step}!")
                    break

    # Step 4: Take final screenshot for analysis
    time.sleep(1.0)
    frame = sc.grab_full()
    if frame is not None:
        cv2.imwrite(str(SCREENSHOT_DIR / "world_map_final.png"), frame)
        state = detector.detect(frame)
        print(f"\n4. Final state: {state.value}")

        # Try finding gem mine at this zoom level
        for tpl in ["resources/gem_mine_close", "resources/gem_mine"]:
            m = matcher.match_single(frame, tpl)
            if m:
                print(f"   Found {tpl}: center={m.center}, conf={m.confidence:.3f}")
                annotated = frame.copy()
                cv2.rectangle(annotated, (m.x, m.y), (m.x+m.w, m.y+m.h), (0,255,0), 2)
                cv2.imwrite(str(SCREENSHOT_DIR / f"match_{tpl.split('/')[-1]}.png"), annotated)
            else:
                print(f"   {tpl}: not found")

    print(f"\nScreenshots saved to: {SCREENSHOT_DIR}")

    # Cleanup
    cmd.send("RESET")
    cmd.stop()
    conn.disconnect()
    sc.close()

if __name__ == "__main__":
    main()
