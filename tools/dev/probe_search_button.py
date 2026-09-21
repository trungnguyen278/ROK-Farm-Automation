"""Press the world-map search button once and photograph what it opens.

A step the operator is walking me through, not part of the farm: they know the
AP-spending flow has several screens, so each one is pressed, photographed and
shown to them before the next is written.

Everything goes through the runner the farm itself uses -- its capture, its
humanised pointer, its window handling. Nothing here talks to the board
directly: the scripting warning on 2026-09-09 came from a diagnostic that did,
and that lesson is expensive enough not to relearn.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import cv2

from rok_farm.runner import GemFarmRunner
from rok_farm.screenshots import save_screenshot

# Fixed, as the operator asked: this button does not move. Measured over 8
# saved world-map frames, every one of them putting its centre at (1488, 716)
# of a 1533x862 client -- not one pixel of spread.
SEARCH_BTN_PCT = (0.9706, 0.8306)


def main() -> int:
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        print("[FAIL] setup did not complete")
        return 1
    try:
        frame = r._grab()
        if frame is None:
            print("[FAIL] no frame from the client")
            return 1
        on_world = r._on_world_map(frame)
        print(f"  view: {'world map' if on_world else 'CITY'}")
        if not on_world:
            print("  [..] switching to the world map first")
            r._toggle_view("probe")
            time.sleep(random.uniform(1.5, 2.5))
            frame = r._grab()

        before = save_screenshot(frame, "PROBE_before_search")
        print(f"  before: {before}")

        # The first run of this pressed nothing at all: the before and after
        # frames came back identical because the editor had the foreground and
        # the click landed there. The farm's own flows have asked this since
        # 2026-08-19; a one-off script needs it just as much.
        if not r._ensure_game_focused("search button probe"):
            print("[FAIL] the game would not come to the front -- not clicking")
            return 1
        time.sleep(random.uniform(0.4, 0.9))

        print(f"  clicking the search button at pct{SEARCH_BTN_PCT}")
        r._click_pct(*SEARCH_BTN_PCT, jitter_px=6)
        time.sleep(random.uniform(1.8, 2.6))

        after = r._grab()
        if after is None:
            print("[FAIL] no frame after the click")
            return 1
        path = save_screenshot(after, "PROBE_after_search")
        print(f"  after:  {path}")
        from rok_farm.state_probe import dim_ratio
        print(f"  dim ratio after the click: {dim_ratio(after):.2f} "
              f"(a panel over the map reads well above 1.8)")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
