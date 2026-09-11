"""Do not print a number the code has already decided not to believe.

The log announced "est. gather 6432030m, home in ~6432044m" and only refused
that estimate on the NEXT line, so a healthy run read as though the bot were
about to wait twelve years. It never was: the guard drops the estimate and the
march goes out untimed.

The operator read it and asked what had gone wrong. Nothing had -- the log was
just lying about what the bot intended to do.
"""

import pytest

from rok_farm import PROJECT_ROOT

SRC = PROJECT_ROOT / "rok_farm" / "queue_ocr.py"


@pytest.fixture(scope="module")
def block():
    src = SRC.read_text(encoding="utf-8")
    start = src.index("est = self.predict_gather_seconds(info)")
    return src[start:src.index("self.note_march_sent(info)", start)]


def test_an_implausible_estimate_is_not_announced_as_a_plan(block):
    assert "MAX_GATHER_SECONDS" in block, (
        "the printed line does not check plausibility, so it will announce a "
        "figure the guard is about to throw away")
    assert "implausible" in block.lower()


def test_the_plausible_case_still_prints_the_arrival(block):
    """The whole point of the line: when the estimate holds, say when troops
    get home."""
    assert "home in ~" in block


def test_the_check_matches_the_guard_that_drops_it(block):
    """Two different thresholds here would be worse than one: the line would
    disagree with the behaviour it is describing."""
    import re
    from rok_farm.queue_ocr import MAX_GATHER_SECONDS
    assert MAX_GATHER_SECONDS > 0
    # the print must compare against that same constant, not a literal
    assert re.search(r"est\s*>\s*MAX_GATHER_SECONDS", block), \
        "the printed line uses its own threshold instead of the guard's"
