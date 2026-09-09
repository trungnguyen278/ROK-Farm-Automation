"""What the bot has learned about the world map, per map.

Two kinds of knowledge, and they must NOT be stored as one thing:

  * TERRAIN -- "this cell is mountain / void". A mountain does not move. This
    survives everything, including teleporting the city to another zone.
  * REACH   -- "I could not get there" / "nothing grows there". This is only
    true relative to where the city currently sits and which passes the
    alliance holds. Teleport away, or lose a pass, and it is worthless.

Conflating them was the mistake: the map is split into zones walled off by
mountains, with passes acting as gates between them (Zone 1, the starting zone
at the map edge, only carries low-tier deposits). So "unreachable" is a fact
about the CURRENT position, while "mountain" is a fact about the WORLD.

Keyed by the map id the HUD prints (`#3560 X:7 Y:86`), so the home kingdom and
a KvK map keep separate books automatically, with no configuration.
"""

from __future__ import annotations

import json
import math
import statistics
import time

from rok_farm import PROJECT_ROOT
from rok_farm.logging_setup import INFO, logger

MEM_DIR = PROJECT_ROOT / "data" / "map_knowledge"

# Coordinates are integers; bucket them so the book stays small and one lucky
# or unlucky tile does not speak for its whole neighbourhood.
CELL = 8

# A pass changing hands makes "unreachable" stale, so REACH observations fade.
# Terrain never does.
REACH_HALFLIFE_H = 18.0

# Teleport detection compares the CURRENT position against a rolling median of
# recent ones, not against the single previous reading.
#
# The first attempt compared consecutive readings with a 120 threshold and fired
# 42 times in one afternoon without a single real teleport -- wiping the reach
# book each time, which is exactly why the feature learned nothing. The mistake
# was conceptual: a teleport moves the CITY, but what we can see is the CAMERA,
# and the camera roams by design (every city round-trip drops it somewhere new).
# A rolling median plus a sustained-departure requirement tells a genuine
# relocation apart from ordinary roaming.
TELEPORT_JUMP = 400
TELEPORT_WINDOW = 20          # positions kept for the median
TELEPORT_CONFIRM = 3          # consecutive far readings before believing it


def _key(x: int, y: int) -> str:
    return f"{int(x) // CELL},{int(y) // CELL}"


class MapMemory:
    """Per-map learned grid. Cheap to update, cheap to consult."""

    def __init__(self, map_id: str):
        self.map_id = str(map_id)
        self.path = MEM_DIR / f"{self.map_id}.json"
        self.terrain: dict[str, dict] = {}
        self.reach: dict[str, dict] = {}
        self._recent: list[tuple[int, int]] = []
        self._far_streak = 0
        self.load()

    # --- persistence ---

    def load(self):
        if not self.path.exists():
            return
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.terrain = d.get("terrain", {})
            self.reach = d.get("reach", {})
            logger.info("MapMemory %s: %d terrain cell(s), %d reach cell(s)",
                        self.map_id, len(self.terrain), len(self.reach))
        except Exception as e:
            logger.warning("MapMemory %s unreadable (%s) -- starting fresh",
                           self.map_id, e)

    def save(self):
        try:
            MEM_DIR.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(
                {"terrain": self.terrain, "reach": self.reach}, indent=1),
                encoding="utf-8")
        except Exception as e:
            logger.warning("MapMemory save failed: %s", e)

    # --- teleport ---

    def note_position(self, x: int, y: int) -> bool:
        """Track where we are; return True if the CITY looks to have relocated.

        A teleport keeps the terrain book (mountains are still mountains) and
        drops the reach book, because the city is now inside a different walled
        area and every "could not get there" was about the old one.

        Judged against a rolling median rather than the previous reading, and
        only after several consecutive far readings, because the camera moves a
        long way on its own between mines and a single jump proves nothing.
        """
        pos = (int(x), int(y))
        self._recent.append(pos)
        if len(self._recent) > TELEPORT_WINDOW:
            self._recent.pop(0)
        if len(self._recent) < TELEPORT_WINDOW // 2:
            return False
        mid = (statistics.median(p[0] for p in self._recent),
               statistics.median(p[1] for p in self._recent))
        if math.dist(mid, pos) < TELEPORT_JUMP:
            self._far_streak = 0
            return False
        self._far_streak += 1
        if self._far_streak < TELEPORT_CONFIRM:
            return False
        self._far_streak = 0
        self._recent = [pos]
        prev = (int(mid[0]), int(mid[1]))
        print(f"  [{INFO}] Teleport detected {prev} -> {pos}: keeping terrain, "
              f"dropping {len(self.reach)} reachability cell(s)")
        logger.info("Teleport %s -> %s on map %s; reach book cleared",
                    prev, pos, self.map_id)
        self.reach = {}
        self.save()
        return True

    # --- learning ---

    def record_wall(self, x: int, y: int):
        """Mountain / out-of-kingdom void seen here. Permanent."""
        k = _key(x, y)
        c = self.terrain.setdefault(k, {"wall": 0})
        c["wall"] = c.get("wall", 0) + 1

    def record_scan(self, x: int, y: int, found_gem: bool):
        k = _key(x, y)
        c = self.reach.setdefault(k, {"gem": 0, "empty": 0, "t": 0.0})
        c["gem" if found_gem else "empty"] += 1
        c["t"] = time.time()
        # Persist periodically. The first version only saved when a WALL was
        # recorded, so every scan observation lived in RAM and died with the
        # process -- after a day of restarts the terrain book had 15 cells while
        # the reach book had 3, i.e. half the feature was never actually on.
        self._dirty = getattr(self, "_dirty", 0) + 1
        if self._dirty >= 10:
            self._dirty = 0
            self.save()

    # --- consulting ---

    def is_wall(self, x: int, y: int) -> bool:
        return self.terrain.get(_key(x, y), {}).get("wall", 0) > 0

    def score(self, x: int, y: int) -> float:
        """How promising this cell looks. 0 is neutral, negative is bad.

        Walls dominate: a cell known to be mountain is never worth steering
        into, however many gems once sat next to it.
        """
        if self.is_wall(x, y):
            return -10.0
        c = self.reach.get(_key(x, y))
        if not c:
            return 0.0            # unexplored is neutral, not bad -- go look
        age_h = (time.time() - c.get("t", 0)) / 3600.0
        weight = 0.5 ** (age_h / REACH_HALFLIFE_H)
        return (c.get("gem", 0) * 2.0 - c.get("empty", 0) * 0.5) * weight

    def heading_score(self, x: int, y: int, heading: float,
                      reach_cells: int = 6) -> float:
        """Sum the scores along a heading, a few cells out."""
        total = 0.0
        for step in range(1, reach_cells + 1):
            d = step * CELL
            total += self.score(int(x + math.cos(heading) * d),
                                int(y + math.sin(heading) * d))
        return total

    def stats(self) -> str:
        return (f"map {self.map_id}: {len(self.terrain)} wall cell(s), "
                f"{len(self.reach)} scanned cell(s)")
