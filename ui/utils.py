from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageTk
import win32com.client
import win32gui

logger = logging.getLogger(__name__)

LNK_PATHS = [
    Path(r"C:\Users\Public\Desktop\Rise of Kingdoms.lnk"),
    Path.home() / "Desktop" / "Rise of Kingdoms.lnk",
]


def resolve_lnk(lnk_path: str | Path) -> str | None:
    lnk_path = Path(lnk_path)
    if not lnk_path.exists():
        return None
    try:
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(str(lnk_path))
        target = shortcut.Targetpath
        if target and Path(target).exists():
            return target
    except Exception as e:
        logger.warning("Failed to resolve LNK %s: %s", lnk_path, e)
    return None


def find_game_exe() -> str | None:
    for lnk in LNK_PATHS:
        target = resolve_lnk(lnk)
        if target:
            return target
    return None


def launch_game() -> bool:
    exe = find_game_exe()
    if not exe:
        logger.error("Game executable not found")
        return False
    try:
        subprocess.Popen(exe)
        logger.info("Launched game: %s", exe)
        return True
    except OSError as e:
        logger.error("Failed to launch game: %s", e)
        return False


def find_game_window(title: str = "Rise of Kingdoms") -> dict | None:
    result: dict | None = None

    def _enum_cb(hwnd, _):
        nonlocal result
        if not win32gui.IsWindowVisible(hwnd):
            return
        wt = win32gui.GetWindowText(hwnd)
        if title.lower() in wt.lower():
            rect = win32gui.GetWindowRect(hwnd)
            result = {
                "hwnd": hwnd,
                "left": rect[0],
                "top": rect[1],
                "width": rect[2] - rect[0],
                "height": rect[3] - rect[1],
            }

    win32gui.EnumWindows(_enum_cb, None)
    return result


def cv2_to_photoimage(frame: np.ndarray, max_width: int = 640) -> ImageTk.PhotoImage:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    img = Image.fromarray(rgb)
    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / w
        img = img.resize((max_width, int(h * scale)), Image.LANCZOS)
    return ImageTk.PhotoImage(img)


def list_serial_ports() -> list[str]:
    import serial.tools.list_ports
    return [p.device for p in serial.tools.list_ports.comports()]
