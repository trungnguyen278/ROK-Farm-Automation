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

# A kingdom's own map is 1200 tiles a side (X and Y 0-1199), and its id is a
# number (#4096). Its edges are known from the coordinates -- nothing about
# them needs learning. Logged on 4096: X up to 1177 (2026-09-14..16), and
# over 5,002 accepted steps every Y past 1150 -- 18 of them -- was the digit
# collision in queue_ocr (196 read as 1965, 524 as 5240).
HOME_TILES = 1200
# A KvK map's id is not a number (#S11465, 2026-09-09..18) and its size is
# not known before it is seen: 1200, 1440 or 2400 by KvK type (researched
# 2026-09-23 through AI Mode, not checked on a map yet). The HUD is read up to
# the largest; the book starts at the smallest and steps up one size at a
# time (note_extent). Too small keeps the sweep off ground past the edge
# until the camera has read positions there; too large would send it at
# ground that is not there, over and over.
MAP_SIZES = (1200, 1440, 2400)
# Positions read past the book's edge within SIZE_WINDOW_S before it grows.
# A camera out there reads one every scan (6-29 tiles apart, a few seconds
# each); what slips past the misread hold in _map_sync comes as an isolated
# pair at most (twice in one pan survey, 2026-09-23), and spread over days
# must not add up.
SIZE_EVIDENCE = 5
SIZE_WINDOW_S = 600.0


def is_home_map(map_id) -> bool:
    """A kingdom's own map: its id is all digits (#4096; KvK: #S11465)."""
    return str(map_id).isdigit()


def read_limit(map_id) -> int:
    """No coordinate on this map reaches this: a larger one is a misread.

    A home map is 1200; a KvK map is read up to the largest size there is,
    so that a map larger than the book believes is never read blind.
    """
    return HOME_TILES if is_home_map(map_id) else MAP_SIZES[-1]


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
        # Where the camera has been, [time, x, y] per position read -- the
        # trajectory the operator asked to keep (2026-09-23) so ground near the
        # city is not left unscanned once the wander has gone far.
        self.track: list[list] = []
        self._recent: list[tuple[int, int]] = []
        self._far_streak = 0
        # Tiles a side. Fixed for a home map; learned for any other.
        self.size = HOME_TILES if is_home_map(self.map_id) else MAP_SIZES[0]
        self._past_edge: list[tuple[float, int]] = []
        # Read at the map's corner (map_edge) -- then it is not a guess any
        # more -- and when that was last tried.
        self.size_measured = False
        self.size_probe_t = 0.0
        self.size_probe_tries = 0
        self.load()

    # --- persistence ---

    def load(self):
        if not self.path.exists():
            return
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.terrain = d.get("terrain", {})
            self.reach = d.get("reach", {})
            self.track = d.get("track", [])
            city = d.get("city")
            if city:
                self.city = (int(city[0]), int(city[1]))
            self.unreachable = d.get("unreachable", [])
            # A KvK map's size as learned -- or as the operator wrote it in
            # the file with the farm stopped. A home map's is not a question.
            if not is_home_map(self.map_id):
                if d.get("size"):
                    self.size = int(d["size"])
                self.size_measured = bool(d.get("size_measured"))
            # When the map was last surveyed, and how often: every map, a home
            # kingdom's provinces are surveyed too.
            self.size_probe_t = float(d.get("size_probe_t") or 0.0)
            self.size_probe_tries = int(d.get("size_probe_tries") or 0)
            logger.info("MapMemory %s: %d terrain cell(s), %d reach cell(s)",
                        self.map_id, len(self.terrain), len(self.reach))
        except Exception as e:
            logger.warning("MapMemory %s unreadable (%s) -- starting fresh",
                           self.map_id, e)

    def save(self):
        try:
            MEM_DIR.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(
                {"terrain": self.terrain, "reach": self.reach,
                 "track": self.track,
                 "city": list(getattr(self, "city", None) or []) or None,
                 "unreachable": getattr(self, "unreachable", []),
                 "size": self.size, "size_measured": self.size_measured,
                 "size_probe_t": self.size_probe_t,
                 "size_probe_tries": self.size_probe_tries},
                indent=1),
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

    # --- the map's size ---

    def set_measured_size(self, size: int) -> None:
        """The size read at the map's corner (map_edge). Positions past it
        can still grow it (note_extent): a read is evidence too."""
        old = self.size
        self.size, self.size_measured = int(size), True
        print(f"  [{INFO}] Map {self.map_id} measured at its corner: "
              f"{self.size} tiles a side")
        logger.info("Map %s measured %d tiles a side (was %d)", self.map_id,
                    self.size, old)
        self.save()

    def note_extent(self, x: int, y: int, now: float | None = None) -> bool:
        """A position read on this map; True if it made the map larger.

        A home map is HOME_TILES and stays so. Any other map grows one size
        of MAP_SIZES at a time, once SIZE_EVIDENCE positions within
        SIZE_WINDOW_S lie past its edge -- to the smallest size that holds
        the NEAREST of them, so a misread among real reads past 1200 cannot
        carry the book to 2400 by itself.
        """
        if is_home_map(self.map_id) or self.size >= MAP_SIZES[-1]:
            return False
        far = max(int(x), int(y))
        if far < self.size:
            return False
        now = time.time() if now is None else now
        self._past_edge = [(t, v) for t, v in self._past_edge
                           if now - t <= SIZE_WINDOW_S]
        self._past_edge.append((now, far))
        if len(self._past_edge) < SIZE_EVIDENCE:
            return False
        nearest = min(v for _t, v in self._past_edge)
        old = self.size
        self.size = next((s for s in MAP_SIZES if s > nearest), MAP_SIZES[-1])
        self._past_edge = []
        print(f"  [{INFO}] Map {self.map_id} is larger than {old} tiles a side: "
              f"now {self.size}")
        logger.info("Map %s grew %d -> %d tiles a side (%d positions past the "
                    "edge in %.0fs, nearest %d)", self.map_id, old, self.size,
                    SIZE_EVIDENCE, SIZE_WINDOW_S, nearest)
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

    # --- ground we cannot march to --------------------------------------
    #
    # The operator, 2026-09-23: clicking Gather on a deposit in a zone we
    # cannot enter makes the game carry the camera to the uncaptured pass in
    # the way, and no deploy panel opens. The deposit's tile is known, so
    # remember the ground around it as out of reach -- for as long as the
    # city stays where it was (a teleport changes which zones are open).
    #
    # One point is one deposit, so points are joined into ground: a disc
    # around each, and the strip between any two close enough to be the same
    # zone. A first version; zone outlines, if they turn out to be the same
    # on every map, would replace this. All three numbers are starting values
    # -- no such case has been seen yet (see PASS_PAN_MIN_TILES).
    UNREACH_RADIUS = 30
    UNREACH_LINK = 80
    UNREACH_CITY_TOL = 20

    def record_unreachable(self, site, city, pass_xy=None):
        pts = getattr(self, "unreachable", [])
        pts.append({"x": int(site[0]), "y": int(site[1]), "t": time.time(),
                    "city": [int(city[0]), int(city[1])],
                    "pass": [int(pass_xy[0]), int(pass_xy[1])] if pass_xy else None})
        self.unreachable = pts
        self.save()

    def _unreach_points(self, city, now: float | None = None):
        """Out-of-reach deposits recorded from this city, in the last
        REACH_HALFLIFE_H: a pass changes hands, and one deposit now closes
        its whole province -- kept for ever, a pass the alliance takes
        would never open it again. Still closed, the next march there
        records it afresh."""
        if not city:
            return []
        now = time.time() if now is None else now
        tol = self.UNREACH_CITY_TOL
        fresh = REACH_HALFLIFE_H * 3600.0
        return [(p["x"], p["y"]) for p in getattr(self, "unreachable", [])
                if max(abs(p["city"][0] - city[0]),
                       abs(p["city"][1] - city[1])) <= tol
                and now - p.get("t", now) <= fresh]

    # --- provinces ---
    #
    # The zones themselves, where the map has been surveyed: the minimap
    # draws the kingdom's province lines, and tools/dev/minimap_zones.py
    # --save turns them into the province of every book cell (home kingdom
    # 4096, 2026-09-24: 10 provinces, the standard 6 + 3 + 1).

    def _province_grid(self):
        if not hasattr(self, "_provinces"):
            self._provinces = None
            path = MEM_DIR / f"{self.map_id}_provinces.png"
            if path.exists():
                import cv2
                grid = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
                if grid is not None and grid.ndim == 2:
                    self._provinces = grid
        return self._provinces

    def has_provinces(self) -> bool:
        return self._province_grid() is not None

    @property
    def size_known(self) -> bool:
        """A home kingdom's size is the rule (1200); a KvK map's is known
        once measured at its edges."""
        return is_home_map(self.map_id) or self.size_measured

    def needs_survey(self) -> bool:
        """The operator, 2026-09-24: what the map is -- its size, its zones
        -- is looked up in the book; only a map the book knows nothing
        about is surveyed, once."""
        return not (self.size_known and self.has_provinces())

    def reload_provinces(self) -> None:
        """Read the province file again (a survey has just written it)."""
        self.__dict__.pop("_provinces", None)

    def province_of(self, x: int, y: int) -> int | None:
        """The province this tile lies in, or None (map not surveyed)."""
        grid = self._province_grid()
        if grid is None:
            return None
        i, j = int(x) // CELL, int(y) // CELL
        if 0 <= j < grid.shape[0] and 0 <= i < grid.shape[1]:
            return int(grid[j, i]) or None
        return None

    def unreachable_at(self, x: int, y: int, city=None) -> bool:
        """Is this tile in ground we could not march to (from this city)?"""
        city = city if city is not None else getattr(self, "city", None)
        pts = self._unreach_points(city)
        if not pts:
            return False
        # A deposit out of reach puts its whole province out of reach -- the
        # pass in the way closes all of it. Never the city's own province:
        # it is always open to the city, and closing it would stop the sweep.
        prov = self.province_of(x, y)
        if prov is not None and prov != self.province_of(*city):
            if prov in {self.province_of(px, py) for px, py in pts}:
                return True
        r = self.UNREACH_RADIUS
        for px, py in pts:
            if max(abs(px - x), abs(py - y)) <= r:
                return True
        for i, a in enumerate(pts):
            for b in pts[i + 1:]:
                if max(abs(a[0] - b[0]), abs(a[1] - b[1])) > self.UNREACH_LINK:
                    continue
                # distance from the tile to the segment a-b
                dx, dy = b[0] - a[0], b[1] - a[1]
                t = ((x - a[0]) * dx + (y - a[1]) * dy) / float(dx * dx + dy * dy or 1)
                t = max(0.0, min(1.0, t))
                qx, qy = a[0] + t * dx, a[1] + t * dy
                if math.hypot(x - qx, y - qy) <= r:
                    return True
        return False

    # How long a cell counts as "just looked at" (see score()). Half an hour
    # covers a whole mine and the one after it; a starting value, not a
    # measurement.
    RECENT_S = 30 * 60
    # The most a cell's counts can say. Two gems and four empties are
    # already a clear verdict; beyond that the number only measured how
    # often the camera happened to overlap it.
    GEM_CAP = 2
    EMPTY_CAP = 4

    # A position read every scan is ~600 a day at the current pace; a few
    # days of trajectory is plenty to see where the wander goes, and the file
    # stays small.
    TRACK_MAX = 3000

    def note_track(self, x: int, y: int):
        """One point of the camera's trajectory."""
        self.track.append([int(time.time()), int(x), int(y)])
        if len(self.track) > self.TRACK_MAX:
            del self.track[:len(self.track) - self.TRACK_MAX]

    def last_seen(self, x: int, y: int) -> float | None:
        """When the cell holding this tile was last in view, or None."""
        c = self.reach.get(_key(x, y))
        return c.get("t") if c else None

    def gaps_near(self, city, radius_tiles: float, stale_h: float,
                  now: float | None = None) -> list[tuple[int, int, int]]:
        """Cells near the city that no scan has shown for `stale_h` hours.

        (x, y, tiles from the city) per cell centre. Walls and ground off the
        map are not gaps: nothing can be gathered there, and steering at them
        is what the wall veto exists to prevent.
        """
        now = time.time() if now is None else now
        cx, cy = int(city[0]) // CELL, int(city[1]) // CELL
        r = int(radius_tiles) // CELL
        stale = stale_h * 3600.0
        out = []
        for i in range(cx - r, cx + r + 1):
            for j in range(cy - r, cy + r + 1):
                x, y = i * CELL + CELL // 2, j * CELL + CELL // 2
                if x < 0 or y < 0 or x >= self.size or y >= self.size:
                    continue
                k = f"{i},{j}"
                if self.terrain.get(k, {}).get("wall", 0) > 0:
                    continue
                if self.unreachable_at(x, y, city):
                    continue
                seen = self.reach.get(k, {}).get("t")
                if seen is not None and now - seen < stale:
                    continue
                out.append((x, y, int(max(abs(x - city[0]), abs(y - city[1])))))
        return out

    def frontier(self, city, stale_h: float, full: float = 0.8,
                 max_tiles: int = 400, now: float | None = None) -> int:
        """How far out from the city the ground is covered, in tiles.

        Rings of cells around the city, from the inside out; the first ring
        with less than `full` of its cells seen in the last `stale_h` hours
        is where the covered ground ends. Cells off the map, walls and ground
        out of reach do not count either way -- nothing there can be filled.
        """
        now = time.time() if now is None else now
        stale = stale_h * 3600.0
        cx, cy = int(city[0]) // CELL, int(city[1]) // CELL
        for r in range(0, max_tiles // CELL + 1):
            if r == 0:
                ring = [(cx, cy)]
            else:
                ring = ([(i, cy - r) for i in range(cx - r, cx + r + 1)]
                        + [(i, cy + r) for i in range(cx - r, cx + r + 1)]
                        + [(cx - r, j) for j in range(cy - r + 1, cy + r)]
                        + [(cx + r, j) for j in range(cy - r + 1, cy + r)])
            tot = seen = 0
            for i, j in ring:
                x, y = i * CELL + CELL // 2, j * CELL + CELL // 2
                if x < 0 or y < 0 or x >= self.size or y >= self.size:
                    continue
                k = f"{i},{j}"
                if self.terrain.get(k, {}).get("wall", 0) > 0:
                    continue
                if self.unreachable_at(x, y, city):
                    continue
                tot += 1
                t = self.reach.get(k, {}).get("t")
                if t is not None and now - t < stale:
                    seen += 1
            if tot and seen < full * tot:
                return r * CELL
        return max_tiles

    def record_view(self, cells, gem_cells=()):
        """One frame's worth of ground, every cell it showed at once.

        record_scan marks the single cell under the camera. A frame at icon
        zoom shows about 460 tiles -- seven or so cells (pan_model, measured
        2026-09-23) -- and all but one of them stayed "unexplored" here
        however often they had been looked at, so the steering kept being
        pulled toward ground it had already seen.

        `cells` and `gem_cells` are tile positions; a cell is marked gem if a
        gem icon stood in it, empty otherwise.
        """
        now = time.time()
        gems = {_key(x, y) for x, y in gem_cells}
        keys = {_key(x, y) for x, y in cells} | gems
        for k in keys:
            c = self.reach.setdefault(k, {"gem": 0, "empty": 0, "t": 0.0})
            if k in gems:
                # One sighting per visit, not one per frame: consecutive
                # scans overlap, and the same deposit seen twelve times is
                # still one deposit (see score(), cell 72,79).
                if now - c.get("tg", 0.0) >= self.RECENT_S:
                    c["gem"] += 1
                    c["tg"] = now
            else:
                c["empty"] += 1
            c["t"] = now
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
        # Off the coordinate space is not "unexplored", it is impossible. The
        # lookup below misses on a negative key and returned 0 -- NEUTRAL -- so
        # a heading pointing straight off the edge scored exactly as safely as
        # one pointing into open ground, and the wander walked out of the
        # kingdom again and again. The recorded walls sit at cell y=0 (tile
        # y 0..7), which is that edge; but the border is a long line and the
        # book only ever knows the handful of cells already crossed at, so
        # learning cannot close this. Bounds can.
        #
        # Not a tuned constant: no map has a tile at a negative coordinate.
        if x < 0 or y < 0 or x >= self.size or y >= self.size:
            return -10.0
        if self.is_wall(x, y):
            return -10.0
        # Out of reach: nothing found there can be gathered. The camera may
        # still pass over it, so this steers away rather than vetoing.
        if self.unreachable_at(x, y):
            return -3.0
        c = self.reach.get(_key(x, y))
        if not c:
            # Unexplored used to be NEUTRAL, which is not the same as
            # attractive. Explored-and-empty scores negative, so the wander
            # drifted away from anywhere it had been -- outward, for ever,
            # with no preference between the unseen cell next door and the
            # unseen cell two hundred tiles away. That is how it ended up
            # marching 18 minutes each way while unscanned ground sat beside
            # the city.
            #
            # The operator's correction, 2026-09-22: do not fence it in, give
            # it a route -- "dung gioi han ban kinh qua chi can tao duong di
            # tranh scan thieu thoi tai no co the khan hiem that va phai chiu
            # xa". So unexplored ground is worth going to, and the nearer to
            # the city the more so. That fills the neighbourhood first and
            # expands outward on its own, and when the near ground really is
            # exhausted the far cells are still positive, so distance is a
            # decision rather than a drift.
            return self._unexplored_worth(x, y)
        age_s = time.time() - c.get("t", 0)
        # Just looked at: whatever stands there, the scan has already dealt
        # with it -- clicked it, skipped it as taken, rejected it. Going back
        # gains nothing, whatever the counts say.
        #
        # 2026-09-23 15:07-15:19, the first run recording whole views: a gem
        # the scan had already tried sat in cell 72,79 and was counted again
        # on every scan that showed it -- gem=24 in twelve minutes. Its score
        # dragged the steering back to it every scan ("steer: 229 -> 103 deg
        # (score 27.5 > -2.7)"), and the camera swung back and forth over the
        # same twenty tiles for thirty-nine scans. Before the Y fix the pull
        # pointed at the mirror image of the cell and the loop never closed.
        if age_s < self.RECENT_S:
            return -1.0
        weight = 0.5 ** (age_s / 3600.0 / REACH_HALFLIFE_H)
        # Capped, so evidence can tip a heading but never run away with it.
        gem = min(c.get("gem", 0), self.GEM_CAP)
        empty = min(c.get("empty", 0), self.EMPTY_CAP)
        return (gem * 2.0 - empty * 0.5) * weight

    # How far ahead the veto looks, in cells. Sized to how far the camera
    # actually travels between position reads, because a guard that sees less
    # than one step is checking ground the bot has already left: measured over
    # 256 readings, the step is 39 tiles at the median, 59 at p75 and 83 at p90,
    # against the 48 tiles (6 cells) this used to look. 36% of steps overshot
    # the guarded zone entirely, which is how 67 real crossings into kingdom
    # 4096 happened with the veto switched on.
    #
    # 12 cells is 96 tiles and covers 92% of steps, and it held: 0 crossings
    # in 561 scans after the change, against 11.6 per 1000 before.
    #
    # It stopped holding the moment the city moved. 2026-09-16, a city 123
    # tiles from the west edge: 6 crossings in 29 scans -- 207 per 1000, 18x
    # the worst rate ever measured here -- and every one of them started from
    # the city itself at (123,226). From there a due-west heading samples out
    # to x=27 and passes, so the veto could not fire at the one position the
    # bot returns to between every single mine.
    #
    # 16 cells is 128 tiles: further than the p90 step (83) and further than
    # the home city stands from the edge, which is what makes it fire there.
    # Scoring is left at 6 on purpose -- this is the hard veto, which should
    # look further than the preference does.
    #
    # CONFIRMED IN PRODUCTION, 2026-09-16, same city and the same morning:
    #     before    29 scans   6 crossings (207 per 1000)    3 vetoes
    #     after    173 scans   0 crossings (  0 per 1000)   20 vetoes
    # and the mines went 5 done / 10 failed to 10 done / 3 failed with it. The
    # veto firing 6.7x more often per scan is the half that makes the zero mean
    # something: it was being exercised, not merely never approached.
    BLOCK_REACH_CELLS = 16

    def blocked(self, x: int, y: int, heading: float,
                reach_cells: int = BLOCK_REACH_CELLS) -> bool:
        """Does this heading run into a wall, or off the map, within reach?

        Separate from heading_score on purpose. The score MIXES two different
        things: terrain that cannot be entered, and ground that simply looked
        empty last time. Summed together a wall (-10) and mild emptiness
        (-0.5 per empty visit) are both "negative", and a veto written against
        the sum fired on every other scan -- refusing headings whose only sin
        was a previous empty scan, which is exactly the pinning the wander's
        margin was designed to prevent.

        A wall is a fact about the map. An empty scan is a guess about gems.
        Only the first is worth a veto.
        """
        for step in range(1, reach_cells + 1):
            d = step * CELL
            cx = int(x + math.cos(heading) * d)
            cy = int(y + math.sin(heading) * d)
            if (cx < 0 or cy < 0 or cx >= self.size or cy >= self.size
                    or self.is_wall(cx, cy)):
                return True
        return False

    # What an unseen cell beside the city is worth, and how fast that fades
    # with distance. The bonus has to stay under a known gem (2.0) so a
    # remembered deposit still wins, and above an empty cell (-0.5) so
    # unscanned ground beats ground already picked over.
    UNEXPLORED_NEAR = 1.0
    UNEXPLORED_HALF_TILES = 120.0
    # Below this it is still worth going, just less so -- never zero, or the
    # far map becomes invisible again the moment the near map is scanned.
    UNEXPLORED_FAR_FLOOR = 0.25

    def set_city(self, x: int, y: int) -> None:
        """Where the sweep expands from. Learned, not configured -- and kept
        in the book, so a farm restarted on the world map still knows it."""
        city = (int(x), int(y))
        if getattr(self, "city", None) != city:
            self.city = city
            # Ground out of reach from where the city WAS says nothing about
            # where it is now.
            self.unreachable = [
                p for p in getattr(self, "unreachable", [])
                if max(abs(p["city"][0] - city[0]),
                       abs(p["city"][1] - city[1])) <= self.UNREACH_CITY_TOL]
            self.save()

    def _unexplored_worth(self, x: int, y: int) -> float:
        city = getattr(self, "city", None)
        if not city:
            return self.UNEXPLORED_NEAR
        dist = max(abs(x - city[0]), abs(y - city[1]))
        # Past the band the scan is working, unseen ground pulls nothing: the
        # frontier used to draw the camera outward along whichever arm it
        # was on -- 2026-09-23, 45 of 220 scans past 100 tiles while the
        # ring at 88-103 was barely a third seen. The band grows as the
        # rings inside fill (see flow_steps._sweep_band).
        band = getattr(self, "band", None)
        if band is not None and dist > band:
            return 0.0
        fade = 0.5 ** (dist / self.UNEXPLORED_HALF_TILES)
        return max(self.UNEXPLORED_FAR_FLOOR, self.UNEXPLORED_NEAR * fade)

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
        return (f"map {self.map_id} ({self.size} a side"
                f"{'' if is_home_map(self.map_id) else ', learned'}): "
                f"{len(self.terrain)} wall cell(s), "
                f"{len(self.reach)} scanned cell(s)")
