from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class TemplateCache:
    def __init__(self, template_dir: str = "templates", max_size: int = 100):
        self._dir = Path(template_dir)
        self._max_size = max_size
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()

    def get(self, name: str) -> np.ndarray | None:
        if name in self._cache:
            self._cache.move_to_end(name)
            return self._cache[name]
        return self._load(name)

    def preload(self, names: list[str]):
        for name in names:
            self.get(name)

    def clear(self):
        self._cache.clear()
        logger.debug("Template cache cleared")

    @property
    def size(self) -> int:
        return len(self._cache)

    def _load(self, name: str) -> np.ndarray | None:
        path = self._dir / f"{name}.png"
        if not path.exists():
            logger.warning("Template not found: %s", path)
            return None

        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            logger.error("Failed to read template: %s", path)
            return None

        if len(self._cache) >= self._max_size:
            evicted = self._cache.popitem(last=False)
            logger.debug("Evicted template: %s", evicted[0])

        self._cache[name] = img
        logger.debug("Loaded template: %s (%dx%d)", name, img.shape[1], img.shape[0])
        return img
