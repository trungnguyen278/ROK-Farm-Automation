"""The wander must not walk off the edge of the coordinate space.

The bot left the home kingdom over and over. The book HAD learned walls -- cell
(22,0) was recorded nine times -- but the border is a long line and a book only
ever knows the handful of cells already crossed at, so the next crossing is
always somewhere unexplored.

Underneath that was a plain hole: score() looked the cell up and missed on a
negative key, returning 0. NEUTRAL. A heading pointing straight off the map
scored exactly as well as one pointing into open ground.
"""

import math

import pytest

from rok_farm.map_memory import CELL, MapMemory


@pytest.fixture
def book(tmp_path, monkeypatch):
    import rok_farm.map_memory as mm
    monkeypatch.setattr(mm, "KNOWLEDGE_DIR", tmp_path, raising=False)
    m = MapMemory("TEST")
    m.terrain = {}
    m.reach = {}
    return m


def test_a_negative_coordinate_is_not_neutral(book):
    """The whole bug in one line."""
    assert book.score(-8, 100) < 0
    assert book.score(100, -8) < 0
    assert book.score(-8, -8) < 0


def test_unexplored_ground_is_still_neutral(book):
    """The fix must not make the bot afraid of everywhere it has not been."""
    assert book.score(500, 500) == 0.0


def test_heading_off_the_edge_scores_worse_than_heading_inland(book):
    """Standing near the corner the bot kept crossing at."""
    x, y = 19, 4                      # a real reading from that morning
    west = book.heading_score(x, y, math.pi)        # toward negative X
    north = book.heading_score(x, y, -math.pi / 2)  # toward negative Y
    inland = book.heading_score(x, y, 0.0)          # toward positive X

    assert west < inland, "heading off the west edge is not penalised"
    assert north < inland, "heading off the north edge is not penalised"


def test_a_recorded_wall_still_dominates(book):
    book.record_wall(200, 200)
    assert book.score(200, 200) < 0
    assert book.is_wall(200, 200)


def test_the_edge_penalty_reaches_before_the_camera_does(book):
    """It has to bite while there is still room to turn.

    heading_score samples six cells out, so standing a few cells from the edge
    must already score negative -- a guard that only fires once the camera is
    off the map is no guard at all.
    """
    for gap_cells in (1, 2, 3):
        y = gap_cells * CELL
        assert book.heading_score(100, y, -math.pi / 2) < 0, (
            f"standing {gap_cells} cells from the edge, heading straight at "
            f"it still scores neutral")
