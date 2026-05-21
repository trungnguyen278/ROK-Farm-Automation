"""Test: WGC grab_full with retry vs without."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capture.screen_capture import ScreenCapture

sc = ScreenCapture()
win = sc.find_window()
if not win:
    print("Game window not found")
    sys.exit(1)
print("Window: %dx%d" % (win["width"], win["height"]))
print("Backend: %s" % sc._backend_name)

# Test grab_full 50 times
success = 0
fail = 0
times = []
for i in range(50):
    t0 = time.monotonic()
    frame = sc.grab_full()
    dt = (time.monotonic() - t0) * 1000
    times.append(dt)
    if frame is not None:
        success += 1
    else:
        fail += 1

avg_ms = sum(times) / len(times)
max_ms = max(times)
print("\n50 grabs: %d success, %d fail" % (success, fail))
print("Avg time: %.1fms, Max: %.1fms" % (avg_ms, max_ms))

sc.close()
