"""Resize the Rise of Kingdoms window so its MEASURED client area == target.

Usage:
    python resize_window.py <client_w> <client_h> [--batch]

<client_w>/<client_h> are the desired client (content) dimensions in pixels --
the same numbers that ScreenCapture.find_window reports and that get printed to
the log (e.g. 1533x863). We do NOT just slam a fixed outer size: the game engine
re-snaps / rounds its render to its own aspect, so a single SetWindowPos usually
lands a few px off. Instead we resize, re-measure the real client rect, compute
the leftover error and correct -- iterating until the measured client matches the
target within tolerance. That self-correction IS the "compensation".

Launched (often elevated via ShellExecute "runas") by
anti_detection/player_actions.py::_try_resize_game. Dependency-light: only
win32gui + win32con + time. ASCII-only output (Windows cp1252 console safe).
"""

import ctypes
import sys
import time

import win32con
import win32gui

# MUST run before any window measurement. The capture process declares
# per-monitor DPI awareness (capture/screen_capture.py), so it measures the
# client rect in PHYSICAL pixels. We must match it -- otherwise, under display
# scaling (e.g. 150%), GetClientRect here returns logical px and our 1533 target
# lands as 1533*scale physical px (the 2301 bug). Same awareness == same units.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

WINDOW_TITLE = "Rise of Kingdoms"
MAX_PASSES = 4          # resize attempts before giving up
TOLERANCE = 1           # px; measured client may differ by at most this
SETTLE_SEC = 0.12       # let the engine react before re-measuring


def find_game_hwnd(title: str = WINDOW_TITLE):
    """Return the hwnd of the first visible window whose title contains `title`."""
    found = []

    def _cb(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        if title.lower() in win32gui.GetWindowText(hwnd).lower():
            found.append(hwnd)

    win32gui.EnumWindows(_cb, None)
    return found[0] if found else None


def _client_size(hwnd):
    _, _, cw, ch = win32gui.GetClientRect(hwnd)  # left/top always 0
    return cw, ch


def resize_client(hwnd, client_w: int, client_h: int) -> bool:
    """Resize `hwnd` until its measured client area == client_w x client_h.

    Keeps the window's top-left corner fixed. Returns True if the final measured
    client size is within TOLERANCE of the target.
    """
    # Restore first: a maximized/minimized window can't be sized.
    placement = win32gui.GetWindowPlacement(hwnd)
    if placement[1] != win32con.SW_SHOWNORMAL:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(SETTLE_SEC)

    cw, ch = _client_size(hwnd)
    if cw <= 0 or ch <= 0:
        print("Client rect is empty; cannot resize")
        return False

    start_cw, start_ch = cw, ch

    for attempt in range(1, MAX_PASSES + 1):
        err_w = client_w - cw
        err_h = client_h - ch
        if abs(err_w) <= TOLERANCE and abs(err_h) <= TOLERANCE:
            break

        ox1, oy1, ox2, oy2 = win32gui.GetWindowRect(hwnd)
        outer_w, outer_h = ox2 - ox1, oy2 - oy1
        # Nudge the outer size by exactly the remaining client error.
        new_outer_w = outer_w + err_w
        new_outer_h = outer_h + err_h

        win32gui.SetWindowPos(
            hwnd, None, ox1, oy1, new_outer_w, new_outer_h,
            win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
        )
        time.sleep(SETTLE_SEC)
        cw, ch = _client_size(hwnd)
        print(f"  pass {attempt}: client now {cw}x{ch} (target {client_w}x{client_h})")

    ok = abs(client_w - cw) <= TOLERANCE and abs(client_h - ch) <= TOLERANCE
    print(f"Resized client {start_cw}x{start_ch} -> {cw}x{ch} "
          f"(target {client_w}x{client_h}) {'OK' if ok else 'MISMATCH'}")
    return ok


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    if len(args) < 2:
        print("Usage: python resize_window.py <client_w> <client_h> [--batch]")
        return 2

    try:
        client_w, client_h = int(args[0]), int(args[1])
    except ValueError:
        print("client_w and client_h must be integers")
        return 2

    hwnd = find_game_hwnd()
    if not hwnd:
        print(f"Window '{WINDOW_TITLE}' not found")
        return 1

    return 0 if resize_client(hwnd, client_w, client_h) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
