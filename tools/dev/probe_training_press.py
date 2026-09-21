"""Press the training button on a selected building's menu, and photograph it.

The button is found by shape and colour, never by the picture inside it: the
operator warns that the icon changes with the troop type -- a catapult for the
siege workshop, a horse for the stable. What does not change is a blue hexagon
about 78x73 sitting beside the green upgrade one.

Circles were the wrong primitive. HoughCircles found these at one zoom and
missed them at another, because they are hexagons; and scanning a whole city
for circles returns ninety-seven of them, which is how an earlier attempt
pressed the build button in the corner of the screen.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import cv2
import numpy as np

from rok_farm.runner import GemFarmRunner
from rok_farm.screenshots import save_screenshot
from tools.dev.probe_training_popup import find_banners

HEX = (60, 100)          # side of the button's bounding box, px
HUD_CORNER_X, HUD_CORNER_Y = 1400, 690


def blue_hexes(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 0] >= 95) & (hsv[:, :, 0] <= 118) &
         (hsv[:, :, 1] > 70) & (hsv[:, :, 2] > 120)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for s, c in zip(st[1:], ce[1:]):
        w, h = int(s[2]), int(s[3])
        if not (HEX[0] <= w <= HEX[1] and HEX[0] <= h <= HEX[1]):
            continue
        if not (0.75 < w / max(1, h) < 1.35):
            continue
        cx, cy = int(c[0]), int(c[1])
        if cx > HUD_CORNER_X and cy > HUD_CORNER_Y:   # the Space button etc.
            continue
        out.append((cx, cy, w, h))
    return sorted(out, key=lambda b: b[0])


def main() -> int:
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        return 1
    try:
        if not r._ensure_game_focused("training press"):
            return 1
        frame = r._grab()
        h, w = frame.shape[:2]
        hexes = blue_hexes(frame)
        if not hexes:
            banners = find_banners(frame)
            if not banners:
                print("[FAIL] no menu and nothing ready")
                return 1
            cx, cy, bw, bh = banners[0]
            tx, ty = cx, cy + int(bh * 1.2)
            print(f"  collect + select at ({tx},{ty})")
            r._click_pct(tx / w, ty / h, jitter_px=3)
            time.sleep(1.6)
            r._click_pct(tx / w, ty / h, jitter_px=3)
            time.sleep(1.8)
            frame = r._grab()
            hexes = blue_hexes(frame)

        print(f"  blue hexes: {hexes}")
        if not hexes:
            save_screenshot(frame, "PRESS_no_menu")
            print("[FAIL] the menu is not up")
            return 1
        tx, ty, bw, bh = hexes[-1]
        print(f"  pressing the training button at ({tx},{ty}) [{bw}x{bh}]")
        save_screenshot(frame, "PRESS_before")
        r._click_pct(tx / w, ty / h, jitter_px=4)
        from rok_farm.state_probe import dim_ratio
        for i in range(6):
            time.sleep(0.45)
            f = r._grab()
            if f is None:
                continue
            p = save_screenshot(f, f"PRESS_after_{i}")
            print(f"     {Path(p).name}  dim {dim_ratio(f):.2f}")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
