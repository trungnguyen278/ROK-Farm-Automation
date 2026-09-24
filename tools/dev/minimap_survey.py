"""Collect the minimap beside the HUD at points spread over the kingdom.

The minimap (top right, at readable zooms) draws the kingdom the camera
stands in, its province lines, and the view as a white outline. Placed
against the HUD read of the same frame, it is what turns the minimap into
tiles -- and the province lines into zones (the operator, 2026-09-24:
"chia zone ... lam di"). The size probe's two walks give two straight lines
of points; a calibration that is to be trusted across the map needs points
spread over it, so this walks a zigzag at the widest readable zoom: columns
of legs north and south, a step west between them, each column ended early
where the HUD leaves the map (another id, or blank).

Output: screenshots/minimap_survey/<stamp>/read_NNN.png (the frame's top
right quarter) and survey.json ([file, [map id, x, y] or null] per read).
The view comes back through the city. Needs the farm stopped (it holds the
board); keeps the game with --keep-game.

    .venv\\Scripts\\python tools\\dev\\minimap_survey.py [--lead 3] [--columns 5] [--legs 6]
        [--step 2] [--keep-game]
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

OUT_ROOT = ROOT / "screenshots" / "minimap_survey"


def walk(r, lead: int, columns: int, legs: int, step: int, map_id: str) -> None:
    """`lead` legs east and `lead` north first, then a zigzag westward:
    `legs` legs south or north a column, `step` legs west between."""
    for axis in (0, 1):
        for _leg in range(lead):
            r._edge_leg(*r._edge_leg_for(axis, +1))
            r._edge_read()
    sign = -1                                   # first column goes south
    for col in range(columns):
        off = 0
        for _leg in range(legs):
            dx, dy = r._edge_leg_for(1, sign)
            r._edge_leg(dx, dy)
            hud = r._edge_read()
            if hud is None or hud[0] != map_id:
                off += 1
                if off >= 2:
                    break
            else:
                off = 0
        print(f"  column {col + 1}/{columns} done, {len(r._edge_kept)} read(s) so far")
        if col + 1 < columns:
            for _leg in range(step):
                r._edge_leg(*r._edge_leg_for(0, -1))
                r._edge_read()
        sign = -sign


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--lead", type=int, default=3)
    ap.add_argument("--columns", type=int, default=5)
    ap.add_argument("--legs", type=int, default=6)
    ap.add_argument("--step", type=int, default=2)
    ap.add_argument("--keep-game", action="store_true")
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
    t0 = time.monotonic()
    try:
        if not r._ensure_game_focused("minimap survey"):
            print("[FAIL] the game would not come to the front")
            return 1
        if not r._step_to_world_map("minimap survey"):
            print("[FAIL] could not reach the world map")
            return 1
        r._edge_settle()
        r._edge_keep_dir, r._edge_kept = out_dir, []
        start = r._edge_read()
        out, back, hud = r._edge_widest_readable()
        print(f"  start {start}, widest readable after {out} out / {back} in: {hud}")
        map_id = (hud or start or [None])[0]
        if map_id is None:
            print("[FAIL] the HUD did not read")
            return 2
        walk(r, args.lead, args.columns, args.legs, args.step, map_id)
        kept = list(r._edge_kept)
        r._edge_keep_dir = None
        r._toggle_view("minimap survey: to the city")
        time.sleep(random.uniform(2.5, 3.5))
        r._view_is_world = False
        back_ok = r._step_to_world_map("minimap survey")
        (out_dir / "survey.json").write_text(json.dumps(
            {"when": datetime.now().isoformat(timespec="seconds"),
             "map_id": map_id, "client": [r.win["width"], r.win["height"]],
             "reads": kept, "seconds": round(time.monotonic() - t0, 1),
             "restored": back_ok}, indent=1), encoding="utf-8")
        on_map = sum(1 for _n, h in kept if h and h[0] == map_id)
        print(f"  {len(kept)} frame(s), {on_map} on {map_id}; back on the world map: "
              f"{back_ok}; saved to {out_dir}")
        return 0
    finally:
        r._edge_keep_dir = None
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
