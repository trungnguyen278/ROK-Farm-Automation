"""Debug mail badge detection -- captures every 2s for 10s.
Open mail in game during the capture window. No ESP32 needed."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
import time
from anti_detection.player_actions import (
    _match_on_frame, _check_badge_near_tab, _mail_btn_has_badge,
    MAIL_TAB_TEMPLATES
)
from capture.screen_capture import ScreenCapture
import ctypes
ctypes.windll.user32.SetProcessDPIAware()

sc = ScreenCapture()
sc.find_window()
time.sleep(0.3)

print("Capturing for 10s -- open mail now!\n")

best_frame = None
best_score = 0

for tick in range(6):
    frame = sc.grab_full()
    if frame is None:
        print("[%ds] no frame" % (tick * 2))
        time.sleep(2)
        continue

    fh, fw = frame.shape[:2]
    matches = []
    for tab in MAIL_TAB_TEMPLATES:
        m = _match_on_frame(frame, tab["template"], threshold=0.7)
        if m:
            matches.append((tab["name"], m))

    score = len(matches)
    avg_conf = sum(m[1][2] for m in matches) / len(matches) if matches else 0
    mail_badge = _mail_btn_has_badge(frame)

    print("[%ds] tabs=%d avg_conf=%.2f mail_btn=%s" % (
        tick * 2, score, avg_conf, "BADGE" if mail_badge else "none"))

    if score > best_score or (score == best_score and avg_conf > 0):
        best_score = score
        best_frame = frame.copy()

    if score >= 3 and avg_conf > 0.85:
        print("  -> mail panel detected, analyzing...")
        break

    time.sleep(2)

if best_frame is None:
    print("\nNo frames captured")
    sc.close()
    sys.exit(1)

frame = best_frame
fh, fw = frame.shape[:2]
debug = frame.copy()

print("\n--- Best frame analysis (%dx%d) ---" % (fw, fh))

for tab in MAIL_TAB_TEMPLATES:
    m = _match_on_frame(frame, tab["template"], threshold=0.5)
    if m is None:
        print("  %s: NOT FOUND" % tab["name"])
        continue
    pct_x, pct_y, conf, tw, th = m
    cx, cy = int(pct_x * fw), int(pct_y * fh)
    has_badge = _check_badge_near_tab(frame, pct_x, pct_y, tw, th)

    print("  %s: px(%d,%d) conf=%.2f tw=%d th=%d -> %s" % (
        tab["name"], cx, cy, conf, tw, th, "BADGE" if has_badge else "clear"))

    cv2.circle(debug, (cx, cy), 5, (0, 255, 0), 2)
    cv2.rectangle(debug, (cx - tw//2, cy - th//2), (cx + tw//2, cy + th//2), (0, 255, 0), 1)

    bx1 = max(0, cx - tw // 4)
    bx2 = min(fw, cx + tw)
    by1 = max(0, cy - th * 2)
    by2 = min(fh, cy + 5)
    cv2.rectangle(debug, (bx1, by1), (bx2, by2), (0, 165, 255), 2)

    if by2 > by1 and bx2 > bx1:
        band = frame[by1:by2, bx1:bx2]
        red_mask = ((band[:, :, 2] > 150) & (band[:, :, 1] < 100) & (band[:, :, 0] < 100))
        red_px = int(red_mask.sum())
        print("    region (%d,%d)-(%d,%d) red=%d" % (bx1, by1, bx2, by2, red_px))

cv2.imwrite("screenshots/mail_badge_debug.png", debug)
print("\nSaved: screenshots/mail_badge_debug.png")
sc.close()
