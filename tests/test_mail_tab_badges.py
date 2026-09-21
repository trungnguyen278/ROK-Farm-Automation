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
