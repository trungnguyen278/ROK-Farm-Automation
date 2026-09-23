"""The matcher runs its scales side by side and must answer exactly as before.

Measured 2026-09-23 on the day's saved frames: the icon scan's seven scales
took 669ms one after another and 160ms on a pool; one zoom-in poll went from
1063ms to 364ms. Speed is only worth having if the answers are the same, so
this compares against the old sequential loop, result for result.
"""

import glob
import os

import cv2
import numpy as np
import pytest

from vision import template_matcher as tm
from vision.template_matcher import Match, TemplateMatcher


class _Cache:
    def __init__(self, **tpls):
        self._t = tpls

    def get(self, name):
        return self._t.get(name)


def _sequential_single(frame, template, name, scales, threshold):
    """The loop as it was before the pool, verbatim in effect."""
    best_val, best_loc, best_size = 0.0, None, None
    for scale in scales:
        resized = cv2.resize(template, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_AREA)
        rh, rw = resized.shape[:2]
        fh, fw = frame.shape[:2]
        if rw > fw or rh > fh:
            continue
        result = cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_val:
            best_val, best_loc, best_size = max_val, max_loc, (rw, rh)
    if best_val < threshold or best_loc is None:
        return None
    x, y = best_loc
    w, h = best_size
    return Match(name, x, y, w, h, best_val, (x + w // 2, y + h // 2))


def _sequential_all(frame, template, name, scales, threshold, overlap):
    matches = []
    for scale in scales:
        resized = cv2.resize(template, None, fx=scale, fy=scale,
                             interpolation=cv2.INTER_AREA)
        rh, rw = resized.shape[:2]
        fh, fw = frame.shape[:2]
        if rw > fw or rh > fh:
            continue
        result = cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED)
        locs = np.where(result >= threshold)
        for pt in zip(*locs[::-1]):
            x, y = int(pt[0]), int(pt[1])
            matches.append(Match(name, x, y, rw, rh, float(result[y, x]),
                                 (x + rw // 2, y + rh // 2)))
    return TemplateMatcher._nms(matches, overlap)


def _synthetic(seed):
    rng = np.random.default_rng(seed)
    frame = rng.integers(0, 255, (300, 500, 3), dtype=np.uint8)
    frame = cv2.GaussianBlur(frame, (5, 5), 0)
    tpl = frame[120:168, 200:236].copy()          # a 36x48 patch, icon-sized
    return frame, tpl


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_single_matches_the_sequential_loop(seed):
    frame, tpl = _synthetic(seed)
    m = TemplateMatcher(_Cache(t=tpl), threshold=0.5)
    got = m.match_single(frame, "t")
    want = _sequential_single(frame, tpl, "t", tm.DEFAULT_SCALES, 0.5)
    assert got == want


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_all_matches_the_sequential_loop(seed):
    frame, tpl = _synthetic(seed)
    m = TemplateMatcher(_Cache(t=tpl), threshold=0.5)
    got = m.match_all(frame, "t", overlap_thresh=0.3)
    want = _sequential_all(frame, tpl, "t", tm.DEFAULT_SCALES, 0.5, 0.3)
    assert got == want


def test_a_template_bigger_than_the_frame_is_skipped_not_fatal():
    frame = np.zeros((40, 40, 3), np.uint8)
    # Too big at every scale: the smallest, 0.7, is still 70px.
    tpl = np.full((100, 100, 3), 200, np.uint8)
    m = TemplateMatcher(_Cache(t=tpl), threshold=0.5)
    assert m.match_single(frame, "t") is None
    assert m.match_all(frame, "t") == []


def test_real_scan_frames_answer_the_same():
    """On the frames the farm actually scans, when any are kept."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    frames = sorted(glob.glob(os.path.join(root, "screenshots", "gem_farm_test",
                                           "m*_scan_*.png")))[-3:]
    tpl_path = os.path.join(root, "templates", "resources", "gem_icon.png")
    if not frames or not os.path.exists(tpl_path):
        pytest.skip("no saved scan frames on this machine")
    tpl = cv2.imread(tpl_path)
    m = TemplateMatcher(_Cache(t=tpl), threshold=0.5)
    for f in frames:
        fr = cv2.imread(f)
        assert m.match_all(fr, "t", 0.3) == _sequential_all(
            fr, tpl, "t", tm.DEFAULT_SCALES, 0.5, 0.3), f


def test_the_pool_is_used_concurrently():
    """Many callers at once, the way the capture and flow threads can."""
    from concurrent.futures import ThreadPoolExecutor
    frame, tpl = _synthetic(5)
    m = TemplateMatcher(_Cache(t=tpl), threshold=0.5)
    want = m.match_single(frame, "t")
    with ThreadPoolExecutor(max_workers=4) as ex:
        got = list(ex.map(lambda _: m.match_single(frame, "t"), range(8)))
    assert all(g == want for g in got)
