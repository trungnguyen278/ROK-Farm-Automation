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
    out = []
    for left, text in pieces:
        box = [[left, 0], [left + 10, 0], [left + 10, 20], [left, 20]]
        out.append((box, text, 0.95))
    return out


class Counter(q.GemCounterMixin):
    pass


@pytest.fixture
def reader(monkeypatch):
    monkeypatch.setattr(q, "_OCR_BACKEND", "rapidocr")
    return Counter()


def test_a_split_number_keeps_its_boxes(reader, monkeypatch):
    """The exact shape seen live: right-most box alone loses the leading digits."""
    monkeypatch.setattr(q, "_ocr_engine",
                        lambda roi: (engine_result([(10.0, "55"), (30.0, "104")]), None))
    frame = np.zeros((862, 1533, 3), dtype=np.uint8)
    value = reader._read_gem_count(frame)

    assert value == 104, "behaviour changed; this test documents the CURRENT rule"
    assert reader._gem_pieces == [(10.0, "55"), (30.0, "104")], \
        "the raw boxes were not kept, so a rejection cannot be explained"


def test_a_single_box_still_reads_normally(reader, monkeypatch):
    monkeypatch.setattr(q, "_ocr_engine",
                        lambda roi: (engine_result([(10.0, "55.104")]), None))
    assert reader._read_gem_count(
        np.zeros((862, 1533, 3), dtype=np.uint8)) == 55104


def test_the_guard_rejects_a_clipped_read_and_keeps_the_previous(reader, monkeypatch):
    """A clipped read must not become the new baseline, or every later
    reading is judged against a number that never existed."""
    seq = iter([
        engine_result([(10.0, "55.040")]),      # good
        engine_result([(10.0, "55"), (30.0, "104")]),   # clipped -> 104
        engine_result([(10.0, "55.104")]),      # good again
    ])
    monkeypatch.setattr(q, "_ocr_engine", lambda roi: (next(seq), None))
    frame = np.zeros((862, 1533, 3), dtype=np.uint8)

    assert reader.note_gem_count(frame) == 55040
    assert reader.note_gem_count(frame) is None, "the clipped read was accepted"
    assert reader.note_gem_count(frame) == 55104, \
        "a rejected read poisoned the baseline"
