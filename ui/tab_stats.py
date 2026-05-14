from __future__ import annotations

import csv
import json
import tkinter as tk
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import MainApp

BG = "#16163a"
FG = "#CCCCCC"
BTN_BG = "#2a2a5e"

STATS_FILE = Path("stats.json")


class SessionStats:
    def __init__(self):
        self.session_start: datetime | None = None
        self.total_actions: int = 0
        self.total_errors: int = 0
        self.gathers: int = 0
        self.trains: int = 0
        self._history: list[dict] = []
        self._load()

    def start_session(self):
        self.session_start = datetime.now()
        self.total_actions = 0
        self.total_errors = 0
        self.gathers = 0
        self.trains = 0

    def record_action(self, action_type: str = "generic"):
        self.total_actions += 1
        if action_type == "gather":
            self.gathers += 1
        elif action_type == "train":
            self.trains += 1

    def record_error(self):
        self.total_errors += 1

    def end_session(self):
        if not self.session_start:
            return
        duration = (datetime.now() - self.session_start).total_seconds()
        self._history.append({
            "date": self.session_start.strftime("%Y-%m-%d"),
            "start": self.session_start.isoformat(),
            "duration_min": round(duration / 60, 1),
            "actions": self.total_actions,
            "errors": self.total_errors,
            "gathers": self.gathers,
            "trains": self.trains,
        })
        self._save()
        self.session_start = None

    @property
    def session_seconds(self) -> int:
        if not self.session_start:
            return 0
        return int((datetime.now() - self.session_start).total_seconds())

    @property
    def apm(self) -> float:
        secs = self.session_seconds
        if secs < 1:
            return 0.0
        return self.total_actions / (secs / 60.0)

    @property
    def today_hours(self) -> float:
        today = datetime.now().strftime("%Y-%m-%d")
        total = sum(
            h["duration_min"] for h in self._history if h["date"] == today
        )
        if self.session_start and self.session_start.strftime("%Y-%m-%d") == today:
            total += self.session_seconds / 60.0
        return total / 60.0

    @property
    def history(self) -> list[dict]:
        return list(self._history)

    def daily_summary(self, days: int = 7) -> list[tuple[str, float]]:
        result = []
        for i in range(days - 1, -1, -1):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            total = sum(h["duration_min"] for h in self._history if h["date"] == d)
            result.append((d, total / 60.0))
        return result

    def _load(self):
        if STATS_FILE.exists():
            try:
                with open(STATS_FILE, "r") as f:
                    self._history = json.load(f)
            except Exception:
                self._history = []

    def _save(self):
        with open(STATS_FILE, "w") as f:
            json.dump(self._history, f, indent=2)


class StatsTab(tk.Frame):
    def __init__(self, parent: tk.Widget, app: MainApp, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._app = app
        self._build_ui()

    def _build_ui(self):
        lbl_opts = dict(font=("Consolas", 10), bg=BG, fg=FG, anchor="w")

        # --- Current session ---
        cur_frame = tk.LabelFrame(
            self, text=" Current Session ", font=("Consolas", 10, "bold"),
            bg=BG, fg="#8888CC", padx=10, pady=5,
        )
        cur_frame.pack(fill="x", padx=10, pady=5)

        row1 = tk.Frame(cur_frame, bg=BG)
        row1.pack(fill="x", pady=2)
        self._lbl_session = tk.Label(row1, text="Session: --", **lbl_opts)
        self._lbl_session.pack(side="left", padx=10)
        self._lbl_today = tk.Label(row1, text="Today: --", **lbl_opts)
        self._lbl_today.pack(side="left", padx=10)

        row2 = tk.Frame(cur_frame, bg=BG)
        row2.pack(fill="x", pady=2)
        self._lbl_actions = tk.Label(row2, text="Actions: 0", **lbl_opts)
        self._lbl_actions.pack(side="left", padx=10)
        self._lbl_errors = tk.Label(row2, text="Errors: 0", **lbl_opts)
        self._lbl_errors.pack(side="left", padx=10)

        row3 = tk.Frame(cur_frame, bg=BG)
        row3.pack(fill="x", pady=2)
        self._lbl_gathers = tk.Label(row3, text="Gathers: 0", **lbl_opts)
        self._lbl_gathers.pack(side="left", padx=10)
        self._lbl_trains = tk.Label(row3, text="Trains: 0", **lbl_opts)
        self._lbl_trains.pack(side="left", padx=10)

        # --- APM bar ---
        apm_frame = tk.LabelFrame(
            self, text=" Performance ", font=("Consolas", 10, "bold"),
            bg=BG, fg="#8888CC", padx=10, pady=5,
        )
        apm_frame.pack(fill="x", padx=10, pady=5)

        row = tk.Frame(apm_frame, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="APM:", font=("Consolas", 9), bg=BG, fg=FG).pack(side="left")
        self._apm_canvas = tk.Canvas(row, bg="#0d0d1a", height=16, highlightthickness=0)
        self._apm_canvas.pack(side="left", fill="x", expand=True, padx=5)
        self._lbl_apm = tk.Label(
            row, text="0.0", font=("Consolas", 9), bg=BG, fg=FG, width=6,
        )
        self._lbl_apm.pack(side="right")

        row = tk.Frame(apm_frame, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Err%:", font=("Consolas", 9), bg=BG, fg=FG).pack(side="left")
        self._err_canvas = tk.Canvas(row, bg="#0d0d1a", height=16, highlightthickness=0)
        self._err_canvas.pack(side="left", fill="x", expand=True, padx=5)
        self._lbl_err = tk.Label(
            row, text="0.0%", font=("Consolas", 9), bg=BG, fg=FG, width=6,
        )
        self._lbl_err.pack(side="right")

        # --- History chart ---
        hist_frame = tk.LabelFrame(
            self, text=" Session History (7 days) ", font=("Consolas", 10, "bold"),
            bg=BG, fg="#8888CC", padx=10, pady=5,
        )
        hist_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self._chart_canvas = tk.Canvas(hist_frame, bg="#0d0d1a", highlightthickness=0, height=120)
        self._chart_canvas.pack(fill="both", expand=True)

        # --- Export ---
        tk.Button(
            self, text="Export CSV", font=("Consolas", 10),
            bg=BTN_BG, fg=FG, bd=0, padx=20, pady=5,
            command=self._export_csv,
        ).pack(padx=10, pady=8)

    def update_display(self, stats: SessionStats):
        secs = stats.session_seconds
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        self._lbl_session.configure(text=f"Session: {h}h {m:02d}m" if h else f"Session: {m}m {s}s")
        self._lbl_today.configure(text=f"Today: {stats.today_hours:.1f}h")
        self._lbl_actions.configure(text=f"Actions: {stats.total_actions:,}")
        self._lbl_errors.configure(text=f"Errors: {stats.total_errors}")
        self._lbl_gathers.configure(text=f"Gathers: {stats.gathers}")
        self._lbl_trains.configure(text=f"Trains: {stats.trains}")

        apm = stats.apm
        self._lbl_apm.configure(text=f"{apm:.1f}")
        self._draw_bar(self._apm_canvas, apm / 20.0, "#4488FF")

        err_rate = (stats.total_errors / max(1, stats.total_actions)) * 100
        self._lbl_err.configure(text=f"{err_rate:.1f}%")
        self._draw_bar(self._err_canvas, err_rate / 10.0, "#FF4444")

        self._draw_history(stats)

    def _draw_bar(self, canvas: tk.Canvas, ratio: float, color: str):
        canvas.delete("all")
        w = canvas.winfo_width() or 200
        h = canvas.winfo_height() or 16
        fill_w = int(w * min(1.0, max(0.0, ratio)))
        if fill_w > 0:
            canvas.create_rectangle(0, 0, fill_w, h, fill=color, outline="")

    def _draw_history(self, stats: SessionStats):
        canvas = self._chart_canvas
        canvas.delete("all")
        w = canvas.winfo_width() or 400
        h = canvas.winfo_height() or 120

        summary = stats.daily_summary(7)
        if not summary:
            return

        max_hours = max((s[1] for s in summary), default=1.0)
        if max_hours < 0.1:
            max_hours = 1.0

        bar_w = w // 9
        padding = (w - bar_w * 7) // 2

        for i, (date, hours) in enumerate(summary):
            x = padding + i * bar_w + bar_w // 4
            bar_h = int((hours / max_hours) * (h - 30))
            y_top = h - 20 - bar_h

            color = "#4488FF" if bar_h > 0 else "#222244"
            canvas.create_rectangle(
                x, y_top, x + bar_w // 2, h - 20,
                fill=color, outline="#6688CC",
            )
            day_label = date[-5:]  # MM-DD
            canvas.create_text(
                x + bar_w // 4, h - 8, text=day_label,
                fill="#888899", font=("Consolas", 7),
            )
            if hours > 0:
                canvas.create_text(
                    x + bar_w // 4, y_top - 8, text=f"{hours:.1f}h",
                    fill="#AAAACC", font=("Consolas", 7),
                )

    def _export_csv(self):
        stats = self._app.stats
        history = stats.history
        if not history:
            self._app.log("No session history to export", "WARNING")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"rok_stats_{datetime.now():%Y%m%d}.csv",
        )
        if not path:
            return

        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=history[0].keys())
            writer.writeheader()
            writer.writerows(history)
        self._app.log(f"Stats exported to {path}", "SUCCESS")
