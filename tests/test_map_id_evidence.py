"""A WRONG map id parses perfectly, so it leaves no trace of its own.

The bot abandons a mine and walks back to the city whenever the HUD says it has
left the home kingdom. On 2026-09-11 it did that five times in a row for
"S11465 -> 4096" while a live capture of the same HUD read S11465 without
trouble: the crossings were false.

The vote guarding this ("three consecutive agreeing reads") only helps while
the misreads DIFFER. Three identical wrong reads sail straight through it, and
this OCR is documented as returning a structurally valid but wrong id in about
8% of reads.

Nothing recorded the string the id came from -- only unparseable text was
logged, which is precisely the case that does NOT cause a bail.
"""


from rok_farm import PROJECT_ROOT

OCR = PROJECT_ROOT / "rok_farm" / "queue_ocr.py"
FLOW = PROJECT_ROOT / "rok_farm" / "flow_steps.py"


def test_the_raw_text_is_kept_on_every_read():
    src = OCR.read_text(encoding="utf-8")
    body = src[src.index("def _read_map_position"):]
    body = body[:body.index("\n    def ", 10)]
    keep = body.index("_last_pos_text")
    unparsed = body.index("Map position unparsed")
    assert keep < unparsed, (
        "the raw text is only kept when parsing FAILS, which is the case that "
        "does not cause a bail -- a wrong id parses fine and leaves nothing")


def test_a_disagreeing_id_is_reported_with_its_text():
    src = FLOW.read_text(encoding="utf-8")
    start = src.index("self._map_id_votes.append(map_id)")
    block = src[start:src.index("self._map_id_votes = []", start)]
    assert "_last_pos_text" in block, \
        "a disagreeing map id is still logged without the string it came from"
    assert "logger.warning" in block, (
        "the disagreement is only at debug level; the five bails that "
        "prompted this were invisible at the level the farm runs at")


def test_the_vote_still_gates_the_switch():
    """Evidence must not become permission: one odd read still cannot switch."""
    src = FLOW.read_text(encoding="utf-8")
    start = src.index("self._map_id_votes.append(map_id)")
    # To the end of the branch, not a fixed number of characters: a window
    # sized to today's code silently stops covering it the moment a comment is
    # added, which is exactly what happened when the frame capture went in.
    block = src[start:src.index("self._map_id_votes = []", start)]
    assert "len(self._map_id_votes) < 3" in block, \
        "the three-vote gate is gone; a single misread can now bail the mine"


def test_a_disagreeing_id_also_keeps_the_frame():
    """The text was not enough, twice over.

    Half the remaining failures are a mine abandoned because the id read as
    another kingdom. It has been explained from guesswork twice -- once as the
    camera being stuck outside, which a live capture disproved -- and none of
    the surviving screenshots reproduces a wrong id, so there is nothing to
    test a fix against. The frame is what settles it.
    """
    src = FLOW.read_text(encoding="utf-8")
    start = src.index("self._map_id_votes.append(map_id)")
    block = src[start:src.index("self._map_id_votes = []", start)]
    assert "save_screenshot" in block, \
        "a disagreeing map id is logged but the frame is thrown away"
    assert "MAPID" in block, \
        "the saved frame is not named for the fault, so it cannot be found"
