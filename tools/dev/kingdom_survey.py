"""Look at the whole kingdom: zoom the world map out to its limit, a notch at
a time, and keep every step -- then put the zoom back. A survey, not a farm
step.

The operator, 2026-09-23/24: the walls between zones are fixed, and the
game shows them -- "the minimap top right when zoomed out, or zoom out to
the limit". Zones are wanted so that a deposit out of reach can rule out its
whole zone (tomorrow's KvK map will need it more than home does). What the
far zooms look like has not been seen by this code yet, so this only
collects: a frame and a HUD reading per notch, nothing inferred.

Output: screenshots/kingdom_survey/<stamp>/step_NN.png (the raw client
frame) and survey.json there: per step the notches scrolled, the HUD read
(map id, x, y) or None, the zoom gauge, and how much the frame changed.

The zoom goes back through the city: toggling to the city and back reopens
the map on the city at the standard zoom, and the usual 3 notches out bring
it to icon zoom -- the one path whose result is known.

Needs the farm stopped (it holds the board). Closes the game at the end
unless --keep-game (use that when the farm is started straight after).

    .venv\\Scripts\\python tools\\dev\\kingdom_survey.py [--max-steps 14] [--keep-game]
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from rok_farm.config import ZOOM_OUT_QUIET_DIFF  # noqa: E402

OUT_ROOT = ROOT / "screenshots" / "kingdom_survey"
# A notch that changes the frame less than this (mean abs diff, 0-255) did
# not zoom: the limit is reached. Two such in a row end the walk out.
STILL_DIFF = 1.5


def wait_still(r, cap=5.0) -> float:
    """Until two looks in a row show the map not moving, capped."""
    t0 = time.monotonic()
    prev, quiet = None, 0
    while time.monotonic() - t0 < cap:
        frame = r._grab()
        cur = r._settle_patch(frame) if frame is not None else None
        if cur is not None:
            if prev is not None:
                if float(np.mean(cv2.absdiff(prev, cur))) < ZOOM_OUT_QUIET_DIFF:
                    quiet += 1
                    if quiet >= 2:
                        break
                else:
                    quiet = 0
            prev = cur
        time.sleep(random.uniform(0.07, 0.11))
    return time.monotonic() - t0


def raw_frame(r, wait=4.0):
    """The raw client frame, waiting for one if the capture has none.

    The capture double-buffers, and on a still screen WGC hands over no new
    frame until something changes -- so right after setup, with one frame
    delivered and already taken, _grab() returns None for a while. The first
    run of this tool (2026-09-24 11:17) died writing that None to disk.
    """
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait:
        if r._grab() is not None and r._raw_frame is not None:
            return r._raw_frame.copy()
        time.sleep(0.1)
    return None


def zoom_until(r, direction: int, want_hud: bool, max_notches: int = 24):
    """Scroll one notch at a time (-1 out, +1 in) until the HUD position
    reads (want_hud) or stops reading (not want_hud). Returns (notches
    scrolled, the HUD read at the stop, the last HUD read before it)."""
    last_read = r._read_map_position(raw_frame(r))
    for n in range(1, max_notches + 1):
        r._scroll_at_center(direction, 1)
        time.sleep(random.uniform(0.35, 0.6))
        wait_still(r)
        hud = r._read_map_position(raw_frame(r))
        if (hud is not None) == want_hud:
            return n, hud, last_read
        if hud is not None:
            last_read = hud
    return max_notches, None, last_read


def zoom_to_limit(r, max_notches: int = 24) -> int:
    """Out until the frame stops changing; returns the notches scrolled."""
    prev = raw_frame(r)
    still = 0
    for n in range(1, max_notches + 1):
        r._scroll_at_center(-1, 1)
        time.sleep(random.uniform(0.35, 0.6))
        wait_still(r)
        frame = raw_frame(r)
        diff = float(np.mean(cv2.absdiff(cv2.resize(prev, (320, 180)),
                                         cv2.resize(frame, (320, 180)))))
        prev = frame
        still = still + 1 if diff < STILL_DIFF else 0
        if still >= 2:
            return n
    return max_notches


def calibrate_leg(r, dx_frac: float, dy_frac: float, out_dir: Path, tag: str):
    """One calibration: HUD at the far edge of readable, out to the limit,
    a measured drag (two halves, pointer kept off the window's edge), in
    until the HUD reads again. Tiles moved over pixels dragged."""
    from capture.screen_info import get_cursor_pos
    win = r.win
    n_out, _hud, before = zoom_until(r, -1, want_hud=False)
    zoom_to_limit(r)
    cv2.imwrite(str(out_dir / f"{tag}_limit_before.png"), raw_frame(r))
    cx = win["left"] + win["width"] // 2
    cy = win["top"] + win["height"] // 2
    hx, hy = int(win["width"] * dx_frac / 2), int(win["height"] * dy_frac / 2)
    total = [0, 0]
    for _half in range(2):
        sx, sy = cx + hx // 2, cy + hy // 2
        ex, ey = cx - hx // 2, cy - hy // 2
        r._moveto(sx, sy)
        time.sleep(random.uniform(0.12, 0.3))
        c0 = get_cursor_pos()
        r._human_drag(c0[0], c0[1], ex, ey, speed_factor=random.uniform(1.0, 1.4),
                      hold_ms=random.randint(320, 480))
        c1 = get_cursor_pos()
        total[0] += c1[0] - c0[0]
        total[1] += c1[1] - c0[1]
        wait_still(r)
    cv2.imwrite(str(out_dir / f"{tag}_limit_after.png"), raw_frame(r))
    n_in, after, _last = zoom_until(r, +1, want_hud=True)
    res = {"tag": tag, "hud_before": before, "hud_after": after,
           "drag_px": total, "notches_out_to_blank": n_out,
           "notches_in_to_read": n_in}
    if before and after and before[0] == after[0]:
        dX, dY = after[1] - before[1], after[2] - before[2]
        res["tiles"] = [dX, dY]
        # The pointer dragged left moves the camera east: tiles and pixels
        # run opposite ways in X, and (screen down = -Y) the same way in Y.
        if abs(total[0]) > 100 and dX:
            res["px_per_tile_x"] = round(-total[0] / dX, 3)
        if abs(total[1]) > 100 and dY:
            res["px_per_tile_y"] = round(total[1] / dY, 3)
    print(f"  {tag}: {res}")
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max-steps", type=int, default=14)
    ap.add_argument("--keep-game", action="store_true")
    ap.add_argument("--calibrate", type=int, default=0, metavar="N",
                    help="instead of the walk out: N pairs of calibration "
                         "drags (one across, one down) at the zoom limit")
    args = ap.parse_args()

    from rok_farm import session_control as sc
    if sc.farm_procs():
        print("[FAIL] the farm is running and holds the board -- stop it first")
        return 1

    from rok_farm.runner import GemFarmRunner
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        print("[FAIL] setup did not complete")
        return 1
    out_dir = OUT_ROOT / datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    steps = []
    try:
        if not r._ensure_game_focused("kingdom survey"):
            print("[FAIL] the game would not come to the front")
            return 1
        if not r._step_to_world_map("survey"):
            print("[FAIL] could not reach the world map")
            return 1
        wait_still(r)
        prev = raw_frame(r)
        if prev is None:
            print("[FAIL] no frame from the capture")
            return 1
        start = r._read_map_position(prev)
        steps.append({"notches": 0, "hud": start, "gauge": r.read_zoom_gauge(),
                      "diff": None})
        cv2.imwrite(str(out_dir / "step_00.png"), prev)
        print(f"  start {start}, gauge {steps[0]['gauge']}, saving to {out_dir}")
        calibration = []
        for k in range(args.calibrate):
            # Alternate the way, so the camera wanders back and stays on the
            # map: ~0.3 of the window is a few hundred tiles at the limit.
            sign = 1 if k % 2 == 0 else -1
            calibration.append(calibrate_leg(r, 0.3 * sign, 0.0, out_dir, f"x{k}"))
            calibration.append(calibrate_leg(r, 0.0, 0.3 * sign, out_dir, f"y{k}"))
        still = 0
        for n in range(1, 0 if args.calibrate else args.max_steps + 1):
            if not r._ensure_game_focused("kingdom survey"):
                print("[FAIL] lost the foreground -- stopping the walk out")
                break
            r._scroll_at_center(-1, 1)
            time.sleep(random.uniform(0.35, 0.6))
            wait_still(r)
            frame = raw_frame(r)
            if frame is None:
                continue
            diff = (float(np.mean(cv2.absdiff(
                cv2.resize(prev, (320, 180)), cv2.resize(frame, (320, 180)))))
                if prev is not None else None)
            hud = r._read_map_position(frame)
            steps.append({"notches": n, "hud": hud, "gauge": None, "diff": diff})
            cv2.imwrite(str(out_dir / f"step_{n:02d}.png"), frame)
            print(f"  notch {n:2d}: hud {hud}, frame change {diff:.1f}")
            prev = frame
            still = still + 1 if diff is not None and diff < STILL_DIFF else 0
            if still >= 2:
                print("  the zoom stopped changing -- the limit")
                break
            time.sleep(random.uniform(0.4, 0.9))
        # Back to icon zoom by the known road.
        r._toggle_view("survey: to the city")
        time.sleep(random.uniform(2.5, 3.5))
        r._view_is_world = False
        back = r._step_to_world_map("survey")
        gauge = r.read_zoom_gauge() if back else None
        print(f"  back on the world map: {back}, gauge {gauge}")
        (out_dir / "survey.json").write_text(json.dumps(
            {"when": datetime.now().isoformat(timespec="seconds"),
             "client": [r.win["width"], r.win["height"]],
             "steps": steps, "calibration": calibration,
             "restored_gauge": gauge}, indent=1),
            encoding="utf-8")
        print(f"  saved {len(steps)} step(s) to {out_dir}")
        return 0
    finally:
        if not args.keep_game:
            try:
                r.game.quit_game(r)
            except Exception as e:
                print(f"[WARN] could not close the game: {e} -- close it by hand")
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
