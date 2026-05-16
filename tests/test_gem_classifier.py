"""Tests for GemPatchClassifier (Phase 8)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision.gem_classifier import (
    GemPatchClassifier,
    _extract_features,
    MIN_SAMPLES,
    PATCH_SIZE,
)


def _make_patch(color_bgr, noise=15):
    """Create a 48x48 BGR patch with given base color + noise."""
    patch = np.full((PATCH_SIZE, PATCH_SIZE, 3), color_bgr, dtype=np.uint8)
    noise_arr = np.random.randint(0, noise, patch.shape, dtype=np.uint8)
    return cv2.add(patch, noise_arr)


def _green_patch():
    return _make_patch([0, 180, 0])


def _brown_patch():
    return _make_patch([30, 80, 120])


def _random_patch():
    return np.random.randint(0, 256, (PATCH_SIZE, PATCH_SIZE, 3), dtype=np.uint8)


class TestFeatureExtraction(unittest.TestCase):
    def test_output_shape(self):
        patch = _green_patch()
        feat = _extract_features(patch)
        self.assertEqual(feat.ndim, 1)
        self.assertGreater(len(feat), 0)
        self.assertEqual(feat.dtype, np.float32)

    def test_different_patches_different_features(self):
        f1 = _extract_features(_green_patch())
        f2 = _extract_features(_brown_patch())
        self.assertFalse(np.allclose(f1, f2))

    def test_resize_non_square_input(self):
        patch = np.zeros((30, 60, 3), dtype=np.uint8)
        feat = _extract_features(patch)
        self.assertGreater(len(feat), 0)

    def test_deterministic(self):
        patch = _green_patch()
        f1 = _extract_features(patch)
        f2 = _extract_features(patch)
        np.testing.assert_array_equal(f1, f2)


class TestColdStart(unittest.TestCase):
    def test_predict_cold(self):
        clf = GemPatchClassifier()
        patch = _green_patch()
        label, conf = clf.predict(patch)
        self.assertEqual(label, "unknown")
        self.assertEqual(conf, 0.0)

    def test_should_click_cold(self):
        clf = GemPatchClassifier()
        should, label, conf = clf.should_click(_green_patch())
        self.assertTrue(should)
        self.assertEqual(label, "unknown")

    def test_is_warm_false(self):
        clf = GemPatchClassifier()
        self.assertFalse(clf.is_warm)
        for i in range(MIN_SAMPLES - 1):
            clf.add_sample(_green_patch(), True, save_patch=False)
        self.assertFalse(clf.is_warm)

    def test_is_warm_true(self):
        clf = GemPatchClassifier()
        for i in range(MIN_SAMPLES):
            clf.add_sample(_green_patch(), True, save_patch=False)
        self.assertTrue(clf.is_warm)


class TestPrediction(unittest.TestCase):
    def setUp(self):
        self.clf = GemPatchClassifier()
        for _ in range(7):
            self.clf.add_sample(_green_patch(), True, save_patch=False)
        for _ in range(5):
            self.clf.add_sample(_brown_patch(), False, save_patch=False)

    def test_predict_gem(self):
        label, conf = self.clf.predict(_green_patch())
        self.assertEqual(label, "gem")
        self.assertGreater(conf, 0.5)

    def test_predict_not_gem(self):
        label, conf = self.clf.predict(_brown_patch())
        self.assertEqual(label, "not_gem")
        self.assertGreater(conf, 0.5)

    def test_should_click_gem(self):
        should, label, conf = self.clf.should_click(_green_patch())
        self.assertTrue(should)
        self.assertEqual(label, "gem")

    def test_should_click_not_gem(self):
        should, label, conf = self.clf.should_click(_brown_patch())
        self.assertFalse(should)
        self.assertEqual(label, "not_gem")


class TestAddSample(unittest.TestCase):
    def test_incremental_count(self):
        clf = GemPatchClassifier()
        self.assertEqual(clf.sample_count, 0)
        clf.add_sample(_green_patch(), True, save_patch=False)
        self.assertEqual(clf.sample_count, 1)
        clf.add_sample(_brown_patch(), False, save_patch=False)
        self.assertEqual(clf.sample_count, 2)

    def test_labels_correct(self):
        clf = GemPatchClassifier()
        clf.add_sample(_green_patch(), True, save_patch=False)
        clf.add_sample(_brown_patch(), False, save_patch=False)
        self.assertEqual(clf._labels, [1, 0])


class TestSaveLoad(unittest.TestCase):
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "model.npz")
            clf = GemPatchClassifier(model_path=model_path)
            for _ in range(7):
                clf.add_sample(_green_patch(), True, save_patch=False)
            for _ in range(5):
                clf.add_sample(_brown_patch(), False, save_patch=False)
            clf.save()

            self.assertTrue(os.path.exists(model_path))

            clf2 = GemPatchClassifier(model_path=model_path)
            loaded = clf2.load()
            self.assertTrue(loaded)
            self.assertEqual(clf2.sample_count, 12)
            self.assertTrue(clf2.is_warm)

            label, conf = clf2.predict(_green_patch())
            self.assertEqual(label, "gem")

    def test_load_nonexistent(self):
        clf = GemPatchClassifier(model_path="/nonexistent/path.npz")
        loaded = clf.load()
        self.assertFalse(loaded)
        self.assertEqual(clf.sample_count, 0)

    def test_save_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "model.npz")
            clf = GemPatchClassifier(model_path=model_path)
            clf.save()
            self.assertFalse(os.path.exists(model_path))


class TestPatchSaving(unittest.TestCase):
    def test_save_patch_images(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            patches_dir = os.path.join(tmpdir, "patches")
            clf = GemPatchClassifier(patches_dir=patches_dir)
            clf.add_sample(_green_patch(), True, save_patch=True)
            clf.add_sample(_brown_patch(), False, save_patch=True)

            gem_dir = os.path.join(patches_dir, "gem")
            not_gem_dir = os.path.join(patches_dir, "not_gem")
            self.assertTrue(os.path.isdir(gem_dir))
            self.assertTrue(os.path.isdir(not_gem_dir))
            self.assertEqual(len(os.listdir(gem_dir)), 1)
            self.assertEqual(len(os.listdir(not_gem_dir)), 1)


class TestIncrementalLearning(unittest.TestCase):
    def test_accuracy_improves(self):
        clf = GemPatchClassifier()

        for _ in range(5):
            clf.add_sample(_green_patch(), True, save_patch=False)
        for _ in range(5):
            clf.add_sample(_brown_patch(), False, save_patch=False)

        label1, conf1 = clf.predict(_green_patch())

        for _ in range(10):
            clf.add_sample(_green_patch(), True, save_patch=False)
        for _ in range(10):
            clf.add_sample(_brown_patch(), False, save_patch=False)

        label2, conf2 = clf.predict(_green_patch())
        self.assertEqual(label2, "gem")
        self.assertGreaterEqual(conf2, conf1)


class TestGetStats(unittest.TestCase):
    def test_stats_structure(self):
        clf = GemPatchClassifier()
        clf.add_sample(_green_patch(), True, save_patch=False)
        clf.add_sample(_brown_patch(), False, save_patch=False)
        stats = clf.get_stats()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["gem"], 1)
        self.assertEqual(stats["not_gem"], 1)
        self.assertFalse(stats["is_warm"])
        self.assertIn("model_path", stats)


class TestAutoSave(unittest.TestCase):
    def test_auto_save_after_10_samples(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, "model.npz")
            clf = GemPatchClassifier(model_path=model_path)
            for i in range(9):
                clf.add_sample(_green_patch(), True, save_patch=False)
            self.assertFalse(os.path.exists(model_path))
            clf.add_sample(_green_patch(), True, save_patch=False)
            self.assertTrue(os.path.exists(model_path))


if __name__ == "__main__":
    unittest.main()
