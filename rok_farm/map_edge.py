"""How large is this map: pan to its edges and see where the HUD's map changes.

The operator, 2026-09-24: "zoom out max roi xac dinh goc duoi ben phai de
zoom in lay toa do tu do xac dinh tuong doi do lon map". Tried live the same
day (screenshots/map_edge/20260924_124014): the far view is held inside the
kingdom -- some forty legs past its corner moved nothing, and the frame still
changed 3-11 a leg, so "the frame stood still" could not even tell -- but at
the widest zoom where the HUD reads, the world goes on: panning east on 4096
read X 1065, 1130, 1193 and then #S11001 X:58, the kingdom next door; south
on S11001, Y 15 and then #4093 Y:1166. North of 4096 there is no map at
all: fog and snow, and the HUD's coordinate box is empty (12:58 run). So an
edge is where the id changes or the HUD goes blank, and the last coordinate
read on this map, plus one, is within a leg of the size -- which snaps to
map_memory.MAP_SIZES, 240+ tiles apart.

East gives the size from X, north from Y (screen up is +Y): the top-right
corner, where both are size - 1. (The bottom-right one the operator named
has Y = 0 and says nothing about the size.) Maps are square, so the two
must agree -- that is what makes it a measurement.

The zoom follows the pointer (a notch keeps the ground under the pointer
where it is) and _scroll_at_center picks a point up to a quarter of the
window off centre, so the notches here are scrolled near the centre.

tools/dev/map_edge_probe.py runs it between mines and keeps its frames; the
farm runs it once on a KvK map (flow_steps._maybe_probe_map_size).
"""

from __future__ import annotations

import random
import time
from pathlib import Path

import cv2

from rok_farm.config import ZOOM_OUT_QUIET_DIFF
from rok_farm.logging_setup import INFO, logger
from rok_farm.map_memory import MAP_SIZES

# A leg is two drags of this fraction of the window. At the widest readable
# zoom two drags of 0.2 moved the camera 63-65 tiles (2026-09-24), so 0.3 is
# ~95 -- and even at the 1.77x an open-loop drag has come out at
# (pan_survey), under the 240 tiles between two map sizes: the last read on
# the map is always within one size of its edge.
EDGE_LEG_FRAC = 0.3
# 2400 tiles at ~95 a leg is 26 legs.
EDGE_LEGS_MAX = 30
# The id OCR misreads about 8% of reads (flow_steps._map_sync): the map is
# left when this many reads in a row name the same other map.
LEFT_READS = 2
# Past the world's edge the HUD shows no coordinates at all: this many blank
# reads in a row after reads on the map. 2026-09-24 12:58, north of 4096: 24
# blank in a row; on the map the full read failed 0 times in 16 that run.
FOG_READS = 3
# Held where there is nothing beyond: this many legs in a row that gained at
# most HELD_TILES on the axis walked.
HELD_LEGS = 2
HELD_TILES = 2
# A read further on than this from the last one is a stray digit, not a leg:
# two legs (one unreadable in between) at the 1.77x drag error are ~340
# tiles, the digit collision multiplies Y by ten (196 read as 1965).
MISREAD_TILES = 360


class MapEdgeMixin:
    """Walks the camera to the map's top-right corner, reading the HUD."""

    def _edge_frame(self, wait: float = 4.0):
        """The raw client frame, waiting for one: on a still screen the
        capture hands over no new frame until something changes."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait:
            if self._grab() is not None and self._raw_frame is not None:
                return self._raw_frame.copy()
            time.sleep(0.1)
        return None

    def _edge_settle(self, cap: float = 5.0) -> None:
        """Until two looks in a row show the map not moving, capped."""
        t0 = time.monotonic()
        prev, quiet = None, 0
        while time.monotonic() - t0 < cap:
            frame = self._grab()
            cur = self._settle_patch(frame) if frame is not None else None
            if cur is not None:
                if prev is not None:
                    moved = float(cv2.absdiff(prev, cur).mean())
                    quiet = quiet + 1 if moved < ZOOM_OUT_QUIET_DIFF else 0
                    if quiet >= 2:
                        return
                prev = cur
            time.sleep(random.uniform(0.07, 0.11))

    def _edge_read(self):
        """The HUD's (map id, x, y) or None. With a keep folder set (the dev
        tool), every read also keeps the frame's top-right quarter -- the
        minimap and its viewport outline, beside the read that places them:
        what calibrating the minimap to tiles needs."""
        frame = self._edge_frame()
        hud = self._read_map_position(frame, full=True)
        keep = getattr(self, "_edge_keep_dir", None)
        if keep is not None and frame is not None:
            fh, fw = frame.shape[:2]
            name = f"read_{len(self._edge_kept):03d}.png"
            cv2.imwrite(str(Path(keep) / name), frame[:fh // 4, fw * 3 // 4:])
            self._edge_kept.append([name, list(hud) if hud else None])
        return hud

    def _edge_notch(self, direction: int) -> None:
        """One notch (-1 out, +1 in), the pointer near the centre."""
        w = self.win
        fx = 0.5 + random.uniform(-0.04, 0.04)
        fy = 0.5 + random.uniform(-0.04, 0.04)
        self._moveto(w["left"] + int(w["width"] * fx), w["top"] + int(w["height"] * fy))
        time.sleep(random.uniform(0.12, 0.3))
        self.cmd.send("SCROLL", direction)
        time.sleep(random.uniform(0.35, 0.6))
        self._edge_settle()

    def _edge_widest_readable(self, max_out: int = 16, max_in: int = 6):
        """Out until the HUD stops reading, back in until it reads again.
        (notches out, notches in, the read there)"""
        out = 0
        for out in range(1, max_out + 1):
            self._edge_notch(-1)
            if self._edge_read() is None:
                break
        hud, back = None, 0
        for back in range(1, max_in + 1):
            self._edge_notch(+1)
            hud = self._edge_read()
            if hud:
                break
        return out, back, hud

    def _edge_leg(self, dx_frac: float, dy_frac: float) -> None:
        """Pan the camera: two drags of the pointer, each dx_frac/dy_frac of
        the window. Positive dx moves the camera east (the pointer goes
        left); positive dy moves it south (the pointer goes up)."""
        w = self.win
        cx, cy = w["left"] + w["width"] // 2, w["top"] + w["height"] // 2
        hx, hy = int(w["width"] * dx_frac), int(w["height"] * dy_frac)
        for _half in range(2):
            jx, jy = random.randint(-12, 12), random.randint(-12, 12)
            self._human_drag(cx + hx // 2 + jx, cy + hy // 2 + jy,
                             cx - hx // 2 + jx, cy - hy // 2 + jy,
                             speed_factor=random.uniform(1.0, 1.4),
                             hold_ms=random.randint(150, 320))
            time.sleep(random.uniform(0.2, 0.45))
        self._edge_settle()

    @staticmethod
    def _edge_leg_for(axis: int, sign: int) -> tuple[float, float]:
        """(dx_frac, dy_frac) that moves the camera `sign`-wards on `axis`
        (0 = X, 1 = Y). Screen down is -Y, so +Y is a leg with dy < 0."""
        if axis == 0:
            return sign * EDGE_LEG_FRAC, 0.0
        return 0.0, -sign * EDGE_LEG_FRAC

    def _edge_walk(self, axis: int, map_id: str) -> dict:
        """Legs toward +X (axis 0) or +Y (axis 1), a HUD read after each,
        until the map is left ("left": another map's id; "fog": no map, the
        HUD blank), the camera is held, or the cap.

        size: the smallest map size above the furthest read on this map;
        estimate: that read plus the mean leg minus the neighbour's first
        read -- the edge to the tile, when the neighbour's coordinates start
        at the shared border as they did on 2026-09-24.
        """
        dx, dy = self._edge_leg_for(axis, +1)
        reads = [self._edge_read()]
        own = [r for r in reads if r and r[0] == map_id]
        other: list = []
        still, blank, ended = 0, 0, "cap"
        for _leg in range(EDGE_LEGS_MAX):
            self._edge_leg(dx, dy)
            hud = self._edge_read()
            reads.append(hud)
            if hud is None:
                blank += 1
                if own and blank >= FOG_READS:
                    ended = "fog"
                    break
                continue
            blank = 0
            if hud[0] == map_id:
                other = []
                gained = hud[1 + axis] - own[-1][1 + axis] if own else None
                if gained is not None and gained > MISREAD_TILES:
                    continue
                still = still + 1 if gained is not None and gained <= HELD_TILES else 0
                own.append(hud)
                if still >= HELD_LEGS:
                    ended = "held"
                    break
            else:
                other = other + [hud] if not other or other[-1][0] == hud[0] else [hud]
                if len(other) >= LEFT_READS:
                    ended = "left"
                    break
        res: dict = {"ended": ended, "reads": reads}
        if not own:
            return res
        last = max(r[1 + axis] for r in own)
        gains = [b[1 + axis] - a[1 + axis] for a, b in zip(own, own[1:])
                 if b[1 + axis] - a[1 + axis] > HELD_TILES]
        res.update(last=last, size=next((s for s in MAP_SIZES if s > last), None))
        if ended == "left" and gains:
            res["neighbour"] = other[0][0]
            res["estimate"] = round(last + sum(gains) / len(gains) - other[0][1 + axis])
        return res

    def _edge_back_onto(self, axis: int, map_id: str, max_legs: int = 5) -> bool:
        """Legs back the way a walk came until the HUD reads this map again."""
        dx, dy = self._edge_leg_for(axis, -1)
        for _leg in range(max_legs):
            self._edge_leg(dx, dy)
            hud = self._edge_read()
            if hud and hud[0] == map_id:
                return True
        return False

    def _probe_map_size(self, out_dir: Path | None = None) -> dict:
        """Walk to the top-right corner, reading the HUD. From the world map
        at any zoom; leaves the camera wherever the walk ended, zoomed out
        -- the caller brings the view back (through the city)."""
        def keep(name):
            if out_dir is not None:
                frame = self._edge_frame()
                if frame is not None:
                    cv2.imwrite(str(Path(out_dir) / f"{name}.png"), frame)

        t0 = time.monotonic()
        self._edge_keep_dir, self._edge_kept = out_dir, []
        try:
            return self._probe_map_size_walks(keep, t0)
        finally:
            self._edge_keep_dir = None

    def _probe_map_size_walks(self, keep, t0) -> dict:
        start = self._edge_read()
        book = getattr(self, "mapmem", None)
        out, back, hud = self._edge_widest_readable()
        res: dict = {"start": start, "notches_out": out, "notches_in": back,
                     "first_read": hud}
        keep("widest_readable")
        map_id = ((book.map_id if book is not None else None)
                  or (start[0] if start else None) or (hud[0] if hud else None))
        res["map_id"] = map_id
        if hud is None or map_id is None:
            res["error"] = "the HUD did not read at the widest zoom"
            return res
        res["east"] = self._edge_walk(0, map_id)
        keep("east_end")
        res["back_on_map"] = self._edge_back_onto(0, map_id)
        if res["back_on_map"]:
            res["north"] = self._edge_walk(1, map_id)
            keep("north_end")
        sx = res["east"].get("size")
        sy = res.get("north", {}).get("size")
        ends_ok = all(res.get(k, {}).get("ended") in ("left", "fog", "held")
                      for k in ("east", "north"))
        res["size"] = sx if sx is not None and sx == sy else None
        res["confident"] = res["size"] is not None and ends_ok
        res["seconds"] = round(time.monotonic() - t0, 1)
        if self._edge_kept:
            res["frames"] = self._edge_kept
        print(f"  [{INFO}] map {map_id}: east edge after X "
              f"{res['east'].get('last')} ({res['east']['ended']}), north edge "
              f"after Y {res.get('north', {}).get('last')} "
              f"({res.get('north', {}).get('ended')}) -> "
              f"{res['size'] or 'no agreed size'}"
              f"{'' if res['confident'] else ' (not confident)'}")
        logger.info("Map size probe: %s", {k: v for k, v in res.items() if k != "frames"})
        return res
