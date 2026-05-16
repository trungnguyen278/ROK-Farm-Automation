"""
Quick tool to capture current game screen and save grid crops for inspection.
Helps identify where gem mines are so we can crop a proper template.

Run: .venv\Scripts\python -m tools.capture_gem_region
"""

import sys
import os
from pathlib import Path
from datetime import datetime

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.screen_capture import ScreenCapture

OUT = Path("tools/screenshots/gem_detect")
OUT.mkdir(parents=True, exist_ok=True)


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

    ts = datetime.now().strftime("%H%M%S")
    h, w = frame.shape[:2]
    print(f"Frame: {w}x{h}")

    # Save full frame
    full_path = OUT / f"full_{ts}.png"
    cv2.imwrite(str(full_path), frame)
    print(f"Full: {full_path}")

    # Save center region (where gem mine likely is)
    regions = {
        "center": (w // 4, h // 4, 3 * w // 4, 3 * h // 4),
        "center_left": (0, h // 4, w // 2, 3 * h // 4),
        "center_right": (w // 2, h // 4, w, 3 * h // 4),
        "top_center": (w // 4, 0, 3 * w // 4, h // 2),
        "bot_center": (w // 4, h // 2, 3 * w // 4, h),
    }

    for name, (x1, y1, x2, y2) in regions.items():
        crop = frame[y1:y2, x1:x2]
        p = OUT / f"region_{name}_{ts}.png"
        cv2.imwrite(str(p), crop)
        print(f"  {name}: {p}")

    sc.close()


if __name__ == "__main__":
    main()
