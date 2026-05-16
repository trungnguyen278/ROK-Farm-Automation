"""Crop gem mine from the latest full screenshot to create a new template."""

import sys
import os
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture.screen_capture import ScreenCapture

OUT = Path("tools/screenshots/gem_detect")
TEMPLATE_DIR = Path("templates/resources")


def main():
    sc = ScreenCapture()
    win = sc.find_window()
    if not win:
        print("Game window not found")
        return

    frame = sc.grab_full()
    if frame is None:
        print("Capture failed")
        return

    h, w = frame.shape[:2]
    print(f"Frame: {w}x{h}")

    # Save full frame for reference
    ts = datetime.now().strftime("%H%M%S")
    cv2.imwrite(str(OUT / f"crop_source_{ts}.png"), frame)

    # The gem mine is visible in center-left of screen
    # Based on region screenshots, it's approximately at:
    # full frame: x ~560-740, y ~330-490
    # Let me scan for the darkest/most colorful region in the play area
    # to find the gem mine structure automatically

    # Convert to HSV to find red/orange crystals
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Red gems in HSV: H=0-10 or 170-180, S>80, V>80
    mask_red1 = cv2.inRange(hsv, (0, 80, 80), (15, 255, 255))
    mask_red2 = cv2.inRange(hsv, (165, 80, 80), (180, 255, 255))
    mask_red = mask_red1 | mask_red2

    # Only look in play area (avoid UI)
    play_mask = np.zeros((h, w), dtype=np.uint8)
    x1_play = int(w * 0.15)
    x2_play = int(w * 0.85)
    y1_play = int(h * 0.10)
    y2_play = int(h * 0.80)
    play_mask[y1_play:y2_play, x1_play:x2_play] = 255
    mask_red = mask_red & play_mask

    # Find contours of red regions
    contours, _ = cv2.findContours(mask_red, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        print("No red crystal regions found — trying broader color range")
        # Try orange/brown range too
        mask_orange = cv2.inRange(hsv, (5, 60, 60), (25, 255, 255))
        mask_orange = mask_orange & play_mask
        contours, _ = cv2.findContours(mask_orange, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        print("No gem-colored regions found. Saving play area for manual inspection.")
        play_crop = frame[y1_play:y2_play, x1_play:x2_play]
        cv2.imwrite(str(OUT / f"play_area_{ts}.png"), play_crop)
        return

    # Merge nearby contours by finding the bounding box of the largest cluster
    # Sort by area, take top clusters
    contours = sorted(contours, key=cv2.contourArea, reverse=True)

    # Get center of largest red region
    best = contours[0]
    bx, by, bw, bh = cv2.boundingRect(best)
    cx, cy = bx + bw // 2, by + bh // 2
    print(f"Largest red cluster: rect=({bx},{by},{bw},{bh}), center=({cx},{cy})")

    # Merge all contours within 150px of this center
    all_pts = []
    for c in contours:
        mx, my, mw, mh = cv2.boundingRect(c)
        mc = (mx + mw // 2, my + mh // 2)
        if abs(mc[0] - cx) < 200 and abs(mc[1] - cy) < 200:
            all_pts.append(c)

    if all_pts:
        merged = np.vstack(all_pts)
        rx, ry, rw, rh = cv2.boundingRect(merged)
    else:
        rx, ry, rw, rh = bx, by, bw, bh

    print(f"Merged gem region: ({rx},{ry}) size ({rw}x{rh})")

    # Add padding and ensure reasonable size for template
    pad = 15
    crop_x1 = max(0, rx - pad)
    crop_y1 = max(0, ry - pad)
    crop_x2 = min(w, rx + rw + pad)
    crop_y2 = min(h, ry + rh + pad)

    gem_crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
    crop_h, crop_w = gem_crop.shape[:2]
    print(f"Template crop: ({crop_x1},{crop_y1})-({crop_x2},{crop_y2}), size={crop_w}x{crop_h}")

    # Save as candidate template
    candidate_path = OUT / f"gem_mine_candidate_{ts}.png"
    cv2.imwrite(str(candidate_path), gem_crop)
    print(f"Candidate saved: {candidate_path}")

    # Also save annotated full frame
    annotated = frame.copy()
    cv2.rectangle(annotated, (crop_x1, crop_y1), (crop_x2, crop_y2), (0, 255, 0), 3)
    cv2.putText(annotated, f"Gem mine crop ({crop_w}x{crop_h})",
                (crop_x1, crop_y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    # Draw red mask overlay
    red_overlay = frame.copy()
    red_overlay[mask_red > 0] = (0, 0, 255)
    blend = cv2.addWeighted(annotated, 0.7, red_overlay, 0.3, 0)
    cv2.imwrite(str(OUT / f"gem_annotated_{ts}.png"), blend)
    print(f"Annotated frame saved")

    # Test: try matching this candidate back on the source frame
    from vision.template_cache import TemplateCache
    from vision.template_matcher import TemplateMatcher

    # Quick test with the candidate
    result = cv2.matchTemplate(frame, gem_crop, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(result)
    print(f"\nSelf-match test: conf={max_val:.3f} at {max_loc}")

    if max_val >= 0.95:
        print(f"Excellent self-match! This crop is a good template candidate.")
        print(f"\nTo use: copy {candidate_path} -> {TEMPLATE_DIR / 'gem_mine_close.png'}")
    else:
        print(f"Self-match low — crop may include too much variable background")

    sc.close()


if __name__ == "__main__":
    main()
