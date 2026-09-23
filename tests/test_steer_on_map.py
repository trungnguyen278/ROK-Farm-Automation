"""The wander steers by the MAP, not by the screen angle.

The wander's heading is a screen direction; the map book is laid out in
tiles. tools/dev/pan_survey.py measured on 2026-09-23 that screen right is +X
but screen DOWN is -Y (dragging the pointer down moves the camera up the
map), and that a pixel across and a pixel down are different amounts of
ground. The steering handed the screen angle to the book as if it were a
map angle, so every vertical heading was scored -- and vetoed -- on the
ground behind the camera.
"""

import math

from rok_farm.flow_steps import GemFlowMixin
from rok_farm.map_memory import CELL


class Book:
    """A map book with one wall row, and a record of what it was asked."""

    def __init__(self, wall_y=None):
        self.asked = []
        self.wall_y = wall_y
        self.map_id = "4096"

    def _hits_wall(self, x, y, h, cells):
        if self.wall_y is None:
            return False
        for step in range(1, cells + 1):
            if int(y + math.sin(h) * step * CELL) <= self.wall_y:
                return True
        return False

    def heading_score(self, x, y, h, reach_cells=6):
        self.asked.append(h)
        return -10.0 if self._hits_wall(x, y, h, reach_cells) else 0.0

    def blocked(self, x, y, h, reach_cells=16):
        return self._hits_wall(x, y, h, reach_cells)


class Wander(GemFlowMixin):
    def __init__(self, book):
        self.mapmem = book
        self._last_map_xy = (500, 600)
        self.win = {"left": 0, "top": 0, "width": 1534, "height": 863}


DOWN, UP = math.pi / 2, -math.pi / 2     # screen angles, y grows downward


def test_a_downward_swipe_is_scored_to_the_south():
    book = Book()
    Wander(book)._steer_heading(DOWN)
    # asked first about the heading itself: the map direction must be -Y
    assert math.sin(book.asked[0]) < -0.99, math.degrees(book.asked[0])


def test_a_wall_to_the_south_stops_a_downward_swipe():
    """Wall 40 tiles below the camera on the map. Heading DOWN the screen
    walks the camera toward it and must be refused."""
    book = Book(wall_y=560)
    out = Wander(book)._steer_heading(DOWN)
    assert out != DOWN, "walked straight at the wall"


def test_the_same_wall_does_not_stop_an_upward_swipe():
    """The mirror-image bug: an UPWARD swipe moves away from that wall, and
    used to be the one refused."""
    book = Book(wall_y=560)
    assert Wander(book)._steer_heading(UP) == UP
