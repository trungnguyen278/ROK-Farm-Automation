"""Read cursor position after delay. Di chuot vao nut X truoc khi het thoi gian."""
import time
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from capture.screen_info import get_cursor_pos
from capture.screen_capture import ScreenCapture

delay = int(sys.argv[1]) if len(sys.argv) > 1 else 5
print(f"Di chuot vao nut X... {delay}s")
time.sleep(delay)

sc = ScreenCapture()
w = sc.find_window()
x, y = get_cursor_pos()
print(f"Cursor: ({x}, {y})")
if w:
    px = (x - w["left"]) / w["width"]
    py = (y - w["top"]) / w["height"]
    print(f"Window: left={w['left']}, top={w['top']}, w={w['width']}, h={w['height']}")
    print(f"Pct: ({px:.4f}, {py:.4f})")
