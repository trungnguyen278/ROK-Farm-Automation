from __future__ import annotations

import tkinter as tk
from datetime import timedelta


class StatusBar(tk.Frame):
    def __init__(self, parent: tk.Widget, **kwargs):
        super().__init__(parent, bg="#12122a", **kwargs)
        self._fields: dict[str, tk.Label] = {}
        self._build_ui()

    def _build_ui(self):
        lbl_opts = dict(
            font=("Consolas", 9), bg="#12122a", fg="#888899", padx=8, pady=3,
        )
        sep_opts = dict(
            font=("Consolas", 9), bg="#12122a", fg="#333355", text="|",
        )

        self._fields["state"] = tk.Label(self, text="State: IDLE", **lbl_opts)
        self._fields["state"].pack(side="left")
        tk.Label(self, **sep_opts).pack(side="left")

        self._fields["session"] = tk.Label(self, text="Session: 0m 0s", **lbl_opts)
        self._fields["session"].pack(side="left")
        tk.Label(self, **sep_opts).pack(side="left")

        self._fields["apm"] = tk.Label(self, text="APM: 0.0", **lbl_opts)
        self._fields["apm"].pack(side="left")
        tk.Label(self, **sep_opts).pack(side="left")

        self._fields["esp32"] = tk.Label(self, text="ESP32: --", **lbl_opts)
        self._fields["esp32"].pack(side="left")

        self._fields["game"] = tk.Label(self, text="Game: --", **lbl_opts)
        self._fields["game"].pack(side="right")

    def set_state(self, state: str):
        self._fields["state"].configure(text=f"State: {state}")

    def set_session_time(self, seconds: int):
        td = timedelta(seconds=seconds)
        h, remainder = divmod(td.seconds, 3600)
        m, s = divmod(remainder, 60)
        if h > 0:
            text = f"Session: {h}h {m}m"
        else:
            text = f"Session: {m}m {s}s"
        self._fields["session"].configure(text=text)

    def set_apm(self, apm: float):
        self._fields["apm"].configure(text=f"APM: {apm:.1f}")

    def set_esp32(self, port: str | None, connected: bool):
        if connected and port:
            text = f"ESP32: {port} ●"
            fg = "#44FF44"
        elif port:
            text = f"ESP32: {port} ○"
            fg = "#FF4444"
        else:
            text = "ESP32: --"
            fg = "#888899"
        self._fields["esp32"].configure(text=text, fg=fg)

    def set_game(self, detected: bool):
        if detected:
            self._fields["game"].configure(text="Game: Running", fg="#44FF44")
        else:
            self._fields["game"].configure(text="Game: --", fg="#888899")
