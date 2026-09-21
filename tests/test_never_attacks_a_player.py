"""The farm must never attack another player.

The operator's rule, 2026-09-21, after their own city was attacked while the
farm was running: "khong sao mien ban dung tan cong nguoi khac la duoc".

There is one place this could plausibly go wrong on its own. A gem deposit
that another player is already gathering does not offer "Thu thap" when you
tap it -- it offers an attack. The badge detector is meant to skip those
before they are ever clicked, and it does not catch every one. So the last
line of defence is the deploy panel itself: the farm may only ever press a
button it has positively recognised as the gather button.

These tests pin that, and the two smaller things around it.
"""

import ast
import inspect
from pathlib import Path

import cv2
import numpy as np
import pytest

from rok_farm import PROJECT_ROOT
from rok_farm.config import GATHER_BTN_THRESHOLD

TPL = PROJECT_ROOT / "templates" / "buttons" / "gather_btn.png"


def button_in_hue(hue):
    """The gather button with its hue rotated -- same shape, text and gloss."""
    tpl = cv2.imread(str(TPL))
    if tpl is None:
        pytest.skip("the gather button template is missing")
    if hue is None:
        out = tpl
    else:
        hsv = cv2.cvtColor(tpl, cv2.COLOR_BGR2HSV)
        hsv[:, :, 0] = hue
        out = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    h, w = out.shape[:2]
    canvas = np.full((h + 80, w + 80, 3), 40, np.uint8)
    canvas[40:40 + h, 40:40 + w] = out
    return canvas


def score(frame):
    tpl = cv2.imread(str(TPL))
    res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
    return float(cv2.minMaxLoc(res)[1])


def test_the_real_gather_button_is_recognised():
    assert score(button_in_hue(None)) >= GATHER_BTN_THRESHOLD


@pytest.mark.parametrize("name,hue", [("attack red", 0), ("orange", 10),
                                      ("green", 60)])
def test_a_button_of_another_colour_is_not_the_gather_button(name, hue):
    """Measured: cyan 1.000, red 0.070, orange 0.105, green 0.580, against a
    threshold of 0.65. The match is strongly colour-discriminating, which is
    what keeps an attack button on an occupied deposit from being pressed."""
    s = score(button_in_hue(hue))
    assert s < GATHER_BTN_THRESHOLD, f"{name} scored {s:.3f}"


def test_the_farm_knows_no_generic_confirm_button():
    """Every confirm template is for one named dialog. A generic OK could
    confirm anything put in front of it, including a march to attack."""
    from rok_farm import button_registry as br
    names = [n for n in dir(br) if not n.startswith("_")]
    confirms = set()
    for n in names:
        v = getattr(br, n)
        if isinstance(v, (list, tuple, set, frozenset)):
            confirms |= {x for x in v if isinstance(x, str) and "confirm" in x}
    allowed = {"ui/btn_confirm_reconnect", "ui/btn_confirm_reward",
               "ui/btn_confirm_alliance", "ui/btn_confirm_exit"}
    assert confirms <= allowed, confirms - allowed


def test_the_barbarian_auto_only_ever_touches_its_own_four_buttons():
    """The action-point run goes after barbarians, which are NPCs. Read off
    the source so a fifth position cannot be added without this noticing."""
    from rok_farm import phases as ph
    tree = ast.parse(inspect.getsource(ph.PhasesMixin._maybe_burn_ap).lstrip())
    used = {n.attr for n in ast.walk(tree)
            if isinstance(n, ast.Attribute)
            and isinstance(n.value, ast.Name) and n.value.id == "ap_burn"
            and n.attr.endswith("_PCT")}
    assert used == {"SEARCH_BTN_PCT", "BARB_TAB_PCT", "AUTO_BTN_PCT",
                    "START_BTN_PCT"}, used
