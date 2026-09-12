"""Never press a button because it is the right SHAPE.

On 2026-09-11 mine 6 matched buttons/gather_btn at 0.793 on the popup for an
empty tile and pressed it. That popup carries "Dich Chuyen" and "Hanh quan" in
exactly the chrome of "Thu thap", so the match was on the button's frame, not
its meaning. 178.000 troops -- a combat army, not a gathering party -- marched
to bare ground at 202:184, where such a march sits until it is recalled by
hand, holding a march slot the whole time.

Confidence cannot separate them: the WRONG button scored 0.793 and real gathers
score 0.778-0.787, so the bad match was the most confident of the set. Position
cannot either; the buttons occupy the same place. Only the words differ.
"""

import pytest

from rok_farm.queue_ocr import button_verdict


def test_the_real_gather_button_is_accepted():
    assert button_verdict(["THU THAP"]) == "gather"


def test_an_ocr_slip_on_the_gather_button_is_still_accepted():
    """Observed live: the P dropped out of THAP."""
    assert button_verdict(["THU HAP"]) == "gather"


def test_the_teleport_button_is_refused():
    """What mine 6 actually matched, read back off the saved frame."""
    assert button_verdict(["Dich Chuyen"]) == "other"


def test_the_march_button_is_refused():
    """The other half of the empty-tile popup, and the costlier one."""
    assert button_verdict(["Hanh quan"]) == "other"
    assert button_verdict(["HANH QUAN"]) == "other"


def test_an_unreadable_button_is_not_refused():
    """Silence must not become a second gate on the happy path.

    This guard exists to stop one catastrophe. If it also refused whenever OCR
    hiccuped, it would trade a rare disaster for a steady drip of lost mines.
    """
    assert button_verdict([]) == "unreadable"
    assert button_verdict([""]) == "unreadable"
    assert button_verdict(["!!!"]) == "unreadable"


def test_diacritics_and_case_do_not_matter():
    for text in ("Thu Thập", "thu thap", "THU  THẬP"):
        assert button_verdict([text]) == "gather", text


def test_the_verdict_holds_on_the_real_frames():
    """End to end on the saved screenshots, template match included."""
    cv2 = pytest.importorskip("cv2")
    from pathlib import Path

    from rok_farm.config import TEMPLATE_DIR
    from rok_farm.queue_ocr import read_button_text
    from vision.template_cache import TemplateCache
    from vision.template_matcher import TemplateMatcher

    shots = Path(__file__).resolve().parents[1] / "screenshots" / "gem_farm_test"
    cases = [("m6_gather_found_040126.png", "other"),
             ("m10_gather_found_040710.png", "gather"),
             ("m11_gather_found_042014.png", "gather")]
    available = [(n, want) for n, want in cases if (shots / n).is_file()]
    if not available:
        pytest.skip("the frames from that night are not on this machine")

    matcher = TemplateMatcher(TemplateCache(TEMPLATE_DIR), threshold=0.50)
    for name, want in available:
        img = cv2.imread(str(shots / name))
        m = matcher.match_single(img, "buttons/gather_btn")
        assert m is not None, f"{name}: no template match"
        got = button_verdict(read_button_text(img, m.x, m.y, m.w, m.h))
        assert got == want, (
            f"{name}: matched at {m.confidence:.3f} and read as {got!r}, "
            f"expected {want!r}")


def test_the_button_text_is_logged_every_time():
    """An unreadable button is allowed through, so it must still be recorded.

    Two deploy-panel timeouts on 2026-09-11 clicked 271px right and 255px left
    of the same mine -- symmetric, the shape of a popup with a button on each
    side -- so one was very likely the wrong button. The guard reported
    nothing, because "unreadable" passes by design. Without the words in the
    log there is no way to tell an unreadable Gather from an unreadable
    something-else, and no way to know whether the guard was even consulted.
    """
    from rok_farm import PROJECT_ROOT

    src = (PROJECT_ROOT / "rok_farm" / "flow_steps.py").read_text(
        encoding="utf-8")
    start = src.index("verdict = button_verdict")
    block = src[start - 400:src.index("if verdict ==", start) + 60]
    assert "logger.debug" in block or "logger.info" in block, (
        "the button text is only recorded on a refusal, so the case that "
        "actually fails leaves no evidence")
    assert "words" in block, "the raw words are not what gets logged"


# --- the recall button, seen live 2026-09-13 06:47 ------------------------

def test_the_recall_button_is_refused():
    """['Sotuolg', 'dRI', '0/30', 'TRIEU HOI'] -- verbatim from the log.

    The bot had clicked a node its own troops were already gathering on, and
    the panel offers to call them HOME, throwing away the gather in progress.
    The verdict was "unreadable", which this guard lets through; only the
    coordinate-based duplicate check stopped the click that time.
    """
    assert button_verdict(["Sotuolg", "dRI", "0/30", "TRIEU HOI"]) == "other"


def test_a_real_gather_still_wins_whatever_else_is_in_the_crop():
    """The crop is loose -- it picked up a troop count and two junk words.

    So the gather words must be matched first, or every word added to the
    refusal list becomes a new way to lose a real mine.
    """
    assert button_verdict(["THU THAP", "TRIEU HOI"]) == "gather"
    assert button_verdict(["0/30", "THU THAP", "Sotuolg"]) == "gather"


def test_half_read_letters_are_still_allowed_through():
    """Measured, not assumed. Over all 66 readings in the log, five matched no
    word: 'HA' three times, 'ar' once, and TRIEU HOI once. Every one of the
    four garbled ones went on to open the deploy panel and send a real march,
    so they were genuine gather buttons OCR only half read. Calling them
    "other" would have cost 4 mines in 66.
    """
    for junk in ("HA", "ar", "h", "T"):
        assert button_verdict([junk]) == "unreadable", (
            f"{junk!r} now refuses the click; four readings exactly like it "
            f"were real gather buttons that marched successfully")
