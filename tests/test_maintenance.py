"""The server-maintenance notice, and not farming into it.

2026-09-22: the game went into maintenance around 13:13 and the farm did not
notice for over an hour. It panned and scanned a notice board looking for gem
deposits -- three mines logged NO_CANDIDATES -- and every frame saved from
14:20 onward shows that notice with its countdown ticking down behind the
farm's own drag marks.

The operator named the risk plainly: swiping around while that screen is up is
a good way to collect a warning letter. The notice answers the question
itself, so the fix is to read it.
"""

import ast
import inspect
import re

import cv2
import pytest

from rok_farm import PROJECT_ROOT, maintenance as mt

KEEP = PROJECT_ROOT / "screenshots" / "keep" / "maintenance"

# What RapidOCR returns for the real screen, verbatim from the kept frame.
REAL = [
    "on cac ngai da thong cam!",
    "Trong khi tam ngung may chu, nhan vao nut goc phai ben duoi de",
    "May chu dang bao tri. Thoi gian con lai: 00:38:27",
    "LAMMO'",
    "FACEBOOK",
]


def test_the_notice_is_recognised():
    assert mt.is_maintenance(REAL)


def test_the_clock_is_read_to_the_second():
    """00:38:27 is 2307 seconds, and that is what the kept frame gives."""
    assert mt.seconds_left(REAL) == 2307.0


def test_one_mark_alone_is_not_enough():
    """The word for maintenance turns up in ordinary announcement mail."""
    assert not mt.is_maintenance(["May chu dang bao tri se dien ra ngay mai"])
    assert not mt.is_maintenance(["Thoi gian con lai: 00:10:00"])


def test_a_clock_without_the_notice_is_ignored():
    """Timers are everywhere in this game -- gathers, training, marches."""
    assert mt.seconds_left(["Hiep si x 1.600", "02:41:57"]) is not None
    assert not mt.is_maintenance(["Hiep si x 1.600", "02:41:57"])


def test_a_silly_clock_is_refused():
    assert mt.seconds_left(["may chu dang bao tri thoi gian con lai: 99:00:00"]) is None
    assert mt.seconds_left(["may chu dang bao tri thoi gian con lai: 00:00:00"]) is None


def test_diacritics_do_not_matter():
    """The OCR mangles them, and the real screen is Vietnamese."""
    with_marks = ["Máy chủ đang bảo trì. Thời gian còn lại: 00:05:00"]
    assert mt.is_maintenance(with_marks)
    assert mt.seconds_left(with_marks) == 300.0


def test_the_band_covers_where_the_line_actually_is():
    """Measured by running OCR over the whole frame rather than reading
    coordinates off a picture: x 0.385-0.616, y 0.592-0.615."""
    y1, y2, x1, x2 = mt.BAND
    assert y1 <= 0.592 and y2 >= 0.615, mt.BAND
    assert x1 <= 0.385 and x2 >= 0.616, mt.BAND


def test_the_kept_frame_still_reads():
    """Skipped rather than failed -- screenshots/ is not in the repo."""
    path = KEEP / "MAINTENANCE_142116.png"
    if not path.is_file():
        pytest.skip("the maintenance frame is not kept any more")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip("the maintenance frame did not decode")
    try:
        from rok_farm.queue_ocr import ocr_texts
    except Exception:
        pytest.skip("no OCR backend here")
    lines = mt.read_lines(frame, ocr_texts)
    if not lines:
        pytest.skip("no OCR backend here")
    assert mt.is_maintenance(lines), lines
    assert mt.seconds_left(lines) == 2307.0, lines


def test_the_farm_checks_before_it_touches_anything():
    """The hold has to come before the queue read and the mine, or the first
    thing that happens on a maintenance screen is still a drag."""
    from rok_farm import runner

    src = inspect.getsource(runner.GemFarmRunner.run) if hasattr(
        runner, "GemFarmRunner") else inspect.getsource(runner)
    hold = src.find("_maintenance_hold")
    queue = src.find("_detect_march_queue")
    assert hold != -1, "the runner no longer checks for maintenance"
    assert queue != -1
    assert hold < queue, "maintenance is checked after the queue is read"


def test_the_wait_is_never_exactly_the_countdown():
    """The operator's warning: the game extends it. Coming back on the second
    means walking straight back in."""
    lo, hi = mt.GRACE_S
    assert lo >= 120.0, mt.GRACE_S
    assert hi > lo, mt.GRACE_S
    assert mt.BLIND_WAIT_S >= 300.0
