"""End-to-end test: open mail popup, detect close_btn, click it, verify city_view.

Usage: python -m tools.test_popup_dismiss --port COM27
"""
import sys
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
from capture.screen_capture import ScreenCapture
from capture.screen_info import screen_to_hid
from serial_comm.connection import SerialConnection
from serial_comm.command_buffer import CommandBuffer
from vision.template_matcher import TemplateMatcher
from vision.template_cache import TemplateCache
from vision.state_detector import StateDetector, GameScreen

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM27")
    args = parser.parse_args()

    cache = TemplateCache("templates")
    matcher = TemplateMatcher(cache, threshold=0.65)
    detector = StateDetector(matcher)
    CLOSE_BTN_THRESHOLD = 0.9

    sc = ScreenCapture()
    sc.find_window()
    if not sc.window:
        print("ERROR: Game window not found")
        return
    win = sc.window
    print(f"Game window: {win}")

    conn = SerialConnection(port=args.port)
    if not conn.connect():
        print("ERROR: Cannot connect to ESP32")
        return
    buf = CommandBuffer(conn)
    buf.start()
    time.sleep(0.3)

    results = []

    def record(name, passed, detail=""):
        tag = PASS if passed else FAIL
        results.append((name, passed))
        print(f"  [{tag}] {name}" + (f" -- {detail}" if detail else ""))

    def click(fx, fy, label=""):
        sx, sy = win["left"] + fx, win["top"] + fy
        hx, hy = screen_to_hid(sx, sy)
        buf.send("MOVETO", hx, hy)
        time.sleep(0.15)
        buf.send("CLICK", "L", 60)

    def grab():
        time.sleep(0.3)
        return sc.grab_full()

    try:
        print("\n" + "=" * 55)
        print("  End-to-End Test: Popup Auto-Dismiss")
        print("=" * 55)

        # Step 1: Verify we're in city view
        print("\n--- Step 1: Verify city view ---")
        frame = grab()
        state = detector.detect(frame)
        record("Initial state = city_view", state == GameScreen.CITY_VIEW, f"detected: {state.value}")
        if state != GameScreen.CITY_VIEW:
            print("  Not in city view, attempting to navigate...")
            fw, fh = win["width"], win["height"]
            click(int(fw * 0.96), int(fh * 0.93), "city btn")
            time.sleep(2.0)
            frame = grab()
            state = detector.detect(frame)
            record("Navigate to city_view", state == GameScreen.CITY_VIEW, f"detected: {state.value}")

        # Step 2: Verify close_btn is NOT visible before opening popup
        print("\n--- Step 2: Verify no close_btn in city view ---")
        frame = grab()
        match = matcher.match_single(frame, "buttons/close_btn")
        no_close_before = match is None or match.confidence < CLOSE_BTN_THRESHOLD
        record("No close_btn in city view", no_close_before,
               f"conf={match.confidence:.3f}" if match else "not found")

        # Step 3: Open mail popup (click M button at bottom-right)
        print("\n--- Step 3: Open mail popup ---")
        fw, fh = win["width"], win["height"]
        click(int(fw * 0.905), int(fh * 0.948), "Mail btn")
        time.sleep(2.5)
        frame = grab()
        match = matcher.match_single(frame, "buttons/close_btn")
        close_visible = match is not None and match.confidence >= CLOSE_BTN_THRESHOLD
        record("close_btn visible in popup", close_visible,
               f"conf={match.confidence:.3f} at ({match.center[0]},{match.center[1]})" if match else "not found")
        cv2.imwrite("_captures/test_popup_open.png", frame)

        if not close_visible:
            print("  WARNING: close_btn not found, test cannot continue")
            buf.send("KEY", 0x29, 60)
            time.sleep(0.5)
            buf.send("RESET"); buf.stop(); conn.disconnect(); sc.close()
            return

        # Step 4: Click close_btn
        print("\n--- Step 4: Click close_btn ---")
        cx, cy = match.center
        click(cx, cy, f"close_btn at ({cx},{cy})")
        time.sleep(1.5)

        # Step 5: Verify popup closed - close_btn gone
        print("\n--- Step 5: Verify popup dismissed ---")
        frame = grab()
        match_after = matcher.match_single(frame, "buttons/close_btn")
        close_gone = match_after is None or match_after.confidence < CLOSE_BTN_THRESHOLD
        record("close_btn gone after click", close_gone,
               f"conf={match_after.confidence:.3f}" if match_after else "not found")

        # Step 6: Verify back to city view
        print("\n--- Step 6: Verify city view restored ---")
        state = detector.detect(frame)
        record("State = city_view after dismiss", state == GameScreen.CITY_VIEW, f"detected: {state.value}")
        cv2.imwrite("_captures/test_popup_closed.png", frame)

        # Summary
        print("\n" + "=" * 55)
        print("  SUMMARY")
        print("=" * 55)
        passed = sum(1 for _, p in results if p)
        failed = sum(1 for _, p in results if not p)
        for name, p in results:
            print(f"  [{PASS if p else FAIL}] {name}")
        print(f"\n  Total: {len(results)}  |  Pass: {passed}  |  Fail: {failed}")
        if failed == 0:
            print(f"\n  [{PASS}] Popup auto-dismiss test PASSED")
        else:
            print(f"\n  [{FAIL}] {failed} check(s) failed")

    finally:
        buf.send("RESET")
        buf.stop()
        conn.disconnect()
        sc.close()


if __name__ == "__main__":
    main()
