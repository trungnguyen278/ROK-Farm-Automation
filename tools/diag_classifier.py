"""Diagnostic: why does k-NN reject gem patches from scan_02?"""
import cv2, numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from vision.gem_classifier import GemPatchClassifier, _extract_features

frame = cv2.imread('tools/screenshots/gem_farm_test/m1_scan_02_095033.png')
if frame is None:
    print("cannot read frame")
    sys.exit(1)
print(f"Frame: {frame.shape[1]}x{frame.shape[0]}")

cache = TemplateCache('templates')
matcher = TemplateMatcher(cache, threshold=0.50)
clf = GemPatchClassifier()
clf.load()

features = np.array(clf._features, dtype=np.float32)
labels = np.array(clf._labels, dtype=np.int32)
gem_idx = np.where(labels == 1)[0]
notgem_idx = np.where(labels == 0)[0]

results = matcher.match_all(frame, 'resources/gem_icon')
print(f"Matches: {len(results)}")
print(f"Training: {len(gem_idx)} gem, {len(notgem_idx)} not_gem\n")

for i, r in enumerate(results[:10]):
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, r.x), max(0, r.y)
    x2, y2 = min(fw, r.x + r.w), min(fh, r.y + r.h)
    patch = frame[y1:y2, x1:x2].copy()

    feat = _extract_features(patch)
    dists = np.linalg.norm(features - feat, axis=1)

    gem_dists = dists[gem_idx]
    notgem_dists = dists[notgem_idx]

    label, conf = clf.predict(patch)

    top5 = np.argsort(dists)[:5]
    top5_info = [(int(labels[j]), round(float(dists[j]), 3)) for j in top5]

    print(f"#{i:2d} tpl={r.confidence:.3f} patch={patch.shape[1]}x{patch.shape[0]} -> {label}({conf:.2f})")
    print(f"     gem  nn: min={gem_dists.min():.3f} mean5={np.sort(gem_dists)[:5].mean():.3f}")
    print(f"     not  nn: min={notgem_dists.min():.3f} mean5={np.sort(notgem_dists)[:5].mean():.3f}")
    print(f"     top5: {top5_info}")
    print()
