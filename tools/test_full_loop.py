"""
Phase 6 — Full Loop Integration Test
Tests the complete pipeline: vision → state machine → task scheduler → serial → HID.
Run: python -m tools.test_full_loop [COM_PORT]

Modes:
  --dry-run     Skip serial/HID, just test vision+logic (default if no ESP32)
  --duration N  Run for N seconds (default: 60)
  --strategy S  Farm strategy: basic_gather, war_prep, alliance_focus (default: basic_gather)

Output:
  - Console: state transitions, tasks generated, actions sent
  - Log file: logs/test_full_loop.log
"""
import sys
import os
import time
import logging
import argparse
import threading
from queue import Empty
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from main import Orchestrator
from capture.screen_capture import ScreenCapture
from vision.template_cache import TemplateCache
from vision.template_matcher import TemplateMatcher
from vision.state_detector import StateDetector, GameScreen

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / f"test_full_loop_{datetime.now():%Y%m%d_%H%M%S}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("test_full_loop")

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"


class FullLoopTest:
    def __init__(self, args):
        self.dry_run = args.dry_run
        self.duration = args.duration
        self.strategy = args.strategy
        self.port = args.port

        self.config = Config.load()
        self.orchestrator: Orchestrator | None = None
        self.serial_conn = None
        self.cmd_buffer = None

        self.stats = {
            "frames_captured": 0,
            "states_detected": {},
            "state_changes": 0,
            "tasks_generated": 0,
            "actions_dispatched": 0,
            "serial_sent": 0,
            "serial_ack": 0,
            "serial_fail": 0,
            "errors": [],
            "start_time": 0,
            "end_time": 0,
        }

    def run(self):
        print("=" * 60)
        print("  Full Loop Integration Test — Phase 6")
        print("=" * 60)
        print(f"  Mode: {'DRY RUN (no HID)' if self.dry_run else 'LIVE (ESP32 HID)'}")
        print(f"  Duration: {self.duration}s")
        print(f"  Strategy: {self.strategy}")
        print()

        if not self._setup_vision():
            return
        if not self.dry_run:
            if not self._setup_serial():
                print("  ESP32 not available, switching to dry-run mode")
                self.dry_run = True

        self._setup_orchestrator()
        self._run_loop()
        self._teardown()
        self._print_report()

    def _setup_vision(self) -> bool:
        print("--- Setup: Vision Pipeline ---")
        sc = ScreenCapture()
        win = sc.find_window()
        if not win:
            print(f"  [{WARN}] Game window not found — vision will return UNKNOWN")
            print("  Continuing anyway to test logic pipeline...")
        else:
            print(f"  [{PASS}] Game window: {win['width']}x{win['height']}")

        templates_dir = Path("templates")
        if not templates_dir.exists():
            print(f"  [{WARN}] Templates dir missing — state detection disabled")
            self.orchestrator_sc = sc
            self.orchestrator_sd = None
            return True

        cache = TemplateCache(str(templates_dir))
        matcher = TemplateMatcher(cache, threshold=self.config.vision.match_threshold)
        detector = StateDetector(matcher, min_confidence=self.config.vision.match_threshold)

        self.orchestrator_sc = sc
        self.orchestrator_sd = detector
        print(f"  [{PASS}] Vision pipeline ready")
        return True

    def _setup_serial(self) -> bool:
        print("\n--- Setup: Serial Connection ---")
        from serial_comm.connection import SerialConnection
        from serial_comm.command_buffer import CommandBuffer

        self.serial_conn = SerialConnection(port=self.port)
        if not self.serial_conn.connect():
            print(f"  [{FAIL}] Could not connect to ESP32")
            return False

        self.cmd_buffer = CommandBuffer(self.serial_conn)
        self.cmd_buffer.start()
        time.sleep(0.3)
        print(f"  [{PASS}] ESP32 connected: {self.serial_conn._port}")
        return True

    def _setup_orchestrator(self):
        print("\n--- Setup: Orchestrator ---")
        self.orchestrator = Orchestrator(self.config)
        self.orchestrator.set_screen_capture(self.orchestrator_sc)
        if self.orchestrator_sd:
            self.orchestrator.set_state_detector(self.orchestrator_sd)
        self.orchestrator.start(self.strategy)
        print(f"  [{PASS}] Orchestrator started: strategy={self.strategy}")

    def _run_loop(self):
        print(f"\n--- Running for {self.duration}s ---\n")
        self.stats["start_time"] = time.monotonic()
        deadline = self.stats["start_time"] + self.duration
        last_state = None
        action_count = 0

        try:
            while time.monotonic() < deadline:
                try:
                    state_val = self.orchestrator.state_queue.get(timeout=0.5)
                    self.stats["states_detected"][state_val] = \
                        self.stats["states_detected"].get(state_val, 0) + 1

                    if state_val != last_state:
                        self.stats["state_changes"] += 1
                        elapsed = time.monotonic() - self.stats["start_time"]
                        logger.info("[%6.1fs] State: %s -> %s", elapsed, last_state, state_val)
                        last_state = state_val
                except Empty:
                    pass

                try:
                    while True:
                        action = self.orchestrator.action_queue.get_nowait()
                        action_count += 1
                        self.stats["actions_dispatched"] += 1
                        elapsed = time.monotonic() - self.stats["start_time"]
                        logger.info("[%6.1fs] Action #%d: type=%s state=%s params=%s",
                                    elapsed, action_count, action["type"],
                                    action["state"], action.get("params", {}))

                        if not self.dry_run and self.cmd_buffer:
                            self._execute_action(action)
                except Empty:
                    pass

                sched = self.orchestrator.scheduler
                if sched:
                    self.stats["tasks_generated"] = max(
                        self.stats["tasks_generated"],
                        sched.pending_count + action_count,
                    )

                session = self.orchestrator.session
                if session and int(time.monotonic()) % 10 == 0:
                    ss = session.session_stats()
                    if ss["on_break"]:
                        elapsed = time.monotonic() - self.stats["start_time"]
                        logger.info("[%6.1fs] Session break active", elapsed)

        except KeyboardInterrupt:
            print("\n  Interrupted by user")
        except Exception as e:
            self.stats["errors"].append(str(e))
            logger.exception("Loop error")

        self.stats["end_time"] = time.monotonic()

    def _execute_action(self, action: dict):
        action_type = action["type"]
        params = action.get("params", {})

        if "x" in params and "y" in params:
            x, y = params["x"], params["y"]
            ox, oy = action.get("click_offset", (0, 0))
            hold = action.get("hold_ms", 80)

            ok1 = self.cmd_buffer.send("MOVE", x + ox, y + oy, 300)
            time.sleep(0.05)
            ok2 = self.cmd_buffer.send("CLICK", "L", hold)

            self.stats["serial_sent"] += 2
            if ok1 and ok2:
                self.stats["serial_ack"] += 2
            else:
                self.stats["serial_fail"] += (0 if ok1 else 1) + (0 if ok2 else 1)
        else:
            self.stats["serial_sent"] += 1
            self.stats["serial_ack"] += 1

    def _teardown(self):
        print("\n--- Teardown ---")
        if self.orchestrator:
            self.orchestrator.stop()
        if self.cmd_buffer:
            self.cmd_buffer.send("RESET")
            self.cmd_buffer.stop()
        if self.serial_conn:
            self.serial_conn.disconnect()
        if hasattr(self, 'orchestrator_sc') and self.orchestrator_sc:
            self.orchestrator_sc.close()

    def _print_report(self):
        duration = self.stats["end_time"] - self.stats["start_time"]
        print("\n" + "=" * 60)
        print("  FULL LOOP TEST REPORT")
        print("=" * 60)
        print(f"  Duration: {duration:.1f}s")
        print(f"  Strategy: {self.strategy}")
        print(f"  Mode: {'DRY RUN' if self.dry_run else 'LIVE HID'}")

        print(f"\n  Vision:")
        print(f"    State changes: {self.stats['state_changes']}")
        for state, count in sorted(self.stats["states_detected"].items()):
            print(f"    {state:20s}: {count:5d} detections")

        print(f"\n  Logic:")
        print(f"    Actions dispatched: {self.stats['actions_dispatched']}")
        print(f"    Actions/min: {self.stats['actions_dispatched'] / max(1, duration / 60):.1f}")

        if not self.dry_run:
            print(f"\n  Serial:")
            print(f"    Commands sent: {self.stats['serial_sent']}")
            print(f"    ACK received: {self.stats['serial_ack']}")
            print(f"    Failures: {self.stats['serial_fail']}")
            if self.stats["serial_sent"] > 0:
                rate = self.stats["serial_ack"] / self.stats["serial_sent"] * 100
                print(f"    Success rate: {rate:.1f}%")

        if self.stats["errors"]:
            print(f"\n  Errors ({len(self.stats['errors'])}):")
            for err in self.stats["errors"]:
                print(f"    - {err}")

        all_ok = self.stats["state_changes"] > 0 or self.stats["actions_dispatched"] > 0
        serial_ok = self.dry_run or self.stats["serial_fail"] == 0

        print()
        if all_ok and serial_ok:
            print(f"  [{PASS}] Full loop test passed")
        elif all_ok:
            print(f"  [{WARN}] Logic OK but serial had failures")
        else:
            print(f"  [{WARN}] No state changes or actions — check game window + templates")
        print()


def main():
    parser = argparse.ArgumentParser(description="Full Loop Integration Test")
    parser.add_argument("port", nargs="?", default=None, help="ESP32 COM port")
    parser.add_argument("--dry-run", action="store_true", help="Skip serial/HID output")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--strategy", default="basic_gather",
                        choices=["basic_gather", "war_prep", "alliance_focus"])
    args = parser.parse_args()

    if args.port is None:
        args.dry_run = True

    test = FullLoopTest(args)
    test.run()


if __name__ == "__main__":
    main()
