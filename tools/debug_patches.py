import cv2, os, sys
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from vision.color_filter import is_gem_icon_color
from vision.gem_classifier import GemPatchClassifier

frame = cv2.imread('tools/screenshots/gem_farm_test/m1_scan_02_095033.png')
cache = TemplateCache('templates')
matcher = TemplateMatcher(cache, threshold=0.50)
clf = GemPatchClassifier()
clf.load()

results = matcher.match_all(frame, 'resources/gem_icon')
fh, fw = frame.shape[:2]
out = 'screenshots/patches'
os.makedirs(out, exist_ok=True)

for i, r in enumerate(results[:15]):
    x1, y1 = max(0, r.x), max(0, r.y)
    x2, y2 = min(fw, r.x + r.w), min(fh, r.y + r.h)
    patch = frame[y1:y2, x1:x2].copy()

    should, label, cconf = clf.should_click(patch)
    is_gem, info = is_gem_icon_color(frame, r.x, r.y, r.w, r.h)
    reason = info.get("reason", "")

    cx, cy = r.x + r.w // 2, r.y + r.h // 2
    pad = 30
    ctx = frame[max(0, cy-pad):min(fh, cy+pad), max(0, cx-pad):min(fw, cx+pad)]
    fname = f"patch_{i:02d}_t{r.confidence:.2f}_c{label}_{reason}.png"
    cv2.imwrite(os.path.join(out, fname), ctx)
    print(f"{i:2d} ({r.x:4d},{r.y:3d}) tpl={r.confidence:.3f} clf={label}({cconf:.2f}) color={is_gem} {reason}")
