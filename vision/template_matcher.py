from __future__ import annotations

import logging
from collections import namedtuple

import cv2
import numpy as np

from .template_cache import TemplateCache

logger = logging.getLogger(__name__)

Match = namedtuple("Match", ["name", "x", "y", "w", "h", "confidence", "center"])

DEFAULT_SCALES = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]


class TemplateMatcher:
    def __init__(
        self,
        cache: TemplateCache,
        threshold: float = 0.8,
        scales: list[float] | None = None,
    ):
        self._cache = cache
        self._threshold = threshold
        self._scales = scales or DEFAULT_SCALES

    def match_single(self, frame: np.ndarray, template_name: str) -> Match | None:
        template = self._cache.get(template_name)
        if template is None:
            return None

        best_val = 0.0
        best_loc = None
        best_size = None

        for scale in self._scales:
            resized = cv2.resize(
                template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )
            rh, rw = resized.shape[:2]
            fh, fw = frame.shape[:2]
            if rw > fw or rh > fh:
                continue

            result = cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(result)

            if max_val > best_val:
                best_val = max_val
                best_loc = max_loc
                best_size = (rw, rh)

        if best_val < self._threshold or best_loc is None or best_size is None:
            return None

        x, y = best_loc
        w, h = best_size
        return Match(
            name=template_name,
            x=x, y=y, w=w, h=h,
            confidence=best_val,
            center=(x + w // 2, y + h // 2),
        )

    def match_all(
        self, frame: np.ndarray, template_name: str, overlap_thresh: float = 0.3
    ) -> list[Match]:
        template = self._cache.get(template_name)
        if template is None:
            return []

        matches: list[Match] = []

        for scale in self._scales:
            resized = cv2.resize(
                template, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
            )
            rh, rw = resized.shape[:2]
            fh, fw = frame.shape[:2]
            if rw > fw or rh > fh:
                continue

            result = cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED)
            locs = np.where(result >= self._threshold)

            for pt in zip(*locs[::-1]):
                x, y = int(pt[0]), int(pt[1])
                conf = float(result[y, x])
                matches.append(Match(
                    name=template_name,
                    x=x, y=y, w=rw, h=rh,
                    confidence=conf,
                    center=(x + rw // 2, y + rh // 2),
                ))

        return self._nms(matches, overlap_thresh)

    def match_best(
        self, frame: np.ndarray, template_names: list[str]
    ) -> Match | None:
        best: Match | None = None
        for name in template_names:
            m = self.match_single(frame, name)
            if m and (best is None or m.confidence > best.confidence):
                best = m
        return best

    @staticmethod
    def _nms(matches: list[Match], overlap_thresh: float) -> list[Match]:
        if not matches:
            return []

        boxes = np.array([[m.x, m.y, m.x + m.w, m.y + m.h] for m in matches])
        scores = np.array([m.confidence for m in matches])
        order = scores.argsort()[::-1]

        keep: list[int] = []
        while order.size > 0:
            i = order[0]
            keep.append(i)

            xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
            yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
            xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
            yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])

            inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
            area_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
            area_j = (boxes[order[1:], 2] - boxes[order[1:], 0]) * (
                boxes[order[1:], 3] - boxes[order[1:], 1]
            )
            iou = inter / (area_i + area_j - inter + 1e-6)

            inds = np.where(iou <= overlap_thresh)[0]
            order = order[inds + 1]

        return [matches[i] for i in keep]
