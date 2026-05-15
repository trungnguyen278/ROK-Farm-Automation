"""Capture close_btn.png and claim_btn.png from game popups.

Uses ESP32 HID to navigate game, triggers popups, captures screenshots,
then saves cropped templates. Run with game visible on screen.

Usage: python -m tools.capture_buttons --port COM27
"""
import sys
import os
import time
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from capture.screen_capture import ScreenCapture
from capture.screen_info import screen_to_hid
from serial_comm.connection import SerialConnection
from serial_comm.command_buffer import CommandBuffer


TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
SCREENSHOT_DIR = Path(__file__).resolve().parent.parent / "_captures"


def capture_and_save(sc: ScreenCapture, name: str) -> np.ndarray | None:
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    frame = sc.grab_full()
    if frame is not None:
        path = SCREENSHOT_DIR / f"{name}.png"
        cv2.imwrite(str(path), frame)
        print(f"  Saved screenshot: {path}")
    return frame


def click_screen(buf: CommandBuffer, sc: ScreenCapture, frame_x: int, frame_y: int, label: str = ""):
    win = sc.window
    screen_x = win["left"] + frame_x
    screen_y = win["top"] + frame_y
    hid_x, hid_y = screen_to_hid(screen_x, screen_y)
    print(f"  Click {label} frame=({frame_x},{frame_y}) screen=({screen_x},{screen_y}) hid=({hid_x},{hid_y})")
    buf.send("MOVETO", hid_x, hid_y)
    time.sleep(0.15)
    buf.send("CLICK", "L", 60)
    time.sleep(0.8)


def find_and_crop_region(frame: np.ndarray, description: str) -> np.ndarray | None:
    """Show frame and let user see it. We'll crop based on known ROK UI positions."""
    h, w = frame.shape[:2]
    print(f"  Frame size: {w}x{h}")
    print(f"  Looking for: {description}")
    return frame


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", default="COM27")
    args = parser.parse_args()

    sc = ScreenCapture()
    sc.find_window()
    if not sc.window:
        print("ERROR: Game window not found")
        return

    win = sc.window
    print(f"Game window: {win}")
    frame_w, frame_h = win["width"], win["height"]

    conn = SerialConnection(port=args.port)
    if not conn.connect():
        print("ERROR: Cannot connect to ESP32")
        return

    buf = CommandBuffer(conn)
    buf.start()
    time.sleep(0.3)

    try:
        # Step 1: Capture current state
        print("\n=== Step 1: Capture current game state ===")
        frame0 = capture_and_save(sc, "step0_initial")

        # Step 2: Go to city view by clicking city button (bottom-left area)
        print("\n=== Step 2: Navigate to city view ===")
        # City button is typically at bottom-left of the screen
        # In ROK, clicking the minimap or city icon goes to city
        # The city_btn template is in the bottom-right area typically
        # Let's first try pressing space or home key to go to city
        # Actually in ROK, the home/city button is usually at bottom-right near minimap

        # Try clicking city button area - usually bottom bar
        # From screenshot, game is 1480x876
        # Bottom bar buttons are roughly at y=830, x varies
        # Let's click the city icon which is typically around bottom-left

        # First, let's press ESC to close any menu, then try to navigate
        buf.send("KEY", 0x29, 60)  # ESC key
        time.sleep(1.0)

        frame1 = capture_and_save(sc, "step1_after_esc")

        # Step 3: Open a popup - click on quest/mission icon
        # In ROK, quest icon is typically on the right side
        # Let's try clicking on the quest button area
        print("\n=== Step 3: Click quest/mission area ===")
        # Quest button is usually at right side of screen, middle area
        # Typical position: around x=95% of width, y=40% of height
        quest_x = int(frame_w * 0.02)  # Left side icons
        quest_y = int(frame_h * 0.35)
        click_screen(buf, sc, quest_x, quest_y, "quest/left-panel icon")
        time.sleep(1.5)

        frame2 = capture_and_save(sc, "step2_after_quest_click")

        # Step 4: Try another location - bottom buttons area
        print("\n=== Step 4: Try bottom bar buttons ===")
        # The quest scroll icon in ROK is typically on the left side
        # Let's try several locations to trigger a popup

        # Click on a building or something in center to trigger info popup
        center_x = int(frame_w * 0.5)
        center_y = int(frame_h * 0.4)
        click_screen(buf, sc, center_x, center_y, "center area")
        time.sleep(1.5)

        frame3 = capture_and_save(sc, "step3_after_center_click")

        # Step 5: Try clicking on commander/profile icon (top-left)
        print("\n=== Step 5: Click profile icon (top-left) ===")
        profile_x = int(frame_w * 0.03)
        profile_y = int(frame_h * 0.04)
        click_screen(buf, sc, profile_x, profile_y, "profile icon")
        time.sleep(2.0)

        frame4 = capture_and_save(sc, "step4_after_profile_click")

        # Step 6: Capture final state and save all screenshots
        print("\n=== Step 6: Final capture ===")
        frame5 = capture_and_save(sc, "step5_final")

        # Close popup with ESC
        buf.send("KEY", 0x29, 60)
        time.sleep(0.5)

        print("\n=== Done! Screenshots saved in _captures/ ===")
        print("Review screenshots to identify close_btn and claim_btn positions.")

    finally:
        buf.send("RESET")
        buf.stop()
        conn.disconnect()
        sc.close()


if __name__ == "__main__":
    main()
