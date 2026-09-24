"""Read the map's size at its bottom-right corner (rok_farm.map_edge).

The operator, 2026-09-24: "zoom out max roi xac dinh goc duoi ben phai de
zoom in lay toa do tu do xac dinh tuong doi do lon map". Out to the far view,
pan until the camera is held at the bottom-right corner, back in until the
HUD reads: X there is the size - 1. Tried first on the home kingdom, whose
size is known (1200), before the farm trusts it on a KvK map.

Output: screenshots/map_edge/<stamp>/ -- far_limit, far_corner, first_read,
corner_read .png and probe.json (every leg's frame change, every HUD read).
The view comes back through the city, the one road whose end is known.

Needs the farm stopped (it holds the board). Closes the game at the end
unless --keep-game.

    .venv\\Scripts\\python tools\\dev\\map_edge_probe.py [--keep-game]
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

OUT_ROOT = ROOT / "screenshots" / "map_edge"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
    try:
        if not r._ensure_game_focused("map edge probe"):
            print("[FAIL] the game would not come to the front")
            return 1
        if not r._step_to_world_map("edge probe"):
            print("[FAIL] could not reach the world map")
            return 1
        r._edge_settle()
        res = r._probe_map_size(out_dir)
        print(f"  result: {json.dumps(res)}")
        # Back to icon zoom by the known road.
        r._toggle_view("edge probe: to the city")
        time.sleep(random.uniform(2.5, 3.5))
        r._view_is_world = False
        back = r._step_to_world_map("edge probe")
        res["restored_gauge"] = r.read_zoom_gauge() if back else None
        print(f"  back on the world map: {back}, gauge {res['restored_gauge']}")
        (out_dir / "probe.json").write_text(json.dumps(
            {"when": datetime.now().isoformat(timespec="seconds"),
             "client": [r.win["width"], r.win["height"]], **res}, indent=1),
            encoding="utf-8")
        print(f"  saved to {out_dir}")
        return 0 if "size" in res else 2
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
