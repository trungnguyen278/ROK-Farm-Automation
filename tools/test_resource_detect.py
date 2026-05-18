import cv2
import numpy as np

frame = cv2.imread(r"C:\Users\LEGION\Pictures\Screenshots\Screenshot 2026-05-18 000647.png")
fh, fw = frame.shape[:2]
ann = frame.copy()

tpls = {}
for name in ["city_wood", "city_food", "city_gold", "city_stone"]:
    tpls[name] = cv2.imread(f"templates/resources/{name}.png")

colors = {
    "city_wood": (0, 165, 255),
    "city_food": (0, 255, 0),
    "city_gold": (0, 255, 255),
    "city_stone": (200, 200, 200),
}
scales = [0.7, 0.8, 0.9, 1.0, 1.1]

for thr in [0.80, 0.85, 0.90]:
    line = f"thr={thr:.2f}: "
    for name, tpl in tpls.items():
        pts = []
        for sc in scales:
            r = cv2.resize(tpl, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
            rh, rw = r.shape[:2]
            if rw > fw or rh > fh:
                continue
            res = cv2.matchTemplate(frame, r, cv2.TM_CCOEFF_NORMED)
            for pt in zip(*np.where(res >= thr)[::-1]):
                cx = int(pt[0]) + rw // 2
                cy = int(pt[1]) + rh // 2
                if not any(abs(p[0] - cx) < 25 and abs(p[1] - cy) < 25 for p in pts):
                    pts.append((cx, cy))
        line += f"{name.split('_')[1]}={len(pts)} "
    print(line)

# Annotate at 0.75
for name, tpl in tpls.items():
    pts = []
    for sc in scales:
        r = cv2.resize(tpl, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA)
        rh, rw = r.shape[:2]
        if rw > fw or rh > fh:
            continue
        res = cv2.matchTemplate(frame, r, cv2.TM_CCOEFF_NORMED)
        for pt in zip(*np.where(res >= 0.75)[::-1]):
            cx = int(pt[0]) + rw // 2
            cy = int(pt[1]) + rh // 2
            conf = float(res[int(pt[1]), int(pt[0])])
            if not any(abs(p[0] - cx) < 25 and abs(p[1] - cy) < 25 for p in pts):
                pts.append((cx, cy, conf))
                cv2.circle(ann, (cx, cy), 18, colors[name], 2)
                cv2.putText(ann, f"{conf:.2f}", (cx - 15, cy - 22),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, colors[name], 1)
    print(f"{name}: {len(pts)} matches at 0.75")
    for cx, cy, conf in pts:
        print(f"  ({cx},{cy}) conf={conf:.3f}")

cv2.imwrite("tools/screenshots/resource_detect_test.png", ann)
print("Saved: tools/screenshots/resource_detect_test.png")
