"""Evidence frames must survive the restart that loads their fix.

The runner deleted every screenshot at startup. That is the worst possible
moment: a restart is usually how a fix reaches the bot after a failure, so the
wipe destroyed the evidence of the run being investigated. Asked for the frames
behind two bad marches, there were none -- the farm had been restarted eight
times that day and each restart threw them away.

Shutdown already pruned by age, so bounded disk use never depended on the wipe.
"""

import re

import pytest

from rok_farm import PROJECT_ROOT

SRC = PROJECT_ROOT / "rok_farm" / "runner.py"


@pytest.fixture(scope="module")
def source():
    return SRC.read_text(encoding="utf-8")


def test_startup_does_not_wipe_everything(source):
    start = source.index("def run(self):")
    block = source[start:start + 1400]
    assert "SCREENSHOT_DIR.glob" in block, "the sweep is gone entirely"
    assert "st_mtime" in block, (
        "startup deletes screenshots without checking their age, so a restart "
        "destroys the evidence of the run that just failed")


def test_fault_frames_are_never_swept(source):
    from rok_farm.runner import GemFarmRunner

    for tag in ("WRONG_BUTTON", "WRONG_PLACE", "TIMEOUT", "MAPID",
                "FOG", "ZOOM_STUCK", "WRONG_NODE"):
        assert tag in GemFarmRunner.KEEP_FOREVER, (
            f"{tag} frames are saved precisely because something went wrong, "
            f"and would be swept away before anyone could look")

    for m in re.finditer(r"SCREENSHOT_DIR\.glob", source):
        window = source[max(0, m.start() - 500):m.start() + 500]
        assert "KEEP_FOREVER" in window, (
            "one of the sweeps still deletes fault frames")


def test_the_window_outlasts_a_night(source):
    """A fault found in the morning must still have its frame.

    The shutdown sweep kept one hour, shorter than the gap between a failure at
    3am and someone reading the log at 8.
    """
    from rok_farm.runner import GemFarmRunner
    assert GemFarmRunner.KEEP_HOURS >= 3, (
        f"{GemFarmRunner.KEEP_HOURS}h is too short to survive the gap between "
        f"a fault and someone looking at it")
