r"""Capture the launcher's Play button (and optionally the in-game exit confirm).

The bot never guesses where a button is. Run this once so it has a template plus
a fallback position:

    .venv\Scripts\python tools\capture_launcher_btn.py            # Play button
    .venv\Scripts\python tools\capture_launcher_btn.py --start    # start the launcher first
    .venv\Scripts\python tools\capture_launcher_btn.py --exit-confirm

Drag a box around the button in the preview window, then press ENTER (or C to
cancel). Writes:

    templates/launcher/play_btn.png     + profiles/paths.json -> play_btn_pct
    templates/ui/btn_confirm_exit.png   (--exit-confirm)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from rok_farm.config import PATHS_FILE, TEMPLATE_DIR
from rok_farm.game_process import (GameProcess, focus_window, grab_rect)


def _pick_box(img, title: str):
    print("  Drag a box around the button, then press ENTER. Press C to cancel.")
    box = cv2.selectROI(title, img, showCrosshair=False, fromCenter=False)
    cv2.destroyAllWindows()
    x, y, w, h = (int(v) for v in box)
    if w < 5 or h < 5:
        return None
    return x, y, w, h


def _save_template(img, box, rel_path: str) -> Path:
    x, y, w, h = box
    out = Path(TEMPLATE_DIR) / f"{rel_path}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), img[y:y + h, x:x + w])
    return out


def capture_play_button(start_launcher: bool) -> int:
    game = GameProcess()
    print(f"  Launcher path: {game.launcher_path or 'NOT FOUND'}")

    if start_launcher and not game.is_launcher_running():
        if not game.start_launcher():
            return 1
    if not game.is_launcher_running():
        print("  Launcher window not found. Open the launcher first, or pass --start.")
        return 1

    win = game.launcher_window()
    focus_window(win["hwnd"])
    time.sleep(1.0)
    win = game.launcher_window() or win
    img = grab_rect(win)
    if img is None:
        print("  Could not screenshot the launcher window.")
        return 1
    print(f"  Launcher window: {win['width']}x{win['height']} at "
          f"({win['left']},{win['top']}) -- '{win['title']}'")

    box = _pick_box(img, "Select the Play button")
    if box is None:
        print("  Cancelled, nothing written.")
        return 1

    out = _save_template(img, box, "launcher/play_btn")
    x, y, w, h = box
    pct = [round((x + w / 2) / win["width"], 4),
           round((y + h / 2) / win["height"], 4)]

    paths = {}
    if PATHS_FILE.exists():
        paths = json.loads(PATHS_FILE.read_text(encoding="utf-8"))
    if game.launcher_path:
        paths["launcher"] = str(game.launcher_path)
    paths["play_btn_pct"] = pct
    PATHS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PATHS_FILE.write_text(json.dumps(paths, indent=2), encoding="utf-8")

    print(f"  Saved template: {out}")
    print(f"  Saved fallback position {pct} to {PATHS_FILE}")
    return 0


def capture_exit_confirm() -> int:
    game = GameProcess()
    win = game.game_window()
    if not win:
        print("  Game window not found. Open the game and trigger the exit "
              "dialog (ALT+F4), then run this again.")
        return 1
    focus_window(win["hwnd"])
    time.sleep(1.0)
    img = grab_rect(game.game_window() or win)
    if img is None:
        print("  Could not screenshot the game window.")
        return 1

    box = _pick_box(img, "Select the exit-confirm button")
    if box is None:
        print("  Cancelled, nothing written.")
        return 1
    out = _save_template(img, box, "ui/btn_confirm_exit")
    print(f"  Saved template: {out}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", action="store_true",
                        help="Start the launcher if it is not running")
    parser.add_argument("--exit-confirm", action="store_true",
                        help="Capture the in-game exit confirmation button instead")
    args = parser.parse_args()

    if args.exit_confirm:
        sys.exit(capture_exit_confirm())
    sys.exit(capture_play_button(args.start))


if __name__ == "__main__":
    main()
