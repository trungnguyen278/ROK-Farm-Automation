"""Twenty scans of an unchanged screen, and why it will not happen again.

2026-09-22 15:05, live: the zoom gauge said the map was too close, the scan
gave up at ten with no candidate, scrolled out to correct it, reset its
counter and spent ten more scans on a screen that had not changed -- because
the scroll had not worked. The gauge still said close throughout.

The operator also drew the distinction that makes the 18-scan limit
questionable in the first place: a poor map still shows resource icons within
two or three pans. A screen with NO icons at all is a screen being looked at
wrongly, not a barren one. That number is now recorded rather than guessed at.
"""

import ast
import inspect


def _hold_src():
    """The scan-and-verify step, by name. An earlier version of this helper
    guessed at the method and fell through to the whole module, where there
    are six zoom-scroll calls and the assertions landed on the wrong one."""
    from rok_farm import flow_steps
    return inspect.getsource(flow_steps.GemFlowMixin._step_scan_and_verify_gem)


def _correction_branch():
    """From the in-place zoom correction to the end of its branch."""
    src = _hold_src()
    marker = "self._zoom_fixed_this_mine = True"
    idx = src.find(marker)
    assert idx != -1, "the in-place zoom correction is gone"
    return src[idx:idx + 1600]


def test_a_zoom_correction_that_did_nothing_does_not_buy_ten_more_scans():
    after = _correction_branch()
    assert "read_zoom_gauge" in after, (
        "nothing checks whether the scroll moved the gauge; a stuck zoom will "
        "buy another full round of scans")
    assert "_step_return_city" in after, (
        "a zoom that did not move should go back through the city now, not "
        "after ten more scans")


def test_the_counter_reset_still_happens_when_the_fix_worked():
    """The reset is right when the scroll actually changed something."""
    after = _correction_branch()
    assert "no_candidate_floor = scan_count" in after


def test_empty_scans_record_what_was_on_screen():
    """A scan that saw icons and rejected them is a poor map; one that saw
    nothing is a broken view. Until now neither was written down."""
    from rok_farm import detect

    src = inspect.getsource(detect.DetectMixin._find_all_gems)
    assert "_icon_candidates_last" in src, (
        "the count of icon-shaped things on screen is not recorded, so the "
        "18-scan limit cannot be replaced with a measurement")
    tree = ast.parse(src.lstrip())
    # it has to be counted before the gem-specific rejects, or it measures
    # nothing new
    assigns = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Attribute) and n.attr == "_icon_candidates_last"]
    rejects = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "should_click"]
    assert assigns, "not assigned"
    assert rejects, "the classifier call is gone"
    assert min(assigns) < min(rejects), (
        "counted after the classifier, which is the wrong side of the question")


def test_the_scan_logs_it_rather_than_only_printing():
    """Every earlier attempt to measure this failed because the line was a
    print, and prints do not reach the log file."""
    src = _hold_src()
    idx = src.find("no icons")
    assert idx != -1
    around = src[idx:idx + 700]
    assert "logger." in around, (
        "the empty-scan line is still print-only, so the number cannot be "
        "counted afterwards")


# --- Seeing nothing is not the same as seeing no gems ---------------------
#
# The operator, 2026-09-22: "con so 18 truoc do toi thay la viec thay mo nhung
# khong phai mo gem, con viec khong thay mo thi la 1 van de can fix nhanh".
# Two different failures were sharing one counter.

def test_a_blank_screen_gives_up_far_sooner_than_a_poor_map():
    from rok_farm import flow_steps

    assert flow_steps.BLIND_GIVEUP < flow_steps.NO_CANDIDATE_GIVEUP, (
        "a screen showing nothing should give up before one showing the "
        "wrong things")
    src = _hold_src()
    assert "max_empty_streak = 18" in src, "the poor-map limit moved"
    assert flow_steps.BLIND_GIVEUP < 18


def test_the_blind_limit_is_the_number_the_operator_set():
    """Three. I argued for six on the grounds that ocean and mountains could
    trip a lower bar; the operator overruled it and set three. A false trip
    costs one trip through the city, which is where a blind mine ends up
    anyway, so the asymmetry is in their favour."""
    from rok_farm import flow_steps
    assert flow_steps.BLIND_GIVEUP == 3, flow_steps.BLIND_GIVEUP


def test_the_streak_counts_icons_not_gems():
    """The whole point: empty_streak already counts scans with no gem."""
    src = _hold_src()
    idx = src.find("blind_streak += 1")
    assert idx != -1, "the blind streak is gone"
    before = src[max(0, idx - 300):idx]
    assert "_icon_candidates_last" in before, (
        "the blind streak is not keyed on icon-shaped candidates, so it is "
        "just empty_streak under another name")


def test_a_blank_screen_tries_the_zoom_before_blaming_the_map():
    src = _hold_src()
    idx = src.find("blind_streak >= BLIND_GIVEUP")
    assert idx != -1
    branch = src[idx:idx + 2000]
    assert "read_zoom_gauge" in branch
    assert "_step_return_city" in branch
    assert "_BLIND" in branch, "no frame is kept, so the cause stays a guess"


def test_the_blind_check_runs_before_the_no_candidate_one():
    """Otherwise it can never fire -- the other one gives up at ten."""
    src = _hold_src()
    blind = src.find("blind_streak >= BLIND_GIVEUP")
    other = src.find("scan_count - no_candidate_floor >= NO_CANDIDATE_GIVEUP")
    assert blind != -1 and other != -1
    assert blind < other, (blind, other)
