import ctypes
import ctypes.wintypes

HID_ABS_MAX = 32767

# OpenProcess access right that a normal user process may request for any of its
# own processes -- enough for QueryFullProcessImageNameW, unlike the wider
# PROCESS_QUERY_INFORMATION.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def pid_for_hwnd(hwnd) -> int:
    pid = ctypes.wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def exe_for_pid(pid: int) -> str:
    """Executable file name (basename, e.g. 'MASS.exe') owning `pid`, '' if unknown."""
    if not pid:
        return ""
    h = ctypes.windll.kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        size = ctypes.wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if not ctypes.windll.kernel32.QueryFullProcessImageNameW(
                h, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1]
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def exe_for_hwnd(hwnd) -> str:
    """Executable file name owning a window. Used to tell the ROK game window
    apart from the Lilith launcher window -- both carry 'Rise of Kingdoms' in
    their title, so the title alone cannot distinguish them."""
    return exe_for_pid(pid_for_hwnd(hwnd))


def get_screen_resolution() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def get_cursor_pos() -> tuple[int, int]:
    pt = _POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def screen_to_hid(screen_x: int, screen_y: int) -> tuple[int, int]:
    res_w, res_h = get_screen_resolution()
    hid_x = int(screen_x * HID_ABS_MAX / res_w)
    hid_y = int(screen_y * HID_ABS_MAX / res_h)
    return max(0, min(HID_ABS_MAX, hid_x)), max(0, min(HID_ABS_MAX, hid_y))


def screen_delta_to_hid(dx: int, dy: int) -> tuple[int, int]:
    res_w, res_h = get_screen_resolution()
    hid_dx = int(dx * HID_ABS_MAX / res_w)
    hid_dy = int(dy * HID_ABS_MAX / res_h)
    return hid_dx, hid_dy
