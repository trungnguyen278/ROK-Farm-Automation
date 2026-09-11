"""Giving up after 18 empty scans has meant two unrelated things.

Barren ground still produces CANDIDATES that the classifier turns down -- six
to nineteen of them in a healthy mine. Zero across the whole streak means the
icon stage found nothing to even consider, which is not scarcity: the map is
not drawing what the bot is looking for.

Seen twice on 2026-09-11, from different causes and with identical log output:
once at the wrong zoom, and once with the map filter panel open and its
resource layer switched OFF, which hides every deposit including gem mines.
Naming it turns an invisible failure into one that says what to check.
"""




import pytest

from rok_farm import PROJECT_ROOT

FLOW = PROJECT_ROOT / "rok_farm" / "flow_steps.py"
DETECT = PROJECT_ROOT / "rok_farm" / "detect.py"


@pytest.fixture(scope="module")
def flow():
    return FLOW.read_text(encoding="utf-8")


def test_the_counter_is_reset_for_each_mine(flow):
    """Carried over, it always says "yes, we saw something" and never fires."""
    start = flow.index("def _step_scan_and_verify_gem")
    head = flow[start:start + 900]
    assert "_candidates_this_mine = 0" in head, \
        "the candidate counter is not reset when a mine's scan begins"


def test_the_counter_is_raised_where_candidates_are_seen():
    src = DETECT.read_text(encoding="utf-8")
    assert "_candidates_this_mine" in src, (
        "nothing counts candidates, so the give-up message cannot tell the "
        "two failures apart")
    # It must count BEFORE the classifier's verdict: a rejected candidate is
    # still evidence the map drew something.
    idx = src.index("_candidates_this_mine")
    verdict = src.index("should_click", idx)
    assert idx < verdict, (
        "candidates are only counted after the classifier accepts them, so a "
        "mine full of rejects would look like a blank map")


def _giveup_block(flow):
    """The branch taken when the scan budget runs out."""
    start = flow.index("if empty_streak >= max_empty_streak:")
    return flow[start:flow.index("self._step_return_city", start) + 200]


def test_the_give_up_message_distinguishes_the_two_cases(flow):
    block = _giveup_block(flow)
    assert "_candidates_this_mine" in block, \
        "the give-up path no longer checks whether anything was ever seen"
    assert "filter" in block.lower(), \
        "the message should name what to check, or it is just another warning"


def test_the_ordinary_message_survives(flow):
    """A genuinely barren patch must still report plainly, not alarmingly."""
    assert "restarting from city" in _giveup_block(flow)
