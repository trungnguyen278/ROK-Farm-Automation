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


def test_the_counter_is_raised_in_the_function_the_scan_loop_calls():
    """detect.py has two near-identical finders and only one is used here.

    The counter first went into _find_all_gems, which the scan loop does not
    call. It therefore never left zero, "no candidates" was always true, and
    the early give-up cut every mine at ten scans -- including one that had
    already classified a gem. Same file, same shape, wrong function.
    """
    src = DETECT.read_text(encoding="utf-8")
    flow = FLOW.read_text(encoding="utf-8")

    called = {m for m in ("_find_all_icons", "_find_all_gems")
              if f"self.{m}(frame)" in flow[flow.index("def _step_scan_and_verify_gem"):]}
    assert called, "the scan loop calls neither finder; has it been renamed?"

    for name in called:
        start = src.index(f"def {name}(")
        nxt = src.find("\n    def ", start + 10)
        body = src[start:nxt if nxt != -1 else len(src)]
        assert "_candidates_this_mine" in body, (
            f"{name} is what the scan loop calls and it does not count "
            f"candidates, so the give-up cannot tell a blank map from a "
            f"barren one")
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


def test_a_blank_map_is_abandoned_early(flow):
    """Eighteen scans cannot fix a zoom. A scroll can; failing that, the city.

    Measured over 649 mines: the first candidate arrives on scan 0 at the
    median, scan 1 at p90, scan 7 at p99, 13 at the worst. Ten scans with
    NOTHING is not a barren patch, it is a map not drawing deposits.

    The give-up now reads the zoom gauge first and scrolls out in place when
    the HUD says the map is zoomed in, so the walk back through the city -- a
    whole mine's worth of actions, taken only to reset the zoom by side
    effect -- is the fallback rather than the only answer.
    """
    from rok_farm.flow_steps import NO_CANDIDATE_GIVEUP

    assert 8 <= NO_CANDIDATE_GIVEUP <= 13, (
        f"{NO_CANDIDATE_GIVEUP} sits outside the measured range: below 8 it "
        f"starts cutting healthy mines, above 13 it saves nothing")

    # Anchor on the condition, not on a character distance from the message:
    # the branch grew and the old window silently stopped covering it.
    start = flow.index("NO_CANDIDATE_GIVEUP\n", flow.index("def _step_scan"))
    early = flow[start:start + 2200]
    assert "NOT ONE candidate" in early
    assert "_step_return_city" in early, \
        "the early exit does not go through the city, so a zoom the scroll " \
        "could not fix is never reset"


def test_the_early_exit_needs_zero_candidates_not_just_empty_scans(flow):
    """A patch that yields candidates the classifier rejects is ordinary."""
    start = flow.index("NO_CANDIDATE_GIVEUP\n", flow.index("def _step_scan"))
    block = flow[start:start + 400]
    assert "_candidates_this_mine" in block, (
        "the early exit fires on empty scans alone, which would cut short any "
        "mine searching genuinely barren ground")
