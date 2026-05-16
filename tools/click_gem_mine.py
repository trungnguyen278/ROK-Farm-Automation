"""Click gem mine and test gather flow via ESP32 HID."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.screen_capture import ScreenCapture
from capture.screen_info import screen_to_hid
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from serial_comm.connection import SerialConnection
from serial_comm.command_buffer import CommandBuffer
import cv2

SHOTS = "tools/screenshots/recapture"

sc = ScreenCapture()
win = sc.find_window()
print(f"Window: {win['width']}x{win['height']}")

conn = SerialConnection(port="COM27")
conn.connect()
cmd = CommandBuffer(conn)
cmd.start()
time.sleep(0.3)

cache = TemplateCache("templates")
matcher = TemplateMatcher(cache, threshold=0.60)

# 1. Close search bar + filter panel
print("1. Closing panels...")
cmd.send("KEY", 27)
time.sleep(0.8)
cx = win["left"] + win["width"] // 2
cy = win["top"] + win["height"] // 2
hx, hy = screen_to_hid(cx, cy)
cmd.send("MOVETO", hx, hy)
time.sleep(0.1)
cmd.send("CLICK", "L", 50)
time.sleep(1.0)

# 2. Screenshot and find gem mine
frame = sc.grab_full()
if frame is not None:
    cv2.imwrite(f"{SHOTS}/clean_view.png", frame)
    for tpl in ["resources/gem_mine_close", "resources/gem_mine"]:
        m = matcher.match_single(frame, tpl)
        if m:
            print(f"  Found {tpl}: center={m.center} conf={m.confidence:.3f}")

# 3. Zoom in a bit (2 steps) to get closer to gem mine
print("2. Zooming in 2 steps...")
cmd.send("MOVETO", hx, hy)
time.sleep(0.1)
for _ in range(2):
    cmd.send("SCROLL", 3)
    time.sleep(0.2)
time.sleep(1.0)

# 4. Find and click gem mine
frame = sc.grab_full()
if frame is None:
    print("No frame!")
    sys.exit(1)

cv2.imwrite(f"{SHOTS}/zoomed_view.png", frame)

mine_match = None
for tpl in ["resources/gem_mine_close", "resources/gem_mine"]:
    m = matcher.match_single(frame, tpl)
    if m:
        tpl_short = tpl.split("/")[-1]
        print(f"  Match {tpl_short}: center={m.center} conf={m.confidence:.3f}")
        annotated = frame.copy()
        cv2.rectangle(annotated, (m.x, m.y), (m.x + m.w, m.y + m.h), (0, 255, 0), 2)
        cv2.circle(annotated, m.center, 5, (0, 0, 255), -1)
        cv2.imwrite(f"{SHOTS}/match_{tpl_short}.png", annotated)
        mine_match = m
        break

if mine_match is None:
    print("Gem mine not found at this zoom level!")
    # Save frame for manual crop
    cv2.imwrite(f"{SHOTS}/no_match_frame.png", frame)
    print("Saved frame — check if gem mine is visible but template doesn't match")
    cmd.send("RESET")
    cmd.stop()
    conn.disconnect()
    sys.exit(1)

# 5. Click gem mine
print(f"3. Clicking gem mine at frame {mine_match.center}...")
screen_x = mine_match.center[0] + win["left"]
screen_y = mine_match.center[1] + win["top"]
hid_x, hid_y = screen_to_hid(screen_x, screen_y)

# MOVETO
cmd.send("MOVETO", hid_x, hid_y)
time.sleep(0.3)

# Verify
frame2 = sc.grab_full()
if frame2 is not None:
    v = matcher.match_single(frame2, mine_match.name)
    if v:
        print(f"  Verified at {v.center}, conf={v.confidence:.3f}")
        new_sx = v.center[0] + win["left"]
        new_sy = v.center[1] + win["top"]
        hid_x, hid_y = screen_to_hid(new_sx, new_sy)
        cmd.send("MOVETO", hid_x, hid_y)
        time.sleep(0.15)

# CLICK
cmd.send("CLICK", "L", 80)
print("  CLICK sent")
time.sleep(2.5)

# 6. Screenshot after click — look for action buttons
frame3 = sc.grab_full()
if frame3 is not None:
    cv2.imwrite(f"{SHOTS}/after_gem_click.png", frame3)
    print("4. After click — looking for buttons...")

    for btn in ["buttons/gather_btn", "buttons/march_btn"]:
        b = matcher.match_single(frame3, btn)
        btn_short = btn.split("/")[-1]
        if b:
            print(f"  FOUND {btn_short}: center={b.center} conf={b.confidence:.3f}")
            ann = frame3.copy()
            cv2.rectangle(ann, (b.x, b.y), (b.x + b.w, b.y + b.h), (0, 255, 0), 2)
            cv2.imwrite(f"{SHOTS}/found_{btn_short}.png", ann)
        else:
            print(f"  Not found: {btn_short}")

# Cleanup
cmd.send("RESET")
cmd.stop()
conn.disconnect()
sc.close()
print("Done")
