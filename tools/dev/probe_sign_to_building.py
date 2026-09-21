"""How far below a troop building's purple signboard does its body start?

Once the ready banner is collected it disappears, so the banner cannot find a
building that is merely idle. The signboard can: four of them, 38x33 each,
evenly spaced down the row of troop buildings, present whatever the building
is doing.

This clicks a given offset below one signboard and reports whether the
three-button menu came up, so the offset can be measured instead of guessed.
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
from tools.dev.probe_training_press import blue_hexes

SIGN_HUE = (140, 155)


def signboards(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 0] >= SIGN_HUE[0]) & (hsv[:, :, 0] <= SIGN_HUE[1]) &
         (hsv[:, :, 1] > 110) & (hsv[:, :, 2] > 70)).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE,
                         cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, _, st, ce = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for s, c in zip(st[1:], ce[1:]):
        if not (600 < s[4] < 1200):
            continue
        if not (30 <= s[2] <= 50 and 26 <= s[3] <= 44):
            continue
        out.append((int(c[0]), int(c[1])))
    return sorted(out, key=lambda p: p[0])


def main() -> int:
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    dy = int(sys.argv[2]) if len(sys.argv) > 2 else 45
    dx = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        return 1
    try:
        if not r._ensure_game_focused("sign probe"):
            return 1
        frame = r._grab()
        h, w = frame.shape[:2]
        signs = signboards(frame)
        print(f"  {len(signs)} signboard(s): {signs}")
        if idx >= len(signs):
            print("[FAIL] no such signboard")
            return 1
        sx, sy = signs[idx]
        tx, ty = sx + dx, sy + dy
        print(f"  clicking ({tx},{ty}) = signboard {idx} at ({sx},{sy}) "
              f"plus ({dx},{dy})")
        r._click_pct(tx / w, ty / h, jitter_px=3)
        time.sleep(1.8)
        after = r._grab()
        hexes = blue_hexes(after)
        p = save_screenshot(after, f"SIGN_{idx}_{dx}_{dy}")
        print(f"  menu hexes after: {hexes}")
        print(f"  {'MENU IS UP' if len(hexes) >= 2 else 'no menu'}   {p}")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
