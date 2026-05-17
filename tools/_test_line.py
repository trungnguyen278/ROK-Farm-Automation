"""Check if gem icons found and whether march lines detected near them."""
import cv2
import numpy as np
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher

cache = TemplateCache("templates")
matcher = TemplateMatcher(cache)

frame = cv2.imread("tools/screenshots/gem_farm_test/m3_scan_49_124957.png")
fh, fw = frame.shape[:2]

# Find gem icons
matches = matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
icons = [m for m in matches if m.confidence >= 0.68]
print(f"Gem icons found: {len(icons)}")
for m in icons:
    print(f"  conf={m.confidence:.3f} center={m.center} size={m.w}x{m.h}")

# For each icon, run the march line detection logic
for icon in icons:
    cx, cy = icon.center
    icon_r = max(icon.w, icon.h)
    pad = icon_r * 5
    y1 = max(cy - pad, 0)
    y2 = min(cy + pad, fh)
    x1 = max(cx - pad, 0)
    x2 = min(cx + pad, fw)
    roi = frame[y1:y2, x1:x2]
    icon_lx = cx - x1
    icon_ly = cy - y1
    min_len = icon_r * 3
    near_r = icon_r * 2

    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    white_mask = ((hsv[:,:,2] > 200) & (hsv[:,:,1] < 50)).astype(np.uint8) * 255
    cyan_mask = (
        (hsv[:,:,0] >= 75) & (hsv[:,:,0] <= 105) &
        (hsv[:,:,1] > 60) & (hsv[:,:,2] > 130)
    ).astype(np.uint8) * 255
    green_mask = (
        (hsv[:,:,0] >= 50) & (hsv[:,:,0] <= 74) &
        (hsv[:,:,1] > 60) & (hsv[:,:,2] > 130)
    ).astype(np.uint8) * 255
    combined = cv2.bitwise_or(white_mask, cv2.bitwise_or(cyan_mask, green_mask))
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    closed = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=1)

    lines = cv2.HoughLinesP(closed, 1, np.pi / 180,
                             threshold=35, minLineLength=int(min_len), maxLineGap=15)
    n_lines = 0 if lines is None else len(lines)

    near_lines = 0
    if lines is not None:
        for line in lines:
            lx1, ly1, lx2, ly2 = line[0]
            length = np.sqrt((lx2-lx1)**2 + (ly2-ly1)**2)
            if length < min_len:
                continue
            angle = abs(np.degrees(np.arctan2(ly2-ly1, lx2-lx1)))
            if angle < 15 or angle > 165 or (75 < angle < 105):
                continue
            d1 = np.sqrt((lx1-icon_lx)**2 + (ly1-icon_ly)**2)
            d2 = np.sqrt((lx2-icon_lx)**2 + (ly2-icon_ly)**2)
            if min(d1, d2) <= near_r:
                near_lines += 1

    print(f"  Icon at {icon.center}: total_lines={n_lines}, near_icon(after filter)={near_lines}")
    print(f"    Result: {'OCCUPIED' if near_lines > 0 else 'FREE'}")

if not icons:
    print("No gem icons found -- _check_icon_occupied was never called")
