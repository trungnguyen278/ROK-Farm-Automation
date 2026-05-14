from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

import cv2
import numpy as np
from PIL import Image, ImageTk

if TYPE_CHECKING:
    from .app import MainApp

BG = "#16163a"
FG = "#CCCCCC"
BTN_BG = "#2a2a5e"

REFRESH_OPTIONS = {"Off": 0, "0.5s": 500, "1s": 1000, "2s": 2000, "5s": 5000}


class MonitorTab(tk.Frame):
    def __init__(self, parent: tk.Widget, app: MainApp, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._app = app
        self._photo: ImageTk.PhotoImage | None = None
        self._auto_refresh_id: str | None = None
        self._build_ui()

    def _build_ui(self):
        self._canvas = tk.Canvas(
            self, bg="#0d0d1a", highlightthickness=0,
            width=640, height=360,
        )
        self._canvas.pack(fill="both", expand=True, padx=5, pady=5)

        bottom = tk.Frame(self, bg=BG)
        bottom.pack(fill="x", padx=5, pady=3)

        tk.Label(
            bottom, text="Refresh:", font=("Consolas", 9),
            bg=BG, fg=FG,
        ).pack(side="left")

        self._refresh_var = tk.StringVar(value="1s")
        ttk.Combobox(
            bottom, textvariable=self._refresh_var,
            values=list(REFRESH_OPTIONS.keys()),
            state="readonly", width=6,
        ).pack(side="left", padx=4)
        self._refresh_var.trace_add("write", lambda *_: self._schedule_refresh())

        tk.Button(
            bottom, text="Capture", font=("Consolas", 9),
            bg=BTN_BG, fg=FG, bd=0, padx=10,
            command=self._capture_once,
        ).pack(side="left", padx=4)

        self._match_label = tk.Label(
            bottom, text="Matches: --", font=("Consolas", 9),
            bg=BG, fg="#888899", anchor="w",
        )
        self._match_label.pack(side="left", padx=10)

        self._state_label = tk.Label(
            bottom, text="State: --", font=("Consolas", 9),
            bg=BG, fg="#888899", anchor="e",
        )
        self._state_label.pack(side="right")

        self._schedule_refresh()

    def _schedule_refresh(self):
        if self._auto_refresh_id:
            self.after_cancel(self._auto_refresh_id)
            self._auto_refresh_id = None

        interval = REFRESH_OPTIONS.get(self._refresh_var.get(), 0)
        if interval > 0:
            self._auto_refresh_loop(interval)

    def _auto_refresh_loop(self, interval: int):
        self._capture_once()
        self._auto_refresh_id = self.after(interval, self._auto_refresh_loop, interval)

    def _capture_once(self):
        capture = self._app.screen_capture
        if capture is None:
            return

        frame = capture.grab_full()
        if frame is None:
            self._match_label.configure(text="Matches: no frame")
            return

        matches = []
        state_text = "UNKNOWN"
        state_detector = self._app.state_detector
        if state_detector:
            screen, match = state_detector.detect_with_match(frame)
            state_text = screen.value
            if match:
                matches = [match]

        self._display_frame(frame, matches)
        self._state_label.configure(text=f"State: {state_text}")

        if matches:
            parts = [f"{m.name}({m.confidence:.2f})@({m.x},{m.y})" for m in matches]
            self._match_label.configure(text=f"Matches: {', '.join(parts)}")
        else:
            self._match_label.configure(text="Matches: none")

    def _display_frame(self, frame: np.ndarray, matches: list):
        canvas_w = self._canvas.winfo_width() or 640
        canvas_h = self._canvas.winfo_height() or 360
        fh, fw = frame.shape[:2]

        scale = min(canvas_w / fw, canvas_h / fh)
        new_w = int(fw * scale)
        new_h = int(fh * scale)

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb).resize((new_w, new_h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)

        self._canvas.delete("all")
        x_off = (canvas_w - new_w) // 2
        y_off = (canvas_h - new_h) // 2
        self._canvas.create_image(x_off, y_off, anchor="nw", image=self._photo)

        for m in matches:
            x1 = int(m.x * scale) + x_off
            y1 = int(m.y * scale) + y_off
            x2 = int((m.x + m.w) * scale) + x_off
            y2 = int((m.y + m.h) * scale) + y_off
            self._canvas.create_rectangle(x1, y1, x2, y2, outline="#44FF44", width=2)
            self._canvas.create_text(
                x1, y1 - 3, anchor="sw",
                text=f"{m.name} {m.confidence:.2f}",
                fill="#44FF44", font=("Consolas", 8),
            )

    def on_tab_selected(self):
        self._schedule_refresh()

    def on_tab_deselected(self):
        if self._auto_refresh_id:
            self.after_cancel(self._auto_refresh_id)
            self._auto_refresh_id = None
