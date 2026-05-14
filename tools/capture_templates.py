"""Interactive template capture tool.

Usage: python tools/capture_templates.py

Keyboard shortcuts:
  S         Save current selection as template
  R         Reset selection
  N         New screenshot (re-capture game)
  1-4       Quick-set category (1=buttons 2=popups 3=states 4=resources)
  F         Fit to window (reset zoom)
  Q / ESC   Quit

Mouse:
  Left-drag     Select region
  Scroll up     Zoom in
  Scroll down   Zoom out
  Middle-drag   Pan (while zoomed)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np
from capture.screen_capture import ScreenCapture

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
CATEGORIES = ["buttons", "popups", "states", "resources"]

HELP_TEXT = """
 [S] Save   [R] Reset   [N] New capture   [F] Fit zoom
 [1] buttons  [2] popups  [3] states  [4] resources
 [Q/ESC] Quit   |   Scroll=Zoom   Drag=Select
"""


class CaptureApp:
    def __init__(self):
        self.frame: np.ndarray | None = None
        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.drawing = False
        self.panning = False
        self.pan_start = (0, 0)
        self.pan_origin = (0, 0)
        self.sel_start = (0, 0)
        self.sel_end = (0, 0)
        self.has_selection = False
        self.category_idx = 2  # default: states
        self.win_name = "ROK Template Capture"
        self.win_w = 0
        self.win_h = 0

    def screen_to_image(self, sx, sy):
        ix = int((sx - self.pan_x) / self.zoom)
        iy = int((sy - self.pan_y) / self.zoom)
        if self.frame is not None:
            h, w = self.frame.shape[:2]
            ix = max(0, min(w - 1, ix))
            iy = max(0, min(h - 1, iy))
        return ix, iy

    def image_to_screen(self, ix, iy):
        sx = int(ix * self.zoom + self.pan_x)
        sy = int(iy * self.zoom + self.pan_y)
        return sx, sy

    def mouse_cb(self, event, x, y, flags, param):
        if event == cv2.EVENT_MOUSEWHEEL:
            old_zoom = self.zoom
            if flags > 0:
                self.zoom = min(8.0, self.zoom * 1.2)
            else:
                self.zoom = max(0.1, self.zoom / 1.2)
            ratio = self.zoom / old_zoom
            self.pan_x = int(x - ratio * (x - self.pan_x))
            self.pan_y = int(y - ratio * (y - self.pan_y))
            return

        if event == cv2.EVENT_MBUTTONDOWN:
            self.panning = True
            self.pan_start = (x, y)
            self.pan_origin = (self.pan_x, self.pan_y)
            return
        if event == cv2.EVENT_MOUSEMOVE and self.panning:
            self.pan_x = self.pan_origin[0] + (x - self.pan_start[0])
            self.pan_y = self.pan_origin[1] + (y - self.pan_start[1])
            return
        if event == cv2.EVENT_MBUTTONUP:
            self.panning = False
            return

        if event == cv2.EVENT_LBUTTONDOWN:
            self.drawing = True
            self.sel_start = self.screen_to_image(x, y)
            self.sel_end = self.sel_start
            self.has_selection = False
        elif event == cv2.EVENT_MOUSEMOVE and self.drawing:
            self.sel_end = self.screen_to_image(x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            self.drawing = False
            self.sel_end = self.screen_to_image(x, y)
            x1, x2 = sorted([self.sel_start[0], self.sel_end[0]])
            y1, y2 = sorted([self.sel_start[1], self.sel_end[1]])
            self.has_selection = (x2 - x1 >= 5 and y2 - y1 >= 5)

    def render(self):
        if self.frame is None:
            return np.zeros((480, 640, 3), dtype=np.uint8)

        fh, fw = self.frame.shape[:2]
        canvas = np.full((self.win_h, self.win_w, 3), 40, dtype=np.uint8)

        zw = int(fw * self.zoom)
        zh = int(fh * self.zoom)
        if zw < 1 or zh < 1:
            return canvas

        resized = cv2.resize(self.frame, (zw, zh), interpolation=(
            cv2.INTER_AREA if self.zoom < 1 else cv2.INTER_LINEAR
        ))

        src_x1 = max(0, -self.pan_x)
        src_y1 = max(0, -self.pan_y)
        src_x2 = min(zw, self.win_w - self.pan_x)
        src_y2 = min(zh, self.win_h - self.pan_y)

        if src_x2 <= src_x1 or src_y2 <= src_y1:
            return canvas

        dst_x1 = max(0, self.pan_x)
        dst_y1 = max(0, self.pan_y)
        dst_x2 = dst_x1 + (src_x2 - src_x1)
        dst_y2 = dst_y1 + (src_y2 - src_y1)

        canvas[dst_y1:dst_y2, dst_x1:dst_x2] = resized[src_y1:src_y2, src_x1:src_x2]

        if self.has_selection or self.drawing:
            s1 = self.image_to_screen(*self.sel_start)
            s2 = self.image_to_screen(*self.sel_end)
            cv2.rectangle(canvas, s1, s2, (0, 255, 0), 2)
            x1, x2 = sorted([self.sel_start[0], self.sel_end[0]])
            y1, y2 = sorted([self.sel_start[1], self.sel_end[1]])
            label = f"{x2-x1}x{y2-y1}"
            cv2.putText(canvas, label, (min(s1[0], s2[0]), min(s1[1], s2[1]) - 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        bar_h = 32
        cv2.rectangle(canvas, (0, self.win_h - bar_h), (self.win_w, self.win_h), (30, 30, 30), -1)
        cat_text = f"Category: [{self.category_idx+1}] {CATEGORIES[self.category_idx]}"
        zoom_text = f"Zoom: {self.zoom:.1f}x"
        status = f"{cat_text}  |  {zoom_text}  |  S=Save R=Reset N=Capture F=Fit Q=Quit"
        cv2.putText(canvas, status, (10, self.win_h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

        return canvas

    def fit_zoom(self):
        if self.frame is None:
            return
        fh, fw = self.frame.shape[:2]
        self.zoom = min(self.win_w / fw, self.win_h / fh)
        self.pan_x = int((self.win_w - fw * self.zoom) / 2)
        self.pan_y = int((self.win_h - fh * self.zoom) / 2)

    def save_template(self):
        if not self.has_selection or self.frame is None:
            print("[!] No selection — drag a rectangle first")
            return

        x1, x2 = sorted([self.sel_start[0], self.sel_end[0]])
        y1, y2 = sorted([self.sel_start[1], self.sel_end[1]])
        crop = self.frame[y1:y2, x1:x2]

        category = CATEGORIES[self.category_idx]
        print(f"\nSelection: ({x1},{y1})-({x2},{y2}) = {x2-x1}x{y2-y1}px")
        print(f"Category: {category} (change with keys 1-4)")
        name = input("Template name (without .png): ").strip()
        if not name:
            print("[!] Empty name, cancelled")
            return

        out_path = TEMPLATE_DIR / category / f"{name}.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), crop)
        print(f"[OK] Saved: {out_path} ({crop.shape[1]}x{crop.shape[0]})")
        self.has_selection = False

    def run(self):
        cap = ScreenCapture()
        w = cap.find_window()
        if not w:
            print("[!] ROK window not found. Is the game running?")
            return

        print(f"[OK] Found ROK: {w['width']}x{w['height']}")
        print(HELP_TEXT)

        self.frame = cap.grab_full()
        if self.frame is None:
            print("[!] Failed to capture")
            return

        fh, fw = self.frame.shape[:2]
        scale = min(1.0, 1280 / fw, 720 / fh)
        self.win_w = int(fw * scale)
        self.win_h = int(fh * scale) + 32

        cv2.namedWindow(self.win_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(self.win_name, self.win_w, self.win_h)
        cv2.setMouseCallback(self.win_name, self.mouse_cb)
        self.fit_zoom()

        while True:
            canvas = self.render()
            cv2.imshow(self.win_name, canvas)
            key = cv2.waitKey(30) & 0xFF

            if key in (ord("q"), 27):  # Q or ESC
                break
            elif key == ord("s"):
                self.save_template()
            elif key == ord("r"):
                self.has_selection = False
                print("[i] Selection reset")
            elif key == ord("n"):
                self.frame = cap.grab_full()
                if self.frame is not None:
                    self.has_selection = False
                    print("[i] New screenshot captured")
            elif key == ord("f"):
                self.fit_zoom()
            elif key in (ord("1"), ord("2"), ord("3"), ord("4")):
                self.category_idx = key - ord("1")
                print(f"[i] Category: {CATEGORIES[self.category_idx]}")

        cv2.destroyAllWindows()
        cap.close()
        print("Done.")


if __name__ == "__main__":
    CaptureApp().run()
