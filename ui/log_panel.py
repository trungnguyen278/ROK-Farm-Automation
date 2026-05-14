from __future__ import annotations

import logging
import tkinter as tk
from queue import Queue, Empty
from datetime import datetime

logger = logging.getLogger(__name__)

LEVEL_COLORS = {
    "DEBUG": "#888888",
    "INFO": "#CCCCCC",
    "WARNING": "#FFD700",
    "ERROR": "#FF4444",
    "SUCCESS": "#44FF44",
}

MAX_LINES = 500


class LogPanel(tk.Frame):
    def __init__(self, parent: tk.Widget, **kwargs):
        super().__init__(parent, **kwargs)
        self._queue: Queue[tuple[str, str]] = Queue()
        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg="#1a1a2e")
        header.pack(fill="x")
        tk.Label(
            header, text="Log", font=("Consolas", 10, "bold"),
            bg="#1a1a2e", fg="#CCCCCC", anchor="w", padx=5,
        ).pack(side="left")
        tk.Button(
            header, text="Clear", font=("Consolas", 8),
            bg="#2a2a3e", fg="#CCCCCC", bd=0, padx=5,
            command=self._clear,
        ).pack(side="right", padx=2, pady=2)

        self._text = tk.Text(
            self, wrap="word", state="disabled",
            bg="#0d0d1a", fg="#CCCCCC", font=("Consolas", 9),
            bd=0, padx=4, pady=4, insertbackground="#CCCCCC",
        )
        scrollbar = tk.Scrollbar(self, command=self._text.yview)
        self._text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._text.pack(fill="both", expand=True)

        for level, color in LEVEL_COLORS.items():
            self._text.tag_configure(level, foreground=color)
        self._text.tag_configure("TIMESTAMP", foreground="#666688")

    def log(self, msg: str, level: str = "INFO"):
        self._queue.put((level, msg))

    def poll(self):
        count = 0
        while count < 50:
            try:
                level, msg = self._queue.get_nowait()
            except Empty:
                break
            self._append(level, msg)
            count += 1

    def _append(self, level: str, msg: str):
        self._text.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self._text.insert("end", f"[{ts}] ", "TIMESTAMP")
        tag = level if level in LEVEL_COLORS else "INFO"
        self._text.insert("end", f"[{level}] {msg}\n", tag)
        self._trim()
        self._text.configure(state="disabled")
        self._text.see("end")

    def _trim(self):
        line_count = int(self._text.index("end-1c").split(".")[0])
        if line_count > MAX_LINES:
            self._text.delete("1.0", f"{line_count - MAX_LINES}.0")

    def _clear(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")


class QueueHandler(logging.Handler):
    def __init__(self, log_panel: LogPanel):
        super().__init__()
        self._panel = log_panel

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            self._panel.log(msg, record.levelname)
        except Exception:
            self.handleError(record)
