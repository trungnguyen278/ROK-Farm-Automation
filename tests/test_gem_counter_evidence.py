"""A rejected gem reading must say what the engine returned.

The jump guard is right to refuse a clipped read -- dropping a leading digit
turns 55.104 into 5104, which parses perfectly and would wreck the session
total. But it refused twice in one night without recording anything, and the
map-position field had a fault of exactly this shape (boxes that split or
overlap where the code assumed one box per number) that was only solvable once
the raw boxes were in the log.

No fix is attempted here on purpose: whether to prefer the right-most box or
the join depends on what else sits in that crop, and guessing at it is what
sent the load-field investigation down a wrong path for two days.
"""

import numpy as np
import pytest

import rok_farm.queue_ocr as q


def engine_result(pieces):
    """Real box extents: whether two boxes OVERLAP is what decides the read."""
    return [([[l, 0], [r, 0], [r, 20], [l, 20]], text, 0.95)
            for l, r, text in pieces]


class Counter(q.GemCounterMixin):
    pass


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.setattr(q, "_OCR_BACKEND", "rapidocr")
    return Counter()


def test_the_real_split_that_was_caught_live(reader, monkeypatch):
    """Verbatim from the log: 62.550 arrived as '62.5' then '.550'.

    The boxes overlap -- 121 starts before 130 ends -- so the '.5' at the seam
    was decoded twice. Taking the last box alone read 550, the guard rejected
    it, and the reading was lost. Merging recovers the real number.
    """
    monkeypatch.setattr(q, "_ocr_engine", lambda roi: (engine_result([
        (11.0, 60.0, "32.0M"), (103.0, 130.0, "62.5"),
        (121.0, 160.0, ".550")]), None))
    assert reader._read_gem_count(
        np.zeros((862, 1533, 3), dtype=np.uint8)) == 62550


def test_the_boxes_are_still_kept_for_evidence(reader, monkeypatch):
    """A rejection that records nothing cannot be diagnosed later."""
    monkeypatch.setattr(q, "_ocr_engine", lambda roi: (engine_result([
        (10.0, 40.0, "55"), (35.0, 70.0, "104")]), None))
    reader._read_gem_count(np.zeros((862, 1533, 3), dtype=np.uint8))
    assert reader._gem_pieces, \
        "the raw boxes were not kept, so a rejection cannot be explained"


def test_a_single_box_still_reads_normally(reader, monkeypatch):
    monkeypatch.setattr(q, "_ocr_engine",
                        lambda roi: (engine_result([(10.0, 80.0, "55.104")]), None))
    assert reader._read_gem_count(
        np.zeros((862, 1533, 3), dtype=np.uint8)) == 55104


def test_the_guard_rejects_a_clipped_read_and_keeps_the_previous(reader, monkeypatch):
    """A clipped read must not become the new baseline, or every later
    reading is judged against a number that never existed."""
    seq = iter([
        engine_result([(10.0, 80.0, "55.040")]),            # good
        engine_result([(10.0, 40.0, "9"), (30.0, 70.0, "99")]),  # nonsense
        engine_result([(10.0, 80.0, "55.104")]),            # good again
    ])
    monkeypatch.setattr(q, "_ocr_engine", lambda roi: (next(seq), None))
    frame = np.zeros((862, 1533, 3), dtype=np.uint8)

    assert reader.note_gem_count(frame) == 55040
    assert reader.note_gem_count(frame) is None, "the clipped read was accepted"
    assert reader.note_gem_count(frame) == 55104, \
        "a rejected read poisoned the baseline"


def test_both_box_edges_are_recorded(reader, monkeypatch):
    """A left edge alone cannot say whether two boxes overlap.

    Six refused readings were logged before this was noticed, and not one of
    them could be used to evaluate a fix: the seam disagreements ('63.' + '8.605',
    where the same glyph reads 3 in one box and 8 in the other) need the overlap
    WIDTH to say how many characters were read twice, and the width needs both
    edges.
    """
    monkeypatch.setattr(q, "_ocr_engine", lambda roi: (engine_result([
        (104.0, 130.0, "63."), (117.0, 160.0, "8.605")]), None))
    reader._read_gem_count(np.zeros((862, 1533, 3), dtype=np.uint8))

    assert reader._gem_pieces, "no boxes recorded at all"
    first = reader._gem_pieces[0]
    assert len(first) == 3, (
        f"recorded {first!r}; without a right edge the overlap cannot be "
        f"measured and the evidence is unusable")
    left, right, text = first
    assert right > left, "the right edge is not to the right of the left one"


def test_the_crop_is_enlarged_before_reading():
    """Bigger text gives the detector less reason to split the number.

    Every corrupted gem reading came from the engine splitting across boxes
    that then disagreed about the glyph in the overlap -- '63.' and '8.989' for
    a real 63.989, the same character read as 3 in one box and 8 in the other.
    Merging cannot repair that; the boxes share no text to align on.

    Measured on the frame that produced exactly that failure: 1x gave three
    boxes and '63.8.989'; 2x, 3x and 4x gave two boxes and '63.989'.
    """
    from rok_farm import PROJECT_ROOT
    src = (PROJECT_ROOT / "rok_farm" / "queue_ocr.py").read_text(encoding="utf-8")
    body = src[src.index("def _read_gem_count"):]
    body = body[:body.index("\n    def ", 10)]
    assert "GEM_OCR_UPSCALE" in body, "the gem crop is no longer enlarged"
    assert q.GEM_OCR_UPSCALE >= 2, \
        "below 2x the engine split the number and corrupted it"

    resize = body.index("cv2.resize")
    call = body.index("_ocr_engine(")
    assert resize < call, "the crop is enlarged after being read, which does nothing"


def test_enlarging_does_not_narrow_the_crop():
    """Sizing the crop to today's number is what once clipped a leading digit.

    152.531 read as 52.531 -- silently, because a clipped number still parses.
    The fix for splitting must not reintroduce that.
    """
    assert q.GEM_ROI[0] <= 0.88, \
        "the gem crop got narrower; a number that grows a digit will be clipped"
    assert q.GEM_ROI[2] >= 0.99
