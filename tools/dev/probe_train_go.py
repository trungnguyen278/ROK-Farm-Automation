"""Press HUAN LUYEN -- the free one -- and never NGAY, which costs 1,500 gems.

The two buttons sit side by side and one of them spends about a day's farming
in a single click, so nothing here is left to ordering or to luck:

  * the ORANGE button is the anchor. It separates cleanly (H10-30, S>110):
    one blob, 160x54, centred at (801,620) on the 13:44 frame.
  * HUAN LUYEN sits +251px to its right, same height. Colour cannot find it
    directly -- the panel's own background is the same blue at the same
    saturation, and only the value differs.
  * before clicking, the target is checked AGAIN and the click is refused if
    it reads orange.
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

NGAY_TO_TRAIN_DX = 251


def orange_button(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 0] >= 10) & (hsv[:, :, 0] <= 30) &
         (hsv[:, :, 1] > 110) & (hsv[:, :, 2] > 120)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_RECT, (9, 5)))
    n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
    best = None
    for s, c in zip(st[1:], ce[1:]):
        if not (120 <= s[2] <= 220 and 35 <= s[3] <= 80):
            continue
        if s[4] < 3000:
            continue
        if best is None or s[4] > best[0]:
            best = (int(s[4]), int(c[0]), int(c[1]))
    return best


def is_orange(frame, x, y):
    hsv = cv2.cvtColor(frame[y - 10:y + 10, x - 30:x + 30], cv2.COLOR_BGR2HSV)
    if hsv.size == 0:
        return True
    return bool(((hsv[:, :, 0] >= 10) & (hsv[:, :, 0] <= 30) &
                 (hsv[:, :, 1] > 110)).mean() > 0.25)


def main() -> int:
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        return 1
    try:
        if not r._ensure_game_focused("train go"):
            return 1
        frame = r._grab()
        h, w = frame.shape[:2]
        from rok_farm.state_probe import dim_ratio
        if dim_ratio(frame) < 2.0:
            print("[FAIL] the training panel is not open")
            return 1
        anchor = orange_button(frame)
        if not anchor:
            save_screenshot(frame, "GO_no_anchor")
            print("[FAIL] could not find the orange NGAY button to measure from")
            return 1
        _, ox, oy = anchor
        tx, ty = ox + NGAY_TO_TRAIN_DX, oy
        print(f"  NGAY at ({ox},{oy}); HUAN LUYEN should be ({tx},{ty})")
        if is_orange(frame, tx, ty):
            print("[FAIL] the target reads ORANGE -- that is the gem button. "
                  "Refusing.")
            return 1
        print("  target is not orange -- pressing HUAN LUYEN")
        save_screenshot(frame, "GO_before")
        r._click_pct(tx / w, ty / h, jitter_px=4)
        for i in range(6):
            time.sleep(0.5)
            f = r._grab()
            if f is None:
                continue
            p = save_screenshot(f, f"GO_after_{i}")
            print(f"     {Path(p).name}  dim {dim_ratio(f):.2f}")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
