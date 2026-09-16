"""A deposit somebody is already gathering is visible before the click.

At icon zoom the game draws the occupier as a commander avatar with a round
pickaxe badge on its lower right. The farm used to see none of that: the only
icon-zoom occupancy signal was a march LINE, which exists while the army is
still travelling and disappears once it arrives and starts gathering. So the
bot clicked the node, waited for the zoom, read the pickaxe at tile zoom and
backed out -- 21 such round trips in the saved frames, about half a minute each.

The avatar is worthless as a signal: it is whichever commander leads that
march, and the frames below carry four different ones. The badge is the
constant. Measured 2026-09-16:

  * 365 icon-zoom scan frames, 978 gem icons -> 18 flagged, every one of them
    a real occupied deposit by eye, and no badge fell near an icon but outside
    the accepted window. Re-run through the shipped code on a corpus that had
    grown to 1015 icons: the same hits, nothing new.
  * the badge centre sits +12..+13 px across and 45..51 px above the icon.
  * disc colours on the 21 tile-zoom frames the farm itself confirmed taken:
    17 green (H 50-65), 4 blue (H 95-98). Red never appeared.
"""

import cv2
import pytest

from rok_farm import PROJECT_ROOT
from rok_farm.detect import DetectMixin
from vision.template_matcher import Match

KEEP = PROJECT_ROOT / "screenshots" / "keep" / "occupied_icon_zoom"

# frame -> centre of a gem icon that an army was sitting on
TAKEN = {
    "m11_scan_00_104011.png": (866, 608),
    "m11_scan_02_132436.png": (612, 513),   # the operator's own sample
    "m13_scan_14_105235.png": (537, 478),   # the operator's own sample
    "m1_scan_14_110230.png": (154, 607),
    "m9_scan_03_103607.png": (790, 428),
}

# frame -> centres of gem icons with nobody on them
FREE = {
    "m5_scan_03_112852.png": [(1249, 599), (678, 318), (711, 564),
                              (389, 651), (477, 274)],
    "m12_scan_05_104239.png": [(878, 363), (493, 393), (999, 546),
                               (710, 501), (576, 516)],
    "m13_scan_10_105251.png": [(316, 524)],
}


class Probe(DetectMixin):
    pass


def load(name):
    path = KEEP / name
    if not path.is_file():
        pytest.skip(f"{name} is not kept any more")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip(f"{name} did not decode")
    return frame


def icon_at(cx, cy, w=36, h=48):
    return Match("resources/gem_icon", cx - w // 2, cy - h // 2, w, h, 0.9, (cx, cy))


@pytest.mark.parametrize("name,centre", sorted(TAKEN.items()))
def test_an_army_on_the_deposit_is_seen_before_the_click(name, centre):
    badge = Probe()._gather_badge(load(name), icon_at(*centre))
    assert badge is not None, name
    assert -2 <= badge["dx"] <= 28 and -65 <= badge["dy"] <= -32


@pytest.mark.parametrize("name,centre", sorted(TAKEN.items()))
def test_the_flow_level_check_reports_the_badge(name, centre):
    occupied, info = Probe()._check_icon_occupied(load(name), icon_at(*centre))
    assert occupied, name
    assert "gather_badge" in info or "march_line" in info


@pytest.mark.parametrize("name", sorted(FREE))
def test_free_deposits_are_left_alone(name):
    frame = load(name)
    p = Probe()
    for centre in FREE[name]:
        assert p._gather_badge(frame, icon_at(*centre)) is None, f"{name} {centre}"


def test_the_hud_march_slots_wear_the_same_badge_and_must_not_count():
    """The right-hand strip shows every march as a portrait with this exact
    badge. An icon detected under it would otherwise read as occupied."""
    frame = load("m13_scan_14_105235.png")
    # the strip's badges sit at x=1506, y=258/322/386 in this frame
    fake = icon_at(1506 - 13, 258 + 49)
    assert Probe()._gather_badge(frame, fake) is None


def test_a_badge_that_belongs_to_a_neighbour_is_not_borrowed():
    """The offset window is what ties a badge to one deposit. Shift the icon a
    long way and the same badge must stop counting."""
    frame = load("m11_scan_02_132436.png")
    p = Probe()
    assert p._gather_badge(frame, icon_at(612, 513)) is not None
    assert p._gather_badge(frame, icon_at(612, 513 + 120)) is None
    assert p._gather_badge(frame, icon_at(612 + 120, 513)) is None


def test_the_badge_is_read_from_the_normalized_frame():
    """Every threshold above was measured on saved frames, and what gets saved
    is the normalized capture. The night filter really does fire in play -- the
    pale KvK map reads brightness 139 with a blue cast -- and it cuts saturation
    to 0.6 and, below brightness 90, lifts V by up to 2.0. So a raw badge can
    sit at half the value measured here: the check would not go wrong, it would
    go quiet. The scan must hand the badge check the normalized frame.
    """
    import ast
    import inspect

    from rok_farm import flow_steps

    src = inspect.getsource(flow_steps)
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_check_icon_occupied"]
    assert calls, "the scan no longer asks whether an icon is occupied"
    for call in calls:
        kw = {k.arg: ast.unparse(k.value) for k in call.keywords}
        assert kw.get("shot") == "frame", ast.unparse(call)
