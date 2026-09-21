"""Step three: press BAT DAU on the game's auto panel.

The operator has already set the panel up -- level, troops, counts -- so this
only presses start and photographs the result.

Their warning, which matters far beyond this script: once auto is running,
losing the network OR CLOSING THE CLIENT stops it and sends the troops home.
The farm quits the client every twelve to fifteen minutes, so the two cannot
simply run side by side.

Measured on the step-two frame (1533x862 client): the BAT DAU block is
162x54 centred at (765, 618) -> pct (0.4990, 0.7169).
"""

from __future__ import annotations

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rok_farm.runner import GemFarmRunner
from rok_farm.screenshots import save_screenshot

START_BTN_PCT = (0.4990, 0.7169)


def main() -> int:
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        print("[FAIL] setup did not complete")
        return 1
    try:
        if not r._ensure_game_focused("auto start probe"):
            print("[FAIL] the game would not come to the front -- not clicking")
            return 1
        frame = r._grab()
        if frame is None:
            print("[FAIL] no frame")
            return 1
        from rok_farm.state_probe import dim_ratio
        ratio = dim_ratio(frame)
        print(f"  dim ratio before: {ratio:.2f} "
              f"({'panel is open' if ratio > 1.8 else 'NO PANEL -- wrong screen'})")
        if ratio <= 1.8:
            print("[FAIL] the auto panel is not open; run probe_auto_button first")
            return 1
        save_screenshot(frame, "PROBE3_before_start")

        print(f"  pressing BAT DAU at pct{START_BTN_PCT}")
        r._click_pct(*START_BTN_PCT, jitter_px=6)
        time.sleep(random.uniform(2.5, 3.5))

        after = r._grab()
        if after is None:
            print("[FAIL] no frame after the click")
            return 1
        path = save_screenshot(after, "PROBE3_after_start")
        print(f"  after: {path}")
        print(f"  dim ratio after: {dim_ratio(after):.2f} "
              f"(back near 1.1 means the panel closed and it started)")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
