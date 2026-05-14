from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import MainApp

BG = "#16163a"
FG = "#CCCCCC"
BTN_BG = "#2a2a5e"
ENTRY_BG = "#1a1a3e"

PROFILES_DIR = Path("profiles")

DEFAULT_PROFILE = {
    "mouse": {
        "speed": 400,
        "spread": 8,
        "overshoot_pct": 15,
        "misclick_pct": 1,
        "jitter_px": 2,
    },
    "timing": {
        "delay_ms": 1200,
        "delay_std_ms": 400,
        "micro_pause_pct": 20,
        "fatigue_enabled": True,
    },
}


class ProfileTab(tk.Frame):
    def __init__(self, parent: tk.Widget, app: MainApp, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._app = app
        self._fields: dict[str, tk.Variable] = {}
        self._build_ui()
        self._refresh_profiles()

    def _build_ui(self):
        # --- Profile selector ---
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=10, pady=5)

        tk.Label(
            top, text="Active:", font=("Consolas", 10),
            bg=BG, fg=FG,
        ).pack(side="left")

        self._profile_var = tk.StringVar(value="default")
        self._profile_combo = ttk.Combobox(
            top, textvariable=self._profile_var,
            values=[], state="readonly", width=15,
        )
        self._profile_combo.pack(side="left", padx=5)
        self._profile_combo.bind("<<ComboboxSelected>>", lambda _: self._load_profile())

        tk.Button(
            top, text="New", font=("Consolas", 9),
            bg=BTN_BG, fg=FG, bd=0, padx=10,
            command=self._on_new,
        ).pack(side="left", padx=2)
        tk.Button(
            top, text="Delete", font=("Consolas", 9),
            bg="#552222", fg="#FF4444", bd=0, padx=10,
            command=self._on_delete,
        ).pack(side="left", padx=2)

        # --- Mouse section ---
        mouse_frame = tk.LabelFrame(
            self, text=" Mouse ", font=("Consolas", 10, "bold"),
            bg=BG, fg="#8888CC", padx=10, pady=5,
        )
        mouse_frame.pack(fill="x", padx=10, pady=5)
        self._mouse_section = mouse_frame

        self._add_field(mouse_frame, "mouse.speed", "Speed", "400", width=8)
        self._add_field(mouse_frame, "mouse.spread", "Spread (px)", "8", width=8)
        self._add_field(mouse_frame, "mouse.overshoot_pct", "Overshoot %", "15", width=8)
        self._add_field(mouse_frame, "mouse.misclick_pct", "Misclick %", "1", width=8)
        self._add_field(mouse_frame, "mouse.jitter_px", "Jitter (px)", "2", width=8)

        # --- Timing section ---
        timing_frame = tk.LabelFrame(
            self, text=" Timing ", font=("Consolas", 10, "bold"),
            bg=BG, fg="#8888CC", padx=10, pady=5,
        )
        timing_frame.pack(fill="x", padx=10, pady=5)

        self._add_field(timing_frame, "timing.delay_ms", "Delay (ms)", "1200", width=8)
        self._add_field(timing_frame, "timing.delay_std_ms", "Std (ms)", "400", width=8)
        self._add_field(timing_frame, "timing.micro_pause_pct", "Pause %", "20", width=8)

        fatigue_row = tk.Frame(timing_frame, bg=BG)
        fatigue_row.pack(fill="x", pady=2)
        tk.Label(
            fatigue_row, text="Fatigue:", font=("Consolas", 9),
            bg=BG, fg=FG, width=16, anchor="w",
        ).pack(side="left")
        self._fatigue_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            fatigue_row, variable=self._fatigue_var,
            bg=BG, fg=FG, selectcolor=ENTRY_BG,
            activebackground=BG, activeforeground=FG,
        ).pack(side="left")
        self._fields["timing.fatigue_enabled"] = self._fatigue_var

        # --- Save button ---
        tk.Button(
            self, text="Save Profile", font=("Consolas", 10, "bold"),
            bg="#225522", fg="#44FF44", bd=0, padx=20, pady=5,
            command=self._save_profile,
        ).pack(padx=10, pady=10)

    def _add_field(self, parent: tk.Widget, key: str, label: str, default: str, width: int = 15):
        row = tk.Frame(parent, bg=BG)
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

    def _refresh_profiles(self):
        PROFILES_DIR.mkdir(exist_ok=True)
        profiles = [p.stem for p in PROFILES_DIR.glob("*.json")]
        if not profiles:
            self._save_default_profile()
            profiles = ["default"]
        self._profile_combo.configure(values=profiles)
        if self._profile_var.get() not in profiles:
            self._profile_var.set(profiles[0])
        self._load_profile()

    def _save_default_profile(self):
        PROFILES_DIR.mkdir(exist_ok=True)
        with open(PROFILES_DIR / "default.json", "w") as f:
            json.dump(DEFAULT_PROFILE, f, indent=2)

    def _load_profile(self):
        name = self._profile_var.get()
        path = PROFILES_DIR / f"{name}.json"
        if not path.exists():
            return

        try:
            with open(path, "r") as f:
                data = json.load(f)
        except Exception:
            return

        field_map = {
            "mouse.speed": ("mouse", "speed"),
            "mouse.spread": ("mouse", "spread"),
            "mouse.overshoot_pct": ("mouse", "overshoot_pct"),
            "mouse.misclick_pct": ("mouse", "misclick_pct"),
            "mouse.jitter_px": ("mouse", "jitter_px"),
            "timing.delay_ms": ("timing", "delay_ms"),
            "timing.delay_std_ms": ("timing", "delay_std_ms"),
            "timing.micro_pause_pct": ("timing", "micro_pause_pct"),
        }

        for key, path_keys in field_map.items():
            val = data
            try:
                for k in path_keys:
                    val = val[k]
                if key in self._fields:
                    self._fields[key].set(str(val))
            except (KeyError, TypeError):
                pass

        fatigue = data.get("timing", {}).get("fatigue_enabled", True)
        self._fatigue_var.set(fatigue)

    def _to_profile_dict(self) -> dict:
        def get_int(key: str) -> int:
            return int(self._fields[key].get())

        return {
            "mouse": {
                "speed": get_int("mouse.speed"),
                "spread": get_int("mouse.spread"),
                "overshoot_pct": get_int("mouse.overshoot_pct"),
                "misclick_pct": get_int("mouse.misclick_pct"),
                "jitter_px": get_int("mouse.jitter_px"),
            },
            "timing": {
                "delay_ms": get_int("timing.delay_ms"),
                "delay_std_ms": get_int("timing.delay_std_ms"),
                "micro_pause_pct": get_int("timing.micro_pause_pct"),
                "fatigue_enabled": self._fatigue_var.get(),
            },
        }

    def _save_profile(self):
        name = self._profile_var.get()
        if not name:
            return
        try:
            data = self._to_profile_dict()
            PROFILES_DIR.mkdir(exist_ok=True)
            with open(PROFILES_DIR / f"{name}.json", "w") as f:
                json.dump(data, f, indent=2)
            self._app.log(f"Profile '{name}' saved", "SUCCESS")
        except Exception as e:
            self._app.log(f"Failed to save profile: {e}", "ERROR")

    def _on_new(self):
        name = simpledialog.askstring("New Profile", "Profile name:", parent=self)
        if not name:
            return
        name = name.strip().lower().replace(" ", "_")
        path = PROFILES_DIR / f"{name}.json"
        if path.exists():
            self._app.log(f"Profile '{name}' already exists", "WARNING")
            return
        with open(path, "w") as f:
            json.dump(DEFAULT_PROFILE, f, indent=2)
        self._refresh_profiles()
        self._profile_var.set(name)
        self._load_profile()
        self._app.log(f"Profile '{name}' created")

    def _on_delete(self):
        name = self._profile_var.get()
        if name == "default":
            self._app.log("Cannot delete default profile", "WARNING")
            return
        if not messagebox.askyesno("Delete Profile", f"Delete '{name}'?"):
            return
        path = PROFILES_DIR / f"{name}.json"
        if path.exists():
            path.unlink()
        self._refresh_profiles()
        self._app.log(f"Profile '{name}' deleted")
