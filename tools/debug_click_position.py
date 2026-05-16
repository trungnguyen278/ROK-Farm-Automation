"""
Debug click positioning — diagnose MOVETO accuracy.
Finds a template on screen, moves mouse there, then captures
actual cursor position to compare expected vs actual.

Usage: python -m tools.debug_click_position [COM_PORT] [template_name]
Example: python -m tools.debug_click_position COM27 buttons/gather_btn
"""
import sys
import os
import time
import ctypes
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

from capture.screen_capture import ScreenCapture
from capture.screen_info import screen_to_hid, get_screen_resolution
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher


def get_cursor_pos() -> tuple[int, int]:
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM27"
    template_name = sys.argv[2] if len(sys.argv) > 2 else "buttons/gather_btn"

    res_w, res_h = get_screen_resolution()
    print(f"Screen resolution: {res_w}x{res_h}")

    sc = ScreenCapture()
    win = sc.find_window()
    if not win:
        print("Game window not found")
        return
    print(f"Window: left={win['left']} top={win['top']} {win['width']}x{win['height']}")

    cache = TemplateCache(str(Path("templates")))
    matcher = TemplateMatcher(cache, threshold=0.65)

    frame = sc.grab_full()
    if frame is None:
        print("Failed to capture frame")
        return

    match = matcher.match_single(frame, template_name)
    if match is None:
        print(f"Template '{template_name}' not found in frame")
        print("Saving frame for inspection...")
        cv2.imwrite("logs/debug_no_match.png", frame)
        return

    frame_cx, frame_cy = match.center
    print(f"\nTemplate match: {template_name}")
    print(f"  Frame coords: ({frame_cx}, {frame_cy})  conf={match.confidence:.3f}")
    print(f"  Match box: x={match.x} y={match.y} w={match.w} h={match.h}")

    screen_x = frame_cx + win["left"]
    screen_y = frame_cy + win["top"]
    print(f"  Screen coords: ({screen_x}, {screen_y})")

    hid_x, hid_y = screen_to_hid(screen_x, screen_y)
    print(f"  HID coords: ({hid_x}, {hid_y})")

    back_x = int(hid_x * res_w / 32767)
    back_y = int(hid_y * res_h / 32767)
    print(f"  Back-converted: ({back_x}, {back_y})")
    print(f"  Rounding error: dx={screen_x - back_x} dy={screen_y - back_y}")

    # Draw expected position on frame
    debug_frame = frame.copy()
    cv2.rectangle(debug_frame, (match.x, match.y),
                  (match.x + match.w, match.y + match.h), (0, 255, 0), 2)
    cv2.circle(debug_frame, (frame_cx, frame_cy), 8, (0, 255, 0), 2)
    cv2.putText(debug_frame, f"expected ({frame_cx},{frame_cy})",
                (frame_cx + 10, frame_cy - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    # Record cursor before move
    before_x, before_y = get_cursor_pos()
    print(f"\nCursor BEFORE move: ({before_x}, {before_y})")

    # Connect ESP32 and send MOVETO
    from serial_comm.connection import SerialConnection
    from serial_comm.command_buffer import CommandBuffer

    conn = SerialConnection(port=port)
    if not conn.connect():
        print(f"Cannot connect to ESP32 on {port}")
        cv2.imwrite("logs/debug_pre_move.png", debug_frame)
        return

    cmd = CommandBuffer(conn)
    cmd.start()
    time.sleep(0.3)

    print(f"\nSending MOVETO {hid_x},{hid_y} ...")
    ok = cmd.send("MOVETO", hid_x, hid_y)
    print(f"  MOVETO result: {'OK' if ok else 'FAIL'}")
    time.sleep(0.5)

    # Capture cursor AFTER move
    after_x, after_y = get_cursor_pos()
    print(f"Cursor AFTER move: ({after_x}, {after_y})")
    print(f"  Expected: ({screen_x}, {screen_y})")
    print(f"  Actual:   ({after_x}, {after_y})")
    print(f"  Error:    dx={after_x - screen_x}  dy={after_y - screen_y}")

    # Draw actual cursor position on frame (convert screen → frame coords)
    actual_fx = after_x - win["left"]
    actual_fy = after_y - win["top"]
    cv2.circle(debug_frame, (actual_fx, actual_fy), 8, (0, 0, 255), 2)
    cv2.putText(debug_frame, f"actual ({actual_fx},{actual_fy})",
                (actual_fx + 10, actual_fy + 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

    # Draw line between expected and actual
    cv2.line(debug_frame, (frame_cx, frame_cy), (actual_fx, actual_fy), (0, 165, 255), 2)

    # Also capture fresh frame with cursor visible
    time.sleep(0.2)
    frame_after = sc.grab_full()
    if frame_after is not None:
        frame_after = frame_after.copy()
        cv2.circle(frame_after, (frame_cx, frame_cy), 12, (0, 255, 0), 2)
        cv2.putText(frame_after, "expected", (frame_cx + 15, frame_cy - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        cv2.imwrite("logs/debug_after_move.png", frame_after)
        print("\nSaved: logs/debug_after_move.png (frame with cursor)")

    cv2.imwrite("logs/debug_positions.png", debug_frame)
    print("Saved: logs/debug_positions.png (expected=green, actual=red)")

    # Cleanup
    cmd.send("RESET")
    cmd.stop()
    conn.disconnect()
    sc.close()

    error_dist = ((after_x - screen_x)**2 + (after_y - screen_y)**2) ** 0.5
    print(f"\nTotal error distance: {error_dist:.1f} px")
    if error_dist < 5:
        print("PASS — positioning is accurate")
    elif error_dist < 20:
        print("WARN — small offset, may still hit large buttons")
    else:
        print("FAIL — significant positioning error, need to investigate")


if __name__ == "__main__":
    main()
