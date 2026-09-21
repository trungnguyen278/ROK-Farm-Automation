"""Open a troop building's training popup by its "ready" banner.

When a batch finishes, a white banner floats over the building. Four of them
sit together in this city -- the operator has the four training buildings
placed side by side -- and the banner is the only pure white thing among all
that colour, which is what makes it findable:

    saturation < 45 and value > 205, closed with a 7x7 ellipse, area > 400.

On the 12:23 frame that returns exactly four blobs, each about 50x42, and
nothing else. Two earlier attempts -- hunting the purple square inside the
banner, and reading coordinates off the rendered picture -- found cherry
blossom and rooftops instead.

The operator says clicking a little BELOW the banner, on the building itself,
opens the training popup. How far below is what this measures: pass an offset,
look at the screenshot, try another.

Their order, left to right by position: A (828,129) cavalry, B (736,191)
infantry, C (921,192) archer, D (830,255) siege. T4 today, possibly T5 later,
so the icons inside are not forever.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import cv2
import numpy as np

from rok_farm.runner import GemFarmRunner
from rok_farm.screenshots import save_screenshot

BANNER_SAT_MAX = 45
BANNER_VAL_MIN = 205
BANNER_AREA_MIN = 400
BANNER_SIZE = (34, 70, 28, 60)      # w_lo, w_hi, h_lo, h_hi

# White alone is not enough: the resource bubbles over every farm and quarry
# are the same white and the same size, and the full frame holds 28 of them.
# What only the training banner has is the purple shield inside its gold
# frame. Measured on the 12:23 frame, fraction of the banner box in H140-155
# with S>110: cavalry 0.173, infantry 0.133, archer 0.124, siege 0.133 --
# against 0.000 for every resource bubble AND for the cherry-blossom plaque
# that a wider purple band had been catching, because blossom pink sits at
# hue 165, just outside.
BANNER_PURPLE = (140, 155)
BANNER_PURPLE_MIN = 0.05


def find_banners(frame):
    """Every "training done" banner on the frame, as (cx, cy, w, h)."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    white = ((hsv[:, :, 1] < BANNER_SAT_MAX) &
             (hsv[:, :, 2] > BANNER_VAL_MIN)).astype(np.uint8) * 255
    white = cv2.morphologyEx(
        white, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    n, _, stats, cents = cv2.connectedComponentsWithStats(white, 8)
    w_lo, w_hi, h_lo, h_hi = BANNER_SIZE
    out = []
    for s, c in zip(stats[1:], cents[1:]):
        if s[4] < BANNER_AREA_MIN:
            continue
        if not (w_lo <= s[2] <= w_hi and h_lo <= s[3] <= h_hi):
            continue
        cx, cy, bw, bh = int(c[0]), int(c[1]), int(s[2]), int(s[3])
        x0, y0 = max(0, cx - bw // 2 - 4), max(0, cy - bh // 2 - 6)
        box = hsv[y0:cy + bh // 2 + 6, x0:cx + bw // 2 + 4].reshape(-1, 3)
        if box.size == 0:
            continue
        purple = ((box[:, 0] >= BANNER_PURPLE[0]) &
                  (box[:, 0] <= BANNER_PURPLE[1]) &
                  (box[:, 1] > 110) & (box[:, 2] > 70)).mean()
        if purple < BANNER_PURPLE_MIN:
            continue
        out.append((cx, cy, bw, bh))
    return sorted(out, key=lambda b: (b[1], b[0]))


def main() -> int:
    offset = int(sys.argv[1]) if len(sys.argv) > 1 else 35
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        print("[FAIL] setup did not complete")
        return 1
    try:
        if not r._ensure_game_focused("training popup probe"):
            print("[FAIL] the game would not come to the front")
            return 1
        frame = r._grab()
        if frame is None:
            print("[FAIL] no frame")
            return 1
        banners = find_banners(frame)
        print(f"  {len(banners)} banner(s): {[(b[0], b[1]) for b in banners]}")
        if not banners:
            save_screenshot(frame, "PROBE_no_banner")
            print("[FAIL] no banner found -- nothing is ready to collect")
            return 1

        cx, cy, _, _ = banners[0]
        h, w = frame.shape[:2]
        tx, ty = cx, cy + offset
        print(f"  clicking {offset}px below the first banner: ({tx},{ty})")
        r._click_pct(tx / w, ty / h, jitter_px=4)
        time.sleep(random.uniform(2.0, 3.0))

        after = r._grab()
        if after is None:
            print("[FAIL] no frame after the click")
            return 1
        path = save_screenshot(after, f"PROBE_train_{offset}")
        from rok_farm.state_probe import dim_ratio
        print(f"  after: {path}")
        print(f"  dim ratio: {dim_ratio(after):.2f} "
              f"(a popup over the city reads well above 1.8)")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
