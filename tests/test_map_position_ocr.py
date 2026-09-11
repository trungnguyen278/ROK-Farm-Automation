"""Reading X/Y off the HUD, against what the OCR engine really returned.

The engine hands back several detection boxes and they can OVERLAP. Joining
them blindly duplicated the glyph on the boundary, and because Y is the last
number before the trailing icon it was always Y that grew a digit -- never X,
which has no neighbour to collide with. Those readings went straight into the
map book: Y values of 1944, 2155 and 5240 on a map whose real Y was ~190.

The fragments below are verbatim from RapidOCR on real frames (the file names
are kept so they can be re-read), including the box extents that show the
overlap: in every bad frame the following box started 8-10px to the LEFT of
where the coordinate box ended, and in the good frames it started 6-21px to the
right.
"""

import pytest

import rok_farm.queue_ocr as q


def engine_result(pieces):
    """Fake what RapidOCR returns: (box, text, confidence) per detection.

    Box extents are the REAL ones measured off these frames, because the
    overlap is the whole point: on the failing frames the following box began
    8-10px to the LEFT of where the coordinate box ended, and on the healthy
    ones it began 6-21px to the right. An earlier version of this fixture gave
    every box a width of 10px, which reproduced no overlap at all -- so it
    passed for the wrong reason and could not have caught a geometry bug.
    """
    return [([[l, 0], [r, 0], [r, 30], [l, 30]], text, 0.95)
            for l, r, text in pieces]


# name -> (fragments as (left_x, text), true reading)
FRAMES = {
    # overlapping second box: 316 starts left of 325, so the 4 is read twice
    "m7_scan_08_023535": ([(70.0, 174.0, "26.089.083"),
                           (195.0, 325.0, "#S11465X:149Y:194"),
                           (316.0, 348.0, "4Q")], ("S11465", 149, 194)),
    "m8_scan_04_023701": ([(35.0, 164.0, "#S11465X:193Y:182"),
                           (154.0, 202.0, "2Q")], ("S11465", 193, 182)),
    "m8_scan_05_023717": ([(35.0, 165.0, "#S11465X:175Y:176"),
                           (157.0, 186.0, "6Q")], ("S11465", 175, 176)),
    # healthy frames: the trailing box starts clear of the previous one
    "m7_scan_00_023443": ([(70.0, 174.0, "26.089.083"),
                           (195.0, 322.0, "#S11465X:179Y:189"),
                           (328.0, 344.0, "Q")], ("S11465", 179, 189)),
    "m7_scan_01_023450": ([(70.0, 174.0, "26.089.083"),
                           (195.0, 323.0, "#S11465X:170Y:188")],
                          ("S11465", 170, 188)),
}


class Reader(q.MapPositionMixin):
    pass


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.setattr(q, "_OCR_BACKEND", "rapidocr")
    return Reader()


@pytest.mark.parametrize("name", sorted(FRAMES))
def test_real_frames_read_correctly(name, reader, monkeypatch):
    pieces, expected = FRAMES[name]
    monkeypatch.setattr(q, "_ocr_engine",
                        lambda roi: (engine_result(pieces), None))
    import numpy as np
    frame = np.zeros((862, 1533, 3), dtype=np.uint8)
    assert reader._read_map_position(frame) == expected


def test_the_old_join_really_did_corrupt_these(reader):
    """Guards against a vacuous suite: the bad frames must be genuinely bad.

    If joining ever stops producing the wrong answer, these fixtures no longer
    reproduce the bug and the tests above prove nothing.
    """
    corrupted = 0
    for name, (pieces, expected) in FRAMES.items():
        joined = "".join(t for _, _, t in pieces)
        m = q._POS_RE.search(joined)
        got = (m.group(1), int(m.group(2)), int(m.group(3))) if m else None
        if got != expected:
            corrupted += 1
    assert corrupted == 3, (
        f"expected the three overlapping frames to be corrupted by joining, "
        f"got {corrupted}")


def test_a_genuine_split_still_falls_back_to_joining(reader, monkeypatch):
    """The join is not dead code: no single box holds the whole pattern here."""
    pieces = [(35.0, 88.0, "#S11465X:1"), (90.0, 150.0, "70Y:188")]
    monkeypatch.setattr(q, "_ocr_engine",
                        lambda roi: (engine_result(pieces), None))
    import numpy as np
    assert reader._read_map_position(
        np.zeros((862, 1533, 3), dtype=np.uint8)) == ("S11465", 170, 188)
