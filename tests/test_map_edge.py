"""A map's size is read where the HUD's map changes (rok_farm.map_edge).

Measured live 2026-09-24: at the widest readable zoom the world goes on past
a kingdom's edge -- east on 4096, X 1065, 1130, 1193, then #S11001 X:58 --
while the far view is held inside the kingdom. These tests walk a simulated
camera over such a world: our map in [0, size) with neighbours past its east
and north edges, whose coordinates start again at the shared border.
"""

import pytest

from rok_farm import map_edge
from rok_farm.map_edge import MapEdgeMixin

READABLE = 9            # notches out from icon zoom where the HUD still reads


class World(MapEdgeMixin):
    """Camera in world tiles; our map is [0, size) on both axes."""

    def __init__(self, size, map_id="4096", start=(577, 615), per_leg=95,
                 walls=False, misread=None, collision=None, fog_north=False,
                 blank_band=None):
        self.size, self.map_id = size, map_id
        self.x, self.y, self.z = float(start[0]), float(start[1]), 0
        self.per_leg, self.walls = per_leg, walls
        # (lo, hi, wrong id): the first read with lo <= X < hi names it
        self.misread = misread
        # (lo, hi, Y read): the first read with lo <= Y < hi reads that Y
        self.collision = collision
        # no map north of ours: the HUD's coordinate box is empty there
        self.fog_north = fog_north
        # (lo, hi): reads with lo <= X < hi fail on our own map (OCR blips)
        self.blank_band = blank_band
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}
        self.n_reads = 0
        self.legs = []

    # -- the game --
    def _edge_frame(self, wait=4.0):
        return None

    def _edge_notch(self, direction):
        self.z = max(0, self.z - direction)

    def _edge_leg(self, dx_frac, dy_frac):
        self.legs.append((dx_frac, dy_frac))
        k = self.per_leg / map_edge.EDGE_LEG_FRAC
        self.x += dx_frac * k
        self.y -= dy_frac * k                     # screen down is -Y
        if self.walls:
            self.x = min(max(self.x, 0), self.size - 1)
            self.y = min(max(self.y, 0), self.size - 1)

    def _read_map_position(self, frame=None, full=False):
        self.n_reads += 1
        if self.z > READABLE:
            return None
        x, y = int(self.x), int(self.y)
        if self.fog_north and y >= self.size:
            return None
        if self.blank_band and self.blank_band[0] <= x < self.blank_band[1]:
            return None
        mid = self.map_id
        if x >= self.size and y >= self.size:
            mid, x, y = "NE", x - self.size, y - self.size
        elif x >= self.size:
            mid, x = "S11001", x - self.size
        elif y >= self.size:
            mid, y = "4100", y - self.size
        if self.misread and self.misread[0] <= x < self.misread[1]:
            mid, self.misread = self.misread[2], None
        if self.collision and self.collision[0] <= y < self.collision[1]:
            y, self.collision = self.collision[2], None
        return mid, x, y


@pytest.mark.parametrize("size", [1200, 1440, 2400])
def test_the_edges_read_the_size(size):
    w = World(size, map_id="S20001" if size != 1200 else "4096")
    res = w._probe_map_size()
    assert res["size"] == size and res["confident"]
    assert res["east"]["ended"] == res["north"]["ended"] == "left"
    assert size - 1 - map_edge.EDGE_LEG_FRAC / 0.3 * 170 <= res["east"]["last"] < size
    assert abs(res["east"]["estimate"] - size) <= 2, res["east"]["estimate"]


def test_the_live_walk_of_2026_09_24():
    """X 1065, 1130, 1193, then the neighbour at 58: 1200."""
    w = World(1200, start=(1065, 170), per_leg=64)
    w.z = READABLE
    east = w._edge_walk(0, "4096")
    assert east["last"] == 1193 and east["size"] == 1200
    assert east["neighbour"] == "S11001" and abs(east["estimate"] - 1200) <= 1


def test_the_live_probe_of_12_58():
    """East: X 602 ... 1177, then S11001 76 and 173. North: Y 714 ... 1179,
    then the HUD blank -- fog past the world's edge -- 24 reads running,
    which walked on to the leg cap and left the size unconfirmed."""
    w = World(1200, start=(602, 713), per_leg=96, fog_north=True)
    w.z = READABLE
    east = w._edge_walk(0, "4096")
    assert east["ended"] == "left" and east["last"] == 1178 and east["size"] == 1200
    assert w._edge_back_onto(0, "4096")
    north = w._edge_walk(1, "4096")
    assert north["ended"] == "fog" and north["size"] == 1200
    assert len(north["reads"]) <= 1 + 6 + map_edge.FOG_READS + 1, "walked on into the fog"


def test_fog_past_an_edge_is_an_edge():
    res = World(1440, map_id="S20001", fog_north=True)._probe_map_size()
    assert res["north"]["ended"] == "fog"
    assert res["size"] == 1440 and res["confident"]


def test_a_blank_read_or_two_on_the_map_is_not_the_fog():
    """The full read fails now and then on a readable HUD: two in a row
    (two legs through X 800-990) must not end the walk there."""
    w = World(1200, blank_band=(800, 990))
    res = w._probe_map_size()
    assert res["east"]["ended"] == "left" and res["east"]["last"] > 1100
    assert res["size"] == 1200 and res["confident"]


def test_a_world_edge_with_nothing_beyond_holds_the_camera():
    res = World(1440, map_id="S20001", walls=True)._probe_map_size()
    assert res["east"]["ended"] == res["north"]["ended"] == "held"
    assert res["size"] == 1440 and res["confident"]


def test_one_misread_id_is_not_leaving_the_map():
    """The id OCR is wrong ~8% of the time: one 4093 in a walk on 4096."""
    w = World(1200, misread=(850, 900, "4093"))
    res = w._probe_map_size()
    assert res["size"] == 1200 and res["confident"]
    assert res["east"]["last"] > 1100


def test_a_stray_digit_on_y_does_not_make_the_map_2400():
    """North on a 1440 KvK map, Y 196 read as 1965 (the gate lets it by there)."""
    w = World(1440, map_id="S20001", start=(700, 101), collision=(190, 200, 1965))
    res = w._probe_map_size()
    assert res["north"]["size"] == 1440, res["north"]
    assert res["size"] == 1440


def test_disagreeing_axes_are_not_a_size():
    class Oblong(World):
        def _read_map_position(self, frame=None, full=False):
            r = super()._read_map_position(frame, full)
            if r and r[0] == self.map_id and self.y > 1200:
                return "4100", r[1], int(self.y) - 1200     # north edge at 1200
            return r
    res = Oblong(1440, map_id="S20001")._probe_map_size()
    assert res["size"] is None and not res["confident"]


def test_walks_that_never_reach_an_edge_prove_nothing():
    """Legs too short for the cap: both walks end short of the edge and
    both snap to 1200 -- the smallest size above what was read, a guess."""
    res = World(2400, map_id="S20001", per_leg=10)._probe_map_size()
    assert res["east"]["ended"] == res["north"]["ended"] == "cap"
    assert res["east"]["size"] == res["north"]["size"] == 1200
    assert not res["confident"]


def test_no_read_at_the_widest_zoom_is_an_error():
    class Blind(World):
        def _read_map_position(self, frame=None, full=False):
            return None
    res = Blind(1200)._probe_map_size()
    assert "error" in res and "size" not in res


def test_it_walks_back_onto_the_map_before_going_north():
    w = World(1200)
    res = w._probe_map_size()
    assert res["back_on_map"]
    east = [leg for leg in w.legs if leg[0] > 0]
    west = [leg for leg in w.legs if leg[0] < 0]
    north = [leg for leg in w.legs if leg[1] < 0]
    assert east and west and north
    first_north = w.legs.index(north[0])
    assert all(w.legs.index(leg) < first_north for leg in west)


def test_the_widest_readable_zoom_is_one_notch_inside_the_last_read():
    w = World(1200)
    out, back, hud = w._edge_widest_readable()
    assert out == READABLE + 1 and back == 1 and hud is not None
    assert w.z == READABLE


def test_a_leg_stays_well_under_the_gap_between_sizes():
    """~95 tiles a leg at 0.3 (63-65 at 0.2, measured); at the 1.77x an
    open-loop drag has come out at, still under the 240 between 1200 and
    1440 -- so the last read on a map is within one size of its edge."""
    per_leg = 64 / 0.2 * map_edge.EDGE_LEG_FRAC
    assert per_leg * 1.77 < 240
    assert per_leg * 1.77 * 2 < map_edge.MISREAD_TILES < 196 * 9


def test_the_dev_tool_keeps_a_minimap_crop_beside_every_read(tmp_path):
    """With a folder, every read keeps the frame's top-right quarter and the
    read that places it -- the minimap calibration's data. The farm's own
    run passes no folder and keeps nothing."""
    import numpy as np

    class Filmed(World):
        def _edge_frame(self, wait=4.0):
            return np.zeros((863, 1534, 3), np.uint8)

    res = Filmed(1200)._probe_map_size(tmp_path)
    names = [n for n, _hud in res["frames"]]
    assert names and all((tmp_path / n).exists() for n in names)
    assert any(hud and hud[0] == "4096" for _n, hud in res["frames"])
    import cv2
    assert cv2.imread(str(tmp_path / names[0])).shape[:2] == (863 // 4, 1534 - 1534 * 3 // 4)
    farm = Filmed(1200)
    assert "frames" not in farm._probe_map_size()
    assert farm._edge_keep_dir is None
