"""Third click: the training button on a selected building's little menu.

Selecting a building raises three round buttons. Measured on the 13:30 frame:
left (834,472) r44 blue 0.40, middle (946,482) r54 GREEN 0.28, right
(1024,462) r47 blue 0.37. The operator says the right-hand one opens training;
the green middle one is upgrade and must not be pressed by accident, which is
why the green fraction is checked rather than the order alone.
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


def menu_buttons(frame):
    """The round buttons of a selected building's menu, left to right."""
    grey = cv2.medianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 3)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    circles = cv2.HoughCircles(grey, cv2.HOUGH_GRADIENT, dp=1, minDist=40,
                               param1=90, param2=30, minRadius=25, maxRadius=55)
    if circles is None:
        return []
    out = []
    for cx, cy, r in np.round(circles[0]).astype(int):
        m = np.zeros(frame.shape[:2], np.uint8)
        cv2.circle(m, (cx, cy), max(4, r - 10), 255, -1)
        px = hsv[m > 0]
        if len(px) == 0:
            continue
        blue = ((px[:, 0] >= 95) & (px[:, 0] <= 115) & (px[:, 1] > 60)).mean()
        green = ((px[:, 0] >= 40) & (px[:, 0] <= 80) & (px[:, 1] > 60)).mean()
        if blue < 0.20 and green < 0.20:
            continue
        out.append({"x": int(cx), "y": int(cy), "r": int(r),
                    "blue": float(blue), "green": float(green)})
    out.sort(key=lambda b: b["x"])

    # A city is full of round things -- scanning the whole frame for circles
    # returned NINETY-SEVEN, and taking "the rightmost" pressed the build
    # button in the corner of the screen. The menu is not any one circle; it
    # is a TRIPLET: three of similar size, evenly spaced across about a
    # hundred pixels, sitting at the same height, with a green one in the
    # middle. Measured on the 13:30 frame: (834,472) r44, (946,482) r54 green
    # 0.28, (1024,462) r47 -- gaps 112 and 78, heights within 20.
    best = None
    for i in range(len(out)):
        for j in range(i + 1, len(out)):
            for k in range(j + 1, len(out)):
                a, b, c = out[i], out[j], out[k]
                if max(abs(a["y"] - b["y"]), abs(b["y"] - c["y"]),
                       abs(a["y"] - c["y"])) > 30:
                    continue
                g1, g2 = b["x"] - a["x"], c["x"] - b["x"]
                if not (60 <= g1 <= 140 and 60 <= g2 <= 140):
                    continue
                if abs(g1 - g2) > 55:
                    continue
                if b["green"] < 0.15:          # the middle one is the green arrow
                    continue
                # A trio of round things in the city itself passed everything
                # above -- (264,546) r41, (334,526) r54, (448,520) r34 on a
                # perfectly ordinary city frame. Two things separate it from
                # the real menu: the real outer buttons carry no green at all
                # (0.00 and 0.01 against 0.13), and the real three are close
                # to the same size (54/50/47, spread 7, against 41/54/34,
                # spread 20).
                if a["green"] > 0.05 or c["green"] > 0.05:
                    continue
                radii = [a["r"], b["r"], c["r"]]
                if max(radii) - min(radii) > 12:
                    continue
                score = b["green"] - abs(g1 - g2) / 1000.0
                if best is None or score > best[0]:
                    best = (score, [a, b, c])
    return best[1] if best else []


def main() -> int:
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        return 1
    try:
        if not r._ensure_game_focused("training third click"):
            return 1
        frame = r._grab()
        btns = menu_buttons(frame)
        print(f"  menu buttons: {[(b['x'], b['y'], round(b['green'], 2)) for b in btns]}")
        if len(btns) < 2:
            save_screenshot(frame, "THIRD_no_menu")
            print("[FAIL] the building menu is not up -- click the building first")
            return 1
        target = btns[-1]
        if target["green"] > 0.20:
            print("[FAIL] the right-hand button reads GREEN -- that is upgrade, "
                  "not training; refusing to press it")
            return 1
        h, w = frame.shape[:2]
        print(f"  pressing the right-hand button at ({target['x']},{target['y']})")
        save_screenshot(frame, "THIRD_before")
        r._click_pct(target["x"] / w, target["y"] / h, jitter_px=4)
        from rok_farm.state_probe import dim_ratio
        for i in range(6):
            time.sleep(0.45)
            f = r._grab()
            if f is None:
                continue
            p = save_screenshot(f, f"THIRD_after_{i}")
            print(f"     {Path(p).name}  dim {dim_ratio(f):.2f}")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
