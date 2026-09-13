"""Does "Doc va nhan tat" empty a mail tab? The tab badges carry the answer.

Live 2026-09-14 the mail button read 47 before the farm read two tabs and 46
right after, and all night it sat between 36 and 48 through four reads. Either
the count lags behind, or reading leaves most of the mail where it was. The
button's number cannot tell those apart; each tab's number, before and after
the read, can.
"""

import ast
import logging

import cv2
import pytest

import anti_detection.player_actions as pa
from rok_farm import PROJECT_ROOT

REFS = PROJECT_ROOT / "screenshots" / "keep" / "feature_refs"
SRC = PROJECT_ROOT / "anti_detection" / "player_actions.py"


def load(name):
    path = REFS / name
    if not path.is_file():
        pytest.skip(f"{name} is not kept any more")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip(f"{name} did not decode")
    return frame


def needs_ocr():
    from rok_farm import queue_ocr
    if queue_ocr._ocr_engine is None:
        pytest.skip("no OCR engine installed")


def test_tab_badges_read_as_the_numbers_on_them():
    """MAIL_NO_TAB_BADGES_180640 shows BAO CAO with 40 and LIEN MINH with 6,
    at the x positions _find_mail_tab_badges measured on that frame."""
    needs_ocr()
    frame = load("MAIL_NO_TAB_BADGES_180640.png")
    assert pa.tab_badge_count(frame, 0.326) == 40
    assert pa.tab_badge_count(frame, 0.412) == 6


def test_a_tab_without_a_badge_reads_nothing():
    """HE THONG, next along from LIEN MINH, has no badge on that frame."""
    needs_ocr()
    frame = load("MAIL_NO_TAB_BADGES_180640.png")
    assert pa.tab_badge_count(frame, 0.488) is None


@pytest.mark.parametrize("badges_now,reading,expected", [
    ([], None, "40 -> gone"),
    ([(0.326, 0.015)], 39, "40 -> 39"),
    ([(0.326, 0.015)], None, "40 -> unreadable"),
    ([(0.412, 0.015)], 6, "40 -> gone"),      # only the neighbouring tab has one
])
def test_each_read_all_logs_the_tab_before_and_after(monkeypatch, caplog,
                                                     badges_now, reading, expected):
    monkeypatch.setattr(pa, "_find_mail_tab_badges", lambda frame: badges_now)
    monkeypatch.setattr(pa, "tab_badge_count", lambda frame, x: reading)
    with caplog.at_level(logging.INFO, logger=pa.logger.name):
        pa._log_tab_after_read("frame", 0.326, 40)
    assert f"badge {expected} after read-all" in caplog.text, caplog.text


def act_mail_code():
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "act_mail")
    return ast.unparse(fn)


def test_every_read_all_click_is_measured():
    code = act_mail_code()
    assert code.count("_click_pct(rx, ry") == code.count("_log_tab_after_read(") == 1, \
        "a read-all click without a before/after reading of its tab"
    assert "tab_badge_count(last, bx)" in code


def test_the_panel_after_reading_is_kept():
    from rok_farm.runner import GemFarmRunner
    assert "MAIL_AFTER_READ" in act_mail_code()
    assert "MAIL_AFTER_READ" in GemFarmRunner.KEEP_FOREVER
