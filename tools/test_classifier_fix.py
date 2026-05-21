"""Test: verify new classifier+color filter logic on scan_02 frame."""
import cv2, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from vision.color_filter import is_gem_icon_color
from vision.gem_classifier import GemPatchClassifier

import glob
candidates = (
    glob.glob('tools/screenshots/gem_farm_test/*scan*.png') +
    glob.glob('tools/screenshots/debug_night/*scan*.png') +
    glob.glob('tools/screenshots/debug_scan/*scan*.png')
)
if not candidates:
    print("No scan frames found")
    sys.exit(1)
# Use the most recent
candidates.sort(key=os.path.getmtime, reverse=True)
path = candidates[0]
print("Using: " + path)
frame = cv2.imread(path)
if frame is None:
    print("Cannot read frame")
    sys.exit(1)
print("Frame: %dx%d" % (frame.shape[1], frame.shape[0]))

cache = TemplateCache('templates')
matcher = TemplateMatcher(cache, threshold=0.50)
clf = GemPatchClassifier()
clf.load()

GEM_ICON_THRESHOLD = 0.69
matches = matcher.match_all(frame, 'resources/gem_icon', overlap_thresh=0.3)

accepted = 0
rejected = 0
for m in matches:
    if m.confidence < GEM_ICON_THRESHOLD:
        continue
    is_gem_color, color_info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
    fh, fw = frame.shape[:2]
    x1, y1 = max(0, m.x), max(0, m.y)
    x2, y2 = min(fw, m.x + m.w), min(fh, m.y + m.h)
    patch = frame[y1:y2, x1:x2].copy()
    should, label, conf = clf.should_click(patch)
    reason = color_info.get('reason', '')

    if not is_gem_color and not should:
        print("  REJECT  (%d,%d) tpl=%.3f color=%s clf=%s(%.2f)" % (m.center[0], m.center[1], m.confidence, reason, label, conf))
        rejected += 1
    elif not is_gem_color:
        print("  REJECT  (%d,%d) tpl=%.3f color=%s" % (m.center[0], m.center[1], m.confidence, reason))
        rejected += 1
    else:
        print("  ACCEPT  (%d,%d) tpl=%.3f color=%s clf=%s(%.2f)" % (m.center[0], m.center[1], m.confidence, reason, label, conf))
        accepted += 1

print("\nResult: %d accepted, %d rejected" % (accepted, rejected))
print("OLD logic: 1 accepted, 14 rejected (classifier blocked color=green gems)")
