"""Being on the world map is not the same as being at icon zoom.

The gather chain zooms IN on the mine it clicks. A mine that starts while
already on the world map therefore begins at whatever zoom the last gather left
behind, and the gem icon template -- captured at icon zoom -- cannot match at
all there.

Measured on 2026-09-11 across ten mines in one run:

    zoomed out on entry   6 mines   all 6 succeeded
    left the zoom alone   4 mines   3 failed, each with 18 empty scans and
                                    ZERO classifier rejects

Zero rejects is the tell: nothing was even detected as a candidate to reject.
It was not barren ground, it was the wrong scale.
"""

import numpy as np

import rok_farm.flow_steps as fs
from rok_farm.flow_steps import GemFlowMixin


class Runner(GemFlowMixin):
    """Just enough of the runner for the world-map step."""

    def __init__(self, gems_visible, on_world):
        self._gems = gems_visible
        self._on_world = on_world
        self.reset_calls = 0
        self.scroll_calls = []
        self.records = []

    # --- what the step under test touches -----------------------------
    def _grab(self):
        return np.zeros((862, 1533, 3), dtype=np.uint8)

    def _find_all_gems(self, frame):
        return ["gem"] if self._gems else []

    def _is_world_map(self, *a, **k):
        return self._on_world

    def _reset_zoom_to_reference(self):
        self.reset_calls += 1

    def _scroll_at_center(self, direction, count):
        self.scroll_calls.append((direction, count))

    def _wait_zoom_settled(self, *a, **k):
        pass

    def _zoom_scrolls(self):
        return 3

    def _record(self, *a, **k):
        self.records.append(a)

    def _wait(self, *a, **k):
        pass


def test_zoom_is_restored_when_a_click_zoomed_us_in():
    """The case that failed three mines in a row."""
    text = open(fs.__file__, encoding="utf-8").read()
    start = text.index("Already on world map icon-zoom")
    branch = text[start:text.index("Step 2", start)]
    assert "_zoomed_in_by_click" in branch, (
        "the not-from-city branch no longer restores the zoom; a mine starting "
        "after a gather will scan at the gather's zoom and match nothing")
    assert "_scroll_at_center(-1" in branch


def test_the_restore_is_paired_and_bounded():
    """Undo exactly the zoom-in that happened -- no clamping, no guessing.

    _reset_zoom_to_reference looked tidier and was wrong: it clamps fully IN
    and comes out the 3 notches the CITY path uses, but the city path starts
    from the world map's default, far further out. From the clamp that lands at
    5 KM against icon zoom's 77 KM -- close enough that plain grass has no
    features, which the fog detector read as being out of the kingdom. It had
    never been called before, so its docstring was never tested.
    """
    text = open(fs.__file__, encoding="utf-8").read()
    start = text.index("Already on world map icon-zoom")
    branch = text[start:text.index("Step 2", start)]
    # The comments name it deliberately, to record why it is not used; only a
    # CALL would be the bug.
    code = "\n".join(ln.split("#", 1)[0] for ln in branch.splitlines())
    assert "_reset_zoom_to_reference(" not in code, \
        "back on the clamp-then-out path, which does not reach icon zoom"
    assert "_zoomed_in_by_click = False" in code, \
        "the flag is never cleared, so the zoom-out can repeat and ratchet"


def test_the_flag_is_set_where_the_game_zooms_in():
    """The pairing is only honest if the flag is set by the click itself."""
    text = open(fs.__file__, encoding="utf-8").read()
    click = text.index("Clicking icon conf=")
    after = text[click:click + 500]
    assert "_zoomed_in_by_click = True" in after,         "clicking an icon zooms the game in but no longer records it"


def test_it_does_not_simply_zoom_out_further():
    """The ratchet this must not become.

    Zooming out whenever no gem is seen walked the view to 0.35x scale over one
    night, because "no gem" cannot tell barren ground from the wrong zoom.

    This used to be checked by asserting the branch never says "leaving the
    zoom alone" -- which passed only because that sentence happened to be
    split across two f-strings, so the substring was never in the file at all.
    The invariant it was reaching for is the one asserted here: nothing zooms
    out on a GUESS. Either we just came from the city, where the world map
    always opens zoomed in, or the HUD was read and said so.
    """
    text = open(fs.__file__, encoding="utf-8").read()
    start = text.index("Already on world map icon-zoom")
    branch = text[start:text.index("Step 2", start)]
    # the bare zoom-out must still be reachable from the city path
    city = branch[branch.index("if toggled_from_city"):]
    assert "_scroll_at_center(-1" in city

    step1 = branch[:branch.index("def _step_stay_and_rezoom")]
    for line in step1.splitlines():
        if "_scroll_at_center(-1" not in line:
            continue
        before = step1[:step1.index(line)]
        assert ("toggled_from_city" in before[-2000:]
                or "read_zoom_gauge" in before[-2000:]), \
            f"this zoom-out is not gated on the city path or on a gauge " \
            f"reading, so it is a guess: {line.strip()}"


def test_visible_gems_short_circuit_before_any_zooming():
    """If gems are already on screen the zoom is right; touching it wastes
    actions and risks losing them off the edge."""
    text = open(fs.__file__, encoding="utf-8").read()
    start = text.index("gems = self._find_all_gems")
    head = text[start:text.index("if toggled_from_city", start)]
    assert "return True" in head, \
        "the early return on visible gems is gone"


def test_the_debt_is_cleared_where_the_undo_actually_happens():
    """Two zoom-outs for one zoom-in leaves the camera too far OUT.

    _return_to_icon_zoom is the real undo, and BOTH exits use it -- a dud icon
    click and step 7 after a march. With the flag left set, the next mine undid
    the same zoom-in again and landed three notches beyond icon zoom: 121 KM
    against 77 KM, where icons render too small to match and a scan finds not
    one candidate in eighteen tries. That is the failure I first blamed on the
    map's resource filter, and then on the area having no gems.
    """
    text = open(fs.__file__, encoding="utf-8").read()
    start = text.index("def _return_to_icon_zoom")
    body = text[start:text.index("\n    def ", start + 10)]
    assert "_zoomed_in_by_click = False" in body, (
        "the paired undo no longer clears the flag, so the next mine will "
        "zoom out a second time for the same zoom-in")
    # and it must clear BEFORE scrolling, so an exception mid-scroll cannot
    # leave the debt outstanding forever
    assert (body.index("_zoomed_in_by_click = False")
            < body.index("_scroll_at_center")), \
        "the flag is cleared after the scroll, so a failure there strands it"
