"""A HUD read that lost its '#' is still read, when the map id anchors it.

2026-09-25 08:30:44, on the operator's second account: right after a march
the game refused at a pass, the position read came back
'3.975.1283560X:1114Y:557Q' -- the power figure run into the badge, the '#'
gone -- and did not parse. The refusal check took "no position" for "not a
refusal", and the march was counted as sent.
"""

import inspect

from rok_farm import queue_ocr
from rok_farm.queue_ocr import _POS_RE, pos_without_hash


def test_the_read_that_was_lost():
    assert _POS_RE.search("3.975.1283560X:1114Y:557Q") is None
    assert pos_without_hash("3.975.1283560X:1114Y:557Q", "3560") == ("3560", 1114, 557)


def test_only_the_map_in_use_anchors_it():
    assert pos_without_hash("3.975.1283560X:1114Y:557Q", "4096") is None
    assert pos_without_hash("3.975.1283561X:1114Y:557Q", "3560") is None
    assert pos_without_hash("3.975.1283560X:1114Y:557Q", None) is None


def test_a_kvk_id_works_the_same_way():
    assert pos_without_hash("12.345S11001X:30Y:535", "S11001") == ("S11001", 30, 535)


def test_both_readers_fall_back_to_it():
    for fn in (queue_ocr.MapPositionMixin._read_position_fast,
               queue_ocr.MapPositionMixin._read_map_position):
        assert "pos_without_hash" in inspect.getsource(fn), fn.__name__
