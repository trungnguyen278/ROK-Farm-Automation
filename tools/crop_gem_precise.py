"""Precise crop of gem mine from current screen — just the structure, no UI."""

import sys
import os
import cv2
import numpy as np
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from capture.screen_capture import ScreenCapture

OUT = Path("tools/screenshots/gem_detect")
OUT.mkdir(parents=True, exist_ok=True)


def find_gem_structure(frame):
    """Find the gem mine structure using color + morphology to isolate the rocky part."""
    h, w = frame.shape[:2]
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    # Gem mine has red/orange crystals + dark brown rock
    mask_red1 = cv2.inRange(hsv, (0, 70, 50), (15, 255, 255))
    mask_red2 = cv2.inRange(hsv, (165, 70, 50), (180, 255, 255))
    mask_brown = cv2.inRange(hsv, (10, 30, 30), (25, 180, 150))
    mask = mask_red1 | mask_red2 | mask_brown

    # Only play area
    play_mask = np.zeros((h, w), dtype=np.uint8)
    play_mask[int(h * 0.15):int(h * 0.80), int(w * 0.15):int(w * 0.85)] = 255
    mask = mask & play_mask

    # Close gaps in the structure
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    # Filter: gem mine structure should be 50-250px in each dimension
    candidates = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cv2.contourArea(c)
        if 2000 < area < 40000 and 40 < cw < 300 and 40 < ch < 300:
            candidates.append((c, x, y, cw, ch, area))

    if not candidates:
        # Fallback: take largest
        c = max(contours, key=cv2.contourArea)
        x, y, cw, ch = cv2.boundingRect(c)
        return (x, y, cw, ch)

    # Take the candidate with largest area (likely the gem mine structure)
    best = max(candidates, key=lambda t: t[5])
    return (best[1], best[2], best[3], best[4])


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
    ts = datetime.now().strftime("%H%M%S")
    print(f"Frame: {w}x{h}")

    result = find_gem_structure(frame)
    if result is None:
        print("Could not find gem structure via color analysis")
        cv2.imwrite(str(OUT / f"no_gem_{ts}.png"), frame)
        return

    rx, ry, rw, rh = result
    print(f"Detected gem structure: ({rx},{ry}) size {rw}x{rh}")

    # Add small padding (10px)
    pad = 10
    x1 = max(0, rx - pad)
    y1 = max(0, ry - pad)
    x2 = min(w, rx + rw + pad)
    y2 = min(h, ry + rh + pad)

    crop = frame[y1:y2, x1:x2]
    ch, cw = crop.shape[:2]
    print(f"Crop with padding: ({x1},{y1})-({x2},{y2}), size={cw}x{ch}")

    # Save multiple sizes for testing
    sizes = {
        "tight": (x1, y1, x2, y2),
        "medium": (max(0, rx - 20), max(0, ry - 20),
                   min(w, rx + rw + 20), min(h, ry + rh + 20)),
        "wide": (max(0, rx - 40), max(0, ry - 40),
                 min(w, rx + rw + 40), min(h, ry + rh + 40)),
    }

    for name, (cx1, cy1, cx2, cy2) in sizes.items():
        c = frame[cy1:cy2, cx1:cx2]
        path = OUT / f"gem_crop_{name}_{ts}.png"
        cv2.imwrite(str(path), c)
        print(f"  {name}: {path} ({c.shape[1]}x{c.shape[0]})")

        # Self-match test
        res = cv2.matchTemplate(frame, c, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        print(f"    self-match: conf={max_val:.3f}")

    # Save annotated
    ann = frame.copy()
    for name, (cx1, cy1, cx2, cy2) in sizes.items():
        color = {"tight": (0, 255, 0), "medium": (255, 255, 0), "wide": (0, 165, 255)}[name]
        cv2.rectangle(ann, (cx1, cy1), (cx2, cy2), color, 2)
        cv2.putText(ann, name, (cx1, cy1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    cv2.imwrite(str(OUT / f"gem_boxes_{ts}.png"), ann)
    print(f"\nAnnotated: {OUT / f'gem_boxes_{ts}.png'}")

    sc.close()


if __name__ == "__main__":
    main()
