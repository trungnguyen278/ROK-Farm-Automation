from __future__ import annotations

import logging
import threading
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from typing import TYPE_CHECKING

from .log_panel import LogPanel, QueueHandler
from .status_bar import StatusBar
from .tab_control import ControlTab
from .tab_monitor import MonitorTab
from .tab_config import ConfigTab
from .tab_profile import ProfileTab
from .tab_stats import StatsTab, SessionStats
from .utils import find_game_window

if TYPE_CHECKING:
    from config import Config

logger = logging.getLogger(__name__)

BG = "#12122a"
TAB_BG = "#16163a"
FG = "#CCCCCC"

UI_POLL_MS = 200
STATUS_POLL_MS = 2000
STATE_POLL_MS = 500


class MainApp(tk.Tk):
    def __init__(self, config: Config | None = None):
        super().__init__()
        self.title("ROK Farm Automation")
        self.configure(bg=BG)
        self.geometry("950x650")
        self.minsize(800, 500)

        self.config = config
        self._serial_conn = None
        self._cmd_buffer = None
        self.screen_capture = None
        self.template_matcher = None
        self.state_detector = None
        self.stats = SessionStats()
        self._orchestrator = None

        self._session_start_time: float | None = None
        self._running = threading.Event()
        self._paused = threading.Event()

        self._setup_style()
        self._build_ui()
        self._setup_logging()
        self._init_vision()
        self._position_window()
        self._start_polling()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.log("ROK Farm Automation started", "SUCCESS")

    # --- UI construction ---

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            background="#1a1a3e", foreground=FG,
            padding=[12, 4], font=("Consolas", 10),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#2a2a5e")],
            foreground=[("selected", "#FFFFFF")],
        )
        style.configure("TCombobox", fieldbackground="#1a1a3e", foreground=FG)

    def _build_ui(self):
        main_pane = tk.PanedWindow(
            self, orient="horizontal", bg=BG,
            sashwidth=4, sashrelief="flat",
        )
        main_pane.pack(fill="both", expand=True)

        left_frame = tk.Frame(main_pane, bg=BG)
        main_pane.add(left_frame, stretch="always")

        self._notebook = ttk.Notebook(left_frame)
        self._notebook.pack(fill="both", expand=True)

        self.tab_control = ControlTab(self._notebook, self)
        self.tab_monitor = MonitorTab(self._notebook, self)
        self.tab_config = ConfigTab(self._notebook, self)
        self.tab_profile = ProfileTab(self._notebook, self)
        self.tab_stats = StatsTab(self._notebook, self)

        self._notebook.add(self.tab_control, text="Control")
        self._notebook.add(self.tab_monitor, text="Monitor")
        self._notebook.add(self.tab_config, text="Config")
        self._notebook.add(self.tab_profile, text="Profile")
        self._notebook.add(self.tab_stats, text="Stats")

        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.status_bar = StatusBar(left_frame)
        self.status_bar.pack(fill="x", side="bottom")

        right_frame = tk.Frame(main_pane, bg=BG, width=280)
        main_pane.add(right_frame, stretch="never")

        self.log_panel = LogPanel(right_frame)
        self.log_panel.pack(fill="both", expand=True)

    def _setup_logging(self):
        handler = QueueHandler(self.log_panel)
        handler.setFormatter(logging.Formatter("%(name)s: %(message)s"))
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        if not root_logger.handlers or root_logger.level == logging.WARNING:
            root_logger.setLevel(logging.INFO)

    def _init_vision(self):
        try:
            from capture.screen_capture import ScreenCapture
            self.screen_capture = ScreenCapture()
        except ImportError:
            logger.warning("capture module not available")

        try:
            from vision.template_cache import TemplateCache
            from vision.template_matcher import TemplateMatcher
            from vision.state_detector import StateDetector

            templates_dir = Path("templates")
            if templates_dir.exists():
                cache = TemplateCache(str(templates_dir))
                matcher = TemplateMatcher(cache)
                self.template_matcher = matcher
                self.state_detector = StateDetector(matcher)
        except ImportError:
            logger.warning("vision module not available")

    def _position_window(self):
        win = find_game_window()
        if win:
            x = win["left"] + win["width"] + 10
            y = win["top"]
            self.geometry(f"+{x}+{y}")
            self.status_bar.set_game(True)
            self.tab_control.update_game_status(True)
        else:
            self.status_bar.set_game(False)

    def _start_polling(self):
        self._poll_ui()
        self._poll_status()
        self._poll_state()

    def _poll_ui(self):
        self.log_panel.poll()
        self.after(UI_POLL_MS, self._poll_ui)

    def _poll_status(self):
        if self._session_start_time:
            elapsed = int(time.monotonic() - self._session_start_time)
            self.status_bar.set_session_time(elapsed)
            self.status_bar.set_apm(self.stats.apm)
            self.tab_stats.update_display(self.stats)

        if self._serial_conn and self._serial_conn.is_connected:
            self.status_bar.set_esp32(self._serial_conn._port, True)
        elif self._serial_conn:
            self.status_bar.set_esp32(self._serial_conn._port, False)

        self.after(STATUS_POLL_MS, self._poll_status)

    def _poll_state(self):
        if self._orchestrator:
            try:
                from queue import Empty
                while True:
                    state_val = self._orchestrator.state_queue.get_nowait()
                    self.status_bar.set_state(state_val.upper())
            except (Empty, Exception):
                pass

            sm = self._orchestrator.state_machine
            sched = self._orchestrator.scheduler
            if sm and sched:
                self.tab_control.update_logic_info(
                    state=sm.state.value,
                    pending_tasks=sched.pending_count,
                )

        self.after(STATE_POLL_MS, self._poll_state)

    def _on_tab_changed(self, event):
        tab_id = self._notebook.select()
        tab_name = self._notebook.tab(tab_id, "text")
        if tab_name == "Monitor":
            self.tab_monitor.on_tab_selected()
        else:
            self.tab_monitor.on_tab_deselected()

    # --- Public API for tabs ---

    def log(self, msg: str, level: str = "INFO"):
        self.log_panel.log(msg, level)

    def connect_esp32(self, port: str, callback):
        def _worker():
            from serial_comm.connection import SerialConnection
            conn = SerialConnection(port=port)
            success = conn.connect()
            if success:
                self._serial_conn = conn
                from serial_comm.command_buffer import CommandBuffer
                self._cmd_buffer = CommandBuffer(conn)
                self._cmd_buffer.start()
            self.after(0, callback, success, port)

        threading.Thread(target=_worker, daemon=True).start()

    def disconnect_esp32(self):
        if self._cmd_buffer:
            self._cmd_buffer.stop()
            self._cmd_buffer = None
        if self._serial_conn:
            self._serial_conn.disconnect()
            self._serial_conn = None

    def on_start(self, strategy: str, profile: str):
        from main import Orchestrator
        cfg = self.config
        if cfg is None:
            from config import Config
            cfg = Config.load()

        self._orchestrator = Orchestrator(cfg)

        if self.screen_capture:
            self._orchestrator.set_screen_capture(self.screen_capture)
        if self.state_detector:
            self._orchestrator.set_state_detector(self.state_detector)
        if self._cmd_buffer:
            self._orchestrator.set_command_buffer(self._cmd_buffer)
        if self.template_matcher:
            self._orchestrator.set_template_matcher(self.template_matcher)

        self._orchestrator.start(strategy)
        self._running.set()
        self._paused.clear()
        self._session_start_time = time.monotonic()
        self.stats.start_session()
        self.log(f"Session started: {strategy}/{profile}")

    def on_pause(self):
        self._paused.set()
        if self._orchestrator:
            self._orchestrator.pause()

    def on_resume(self):
        self._paused.clear()
        if self._orchestrator:
            self._orchestrator.resume()

    def on_stop(self):
        self._running.clear()
        self._paused.clear()
        if self._orchestrator:
            self._orchestrator.stop()
            self._orchestrator = None
        self._session_start_time = None
        self.stats.end_session()
        self.status_bar.set_session_time(0)
        self.status_bar.set_apm(0.0)
        self.status_bar.set_state("IDLE")

    def _on_close(self):
        self.log("Shutting down...")
        self._running.clear()
        if self._orchestrator:
            self._orchestrator.stop()
            self._orchestrator = None
        if self.stats.session_start:
            self.stats.end_session()
        self.disconnect_esp32()
        if self.screen_capture:
            self.screen_capture.close()
        self.destroy()


def run(config=None):
    app = MainApp(config)
    app.mainloop()
