"""The mail tab badges sit above the strip that was scanned for them.

_find_mail_tab_badges found nothing on 47 opens out of 47, while the mail
BUTTON's own badge was detected perfectly every time -- so there was unread
mail on every one of those opens and the panel was opened and closed again
without reading a letter.

Measured on the two frames the panel saved on 2026-09-13:

    MAIL_NO_TAB_BADGES_130505   x=0.412 y=0.015  20x22  aspect 0.91
    MAIL_NO_TAB_BADGES_180640   x=0.326 y=0.015  19x21  aspect 0.90
                                x=0.412 y=0.015  20x22  aspect 0.91

The band started at y=0.03. It began just BELOW them.

In the second frame BAO CAO read 40 unread and LIEN MINH 6, and it was the
operator who noticed the alliance tab was still being ignored.
"""

import cv2
import pytest

from anti_detection.player_actions import _find_mail_tab_badges
from rok_farm import PROJECT_ROOT

REFS = PROJECT_ROOT / "screenshots" / "keep" / "feature_refs"
# (file, how many badges are visible by eye, their x positions)
CASES = [
    ("MAIL_NO_TAB_BADGES_130505.png", [0.412]),
    ("MAIL_NO_TAB_BADGES_180640.png", [0.326, 0.412]),
]


def load(name):
    path = REFS / name
    if not path.is_file():
        pytest.skip(f"{name} is not kept any more")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip(f"{name} did not decode")
    return frame


@pytest.mark.parametrize("name,xs", CASES)
def test_every_badge_on_the_frame_is_found(name, xs):
    got = _find_mail_tab_badges(load(name))
    assert len(got) == len(xs), (
        f"{name}: expected {len(xs)} tab badge(s) at {xs}, got "
        f"{[(round(x, 3), round(y, 3)) for x, y in got]}")
    for (gx, gy), want in zip(got, xs):
        assert abs(gx - want) < 0.02, f"{name}: badge at {gx:.3f}, expected {want}"
        assert gy < 0.03, (
            f"{name}: badge reported at y={gy:.3f}; they sit at 0.015 and a "
            f"band that starts below that is what caused 47 empty opens")


def test_the_band_reaches_the_last_tab():
    """A badge sits about 0.035 right of its tab's label, and the last tab
    (MUC UA THICH, label x=0.633) would put one at 0.668 -- outside the old
    crop, which stopped at 0.60."""
    src = (PROJECT_ROOT / "anti_detection" / "player_actions.py").read_text(
        encoding="utf-8")
    at = src.index("def _find_mail_tab_badges")
    body = src[at:src.index("\ndef ", at + 10)]
    import re
    x2 = float(re.search(r"x2 = int\(fw \* ([\d.]+)\)", body).group(1))
    y1 = float(re.search(r"y1 = int\(fh \* ([\d.]+)\)", body).group(1))
    assert x2 >= 0.68, f"the crop stops at {x2}; the last tab's badge is at 0.668"
    assert y1 <= 0.005, f"the band starts at {y1}; the badges are at 0.015"


def test_the_wrong_active_tab_check_is_gone():
    """It returned x=0.488 (HE THONG) on both frames while BAO CAO at 0.292
    was the highlighted tab. With badges at 0.326 and 0.412 that would have
    marked LIEN MINH "already active" and read the reports tab instead."""
    src = (PROJECT_ROOT / "anti_detection" / "player_actions.py").read_text(
        encoding="utf-8")
    # Comments stripped: the only mention left IS the paragraph explaining why
    # it was removed, and a test that trips over its own documentation has
    # cost four rounds of this today already.
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith("#"))
    assert "_detect_active_mail_tab_x" not in code, \
        "the active-tab detector is back; it was wrong on every frame tested"


# --- The alert border ------------------------------------------------------

def test_an_alert_border_is_not_an_empty_mailbox():
    """2026-09-21 16:01:05 reported 0 badged tabs off a panel whose HE THONG
    tab carries a red 3. A red border round the whole client had filled the
    strip the badges are counted in.

    Measured on the 26px edge ring: 42.3% and 55.9% red on the three alert
    frames, 1.8% on an ordinary city frame, and nothing else in 645 frames
    came near.
    """
    from rok_farm.state_probe import alert_border, under_alert
    keep = PROJECT_ROOT / "screenshots"
    alert = keep / "gem_farm_test" / "MAIL_NO_TAB_BADGES_160038.png"
    if not alert.exists():
        pytest.skip("the alert frame is not kept any more")
    im = cv2.imread(str(alert))
    assert under_alert(im), alert_border(im)

    calm = sorted(keep.glob("**/MAIL_AFTER_READ_*.png"))
    if not calm:
        pytest.skip("no ordinary mail panels are kept any more")
    for f in calm:
        c = cv2.imread(str(f))
        if c is not None:
            assert not under_alert(c), (f.name, alert_border(c))


# --- The system tab -------------------------------------------------------
#
# The rare glance at HE THONG exists because the anti-cheat letters arrive
# there. It was opening LIEN MINH instead, and saying it had not.

SYSTEM_TAB_FRAMES = PROJECT_ROOT / "screenshots" / "keep" / "mail"


def mail_frame(name):
    path = SYSTEM_TAB_FRAMES / name
    if not path.is_file():
        pytest.skip(f"{name} is not kept any more")
    im = cv2.imread(str(path))
    if im is None:
        pytest.skip(f"{name} did not decode")
    return im


def system_tab_match(frame):
    """Where the inactive HE THONG artwork matches, as the feature sees it."""
    tpl = cv2.imread(str(PROJECT_ROOT / "templates" / "ui" / "mail_tab_system.png"))
    if tpl is None:
        pytest.skip("the system tab template is missing")
    res = cv2.matchTemplate(frame, tpl, cv2.TM_CCOEFF_NORMED)
    _, conf, _, loc = cv2.minMaxLoc(res)
    return (loc[0] + tpl.shape[1] / 2) / frame.shape[1], conf


def test_the_alliance_tab_wearing_system_artwork_is_refused():
    """With HE THONG already active its own artwork is not on screen, so the
    template settles on LIEN MINH at x 0.374 with confidence 0.92 -- over the
    0.70 the code accepts. 15 of 40 accepted matches across the saved frames
    were this."""
    import anti_detection.player_actions as pa
    x, conf = system_tab_match(mail_frame("SYSTEM_TAB_ACTIVE_110504.png"))
    assert conf >= 0.70, conf
    assert abs(x - pa.MAIL_SYSTEM_TAB_AT) > pa.MAIL_SYSTEM_TAB_TOL, (
        f"the decoy at x {x:.3f} still passes the position gate")


def test_the_real_system_tab_passes():
    """21 matches at x 0.461 across the saved frames, to three decimals."""
    import anti_detection.player_actions as pa
    x, conf = system_tab_match(mail_frame("OPENED_THE_WRONG_TAB_110444.png"))
    assert conf >= 0.70, conf
    assert abs(x - pa.MAIL_SYSTEM_TAB_AT) <= pa.MAIL_SYSTEM_TAB_TOL, x


def test_the_feature_checks_the_position_before_it_clicks():
    import ast
    import inspect
    import anti_detection.player_actions as pa

    tree = ast.parse(inspect.getsource(pa._open_system_tab).lstrip())
    gate = click = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "MAIL_SYSTEM_TAB_AT" and gate is None:
            gate = node.lineno
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_click_in_mail_panel" and click is None):
            click = node.lineno
    assert gate is not None, "the position gate is gone"
    assert click is not None
    assert gate < click, f"gate at {gate} comes after the click at {click}"


def test_already_on_the_system_tab_still_keeps_a_picture():
    """The refusal added this morning was right but left a hole.

    Live 2026-09-22 17:37: HE THONG was already the active tab after a
    read-all on it, so its inactive artwork was not on screen, the template
    settled on LIEN MINH at 0.374, and the glance correctly declined to click
    -- and returned with no picture of the one tab the anti-cheat letters
    arrive on. Being already there is the good case.
    """
    import ast
    import inspect
    import anti_detection.player_actions as pa

    tree = ast.parse(inspect.getsource(pa._open_system_tab).lstrip())
    names = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
             and isinstance(n.value, str)}
    assert "ui/mail_tab_system_active" in names, (
        "nothing checks whether the system tab is already open, so the glance "
        "gives up exactly when the picture was free to take")
    assert "MAIL_SYSTEM_TAB" in names, "it no longer saves the frame"
