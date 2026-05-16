from __future__ import annotations

import logging
import os
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

PATCH_SIZE = 48
HSV_BINS = (8, 8, 4)
HOG_CELL = (8, 8)
HOG_BLOCK = (2, 2)
HOG_NBINS = 9

MIN_SAMPLES = 10
DEFAULT_K = 5
DEFAULT_CONFIDENCE_THRESHOLD = 0.6

DEFAULT_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"
)
DEFAULT_MODEL_PATH = os.path.join(DEFAULT_DATA_DIR, "gem_classifier.npz")
DEFAULT_PATCHES_DIR = os.path.join(DEFAULT_DATA_DIR, "gem_patches")


def _extract_features(patch: np.ndarray) -> np.ndarray:
    """Extract color histogram + HOG from a 48x48 BGR patch."""
    resized = cv2.resize(patch, (PATCH_SIZE, PATCH_SIZE), interpolation=cv2.INTER_AREA)

    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist(
        [hsv], [0, 1, 2], None, list(HSV_BINS),
        [0, 180, 0, 256, 0, 256],
    )
    hist = cv2.normalize(hist, hist).flatten()

    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    hog = cv2.HOGDescriptor(
        _winSize=(PATCH_SIZE, PATCH_SIZE),
        _blockSize=(HOG_BLOCK[0] * HOG_CELL[0], HOG_BLOCK[1] * HOG_CELL[1]),
        _blockStride=(HOG_CELL[0], HOG_CELL[1]),
        _cellSize=HOG_CELL,
        _nbins=HOG_NBINS,
    )
    hog_feat = hog.compute(gray).flatten()

    return np.concatenate([hist, hog_feat]).astype(np.float32)


class GemPatchClassifier:
    """k-NN classifier that learns gem vs non-gem icon patches from zoom-in verification.

    Cold start: when fewer than MIN_SAMPLES samples exist, predict() returns
    confidence=0 so callers can bypass filtering (click all candidates).
    """

    def __init__(
        self,
        model_path: str = DEFAULT_MODEL_PATH,
        patches_dir: str = DEFAULT_PATCHES_DIR,
        k: int = DEFAULT_K,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    ):
        self._model_path = model_path
        self._patches_dir = patches_dir
        self._k = k
        self.confidence_threshold = confidence_threshold

        self._features: list[np.ndarray] = []
        self._labels: list[int] = []  # 1=gem, 0=not_gem
        self._samples_since_save = 0

    @property
    def sample_count(self) -> int:
        return len(self._labels)

    @property
    def is_warm(self) -> bool:
        return self.sample_count >= MIN_SAMPLES

    def load(self, path: str | None = None) -> bool:
        """Load persisted training data. Returns True if loaded successfully."""
        p = path or self._model_path
        if not os.path.exists(p):
            logger.info("No classifier data at %s, starting cold", p)
            return False
        try:
            data = np.load(p)
            features = data["features"]
            labels = data["labels"]
            self._features = [features[i] for i in range(len(labels))]
            self._labels = labels.tolist()
            gem_count = sum(1 for lb in self._labels if lb == 1)
            logger.info(
                "Loaded classifier: %d samples (%d gem, %d not_gem)",
                self.sample_count, gem_count, self.sample_count - gem_count,
            )
            return True
        except Exception:
            logger.warning("Failed to load classifier from %s", p, exc_info=True)
            return False

    def save(self, path: str | None = None) -> None:
        """Persist training data to disk."""
        p = path or self._model_path
        if not self._features:
            return
        os.makedirs(os.path.dirname(p), exist_ok=True)
        features = np.array(self._features, dtype=np.float32)
        labels = np.array(self._labels, dtype=np.int32)
        np.savez(p, features=features, labels=labels)
        self._samples_since_save = 0
        logger.info("Saved classifier: %d samples to %s", self.sample_count, p)

    def add_sample(self, patch: np.ndarray, is_gem: bool, save_patch: bool = True) -> int:
        """Add a labeled patch to training data. Returns new sample count."""
        feat = _extract_features(patch)
        self._features.append(feat)
        self._labels.append(1 if is_gem else 0)
        self._samples_since_save += 1

        if save_patch:
            self._save_patch_image(patch, is_gem)

        if self._samples_since_save >= 10:
            self.save()

        return self.sample_count

    def predict(self, patch: np.ndarray) -> tuple[str, float]:
        """Predict whether patch is gem or not_gem.

        Returns (label, confidence) where label is "gem" or "not_gem".
        When cold (< MIN_SAMPLES), returns ("unknown", 0.0) to signal bypass.
        """
        if not self.is_warm:
            return ("unknown", 0.0)

        feat = _extract_features(patch)
        features = np.array(self._features, dtype=np.float32)
        labels = np.array(self._labels, dtype=np.int32)

        dists = np.linalg.norm(features - feat, axis=1)
        k = min(self._k, len(dists))
        indices = np.argpartition(dists, k)[:k]

        k_dists = dists[indices]
        k_labels = labels[indices]

        weights = 1.0 / (k_dists + 1e-6)

        gem_weight = float(weights[k_labels == 1].sum())
        total_weight = float(weights.sum())
        gem_score = gem_weight / total_weight if total_weight > 0 else 0.0

        label = "gem" if gem_score > 0.5 else "not_gem"
        confidence = gem_score if label == "gem" else 1.0 - gem_score

        return (label, confidence)

    def should_click(self, patch: np.ndarray) -> tuple[bool, str, float]:
        """Decide if an icon candidate should be clicked.

        Returns (should_click, label, confidence).
        Cold start -> always click. Warm -> click only if gem with enough confidence.
        """
        label, conf = self.predict(patch)
        if label == "unknown":
            return (True, label, conf)
        if label == "gem" and conf >= self.confidence_threshold:
            return (True, label, conf)
        if label == "not_gem" and conf >= self.confidence_threshold:
            return (False, label, conf)
        return (True, label, conf)

    def _save_patch_image(self, patch: np.ndarray, is_gem: bool) -> None:
        subdir = "gem" if is_gem else "not_gem"
        out_dir = os.path.join(self._patches_dir, subdir)
        os.makedirs(out_dir, exist_ok=True)
        idx = self.sample_count
        fname = os.path.join(out_dir, f"{idx:04d}.png")
        try:
            cv2.imwrite(fname, patch)
        except Exception:
            logger.debug("Failed to save patch image %s", fname)

    def get_stats(self) -> dict:
        """Return classifier statistics."""
        gem_count = sum(1 for lb in self._labels if lb == 1)
        not_gem_count = self.sample_count - gem_count
        return {
            "total": self.sample_count,
            "gem": gem_count,
            "not_gem": not_gem_count,
            "is_warm": self.is_warm,
            "model_path": self._model_path,
        }
