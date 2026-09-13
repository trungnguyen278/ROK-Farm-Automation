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


def test_the_refusal_closes_what_it_opened():
    at = FLOW.index("if load is not None and load > GEM_MAX_LOAD:")
    branch = FLOW[at:FLOW.index("return False", at) + len("return False")]
    assert "_dismiss_modal()" in branch, (
        "the march refusal still returns with the deploy panel covering the "
        "game, and the next mine starts behind it")


def test_it_says_so_when_the_panel_will_not_close(): 
    at = FLOW.index("if load is not None and load > GEM_MAX_LOAD:")
    branch = FLOW[at:FLOW.index("return False", at) + 40]
    assert "did not close" in branch, (
        "a panel that refuses to close leaves no trace, which is how this "
        "cost three mines without anything in the log naming the cause")


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
