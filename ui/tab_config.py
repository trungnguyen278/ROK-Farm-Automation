from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from .app import MainApp

BG = "#16163a"
FG = "#CCCCCC"
BTN_BG = "#2a2a5e"
ENTRY_BG = "#1a1a3e"

CONFIG_PATH = Path("config.yaml")


class ConfigTab(tk.Frame):
    def __init__(self, parent: tk.Widget, app: MainApp, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._app = app
        self._fields: dict[str, tk.Variable] = {}
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self._inner = tk.Frame(canvas, bg=BG)
        self._inner.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=self._inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)

        self._add_section("Serial")
        self._add_field("serial.port", "Port", "COM3", width=12)
        self._add_field("serial.baud", "Baud", "115200", width=12)
        self._add_field("serial.heartbeat_interval", "Heartbeat (s)", "2.0", width=8)
        self._add_field("serial.ack_timeout", "ACK Timeout (s)", "0.5", width=8)

        self._add_section("Capture")
        self._add_field("capture.window_title", "Window Title", "Rise of Kingdoms", width=25)
        self._add_field("capture.fps", "FPS", "5", width=6)

        self._add_section("Vision")
        self._add_field("vision.match_threshold", "Threshold", "0.8", width=8)
        self._add_field("vision.scales", "Scales", "0.8,0.9,1.0,1.1,1.2", width=25)
        self._add_field("vision.cache_max_size", "Cache Size", "100", width=8)

        self._add_section("Session")
        self._add_field("session.farm_mean", "Farm (min)", "25", width=6)
        self._add_field("session.farm_std", "Farm ± (min)", "8", width=6)
        self._add_field("session.break_mean", "Break (min)", "8", width=6)
        self._add_field("session.break_std", "Break ± (min)", "3", width=6)
        self._add_field("session.daily_hours_max", "Daily Max (hrs)", "6", width=6)
        self._add_field("session.active_start", "Active Start", "08:00", width=8)
        self._add_field("session.active_end", "Active End", "23:00", width=8)

        btn_row = tk.Frame(self._inner, bg=BG)
        btn_row.pack(fill="x", padx=10, pady=10)
        tk.Button(
            btn_row, text="Save", font=("Consolas", 10, "bold"),
            bg="#225522", fg="#44FF44", bd=0, padx=20, pady=5,
            command=self._save_config,
        ).pack(side="left", padx=4)
        tk.Button(
            btn_row, text="Reset Default", font=("Consolas", 10),
            bg=BTN_BG, fg=FG, bd=0, padx=20, pady=5,
            command=self._reset_defaults,
        ).pack(side="left", padx=4)

    def _add_section(self, title: str):
        frame = tk.LabelFrame(
            self._inner, text=f" {title} ", font=("Consolas", 10, "bold"),
            bg=BG, fg="#8888CC", padx=10, pady=5,
        )
        frame.pack(fill="x", padx=10, pady=5)
        self._current_section = frame

    def _add_field(self, key: str, label: str, default: str, width: int = 15):
        row = tk.Frame(self._current_section, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(
            row, text=f"{label}:", font=("Consolas", 9),
            bg=BG, fg=FG, width=16, anchor="w",
        ).pack(side="left")
        var = tk.StringVar(value=default)
        tk.Entry(
            row, textvariable=var, font=("Consolas", 9),
            bg=ENTRY_BG, fg=FG, insertbackground=FG,
            bd=1, relief="flat", width=width,
        ).pack(side="left", padx=4)
        self._fields[key] = var

    def _load_config(self):
        if not CONFIG_PATH.exists():
            return
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            return

        mapping = {
            "serial.port": ("serial", "port"),
            "serial.baud": ("serial", "baud"),
            "serial.heartbeat_interval": ("serial", "heartbeat_interval"),
            "serial.ack_timeout": ("serial", "ack_timeout"),
            "capture.window_title": ("capture", "window_title"),
            "capture.fps": ("capture", "fps"),
            "vision.match_threshold": ("vision", "match_threshold"),
            "vision.scales": ("vision", "scales"),
            "vision.cache_max_size": ("vision", "cache_max_size"),
            "session.farm_mean": ("session", "farm_duration", "mean"),
            "session.farm_std": ("session", "farm_duration", "std"),
            "session.break_mean": ("session", "break_duration", "mean"),
            "session.break_std": ("session", "break_duration", "std"),
            "session.daily_hours_max": ("session", "daily_hours_max"),
            "session.active_start": ("session", "active_window", 0),
            "session.active_end": ("session", "active_window", 1),
        }

        for key, path in mapping.items():
            val = cfg
            try:
                for p in path:
                    val = val[p]
                if isinstance(val, list):
                    val = ",".join(str(v) for v in val)
                if key in self._fields:
                    self._fields[key].set(str(val))
            except (KeyError, IndexError, TypeError):
                pass

    def _to_config_dict(self) -> dict:
        def get(key: str) -> str:
            return self._fields[key].get()

        scales_str = get("vision.scales")
        scales = [float(s.strip()) for s in scales_str.split(",")]

        return {
            "serial": {
                "port": get("serial.port"),
                "baud": int(get("serial.baud")),
                "timeout": 0.5,
                "heartbeat_interval": float(get("serial.heartbeat_interval")),
                "heartbeat_timeout": 5.0,
                "max_retries": 3,
                "ack_timeout": float(get("serial.ack_timeout")),
            },
            "capture": {
                "window_title": get("capture.window_title"),
                "fps": int(get("capture.fps")),
                "roi": {
                    "top_bar": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.05},
                    "center": {"x": 0.1, "y": 0.15, "w": 0.8, "h": 0.55},
                    "bottom_bar": {"x": 0.0, "y": 0.9, "w": 1.0, "h": 0.1},
                    "popup": {"x": 0.25, "y": 0.2, "w": 0.5, "h": 0.5},
                    "minimap": {"x": 0.8, "y": 0.75, "w": 0.2, "h": 0.25},
                },
            },
            "vision": {
                "template_dir": "templates/",
                "match_threshold": float(get("vision.match_threshold")),
                "scales": scales,
                "cache_max_size": int(get("vision.cache_max_size")),
            },
            "logic": {
                "strategy": "basic_gather",
                "decision_rate": 10,
                "unknown_state_timeout": 5.0,
                "max_task_queue": 50,
            },
            "anti_detection": {
                "profile": "default",
                "profile_dir": "profiles/",
            },
            "session": {
                "enabled": True,
                "farm_duration": {
                    "mean": int(get("session.farm_mean")),
                    "std": int(get("session.farm_std")),
                },
                "break_duration": {
                    "mean": int(get("session.break_mean")),
                    "std": int(get("session.break_std")),
                },
                "daily_hours_max": int(get("session.daily_hours_max")),
                "active_window": [get("session.active_start"), get("session.active_end")],
            },
            "logging": {
                "level": "INFO",
                "file": "logs/rok_automation.log",
                "max_size_mb": 10,
                "backup_count": 5,
            },
        }

    def _save_config(self):
        try:
            cfg = self._to_config_dict()
            with open(CONFIG_PATH, "w") as f:
                yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)
            self._app.log("Config saved to config.yaml", "SUCCESS")
        except Exception as e:
            self._app.log(f"Failed to save config: {e}", "ERROR")

    def _reset_defaults(self):
        defaults = {
            "serial.port": "COM3",
            "serial.baud": "115200",
            "serial.heartbeat_interval": "2.0",
            "serial.ack_timeout": "0.5",
            "capture.window_title": "Rise of Kingdoms",
            "capture.fps": "5",
            "vision.match_threshold": "0.8",
            "vision.scales": "0.8,0.9,1.0,1.1,1.2",
            "vision.cache_max_size": "100",
            "session.farm_mean": "25",
            "session.farm_std": "8",
            "session.break_mean": "8",
            "session.break_std": "3",
            "session.daily_hours_max": "6",
            "session.active_start": "08:00",
            "session.active_end": "23:00",
        }
        for key, val in defaults.items():
            if key in self._fields:
                self._fields[key].set(val)
        self._app.log("Config reset to defaults")
