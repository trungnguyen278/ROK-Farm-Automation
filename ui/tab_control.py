from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app import MainApp

BG = "#16163a"
FG = "#CCCCCC"
BTN_BG = "#2a2a5e"
ENTRY_BG = "#1a1a3e"


def _load_strategies() -> list[str]:
    from logic.farm_strategies import FarmStrategy
    return FarmStrategy.available_strategies()


def _load_profiles() -> list[str]:
    profiles_dir = Path("profiles")
    if not profiles_dir.exists():
        return ["default"]
    found = [p.stem for p in sorted(profiles_dir.glob("*.json"))]
    if not found:
        return ["default"]
    if "default" in found:
        found.remove("default")
        found.insert(0, "default")
    return found


class ControlTab(tk.Frame):
    def __init__(self, parent: tk.Widget, app: MainApp, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._app = app
        self._running = False
        self._paused = False
        self._build_ui()

    def _build_ui(self):
        pad = dict(padx=10, pady=4)
        lbl_opts = dict(font=("Consolas", 10), bg=BG, fg=FG, anchor="w")

        # --- Game section ---
        game_frame = tk.LabelFrame(
            self, text=" Game ", font=("Consolas", 10, "bold"),
            bg=BG, fg="#8888CC", padx=10, pady=5,
        )
        game_frame.pack(fill="x", **pad)

        row = tk.Frame(game_frame, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Game:", **lbl_opts).pack(side="left")
        self._game_status = tk.Label(
            row, text="Not detected", font=("Consolas", 10),
            bg=BG, fg="#FF8844",
        )
        self._game_status.pack(side="left", padx=10)

        btn_row = tk.Frame(game_frame, bg=BG)
        btn_row.pack(fill="x", pady=2)
        self._btn_launch = tk.Button(
            btn_row, text="Launch", font=("Consolas", 9),
            bg=BTN_BG, fg=FG, bd=0, padx=12, pady=3,
            command=self._on_launch,
        )
        self._btn_launch.pack(side="left", padx=2)
        self._btn_detect = tk.Button(
            btn_row, text="Detect", font=("Consolas", 9),
            bg=BTN_BG, fg=FG, bd=0, padx=12, pady=3,
            command=self._on_detect,
        )
        self._btn_detect.pack(side="left", padx=2)

        # --- Strategy section ---
        strat_frame = tk.LabelFrame(
            self, text=" Strategy ", font=("Consolas", 10, "bold"),
            bg=BG, fg="#8888CC", padx=10, pady=5,
        )
        strat_frame.pack(fill="x", **pad)

        strategies = _load_strategies()
        profiles = _load_profiles()

        cfg = self._app.config
        default_strategy = cfg.logic.strategy if cfg else strategies[0]
        if default_strategy not in strategies:
            default_strategy = strategies[0]
        default_profile = cfg.anti_detection.profile if cfg else profiles[0]
        if default_profile not in profiles:
            default_profile = profiles[0]

        row = tk.Frame(strat_frame, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Strategy:", **lbl_opts).pack(side="left")
        self._strategy_var = tk.StringVar(value=default_strategy)
        self._strategy_combo = ttk.Combobox(
            row, textvariable=self._strategy_var,
            values=strategies, state="readonly", width=20,
        )
        self._strategy_combo.pack(side="left", padx=10)

        row = tk.Frame(strat_frame, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Profile:", **lbl_opts).pack(side="left")
        self._profile_var = tk.StringVar(value=default_profile)
        self._profile_combo = ttk.Combobox(
            row, textvariable=self._profile_var,
            values=profiles, state="readonly", width=20,
        )
        self._profile_combo.pack(side="left", padx=10)

        # --- Controls ---
        ctrl_frame = tk.LabelFrame(
            self, text=" Controls ", font=("Consolas", 10, "bold"),
            bg=BG, fg="#8888CC", padx=10, pady=5,
        )
        ctrl_frame.pack(fill="x", **pad)

        btn_row = tk.Frame(ctrl_frame, bg=BG)
        btn_row.pack(fill="x", pady=5)

        self._btn_start = tk.Button(
            btn_row, text="▶ START", font=("Consolas", 11, "bold"),
            bg="#225522", fg="#44FF44", bd=0, padx=20, pady=6,
            command=self._on_start,
        )
        self._btn_start.pack(side="left", padx=4)

        self._btn_pause = tk.Button(
            btn_row, text="⏸ PAUSE", font=("Consolas", 11, "bold"),
            bg="#555522", fg="#FFDD44", bd=0, padx=20, pady=6,
            command=self._on_pause, state="disabled",
        )
        self._btn_pause.pack(side="left", padx=4)

        self._btn_stop = tk.Button(
            btn_row, text="■ STOP", font=("Consolas", 11, "bold"),
            bg="#552222", fg="#FF4444", bd=0, padx=20, pady=6,
            command=self._on_stop, state="disabled",
        )
        self._btn_stop.pack(side="left", padx=4)

        # --- ESP32 section ---
        esp_frame = tk.LabelFrame(
            self, text=" ESP32 ", font=("Consolas", 10, "bold"),
            bg=BG, fg="#8888CC", padx=10, pady=5,
        )
        esp_frame.pack(fill="x", **pad)

        row = tk.Frame(esp_frame, bg=BG)
        row.pack(fill="x", pady=2)
        tk.Label(row, text="Port:", **lbl_opts).pack(side="left")
        self._port_var = tk.StringVar()
        self._port_combo = ttk.Combobox(
            row, textvariable=self._port_var, values=[], state="readonly", width=12,
        )
        self._port_combo.pack(side="left", padx=5)
        tk.Button(
            row, text="Scan", font=("Consolas", 8),
            bg=BTN_BG, fg=FG, bd=0, padx=8,
            command=self._on_scan_ports,
        ).pack(side="left", padx=2)

        self._esp_status = tk.Label(
            row, text="Disconnected ○", font=("Consolas", 10),
            bg=BG, fg="#FF4444",
        )
        self._esp_status.pack(side="left", padx=10)

        btn_row = tk.Frame(esp_frame, bg=BG)
        btn_row.pack(fill="x", pady=2)
        self._btn_connect = tk.Button(
            btn_row, text="Connect", font=("Consolas", 9),
            bg=BTN_BG, fg=FG, bd=0, padx=12, pady=3,
            command=self._on_connect,
        )
        self._btn_connect.pack(side="left", padx=2)
        self._btn_disconnect = tk.Button(
            btn_row, text="Disconnect", font=("Consolas", 9),
            bg=BTN_BG, fg=FG, bd=0, padx=12, pady=3,
            command=self._on_disconnect, state="disabled",
        )
        self._btn_disconnect.pack(side="left", padx=2)

    # --- Game callbacks ---

    def _on_launch(self):
        from .utils import launch_game
        self._app.log("Launching game...")
        if launch_game():
            self._app.log("Game launched", "SUCCESS")
        else:
            self._app.log("Failed to launch game", "ERROR")

    def _on_detect(self):
        from .utils import find_game_window
        win = find_game_window()
        if win:
            self._game_status.configure(text="Running", fg="#44FF44")
            self._app.log(f"Game window found: {win['width']}x{win['height']}")
            self._app.status_bar.set_game(True)
        else:
            self._game_status.configure(text="Not detected", fg="#FF8844")
            self._app.log("Game window not found", "WARNING")
            self._app.status_bar.set_game(False)

    # --- Strategy callbacks ---

    def _on_start(self):
        self._running = True
        self._paused = False
        self._btn_start.configure(state="disabled")
        self._btn_pause.configure(state="normal")
        self._btn_stop.configure(state="normal")
        strategy = self._strategy_var.get()
        profile = self._profile_var.get()
        self._app.log(f"Started: strategy={strategy}, profile={profile}", "SUCCESS")
        self._app.status_bar.set_state("RUNNING")
        self._app.on_start(strategy, profile)

    def _on_pause(self):
        self._paused = not self._paused
        if self._paused:
            self._btn_pause.configure(text="▶ RESUME")
            self._app.log("Paused")
            self._app.status_bar.set_state("PAUSED")
            self._app.on_pause()
        else:
            self._btn_pause.configure(text="⏸ PAUSE")
            self._app.log("Resumed")
            self._app.status_bar.set_state("RUNNING")
            self._app.on_resume()

    def _on_stop(self):
        self._running = False
        self._paused = False
        self._btn_start.configure(state="normal")
        self._btn_pause.configure(state="disabled", text="⏸ PAUSE")
        self._btn_stop.configure(state="disabled")
        self._app.log("Stopped")
        self._app.status_bar.set_state("IDLE")
        self._app.on_stop()

    # --- ESP32 callbacks ---

    def _on_scan_ports(self):
        from .utils import list_serial_ports
        ports = list_serial_ports()
        self._port_combo.configure(values=ports)
        if ports:
            self._port_var.set(ports[0])
            self._app.log(f"Found ports: {', '.join(ports)}")
        else:
            self._port_var.set("")
            self._app.log("No serial ports found", "WARNING")

    def _on_connect(self):
        port = self._port_var.get()
        if not port:
            self._app.log("Select a port first", "WARNING")
            return
        self._app.log(f"Connecting to {port}...")
        self._btn_connect.configure(state="disabled")
        self._app.connect_esp32(port, self._on_connect_result)

    def _on_connect_result(self, success: bool, port: str):
        if success:
            self._esp_status.configure(text=f"Connected ●", fg="#44FF44")
            self._btn_connect.configure(state="disabled")
            self._btn_disconnect.configure(state="normal")
            self._app.log(f"Connected to {port}", "SUCCESS")
            self._app.status_bar.set_esp32(port, True)
        else:
            self._esp_status.configure(text="Failed ○", fg="#FF4444")
            self._btn_connect.configure(state="normal")
            self._app.log(f"Connection to {port} failed", "ERROR")
            self._app.status_bar.set_esp32(port, False)

    def _on_disconnect(self):
        self._app.disconnect_esp32()
        self._esp_status.configure(text="Disconnected ○", fg="#FF4444")
        self._btn_connect.configure(state="normal")
        self._btn_disconnect.configure(state="disabled")
        self._app.status_bar.set_esp32(None, False)
        self._app.log("ESP32 disconnected")

    def update_esp32_status(self, port: str | None, connected: bool):
        if connected and port:
            self._esp_status.configure(text=f"Connected ●", fg="#44FF44")
            self._btn_connect.configure(state="disabled")
            self._btn_disconnect.configure(state="normal")
        else:
            self._esp_status.configure(text="Disconnected ○", fg="#FF4444")
            self._btn_connect.configure(state="normal")
            self._btn_disconnect.configure(state="disabled")

    def update_game_status(self, detected: bool):
        if detected:
            self._game_status.configure(text="Running", fg="#44FF44")
        else:
            self._game_status.configure(text="Not detected", fg="#FF8844")

    def update_logic_info(self, state: str, pending_tasks: int):
        pass
