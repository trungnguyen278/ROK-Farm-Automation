"""Get as far as the building menu and STOP, with the click point marked.

Collect, select, then photograph the three buttons with the training one
circled -- and press nothing. The operator confirms from the picture; three
blind presses earlier today went to a resource bubble, a building menu and the
city's build panel, each time because something was pressed before anyone had
looked.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import cv2

from rok_farm.runner import GemFarmRunner
from rok_farm.screenshots import save_screenshot
from tools.dev.probe_training_popup import find_banners
from tools.dev.probe_training_third import menu_buttons

OUT = (r"C:/Users/LEGION/AppData/Local/Temp/claude/d--ROK-Farm-Automation/"
       r"ffb825e2-dc2c-4891-a7bd-3b4be56ec1a8/scratchpad/train_confirm.png")


def main() -> int:
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        return 1
    try:
        if not r._ensure_game_focused("training confirm"):
            return 1
        frame = r._grab()
        h, w = frame.shape[:2]

        btns = menu_buttons(frame)
        if len(btns) != 3:
            banners = find_banners(frame)
            print(f"  {len(banners)} banner(s) ready")
            if not banners:
                print("[FAIL] nothing ready and no menu up")
                return 1
            cx, cy, bw, bh = banners[0]
            tx, ty = cx, cy + int(bh * 1.2)
            print(f"  collecting: click ({tx},{ty})")
            r._click_pct(tx / w, ty / h, jitter_px=3)
            time.sleep(1.6)
            print(f"  selecting:  click ({tx},{ty}) again")
            r._click_pct(tx / w, ty / h, jitter_px=3)
            time.sleep(1.8)
            frame = r._grab()
            btns = menu_buttons(frame)

        print(f"  menu buttons: {[(b['x'], b['y'], round(b['green'], 2)) for b in btns]}")
        if len(btns) != 3:
            save_screenshot(frame, "CONFIRM_no_menu")
            print("[FAIL] the three-button menu is not up")
            return 1

        target = btns[-1]
        shot = frame.copy()
        for b, name in zip(btns, ("info", "NANG CAP - tranh", "huan luyen?")):
            col = (0, 0, 255) if b is target else (160, 160, 160)
            cv2.circle(shot, (b["x"], b["y"]), b["r"] + 6, col, 3)
            cv2.putText(shot, name, (b["x"] - 70, b["y"] - b["r"] - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2, cv2.LINE_AA)
        cv2.circle(shot, (target["x"], target["y"]), 7, (255, 255, 255), -1)
        cv2.circle(shot, (target["x"], target["y"]), 4, (0, 0, 255), -1)
        cv2.imwrite(OUT, shot)
        print(f"  marked image: {OUT}")
        print(f"  WOULD click ({target['x']},{target['y']}) -- pressed nothing")
        return 0
    finally:
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
