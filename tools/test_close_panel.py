"""Test open + close panels via ESP32 HID.

Usage: .venv\Scripts\python -m tools.test_close_panel --port COM28
"""
import sys
import os
import time
import random
import argparse
import cv2
import win32gui
import win32con

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.screen_capture import ScreenCapture
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from serial_comm.connection import SerialConnection
from serial_comm.command_buffer import CommandBuffer
from capture.screen_info import get_cursor_pos

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="COM28")
args = parser.parse_args()

sc = ScreenCapture()
win = sc.find_window()
if not win:
    print("Game window not found")
    sys.exit(1)
print(f"Window: {win['width']}x{win['height']}")

cache = TemplateCache("templates")
matcher = TemplateMatcher(cache, threshold=0.50)

conn = SerialConnection(args.port)
if not conn.connect():
    print(f"Failed to connect to {args.port}")
    sys.exit(1)
cmd = CommandBuffer(conn)
cmd.start()
print(f"ESP32 connected on {args.port}")

def focus_game():
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and "Rise of Kingdoms" in win32gui.GetWindowText(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
    win32gui.EnumWindows(_cb, None)

focus_game()
time.sleep(0.5)

BTN_POS = {
    "bag":      (0.755, 0.953),
    "alliance": (0.803, 0.953),
    "mail":     (0.898, 0.953),
}
X_CLOSE_POS = {
    "bag":      (0.865, 0.187),
    "alliance": (0.765, 0.233),
    "mail":     (0.817, 0.086),
}

def move_to(sx, sy):
    for _ in range(5):
        cur_x, cur_y = get_cursor_pos()
        dx, dy = sx - cur_x, sy - cur_y
        if abs(dx) < 3 and abs(dy) < 3:
            return
        cmd.send("MOVE", dx, dy, max(30, min(abs(dx) + abs(dy), 200)))
        time.sleep(0.05)

def click_pct(pct_x, pct_y, jitter_px=5):
    sx = win["left"] + int(win["width"] * pct_x) + random.randint(-jitter_px, jitter_px)
    sy = win["top"] + int(win["height"] * pct_y) + random.randint(-jitter_px, jitter_px)
    move_to(sx, sy)
    time.sleep(random.uniform(0.08, 0.15))
    cmd.send("CLICK", "L", random.randint(40, 100))
    print(f"  Click ({pct_x:.3f}, {pct_y:.3f}) -> screen ({sx}, {sy})")

def grab_and_save(label):
    frame = sc.grab_full()
    if frame is None:
        print(f"  [{label}] grab failed")
        return None
    os.makedirs("tools/screenshots", exist_ok=True)
    path = f"tools/screenshots/test_close_{label}.png"
    cv2.imwrite(path, frame)
    print(f"  [{label}] saved: {path}")
    return frame

print("\n=== Test: Open mail -> close -> Open alliance -> close ===\n")

grab_and_save("01_before")

print("\nOpening mail...")
click_pct(*BTN_POS["mail"])
time.sleep(2.0)
grab_and_save("02_mail_open")

print("\nClosing mail (0.940, 0.040)...")
click_pct(*X_CLOSE_POS["mail"], jitter_px=2)
time.sleep(1.0)
grab_and_save("03_mail_closed")

print("\nOpening alliance...")
click_pct(*BTN_POS["alliance"])
time.sleep(2.0)
grab_and_save("04_alliance_open")

print("\nClosing alliance (0.765, 0.233)...")
click_pct(*X_CLOSE_POS["alliance"], jitter_px=2)
time.sleep(1.0)
grab_and_save("05_alliance_closed")

print("\nDone!")
cmd.stop()
conn.disconnect()
