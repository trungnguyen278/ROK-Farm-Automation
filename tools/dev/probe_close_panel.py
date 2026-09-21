"""Close whatever panel is open and stand in the city again.

Uses the farm's own dismiss path -- never ESC, which opens the profile when
nothing is up.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rok_farm.runner import GemFarmRunner
from rok_farm.screenshots import save_screenshot
from rok_farm.state_probe import dim_ratio


def main() -> int:
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        return 1
    try:
        if not r._ensure_game_focused("close panel"):
            return 1
        for attempt in range(3):
            frame = r._grab()
            if frame is None:
                return 1
            print(f"  attempt {attempt + 1}: dim {dim_ratio(frame):.2f}, "
                  f"view {'WORLD' if r._on_world_map(frame) else 'city/panel'}")
            if not r._dismiss_modal():
                print("    dismiss found nothing to close")
            time.sleep(1.2)
        frame = r._grab()
        save_screenshot(frame, "CLOSED_state")
        print(f"  final dim {dim_ratio(frame):.2f}")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
