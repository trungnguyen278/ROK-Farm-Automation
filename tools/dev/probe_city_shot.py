"""Bring the client up, stand in the city, and photograph it.

Used while the farm is stopped, to look at things the farm does not yet know
about -- here the troop buildings and what they show when training finishes.
No clicking beyond the view toggle.
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rok_farm.runner import GemFarmRunner
from rok_farm.screenshots import save_screenshot


def main() -> int:
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=True, allow_restart=False, use_oracle=False)
    if not r._setup():
        print("[FAIL] setup did not complete")
        return 1
    try:
        if not r._ensure_game_focused("city shot"):
            print("[FAIL] the game would not come to the front")
            return 1
        if r._on_world_map():
            print("  on the world map -- switching to the city")
            r._toggle_view("city_shot")
            time.sleep(random.uniform(2.0, 3.0))
        time.sleep(random.uniform(1.0, 2.0))
        frame = r._grab()
        if frame is None:
            print("[FAIL] no frame")
            return 1
        path = save_screenshot(frame, "PROBE_city")
        print(f"  saved: {path}")
        print(f"  view now: {'WORLD MAP' if r._on_world_map(frame) else 'CITY'}")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
