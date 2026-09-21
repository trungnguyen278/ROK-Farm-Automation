"""Collect a finished batch, then open the training popup -- and photograph
everything in between.

The operator's correction, 2026-09-21: the first click on a building with a
ready banner COLLECTS the troops. Opening the training popup takes a SECOND
click on the same building.

The first attempt at this clicked twice, three seconds apart, looked at the dim
ratio each time, read 1.20 both times and reported "nothing happened" -- while
two batches had in fact been collected. The dim ratio was the wrong instrument
and the sampling was too sparse to see anything transient. So this one shoots
a burst after every click and saves the lot; the pictures decide, not a number.
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
from tools.dev.probe_training_popup import find_banners


def burst(r, tag, shots=5, gap=0.45):
    """Photograph the next couple of seconds, not just the end of them."""
    out = []
    for i in range(shots):
        time.sleep(gap)
        f = r._grab()
        if f is None:
            continue
        out.append((f, save_screenshot(f, f"{tag}_{i}")))
    return out


def main() -> int:
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        print("[FAIL] setup did not complete")
        return 1
    try:
        if not r._ensure_game_focused("training two-click probe"):
            print("[FAIL] the game would not come to the front")
            return 1
        frame = r._grab()
        banners = find_banners(frame)
        print(f"  {len(banners)} banner(s) ready: {[(b[0], b[1]) for b in banners]}")
        if not banners:
            print("[FAIL] nothing ready to collect")
            return 1

        cx, cy, bw, bh = banners[0]
        h, w = frame.shape[:2]
        # Below the banner by a fraction of its own height, so a zoom change
        # moves the target with it instead of leaving it behind.
        drop = int(bh * 1.2)
        tx, ty = cx, cy + drop
        print(f"  banner {bw}x{bh} at ({cx},{cy}); clicking ({tx},{ty}), "
              f"{drop}px below = 1.2 banner heights")

        save_screenshot(frame, "TWO_before")
        r._click_pct(tx / w, ty / h, jitter_px=3)
        shots = burst(r, "TWO_afterA")
        left = find_banners(shots[-1][0]) if shots else []
        print(f"  after the FIRST click: {len(left)} banner(s) left")

        time.sleep(random.uniform(0.8, 1.4))
        print(f"  clicking the same spot again")
        r._click_pct(tx / w, ty / h, jitter_px=3)
        shots2 = burst(r, "TWO_afterB", shots=6)
        from rok_farm.state_probe import dim_ratio
        for f, p in shots2:
            print(f"     {Path(p).name}  dim {dim_ratio(f):.2f}")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
