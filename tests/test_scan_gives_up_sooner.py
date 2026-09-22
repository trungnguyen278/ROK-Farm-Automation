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
