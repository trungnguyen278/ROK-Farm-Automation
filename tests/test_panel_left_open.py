"""Refusing to march must not leave the deploy panel on the screen.

Photographed on 2026-09-13. One refusal at 12:17 cost three mines:

    m12  load=1,272,602 -- not a gem node, refused, panel left open
    m13  "10 scans and NOT ONE candidate (zoom gauge: None)" -- the panel
         hides the deposits AND the coordinate badge the gauge reads, so the
         detector and its own instrument went blind together
    m14  "Not on world map after toggling" -- the toggles were landing on
         the panel

m14's world_fail frame is that deploy panel, pixel for pixel the one m12
refused: 45,613 troops, load 1,272,602, HANH QUAN 00:05:11. It is also the
likeliest reading of the 19 world-nav failures in the log that had no
explanation at all -- no frame of one had ever been kept until today.
"""

from rok_farm import PROJECT_ROOT

FLOW = (PROJECT_ROOT / "rok_farm" / "flow_steps.py").read_text(encoding="utf-8")


def test_nothing_returns_from_the_march_step_with_the_panel_open():
    """The leak, closed by removing the refusal that caused it.

    The load guard used to refuse a non-gem node and return False with the
    deploy panel still up. The operator's call on 2026-09-13 was that
    gathering the wrong mine occasionally is fine as long as it IS a mine, so
    that branch now marches instead -- and the march click closes the panel by
    itself. This pins the property rather than the mechanism: once the deploy
    panel is open, the step must not bail out and leave it there.
    """
    start = FLOW.index("def _step_click_march")
    body = FLOW[start:FLOW.index("\n    def ", start + 10)]
    after_panel = body[body.index("_wait_for_troop_panel"):]
    code = "\n".join(ln for ln in after_panel.splitlines()
                     if not ln.strip().startswith("#"))
    # The one return False right there is the panel NOT opening, which leaves
    # nothing on screen to strand us.
    bails = [ln for ln in code.splitlines() if "return False" in ln]
    assert len(bails) <= 1, (
        "something returns from the march step after the deploy panel has "
        f"opened, leaving it covering the game: {bails}")


def test_a_non_gem_mine_is_gathered_not_refused():
    """It is still a mine, and the troops still come home with something."""
    at = FLOW.index("if load is not None and load > GEM_MAX_LOAD:")
    branch = FLOW[at:at + 1200]
    assert "gathering it anyway" in branch
    assert "return False" not in branch[:branch.index("March (Hanh quan)")], \
        "a big load still aborts the march"


def test_the_nav_failure_asks_whether_something_is_covering_the_button():
    """Three toggles that all miss look the same whether the corner is wrong
    or a panel is sitting on it."""
    at = FLOW.index('[{FAIL}] Not on world map after toggling')
    before = FLOW[max(0, at - 1200):at]
    assert "_dismiss_modal()" in before, (
        "world-map navigation gives up without checking whether anything is "
        "covering the button it keeps missing")
    assert "_wait_until_world_map" in before


def test_the_retry_after_a_dismiss_is_bounded():
    """One extra toggle, not a loop. If the panel was not the problem,
    clicking the corner over and over is exactly the mechanical behaviour the
    anti-detection work exists to avoid."""
    at = FLOW.index('[{FAIL}] Not on world map after toggling')
    branch = FLOW[FLOW.index("_dismiss_modal()", at - 1200):at]
    code = "\n".join(ln for ln in branch.splitlines()
                     if not ln.strip().startswith("#"))
    assert " for " not in code and "while " not in code, \
        "the post-dismiss retry loops instead of trying once"
    assert code.count("_toggle_view(") <= 1, \
        "more than one extra toggle after the dismiss"
