"""Comprehensive diagnostic: gem icon detection + march line analysis on scan_49."""
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
print(f"Frame size: {fw}x{fh}")

# 1. Find ALL template matches (including low confidence)
all_matches = matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
print(f"\nAll gem_icon matches (any conf): {len(all_matches)}")
for m in sorted(all_matches, key=lambda x: -x.confidence)[:20]:
    print(f"  conf={m.confidence:.3f} center={m.center} size={m.w}x{m.h}")

above = [m for m in all_matches if m.confidence >= 0.68]
print(f"\nAbove 0.68: {len(above)}")

above_low = [m for m in all_matches if m.confidence >= 0.50]
print(f"Above 0.50: {len(above_low)}")

# 2. Full-frame HoughLinesP analysis (like _has_march_line but frame-wide)
hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
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

white_pct = white_mask.sum() / 255 / (fh*fw) * 100
cyan_pct = cyan_mask.sum() / 255 / (fh*fw) * 100
green_pct = green_mask.sum() / 255 / (fh*fw) * 100
print(f"\nColor mask coverage: white={white_pct:.1f}% cyan={cyan_pct:.1f}% green={green_pct:.1f}%")

kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
closed = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=1)

lines = cv2.HoughLinesP(closed, 1, np.pi/180, threshold=35, minLineLength=80, maxLineGap=15)
n_lines = 0 if lines is None else len(lines)
print(f"HoughLinesP lines (minLen=80): {n_lines}")

# Classify lines by angle
if lines is not None:
    horizontal = 0
    vertical = 0
    diagonal = 0
    for line in lines:
        lx1, ly1, lx2, ly2 = line[0]
        angle = abs(np.degrees(np.arctan2(ly2-ly1, lx2-lx1)))
        if angle < 15 or angle > 165:
            horizontal += 1
        elif 75 < angle < 105:
            vertical += 1
        else:
            diagonal += 1
    print(f"  Horizontal(<15 or >165): {horizontal}")
    print(f"  Vertical(75-105): {vertical}")
    print(f"  Diagonal(valid march): {diagonal}")

# 3. Save debug visualization
debug = frame.copy()
if lines is not None:
    for line in lines:
        lx1, ly1, lx2, ly2 = line[0]
        angle = abs(np.degrees(np.arctan2(ly2-ly1, lx2-lx1)))
        if angle < 15 or angle > 165 or (75 < angle < 105):
            color = (128, 128, 128)  # gray = filtered out
        else:
            color = (0, 0, 255)  # red = would pass angle filter
        cv2.line(debug, (lx1, ly1), (lx2, ly2), color, 2)

for m in all_matches:
    cx, cy = m.center
    if m.confidence >= 0.68:
        cv2.circle(debug, (cx, cy), 15, (0, 255, 0), 2)  # green = above threshold
    elif m.confidence >= 0.50:
        cv2.circle(debug, (cx, cy), 15, (0, 255, 255), 2)  # yellow = borderline
    else:
        cv2.circle(debug, (cx, cy), 10, (200, 200, 200), 1)  # gray = low

cv2.imwrite("tools/screenshots/gem_farm_test/scan49_debug.png", debug)
print("\nDebug image saved: scan49_debug.png")
print("  Green circles = icon conf >= 0.68")
print("  Yellow circles = icon conf 0.50-0.68")
print("  Red lines = diagonal (pass angle filter)")
print("  Gray lines = horizontal/vertical (filtered out)")
