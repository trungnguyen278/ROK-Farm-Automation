"""How large is this map: read at its bottom-right corner.

The operator, 2026-09-24: "zoom out max roi xac dinh goc duoi ben phai de
zoom in lay toa do tu do xac dinh tuong doi do lon map". Out to the far view
(it shows no coordinates), pan until the map stops moving east and then
south -- the camera is held at the corner -- and back in until the HUD
reads. Screen right is +X and screen down is -Y (pan_survey), so the
bottom-right corner is X = size - 1, Y = 0: the X read there is the size.
The sizes that exist are far apart (map_memory.MAP_SIZES: 1200, 1440, 2400),
so a read some tiles short of the corner still tells them apart.

The zoom follows the pointer: a notch keeps the ground under the pointer
where it is. _scroll_at_center scrolls at a random point up to a quarter of
the window off centre, which carries the camera by as much as a couple of
hundred tiles at the far view. So every notch here is scrolled with the
pointer on the corner's side of the centre: zooming in then pushes the
camera into the corner it is held at, not away from it.

Not a farm step yet. tools/dev/map_edge_probe.py runs it between mines and
keeps its frames; it is tried first on the home kingdom, whose size is known.
"""

from __future__ import annotations

import random
import time
from pathlib import Path

import cv2
import numpy as np

from rok_farm.config import ZOOM_OUT_QUIET_DIFF
from rok_farm.logging_setup import INFO, logger
from rok_farm.map_memory import MAP_SIZES

# The map did not move: mean abs difference of two frames at 320x180, 0-255.
# kingdom_survey 2026-09-24, 31 notches of zoom: every notch that zoomed
# changed the frame by 6.44-29.83; the two past the limit by 0.59 and 0.69.
EDGE_STILL_DIFF = 1.5
# A far-view leg: two drags of this fraction of the window each, the pointer
# kept inside it. At the limit a drag of 0.3 of the width moved the camera
# 234-277 tiles (calibration, 2026-09-24), so a home kingdom is crossed in
# three legs and a 2400 map in six; the caps leave room over that.
FAR_LEG_FRAC = 0.3
FAR_LEGS_MAX = 8
# Once the HUD reads, a few shorter legs make sure the camera is still at the
# corner -- the far view's hold and the near view's may not be the same.
NEAR_LEG_FRAC = 0.2
NEAR_LEGS_MAX = 4
# Where the pointer sits for a notch toward the corner (fractions of the
# window, before a small jitter): right of and below the centre.
CORNER_POINTER = (0.68, 0.62)


class MapEdgeMixin:
    """Walks the camera to the map's bottom-right corner and reads it."""

    def _edge_frame(self, wait: float = 4.0):
        """The raw client frame, waiting for one: on a still screen the
        capture hands over no new frame until something changes."""
        t0 = time.monotonic()
        while time.monotonic() - t0 < wait:
            if self._grab() is not None and self._raw_frame is not None:
                return self._raw_frame.copy()
            time.sleep(0.1)
        return None

    @staticmethod
    def _edge_diff(a, b) -> float:
        if a is None or b is None:
            return float("inf")
        return float(np.mean(cv2.absdiff(cv2.resize(a, (320, 180)),
                                         cv2.resize(b, (320, 180)))))

    def _edge_settle(self, cap: float = 5.0) -> None:
        """Until two looks in a row show the map not moving, capped."""
        t0 = time.monotonic()
        prev, quiet = None, 0
        while time.monotonic() - t0 < cap:
            frame = self._grab()
            cur = self._settle_patch(frame) if frame is not None else None
            if cur is not None:
                if prev is not None:
                    quiet = quiet + 1 if float(np.mean(cv2.absdiff(prev, cur))) < ZOOM_OUT_QUIET_DIFF else 0
                    if quiet >= 2:
                        return
                prev = cur
            time.sleep(random.uniform(0.07, 0.11))

    def _edge_notch(self, direction: int, at=(0.5, 0.5)) -> None:
        """One notch (-1 out, +1 in) with the pointer near `at`."""
        w = self.win
        fx = at[0] + random.uniform(-0.03, 0.03)
        fy = at[1] + random.uniform(-0.03, 0.03)
        self._moveto(w["left"] + int(w["width"] * fx), w["top"] + int(w["height"] * fy))
        time.sleep(random.uniform(0.12, 0.3))
        self.cmd.send("SCROLL", direction)
        time.sleep(random.uniform(0.35, 0.6))
        self._edge_settle()

    def _edge_out_to_limit(self, max_notches: int = 24) -> int:
        """Out until two notches in a row leave the frame as it was."""
        prev, still = self._edge_frame(), 0
        for n in range(1, max_notches + 1):
            self._edge_notch(-1)
            frame = self._edge_frame()
            still = still + 1 if self._edge_diff(prev, frame) < EDGE_STILL_DIFF else 0
            prev = frame
            if still >= 2:
                return n
        return max_notches

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

    def _edge_pin_far(self, dx_frac: float, dy_frac: float) -> tuple[int, bool, list]:
        """Legs one way until one of them leaves the frame as it was: the
        camera is held at the edge. (legs, held, the frame change per leg)"""
        prev, diffs = self._edge_frame(), []
        for leg in range(1, FAR_LEGS_MAX + 1):
            self._edge_leg(dx_frac, dy_frac)
            frame = self._edge_frame()
            diffs.append(round(self._edge_diff(prev, frame), 2))
            prev = frame
            if diffs[-1] < EDGE_STILL_DIFF:
                return leg, True, diffs
        return FAR_LEGS_MAX, False, diffs

    def _edge_pin_far_corner(self) -> dict:
        """South legs until the camera is held at the bottom-right corner.

        Each south leg is judged together with the east legs after it (until
        those are held): the far calibration moved -164 X on a drag straight
        up -- perhaps the zoom's pointer rather than the drag, not settled --
        and a camera already held at the bottom would keep sliding west on
        every south leg, so the frame alone would never stand still. A south
        leg plus the east legs after it that bring the frame back to what it
        was means neither way moves any more.
        """
        steps = []
        for _step in range(FAR_LEGS_MAX):
            before = self._edge_frame()
            self._edge_leg(0.0, FAR_LEG_FRAC)
            legs, held, _diffs = self._edge_pin_far(FAR_LEG_FRAC, 0.0)
            diff = round(self._edge_diff(before, self._edge_frame()), 2)
            steps.append({"east_legs": legs, "east_held": held, "diff": diff})
            if held and diff < EDGE_STILL_DIFF:
                return {"held": True, "steps": steps}
        return {"held": False, "steps": steps}

    def _edge_pin_near(self, axis: int, sign: int) -> tuple[tuple | None, list]:
        """Legs one way, reading the HUD after each, until the coordinate on
        `axis` (0 = X, 1 = Y) stops moving `sign`-wards. (last read, reads)"""
        reads = [self._read_map_position(self._edge_frame(), full=True)]
        dx, dy = (NEAR_LEG_FRAC, 0.0) if axis == 0 else (0.0, NEAR_LEG_FRAC)
        for _leg in range(NEAR_LEGS_MAX):
            self._edge_leg(dx, dy)
            hud = self._read_map_position(self._edge_frame(), full=True)
            reads.append(hud)
            before = next((r for r in reversed(reads[:-1]) if r), None)
            if hud and before and (hud[1 + axis] - before[1 + axis]) * sign <= 2:
                break
        return next((r for r in reversed(reads) if r), None), reads

    def _probe_map_size(self, out_dir: Path | None = None) -> dict:
        """Walk to the bottom-right corner and read it. From the world map at
        any zoom; leaves the camera at the corner, zoomed in just enough for
        the HUD to read -- the caller brings the view back."""
        def keep(name, frame):
            if out_dir is not None and frame is not None:
                cv2.imwrite(str(Path(out_dir) / f"{name}.png"), frame)

        res: dict = {"start": self._read_map_position(self._edge_frame(), full=True)}
        t0 = time.monotonic()
        res["notches_out"] = self._edge_out_to_limit()
        keep("far_limit", self._edge_frame())
        legs, held, diffs = self._edge_pin_far(FAR_LEG_FRAC, 0.0)
        res["east"] = {"legs": legs, "held": held, "diffs": diffs}
        res["south"] = self._edge_pin_far_corner()
        keep("far_corner", self._edge_frame())
        hud, notches = None, 0
        for notches in range(1, 25):
            self._edge_notch(+1, at=CORNER_POINTER)
            hud = self._read_map_position(self._edge_frame(), full=True)
            if hud:
                break
        res["notches_in"], res["first_read"] = notches, hud
        keep("first_read", self._edge_frame())
        if hud is None:
            res["error"] = "the HUD never read on the way back in"
            return res
        east, res["near_east"] = self._edge_pin_near(0, +1)
        south, res["near_south"] = self._edge_pin_near(1, -1)
        last = south or east or hud
        keep("corner_read", self._edge_frame())
        _mid, x, y = last
        res["corner"] = [x, y]
        res["map_id"] = last[0]
        res["size"] = next((s for s in MAP_SIZES if s > x), None)
        res["short_of_edge"] = None if res["size"] is None else res["size"] - 1 - x
        res["seconds"] = round(time.monotonic() - t0, 1)
        print(f"  [{INFO}] map {last[0]}: bottom-right corner reads {x},{y} -> "
              f"{res['size']} tiles a side ({res['short_of_edge']} short of the edge)")
        logger.info("Map size probe: %s", res)
        return res
