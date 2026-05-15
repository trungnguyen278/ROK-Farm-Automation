"""
Phase 6 — Real-Time Session Monitor
Console dashboard for monitoring a 30-min farm session.
Run: python -m tools.test_session_monitor [--port COM_PORT] [--duration MIN]

Features:
  - Live state tracking with transition log
  - Action counter with APM calculation
  - Serial health (ACK/NACK/timeout rates)
  - Anti-detection status (fatigue, break countdown, idle actions)
  - Memory usage tracking
  - Auto-screenshot on state changes
  - Summary report on exit
"""
import sys
import os
import time
import logging
import argparse
import threading
from pathlib import Path
from datetime import datetime
from queue import Empty

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psutil

from config import Config
from main import Orchestrator
from capture.screen_capture import ScreenCapture
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from vision.state_detector import StateDetector, GameScreen

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(
            LOG_DIR / f"session_{datetime.now():%Y%m%d_%H%M%S}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("session_monitor")

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


class SessionMonitor:
    def __init__(self, args):
        self.duration_min = args.duration
        self.port = args.port
        self.dry_run = args.port is None

        self.process = psutil.Process(os.getpid())
        self.start_time = 0.0

        self.state_history: list[tuple[float, str]] = []
        self.action_log: list[tuple[float, str]] = []
        self.current_state = "INIT"
        self.state_changes = 0
        self.total_actions = 0
        self.serial_sent = 0
        self.serial_ack = 0
        self.serial_fail = 0
        self.errors: list[str] = []
        self.idle_actions: dict[str, int] = {}
        self.break_count = 0

    def run(self):
        duration_s = self.duration_min * 60
        config = Config.load()

        clear_screen()
        print(f"{BOLD}  ROK Farm Session Monitor — Phase 6{RESET}")
        print(f"  Duration: {self.duration_min}min | Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"  Starting...\n")

        orchestrator = Orchestrator(config)

        sc = ScreenCapture()
        sc.find_window()
        orchestrator.set_screen_capture(sc)

        templates_dir = Path("templates")
        if templates_dir.exists():
            cache = TemplateCache(str(templates_dir))
            matcher = TemplateMatcher(cache)
            detector = StateDetector(matcher)
            orchestrator.set_state_detector(detector)

        serial_conn = None
        cmd_buffer = None
        if not self.dry_run:
            from serial_comm.connection import SerialConnection
            from serial_comm.command_buffer import CommandBuffer
            serial_conn = SerialConnection(port=self.port)
            if serial_conn.connect():
                cmd_buffer = CommandBuffer(serial_conn)
                cmd_buffer.start()
            else:
                self.dry_run = True

        orchestrator.start("basic_gather")
        self.start_time = time.monotonic()

        last_refresh = 0.0
        refresh_interval = 2.0

        try:
            while time.monotonic() - self.start_time < duration_s:
                now = time.monotonic()
                elapsed = now - self.start_time

                try:
                    while True:
                        state_val = orchestrator.state_queue.get_nowait()
                        if state_val != self.current_state:
                            self.state_changes += 1
                            self.state_history.append((elapsed, state_val))
                            self.current_state = state_val
                except Empty:
                    pass

                try:
                    while True:
                        action = orchestrator.action_queue.get_nowait()
                        self.total_actions += 1
                        self.action_log.append((elapsed, action["type"]))

                        idle = action.get("idle_action")
                        if idle:
                            self.idle_actions[idle] = self.idle_actions.get(idle, 0) + 1

                        if not self.dry_run and cmd_buffer:
                            params = action.get("params", {})
                            if "x" in params and "y" in params:
                                ok = cmd_buffer.send("MOVE", params["x"], params["y"], 300)
                                self.serial_sent += 1
                                if ok:
                                    self.serial_ack += 1
                                else:
                                    self.serial_fail += 1
                except Empty:
                    pass

                session = orchestrator.session
                if session:
                    ss = session.session_stats()
                    if ss["on_break"]:
                        self.break_count = max(self.break_count, 1)

                if now - last_refresh >= refresh_interval:
                    self._render_dashboard(elapsed, duration_s, orchestrator)
                    last_refresh = now

                time.sleep(0.5)

        except KeyboardInterrupt:
            pass
        except Exception as e:
            self.errors.append(str(e))
            logger.exception("Session error")

        orchestrator.stop()
        if cmd_buffer:
            cmd_buffer.stop()
        if serial_conn:
            serial_conn.disconnect()
        sc.close()

        clear_screen()
        self._print_final_report()

    def _render_dashboard(self, elapsed: float, total: float, orchestrator):
        clear_screen()
        pct = min(100, elapsed / total * 100)
        bar_len = 40
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        elapsed_str = self._fmt_time(elapsed)
        remaining_str = self._fmt_time(max(0, total - elapsed))

        print(f"{BOLD}  ╔══════════════════════════════════════════════════════════╗{RESET}")
        print(f"{BOLD}  ║  ROK Farm Session Monitor                               ║{RESET}")
        print(f"{BOLD}  ╚══════════════════════════════════════════════════════════╝{RESET}")
        print()
        print(f"  {DIM}Progress:{RESET}  [{bar}] {pct:.0f}%")
        print(f"  {DIM}Elapsed:{RESET}   {elapsed_str}  |  {DIM}Remaining:{RESET} {remaining_str}")
        print()

        state_color = GREEN if self.current_state not in ("unknown", "UNKNOWN", "ERROR") else RED
        print(f"  {BOLD}State:{RESET}     {state_color}{self.current_state}{RESET}  "
              f"({self.state_changes} changes)")

        apm = self.total_actions / max(1, elapsed / 60)
        print(f"  {BOLD}Actions:{RESET}   {self.total_actions}  ({apm:.1f} APM)")

        session = orchestrator.session
        if session:
            ss = session.session_stats()
            fatigue = 1.0 + 0.5 * min(ss["session_minutes"] / 60.0, 1.0)
            break_str = f"{YELLOW}ON BREAK{RESET}" if ss["on_break"] else f"{GREEN}farming{RESET}"
            print(f"  {BOLD}Session:{RESET}   {break_str}  |  "
                  f"fatigue={fatigue:.2f}x  |  "
                  f"farm_target={ss['current_farm_target_min']:.0f}min")
            print(f"  {BOLD}Daily:{RESET}     {ss['daily_active_hours']:.1f}h / {ss['daily_max_hours']}h")

        if not self.dry_run:
            total_serial = self.serial_sent
            rate = (self.serial_ack / total_serial * 100) if total_serial > 0 else 0
            serial_color = GREEN if rate >= 95 else (YELLOW if rate >= 80 else RED)
            print(f"  {BOLD}Serial:{RESET}    {total_serial} sent  "
                  f"{serial_color}{self.serial_ack} ACK{RESET}  "
                  f"{self.serial_fail} fail  ({rate:.0f}%)")

        mem = self.process.memory_info().rss / (1024 * 1024)
        cpu = self.process.cpu_percent(interval=0)
        threads = threading.active_count()
        print(f"  {BOLD}System:{RESET}    mem={mem:.0f}MB  cpu={cpu:.0f}%  threads={threads}")

        if self.idle_actions:
            idle_str = "  ".join(f"{k}:{v}" for k, v in self.idle_actions.items())
            print(f"  {BOLD}Idle:{RESET}      {idle_str}")

        print()
        if self.state_history:
            print(f"  {DIM}Recent state changes:{RESET}")
            for t, state in self.state_history[-5:]:
                print(f"    [{self._fmt_time(t)}] → {state}")

        if self.errors:
            print(f"\n  {RED}Errors ({len(self.errors)}):{RESET}")
            for err in self.errors[-3:]:
                print(f"    {RED}• {err}{RESET}")

        print(f"\n  {DIM}Press Ctrl+C to stop{RESET}")

    def _print_final_report(self):
        elapsed = time.monotonic() - self.start_time

        print(f"\n{BOLD}  ═══════════════════════════════════════{RESET}")
        print(f"{BOLD}  SESSION REPORT{RESET}")
        print(f"{BOLD}  ═══════════════════════════════════════{RESET}")
        print(f"  Duration: {self._fmt_time(elapsed)}")
        print(f"  Mode: {'DRY RUN' if self.dry_run else 'LIVE HID'}")

        print(f"\n  {BOLD}State Transitions ({self.state_changes}):{RESET}")
        state_counts: dict[str, int] = {}
        for _, state in self.state_history:
            state_counts[state] = state_counts.get(state, 0) + 1
        for state, count in sorted(state_counts.items(), key=lambda x: -x[1]):
            print(f"    {state:20s}: {count}")

        print(f"\n  {BOLD}Actions:{RESET}")
        print(f"    Total: {self.total_actions}")
        apm = self.total_actions / max(1, elapsed / 60)
        print(f"    APM: {apm:.1f}")

        action_counts: dict[str, int] = {}
        for _, atype in self.action_log:
            action_counts[atype] = action_counts.get(atype, 0) + 1
        for atype, count in sorted(action_counts.items(), key=lambda x: -x[1]):
            print(f"    {atype:20s}: {count}")

        if not self.dry_run:
            print(f"\n  {BOLD}Serial:{RESET}")
            print(f"    Sent: {self.serial_sent}")
            print(f"    ACK: {self.serial_ack}")
            print(f"    Fail: {self.serial_fail}")

        if self.idle_actions:
            print(f"\n  {BOLD}Idle Actions:{RESET}")
            for action, count in self.idle_actions.items():
                print(f"    {action}: {count}")

        print(f"\n  {BOLD}Errors:{RESET} {len(self.errors)}")
        for err in self.errors:
            print(f"    • {err}")

        no_errors = len(self.errors) == 0
        serial_ok = self.dry_run or self.serial_fail <= self.serial_sent * 0.05

        print()
        if no_errors and serial_ok:
            print(f"  [{PASS}] Session completed successfully")
        elif no_errors:
            print(f"  [{WARN}] Session completed with serial issues")
        else:
            print(f"  [{FAIL}] Session had errors")

        log_file = LOG_DIR / f"session_{datetime.now():%Y%m%d_%H%M%S}.log"
        print(f"\n  Log: {log_file}")
        print()

    @staticmethod
    def _fmt_time(seconds: float) -> str:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m:02d}:{s:02d}"


def main():
    parser = argparse.ArgumentParser(description="Session Monitor")
    parser.add_argument("--port", default=None, help="ESP32 COM port (omit for dry-run)")
    parser.add_argument("--duration", type=int, default=30, help="Duration in minutes")
    args = parser.parse_args()

    monitor = SessionMonitor(args)
    monitor.run()


if __name__ == "__main__":
    main()
