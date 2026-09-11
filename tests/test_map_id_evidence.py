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

import pytest

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
    block = src[start:start + 1400]
    assert "len(self._map_id_votes) < 3" in block, \
        "the three-vote gate is gone; a single misread can now bail the mine"
