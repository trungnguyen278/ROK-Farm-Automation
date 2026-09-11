"""A wait shorter than the alt-tab cycle must not be spent alt-tabbing.

Tabbing out and back costs about twenty seconds of sleeps on its own. Planning
to stay out for less than that is all overhead and no waiting -- and it leaves
a burst of alt-tabs that no player produces, which by this project's own rule
matters more than being slow: mechanical repetition is the tell, not latency.

The floor for this was already written, with a comment describing the exact
symptom, and it did not reach the case it was for: a wait under
WAIT_EARLY_MARGIN takes the earlier branch where plan = wait_s with no floor.
Nine of 112 waits in the log came out under six seconds, printing
"alt-tab out for 0.0min".
"""

import re

import pytest

from rok_farm import PROJECT_ROOT

SRC = PROJECT_ROOT / "rok_farm" / "phases.py"


@pytest.fixture(scope="module")
def source():
    return SRC.read_text(encoding="utf-8")


def test_a_short_wait_returns_before_any_tab(source):
    body = source[source.index("wait_s = self.seconds_until_first_return()"):]
    body = body[:body.index("# No estimate available")]

    guard = body.index("if wait_s < TAB_CYCLE_COST")
    tab_out = body.index("self._tab_out()")
    assert guard < tab_out, \
        "the short-wait guard sits after the alt-tab, so it cannot prevent it"
    # and it must actually leave, not fall through into the tab
    between = body[guard:tab_out]
    assert "return" in between, "the guard does not return; the tab still runs"


def test_the_guard_still_waits(source):
    """Skipping the tab must not skip the WAIT -- the troops are still out."""
    body = source[source.index("if wait_s < TAB_CYCLE_COST"):]
    body = body[:body.index("if plan >")]
    assert "_sleep_until_woken" in body, \
        "the short wait no longer sleeps, so the queue is re-read too early"
    assert "wait_s" in body


def test_the_short_wait_is_still_interruptible(source):
    """!check must still be able to cut a wait short, however short it is."""
    body = source[source.index("if wait_s < TAB_CYCLE_COST"):]
    body = body[:body.index("if plan >")]
    assert "_sleep_until_woken" in body, \
        "a plain sleep here would ignore a wake request"


def test_the_tab_cost_is_a_measurement_not_a_knob(source):
    """It is derived from _tab_back's own sleeps; keep it documented as such."""
    m = re.search(r"TAB_CYCLE_COST = ([\d.]+)", source)
    assert m, "TAB_CYCLE_COST is gone"
    assert float(m.group(1)) >= 10, \
        "a tab cycle cannot cost less than its own sleeps"
