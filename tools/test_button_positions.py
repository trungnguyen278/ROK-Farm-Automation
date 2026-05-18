import cv2
import sys
sys.path.insert(0, ".")
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from vision.color_filter import is_gem_icon_color

cache = TemplateCache("templates")
matcher = TemplateMatcher(cache, threshold=0.50)

frame = cv2.imread(r"C:\Users\LEGION\Pictures\Screenshots\Screenshot 2026-05-18 104331.png")
if frame is None:
    print("Screenshot not found")
    sys.exit(1)

fh, fw = frame.shape[:2]
print(f"Frame: {fw}x{fh}")

matches = matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
print(f"\nAll gem_icon matches: {len(matches)}")

ann = frame.copy()
for m in sorted(matches, key=lambda x: -x.confidence):
    is_gem, info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
    reason = info.get("reason", "")
    tag = "GEM" if is_gem else "REJECT"
    print(f"  conf={m.confidence:.3f} at {m.center} ({m.w}x{m.h}) "
          f"[{tag}] green={info.get('green_pct',0):.1f}% gold={info.get('gold_pct',0):.1f}% "
          f"white={info.get('white_pct',0):.1f}% reason={reason}")

    color = (0, 255, 0) if is_gem else (0, 0, 255)
    cv2.circle(ann, m.center, 20, color, 2)
    cv2.putText(ann, f"{m.confidence:.2f} {tag}", (m.center[0]-30, m.center[1]-25),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
    cv2.putText(ann, f"g={info.get('green_pct',0):.0f} au={info.get('gold_pct',0):.0f}",
                (m.center[0]-30, m.center[1]+35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.35, color, 1)

cv2.imwrite("tools/screenshots/verify_color_filter.png", ann)
print("\nSaved: tools/screenshots/verify_color_filter.png")
