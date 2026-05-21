"""Test: verify mouse humanizer produces clean, fast paths."""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anti_detection.mouse_humanizer import MouseHumanizer

with open('profiles/default.json') as f:
    profile = json.load(f)

h = MouseHumanizer(profile)

tests = [
    (100, 100, 500, 300, "medium 500px"),
    (100, 100, 200, 150, "short 120px"),
    (100, 100, 900, 600, "long 950px"),
]

for x1, y1, x2, y2, desc in tests:
    print("--- %s ---" % desc)
    path = h.humanize_move(x1, y1, x2, y2)
    total_ms = sum(p[2] for p in path)

    max_dev = 0
    for px, py, ms in path:
        # deviation from straight line
        t = 0  # approximate
        dx, dy = x2 - x1, y2 - y1
        if dx != 0 or dy != 0:
            t = ((px - x1) * dx + (py - y1) * dy) / (dx*dx + dy*dy)
            t = max(0, min(1, t))
            lx = x1 + t * dx
            ly = y1 + t * dy
            dev = ((px - lx)**2 + (py - ly)**2) ** 0.5
            max_dev = max(max_dev, dev)

    print("  steps=%d, total_ms=%d, max_deviation=%.1fpx" % (len(path), total_ms, max_dev))
    # Show first/last 3 points
    for i, (px, py, ms) in enumerate(path[:3]):
        print("    [%d] (%d, %d) %dms" % (i, px, py, ms))
    if len(path) > 6:
        print("    ...")
    for i, (px, py, ms) in enumerate(path[-3:]):
        print("    [%d] (%d, %d) %dms" % (len(path)-3+i, px, py, ms))
    print()

# Test click spread
spreads = []
for _ in range(100):
    ox, oy, hold = h.humanize_click(500, 500)
    spreads.append((ox**2 + oy**2)**0.5)
avg_spread = sum(spreads) / len(spreads)
max_spread = max(spreads)
print("Click spread (100 samples): avg=%.1fpx, max=%.1fpx" % (avg_spread, max_spread))

# Overshoot rate
os_count = sum(1 for _ in range(1000) if h.should_overshoot())
print("Overshoot rate: %d/1000 (%.1f%%)" % (os_count, os_count/10))
