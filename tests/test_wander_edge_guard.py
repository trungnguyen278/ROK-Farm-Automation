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


def test_a_previously_empty_cell_is_not_blocked(book):
    """The veto is about terrain, not about where gems happened to be.

    The first version of this guard asked the SCORE whether the way was
    blocked. The score adds terrain and gem history together, so a cell that
    merely scanned empty once is negative too -- and the veto fired on nine
    scans out of nine, refusing headings for having been unlucky. That is the
    pinning the wander's margin exists to prevent.
    """
    book.record_scan(300, 300, [])          # seen, nothing there
    book.record_scan(300, 300, [])
    assert book.score(300, 300) < 0, "an empty cell should still score badly"
    assert not book.blocked(292, 300, 0.0), \
        "an empty cell must not block a heading -- only terrain does"


def test_a_wall_blocks(book):
    book.record_wall(300, 300)
    assert book.blocked(300 - 6 * CELL, 300, 0.0)


def test_the_map_edge_blocks(book):
    assert book.blocked(10, 10, math.pi), "heading west off the map"
    assert book.blocked(10, 10, -math.pi / 2), "heading north off the map"


def test_open_ground_does_not_block(book):
    assert not book.blocked(500, 500, 0.0)
    assert not book.blocked(500, 500, math.pi / 2)


def test_the_veto_looks_further_than_the_camera_travels(book):
    """A guard that sees less than one step checks ground already left behind.

    Measured over 256 position readings, the camera moves 39 tiles between
    reads at the median, 59 at p75 and 83 at p90. The veto used to look 48
    tiles, so 36% of steps jumped clean over the zone it had just cleared --
    which is how 67 real crossings into kingdom 4096 happened with the veto
    switched on.

    CONFIRMED IN PRODUCTION, 2026-09-13. Counted per farm start over the whole
    log, before and after the reach went 6 -> 12 cells:

        before   5772 scans   67 crossings (11.6 per 1000)   31 vetoes
        after     561 scans    0 crossings ( 0.0 per 1000)   26 vetoes

    Both halves of that matter. Zero crossings alone would prove nothing -- a
    run that never approached the border would also show zero -- but the veto
    fired 8.6x more often per scan, so it was being exercised, and the old
    rate predicted about 6.5 crossings over those scans.
    """
    from rok_farm.map_memory import CELL, MapMemory

    assert MapMemory.BLOCK_REACH_CELLS * CELL >= 83, (
        f"the veto looks {MapMemory.BLOCK_REACH_CELLS * CELL} tiles ahead but "
        f"the camera moves 83 tiles between reads at p90")


def test_a_wall_beyond_the_old_reach_is_now_seen(book):
    """The specific gap: a wall 10 cells out was invisible, and is not now."""
    import math
    book.record_wall(100 + 10 * CELL, 100)
    assert book.blocked(100, 100, 0.0), \
        "a wall ten cells ahead is still invisible to the veto"
    assert not book.blocked(100, 100, math.pi), \
        "the veto now fires in every direction, which would pin the wander"


def test_scoring_still_uses_the_shorter_horizon(book):
    """Preference and veto answer different questions and keep their own reach."""
    import inspect
    sig = inspect.signature(book.heading_score)
    assert sig.parameters["reach_cells"].default == 6, (
        "heading_score's horizon moved with the veto's; steering preference "
        "was not what the measurement was about")
