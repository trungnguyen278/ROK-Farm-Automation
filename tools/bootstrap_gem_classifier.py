r"""
Bootstrap gem classifier from saved patch images.

Reads labeled patches from data/gem_patches/{gem,not_gem}/ (saved during
previous test_gem_farm_flow or action_executor runs), trains the classifier
offline, and exports accuracy report.

Run: .venv\Scripts\python -m tools.bootstrap_gem_classifier
"""

import os
import sys
import glob

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision.gem_classifier import GemPatchClassifier, DEFAULT_PATCHES_DIR, DEFAULT_MODEL_PATH


def load_patches(patches_dir: str) -> tuple[list[np.ndarray], list[int]]:
    patches = []
    labels = []
    for label_name, label_val in [("gem", 1), ("not_gem", 0)]:
        label_dir = os.path.join(patches_dir, label_name)
        if not os.path.isdir(label_dir):
            print(f"  Directory not found: {label_dir}")
            continue
        files = sorted(glob.glob(os.path.join(label_dir, "*.png")))
        for f in files:
            img = cv2.imread(f)
            if img is not None:
                patches.append(img)
                labels.append(label_val)
        print(f"  {label_name}: {len(files)} files loaded")
    return patches, labels


def evaluate_loocv(clf: GemPatchClassifier) -> dict:
    """Leave-one-out cross-validation accuracy."""
    if clf.sample_count < 2:
        return {"accuracy": 0.0, "total": 0, "correct": 0}

    features = np.array(clf._features, dtype=np.float32)
    labels = np.array(clf._labels, dtype=np.int32)
    n = len(labels)
    correct = 0

    for i in range(n):
        mask = np.ones(n, dtype=bool)
        mask[i] = False
        train_feat = features[mask]
        train_labels = labels[mask]

        feat = features[i]
        dists = np.linalg.norm(train_feat - feat, axis=1)
        k = min(clf._k, len(dists))
        indices = np.argpartition(dists, k)[:k]
        k_dists = dists[indices]
        k_labels = train_labels[indices]

        weights = 1.0 / (k_dists + 1e-6)
        gem_weight = float(weights[k_labels == 1].sum())
        total_weight = float(weights.sum())
        predicted = 1 if (gem_weight / total_weight) > 0.5 else 0

        if predicted == labels[i]:
            correct += 1

    return {"accuracy": correct / n * 100, "total": n, "correct": correct}


def main():
    print("=" * 60)
    print("  Gem Classifier Bootstrap")
    print("=" * 60)
    print(f"  Patches dir: {DEFAULT_PATCHES_DIR}")
    print(f"  Model path:  {DEFAULT_MODEL_PATH}")
    print()

    patches, labels = load_patches(DEFAULT_PATCHES_DIR)
    if not patches:
        print("  No patches found. Run test_gem_farm_flow first to collect samples.")
        return

    print(f"\n  Total: {len(patches)} patches ({sum(labels)} gem, {len(labels) - sum(labels)} not_gem)")

    clf = GemPatchClassifier()
    for patch, label in zip(patches, labels):
        clf.add_sample(patch, bool(label), save_patch=False)

    print(f"  Classifier: {clf.sample_count} samples, warm={clf.is_warm}")

    if clf.is_warm:
        result = evaluate_loocv(clf)
        print(f"\n  LOOCV Accuracy: {result['accuracy']:.1f}% ({result['correct']}/{result['total']})")

    clf.save()
    print(f"\n  Saved to {DEFAULT_MODEL_PATH}")

    stats = clf.get_stats()
    print(f"\n  Stats: {stats}")
    print("=" * 60)


if __name__ == "__main__":
    main()
