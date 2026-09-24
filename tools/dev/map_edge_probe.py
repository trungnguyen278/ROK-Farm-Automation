"""Measure the map's size at its edges (rok_farm.map_edge).

The operator, 2026-09-24: zoom out, find the map's corner, read the
coordinates there. The first try (20260924_124014) found the far view held
inside the kingdom but the world going on past its edge at readable zooms,
so this walks east and north at the widest readable zoom until the HUD names
the kingdom next door: the last X and Y read on this map snap to its size.
Tried on the home kingdom, whose size is known (1200), before the farm
trusts it on a KvK map.

It runs the farm's whole trip on a new KvK map (MapEdgeMixin._survey_map):
the size, then the provinces from the minimap crops the walks kept -- a
spread walk too if the home calibration does not fit. The map's saved
provinces (data/map_knowledge) are left alone; the trip's go beside them
for comparison.

Output: screenshots/map_edge/<stamp>/ -- widest_readable, east_end,
north_end .png, read_NNN.png (the minimap beside each read), provinces.png
(the trip's province per book cell) and probe.json. The view comes back
through the city, the one road whose end is known.

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

import cv2  # noqa: E402
import numpy as np  # noqa: E402

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
        # The farm's own trip on a new KvK map: the size and the provinces.
        city = getattr(r, "_city_xy", None) or (tuple(r.mapmem.city) if getattr(
            r.mapmem, "city", None) else None)
        res = r._survey_map(city=city, out_dir=out_dir)
        res["frames"] = list(r._edge_kept)
        prov = res.pop("provinces", {}) or {}
        if "grid" in prov:
            grid = np.asarray(prov.pop("grid"), np.uint8)
            cv2.imwrite(str(out_dir / "provinces.png"), grid)
            known = ROOT / "data" / "map_knowledge" / f"{res.get('map_id')}_provinces.png"
            if known.exists():
                ref = cv2.imread(str(known), cv2.IMREAD_UNCHANGED)
                if ref is not None and ref.shape == grid.shape:
                    prov["same_as_saved_pct"] = round(100.0 * float((ref == grid).mean()), 2)
        res["provinces"] = prov
        print(f"  result: {json.dumps({k: v for k, v in res.items() if k != 'frames'})}")
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
