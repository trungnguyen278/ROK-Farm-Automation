import ctypes

HID_ABS_MAX = 32767


def get_screen_resolution() -> tuple[int, int]:
    user32 = ctypes.windll.user32
    user32.SetProcessDPIAware()
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


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
