"""Loop test: only alt_tab, mail, chat. Ctrl+C to stop."""
import sys, os, random, time, ctypes
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ctypes.windll.user32.SetProcessDPIAware()

import win32gui
from capture.screen_capture import ScreenCapture
from capture.screen_info import get_cursor_pos
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from anti_detection.profile_loader import ProfileLoader, DEFAULT_PROFILE
from anti_detection.mouse_humanizer import MouseHumanizer
from serial_comm.connection import SerialConnection
from serial_comm.command_buffer import CommandBuffer
from anti_detection.player_actions import ACTION_REGISTRY
import anti_detection.player_actions as pa

pa._DEBUG_BADGES = True
TITLE_BAR_H = 40


def find_game_window(title="Rise of Kingdoms"):
    result = {}
    def cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            t = win32gui.GetWindowText(hwnd)
            if title.lower() in t.lower():
                r = win32gui.GetWindowRect(hwnd)
                result.update(left=r[0], top=r[1],
                              width=r[2] - r[0], height=r[3] - r[1])
    win32gui.EnumWindows(cb, None)
    return result if result else None


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "COM28"

    win = find_game_window()
    if not win:
        print("Game not found")
        return
    print("Game: %dx%d at (%d,%d)" % (win["width"], win["height"],
                                       win["left"], win["top"]))

    conn = SerialConnection(port=port)
    if not conn.connect():
        print("ESP32 failed on %s" % port)
        return
    cmd = CommandBuffer(conn)
    cmd.start()
    print("ESP32: %s" % port)

    loader = ProfileLoader()
    profile = loader.load_random() if loader.list_profiles() else DEFAULT_PROFILE.copy()
    humanizer = MouseHumanizer(profile)
    cache = TemplateCache()
    matcher = TemplateMatcher(cache)
    sc = ScreenCapture()

    class Ctx:
        def __init__(self):
            self.win = win
            self.cmd = cmd

        def _center_screen(self):
            return (win["left"] + win["width"] // 2,
                    win["top"] + win["height"] // 2)

        def _clamp_to_play_area(self, sx, sy):
            wl, wt = win["left"], win["top"]
            ww, wh = win["width"], win["height"]
            return (max(wl + int(ww * 0.12), min(wl + int(ww * 0.88), sx)),
                    max(wt + int(wh * 0.22), min(wt + int(wh * 0.70), sy)))

        def _clamp_to_window(self, sx, sy, pad=5):
            return (max(win["left"] + pad, min(win["left"] + win["width"] - pad, sx)),
                    max(win["top"] + max(pad, TITLE_BAR_H),
                        min(win["top"] + win["height"] - pad, sy)))

        def _moveto(self, sx, sy):
            sx, sy = self._clamp_to_window(sx, sy)
            cur_x, cur_y = get_cursor_pos()
            if abs(sx - cur_x) < 3 and abs(sy - cur_y) < 3:
                return True
            path = humanizer.humanize_move(cur_x, cur_y, sx, sy)
            for px, py, step_ms in path:
                ax, ay = get_cursor_pos()
                mdx, mdy = int(px - ax), int(py - ay)
                if abs(mdx) > 0 or abs(mdy) > 0:
                    dur = max(step_ms, max(abs(mdx), abs(mdy)))
                    cmd.send("MOVE", mdx, mdy, dur)
            return True

        def _click(self, sx, sy, hold_ms=0):
            self._moveto(sx, sy)
            time.sleep(random.uniform(0.15, 0.4))
            if hold_ms <= 0:
                hold_ms = random.randint(35, 90)
            cmd.send("CLICK", "L", hold_ms)
            time.sleep(random.uniform(0.1, 0.3))
            return True

        def _click_pct(self, pct_x, pct_y, jitter_px=10):
            sx = win["left"] + int(win["width"] * pct_x) + random.randint(-jitter_px, jitter_px)
            sy = win["top"] + int(win["height"] * pct_y) + random.randint(-jitter_px, jitter_px)
            return self._click(sx, sy)

        def _human_drag(self, sx, sy, ex, ey, button="L",
                        speed_factor=1.0, easing="in_out"):
            sx, sy = self._clamp_to_window(sx, sy)
            ex, ey = self._clamp_to_window(ex, ey)
            self._moveto(sx, sy)
            time.sleep(random.uniform(0.08, 0.2))
            path = humanizer.humanize_move(sx, sy, ex, ey)
            if speed_factor != 1.0:
                path = [(x, y, max(3, int(ms / speed_factor))) for x, y, ms in path]
            cmd.send("MDOWN", button)
            time.sleep(random.uniform(0.01, 0.03))
            prev_x, prev_y = float(sx), float(sy)
            for px, py, step_ms in path:
                mdx, mdy = int(px - prev_x), int(py - prev_y)
                if abs(mdx) > 0 or abs(mdy) > 0:
                    cmd.send("MOVE", mdx, mdy, step_ms)
                prev_x, prev_y = float(px), float(py)
            time.sleep(random.uniform(0.01, 0.03))
            cmd.send("MUP", button)

        def _scroll_at_center(self, amount, count=1):
            cx, cy = self._center_screen()
            cx += random.randint(-int(win["width"] * 0.15), int(win["width"] * 0.15))
            cy += random.randint(-int(win["height"] * 0.10), int(win["height"] * 0.10))
            self._moveto(cx, cy)
            time.sleep(random.uniform(0.15, 0.4))
            direction = 1 if amount > 0 else -1
            for _ in range(abs(amount) * count):
                cmd.send("SCROLL", direction)
                time.sleep(random.uniform(0.04, 0.12))

        def _press_escape(self):
            cmd.send("KEY", "ESC", random.randint(30, 80))

        def _wait(self, spec, variance=0.0):
            if isinstance(spec, tuple):
                center, spread = spec[0], spec[1] if len(spec) > 1 else spec[0] * 0.15
            else:
                center, spread = float(spec), float(spec) * 0.15
            sigma = spread / center if center > 0 else 0.15
            actual = max(0.05, center * random.lognormvariate(0, sigma))
            time.sleep(actual)
            return actual

        def _grab(self):
            return sc.grab_full()

        def _find(self, template, threshold=0.65):
            frame = sc.grab_full()
            if frame is None:
                return None
            m = matcher.match_single(frame, template)
            if m and m.confidence >= threshold:
                return m
            return None

        def _close_panel(self, panel):
            self._press_escape()
            time.sleep(random.uniform(0.2, 0.5))

    ctx = Ctx()
    pool = ["alt_tab", "mail", "chat"]
    print("\nLoop: %s  |  Ctrl+C to stop\n" % ", ".join(pool))

    i = 0
    try:
        while True:
            action = random.choice(pool)
            i += 1
            print("--- [%d] %s ---" % (i, action))
            try:
                ACTION_REGISTRY[action](ctx)
                print("  OK")
            except Exception as e:
                print("  ERROR: %s" % e)
            delay = random.uniform(15, 45)
            print("  wait %.0fs\n" % delay)
            time.sleep(delay)
    except KeyboardInterrupt:
        print("\nStopped after %d actions" % i)

    cmd.stop()
    conn.disconnect()


if __name__ == "__main__":
    main()
