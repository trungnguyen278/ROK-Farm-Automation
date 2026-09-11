"""A wood mine is not a gem mine, and only the payload says so.

Three marches went out carrying 29.921 to 178.000 troops. I read the first as
a wrong button pressed on an empty tile; the operator identified it as a WOOD
mine taken for a gem one. That distinction matters: the popup is genuine and
the buttons are the right buttons, so neither the button text nor its position
can see the mistake. The deploy panel can.

Measured over 272 panel readings:

    gem mine      load = 10 or 30          troops   363 - 1.384
    anything else load = 954.459-2.144.010 troops 29.921 - 178.000

Three orders of magnitude apart, nothing between.

The cost of refusing is nothing: the node was never a gem, so no gem mine is
lost. The cost of NOT refusing is an army out, a march slot held, and a record
that cannot be timed -- which blinds every wait that follows for up to three
hours.
"""

import pytest

from rok_farm.config import GEM_MAX_LOAD

# 10 and 30 are what the log shows. The operator puts the ceiling near 50
# and says a partly gathered mine reads lower still, so single digits are
# ordinary and must not be refused.
GEM_LOADS = [1, 3, 7, 10, 30, 49]
OTHER_LOADS = [954459, 954479, 1272602, 1431688, 2144010]


@pytest.mark.parametrize("load", GEM_LOADS)
def test_a_gem_mine_is_allowed(load):
    assert load <= GEM_MAX_LOAD


@pytest.mark.parametrize("load", OTHER_LOADS)
def test_every_other_node_is_refused(load):
    assert load > GEM_MAX_LOAD


def test_the_threshold_sits_in_empty_space():
    """Not tuned to an edge: the nearest values are 30 and 954.459."""
    assert GEM_MAX_LOAD > max(GEM_LOADS) * 10, \
        "too close to a real gem reading; jitter would refuse real mines"
    assert GEM_MAX_LOAD < min(OTHER_LOADS) / 100, \
        "too close to a non-gem reading to be safe"


def test_the_check_runs_before_the_march_is_committed():
    """Reading the panel after the march is too late to refuse it."""
    from rok_farm import PROJECT_ROOT
    src = (PROJECT_ROOT / "rok_farm" / "flow_steps.py").read_text(encoding="utf-8")
    start = src.index("Step 6: Troop + March")
    block = src[start:src.index("March sent (fixed", start)]
    check = block.index("GEM_MAX_LOAD")
    click = block.index("MARCH_BTN_PCT, jitter_px")
    assert check < click, \
        "the load is read after the March button is pressed, which cannot stop it"
