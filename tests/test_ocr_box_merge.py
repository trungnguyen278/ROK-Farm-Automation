"""RapidOCR does not promise one box per number, and this project assumed it did.

Both readings broke, in opposite directions, from the same cause -- boxes that
OVERLAP, so the glyph at the seam is decoded twice:

    map position  joined every box   '...Y:182' + '2Q'   -> Y=1822
    gem counter   took the last box  '62.5' + '.550'     -> 550

Measured on the frames that failed, the following box began 8-10px to the LEFT
of where the previous one ended; on the frames that worked it began 6-21px to
the right. So overlap is decided on geometry, and only then is the repeated
text removed -- doing it on text alone would eat a genuine repeat, since two
boxes reading "11" and "11" are a real "1111" when they merely abut.

Box lists below are verbatim from the log.
"""

import pytest

from rok_farm.queue_ocr import merge_boxes


def det(left, right, text):
    return ([[left, 0], [right, 0], [right, 30], [left, 30]], text, 0.95)


def test_the_gem_counter_number_split_across_two_boxes():
    """Real: 62.550 read as '62.5' then '.550', the '.5' seen twice."""
    out = merge_boxes([det(11, 60, "32.0M"), det(103, 130, "62.5"),
                       det(121, 160, ".550")])
    assert out.endswith("62.550"), out


def test_the_map_position_trailing_box():
    """Real: Y:194 with a following box that re-read the 4."""
    out = merge_boxes([det(195, 325, "#S11465X:149Y:194"), det(316, 348, "4Q")])
    assert out.endswith("Y:194Q"), out
    assert "1944" not in out


@pytest.mark.parametrize("y,tail", [("182", "2Q"), ("176", "6Q")])
def test_the_other_recorded_map_failures(y, tail):
    out = merge_boxes([det(35, 164, f"#S11465X:193Y:{y}"), det(154, 202, tail)])
    assert f"Y:{y}Q" in out
    assert y + tail[0] not in out


def test_a_healthy_frame_is_unchanged():
    """Non-overlapping boxes must join exactly as before."""
    out = merge_boxes([det(70, 174, "26.089.083"),
                       det(195, 322, "#S11465X:179Y:189"), det(328, 344, "Q")])
    assert out == "26.089.083#S11465X:179Y:189Q"


def test_abutting_boxes_keep_a_real_repeat():
    """The reason geometry decides, not text.

    Two boxes that merely touch can legitimately read the same digits; only
    an overlap means the same glyph was decoded twice.
    """
    assert merge_boxes([det(10, 40, "11"), det(40, 70, "11")]) == "1111"


def test_overlapping_boxes_drop_the_repeat():
    assert merge_boxes([det(10, 40, "11"), det(35, 70, "11")]) == "11"


def test_no_boxes_is_empty_not_an_error():
    assert merge_boxes([]) == ""
    assert merge_boxes(None) == ""
