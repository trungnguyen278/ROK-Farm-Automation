"""Step two: open the game's own auto mode from the barbarian search panel.

The operator is walking me through their AP-spending flow one screen at a
time. Step one (tools/dev/probe_search_button.py) opened the search panel;
this presses the little round button beside TIM KIEM, which is how the game's
built-in auto is opened.

Their two warnings, both encoded here:
  * the panel sometimes comes up on the "Phao dai Barbaria" tab, and the
    button is not there -- so switch back to "Nguoi man ro" first;
  * the auto is a VIP feature and needs two or three minutes after the client
    starts before it will run, otherwise it errors.

Measured on the frame from step one (1533x862 client):
  gear button   centre (570, 654) r=17   -> pct (0.3718, 0.7587)
  barbarian tab centre (375, 458)        -> pct (0.2446, 0.5313)
  the active tab reads mean saturation 78, the inactive one 38.
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

AUTO_BTN_PCT = (0.3718, 0.7587)
BARB_TAB_PCT = (0.2446, 0.5313)
TAB_ACTIVE_SAT = 55          # between the measured 78 (active) and 38 (not)
WARMUP_S = 180               # the operator's "wait 2-3 minutes after entering"


def tab_saturation(frame, pct) -> float:
    h, w = frame.shape[:2]
    x, y = int(w * pct[0]), int(h * pct[1])
    patch = frame[y - 14:y + 14, x - 55:x + 55]
    if patch.size == 0:
        return -1.0
    return float(cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)[:, :, 1].mean())


def main() -> int:
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        print("[FAIL] setup did not complete")
        return 1
    try:
        from rok_farm.session_control import game_proc
        proc = game_proc()
        up = (time.time() - proc.create_time()) if proc else None
        if up is not None:
            print(f"  client has been up {up / 60:.1f} min "
                  f"({'past' if up >= WARMUP_S else 'UNDER'} the {WARMUP_S // 60}"
                  f"-minute warm-up the auto needs)")

        if not r._ensure_game_focused("auto button probe"):
            print("[FAIL] the game would not come to the front -- not clicking")
            return 1

        frame = r._grab()
        if frame is None:
            print("[FAIL] no frame")
            return 1
        save_screenshot(frame, "PROBE2_before_auto")

        sat = tab_saturation(frame, BARB_TAB_PCT)
        print(f"  barbarian tab saturation {sat:.0f} "
              f"(active reads ~78, inactive ~38)")
        if sat < TAB_ACTIVE_SAT:
            print("  [..] the panel is on the other tab -- switching back first")
            r._click_pct(*BARB_TAB_PCT, jitter_px=5)
            time.sleep(random.uniform(1.0, 1.8))
            frame = r._grab()

        print(f"  clicking the auto button at pct{AUTO_BTN_PCT}")
        r._click_pct(*AUTO_BTN_PCT, jitter_px=5)
        time.sleep(random.uniform(2.0, 3.0))

        after = r._grab()
        if after is None:
            print("[FAIL] no frame after the click")
            return 1
        path = save_screenshot(after, "PROBE2_after_auto")
        print(f"  after: {path}")
        from rok_farm.state_probe import dim_ratio
        print(f"  dim ratio: {dim_ratio(after):.2f}")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
