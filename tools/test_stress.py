"""
Phase 6 — Stress Test Runner
Long-running test with memory/CPU monitoring and crash detection.
Run: python -m tools.test_stress [--duration HOURS] [--port COM_PORT]

Features:
  - Runs Orchestrator for specified duration (default: 1h)
  - Samples memory/CPU every 10s
  - Detects memory leaks (>50MB growth)
  - Tracks thread count stability
  - Monitors serial reconnects
  - Writes CSV report to logs/stress_YYYYMMDD_HHMMSS.csv

Output:
  - Console: live stats every 30s
  - CSV: detailed time-series data
  - Summary: pass/fail with recommendations
"""
import sys
import os
import time
import logging
import argparse
import threading
import csv
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
from vision.state_detector import StateDetector

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            LOG_DIR / f"stress_{datetime.now():%Y%m%d_%H%M%S}.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("test_stress")

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"

SAMPLE_INTERVAL = 10
REPORT_INTERVAL = 30
MEMORY_LEAK_THRESHOLD_MB = 50


class StressTest:
    def __init__(self, args):
        self.duration_hours = args.duration
        self.port = args.port
        self.dry_run = args.port is None

        self.process = psutil.Process(os.getpid())
        self.samples: list[dict] = []
        self.errors: list[str] = []
        self.reconnects = 0
        self.start_time = 0.0

        self.csv_path = LOG_DIR / f"stress_{datetime.now():%Y%m%d_%H%M%S}.csv"

    def run(self):
        duration_s = self.duration_hours * 3600
        print("=" * 60)
        print("  Stress Test Runner — Phase 6")
        print("=" * 60)
        print(f"  Duration: {self.duration_hours}h ({duration_s}s)")
        print(f"  Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")
        print(f"  CSV output: {self.csv_path}")
        print()

        config = Config.load()
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
                print(f"  ESP32 connected: {serial_conn._port}")
            else:
                print("  ESP32 connection failed, switching to dry-run")
                self.dry_run = True

        orchestrator.start("basic_gather")
        self.start_time = time.monotonic()
        baseline_mem = self._get_memory_mb()
        print(f"  Baseline memory: {baseline_mem:.1f} MB")
        print(f"  Threads at start: {threading.active_count()}")
        print(f"\n  Running... (Ctrl+C to stop early)\n")

        self._init_csv()

        state_changes = 0
        actions = 0
        last_report = time.monotonic()
        last_sample = time.monotonic()
        last_state = None

        try:
            while time.monotonic() - self.start_time < duration_s:
                now = time.monotonic()

                try:
                    while True:
                        state_val = orchestrator.state_queue.get_nowait()
                        if state_val != last_state:
                            state_changes += 1
                            last_state = state_val
                except Empty:
                    pass

                try:
                    while True:
                        orchestrator.action_queue.get_nowait()
                        actions += 1
                except Empty:
                    pass

                if now - last_sample >= SAMPLE_INTERVAL:
                    sample = self._take_sample(state_changes, actions)
                    self.samples.append(sample)
                    self._write_csv_row(sample)
                    last_sample = now

                if now - last_report >= REPORT_INTERVAL:
                    elapsed = now - self.start_time
                    mem = self._get_memory_mb()
                    cpu = self.process.cpu_percent(interval=0)
                    threads = threading.active_count()
                    delta_mem = mem - baseline_mem

                    elapsed_str = self._format_duration(elapsed)
                    remaining = duration_s - elapsed
                    remaining_str = self._format_duration(remaining)

                    print(f"  [{elapsed_str}] mem={mem:.1f}MB (delta={delta_mem:+.1f}) "
                          f"cpu={cpu:.0f}% threads={threads} "
                          f"states={state_changes} actions={actions} "
                          f"errors={len(self.errors)} | remaining={remaining_str}")

                    last_report = now

                if serial_conn and not serial_conn.is_connected:
                    self.reconnects += 1
                    logger.warning("Serial disconnected, reconnect #%d", self.reconnects)

                time.sleep(1.0)

        except KeyboardInterrupt:
            print("\n  Stopped by user")
        except Exception as e:
            self.errors.append(f"Fatal: {e}")
            logger.exception("Stress test fatal error")

        orchestrator.stop()
        if cmd_buffer:
            cmd_buffer.stop()
        if serial_conn:
            serial_conn.disconnect()
        sc.close()

        self._print_report(baseline_mem, state_changes, actions)

    def _take_sample(self, state_changes: int, actions: int) -> dict:
        mem = self._get_memory_mb()
        try:
            cpu = self.process.cpu_percent(interval=0)
        except Exception:
            cpu = 0.0

        return {
            "timestamp": time.monotonic() - self.start_time,
            "memory_mb": mem,
            "cpu_percent": cpu,
            "threads": threading.active_count(),
            "state_changes": state_changes,
            "actions": actions,
            "errors": len(self.errors),
            "reconnects": self.reconnects,
        }

    def _get_memory_mb(self) -> float:
        return self.process.memory_info().rss / (1024 * 1024)

    def _init_csv(self):
        with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "elapsed_s", "memory_mb", "cpu_percent", "threads",
                "state_changes", "actions", "errors", "reconnects",
            ])

    def _write_csv_row(self, sample: dict):
        with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                f"{sample['timestamp']:.1f}",
                f"{sample['memory_mb']:.1f}",
                f"{sample['cpu_percent']:.1f}",
                sample["threads"],
                sample["state_changes"],
                sample["actions"],
                sample["errors"],
                sample["reconnects"],
            ])

    def _print_report(self, baseline_mem: float, state_changes: int, actions: int):
        elapsed = time.monotonic() - self.start_time
        final_mem = self._get_memory_mb()
        mem_delta = final_mem - baseline_mem

        print("\n" + "=" * 60)
        print("  STRESS TEST REPORT")
        print("=" * 60)
        print(f"  Duration: {self._format_duration(elapsed)}")
        print(f"  Mode: {'DRY RUN' if self.dry_run else 'LIVE'}")

        print(f"\n  Memory:")
        print(f"    Baseline: {baseline_mem:.1f} MB")
        print(f"    Final: {final_mem:.1f} MB")
        print(f"    Delta: {mem_delta:+.1f} MB")

        if self.samples:
            mems = [s["memory_mb"] for s in self.samples]
            print(f"    Peak: {max(mems):.1f} MB")
            print(f"    Min: {min(mems):.1f} MB")

        mem_ok = abs(mem_delta) < MEMORY_LEAK_THRESHOLD_MB
        print(f"    Leak check: {PASS if mem_ok else FAIL} "
              f"(threshold={MEMORY_LEAK_THRESHOLD_MB}MB)")

        print(f"\n  CPU:")
        if self.samples:
            cpus = [s["cpu_percent"] for s in self.samples]
            avg_cpu = sum(cpus) / len(cpus)
            print(f"    Avg: {avg_cpu:.1f}%")
            print(f"    Peak: {max(cpus):.1f}%")

        print(f"\n  Threads:")
        if self.samples:
            threads = [s["threads"] for s in self.samples]
            print(f"    Start: {threads[0]}")
            print(f"    Final: {threads[-1]}")
            print(f"    Peak: {max(threads)}")
            thread_stable = max(threads) - min(threads) <= 2
            print(f"    Stability: {PASS if thread_stable else WARN}")

        print(f"\n  Activity:")
        print(f"    State changes: {state_changes}")
        print(f"    Actions: {actions}")
        print(f"    Actions/min: {actions / max(1, elapsed / 60):.1f}")
        print(f"    Serial reconnects: {self.reconnects}")

        print(f"\n  Errors: {len(self.errors)}")
        for err in self.errors[:5]:
            print(f"    - {err}")
        if len(self.errors) > 5:
            print(f"    ... and {len(self.errors) - 5} more")

        all_ok = mem_ok and len(self.errors) == 0 and self.reconnects <= 3
        print()
        if all_ok:
            print(f"  [{PASS}] Stress test PASSED")
        elif len(self.errors) == 0:
            print(f"  [{WARN}] Stress test completed with warnings")
        else:
            print(f"  [{FAIL}] Stress test had errors")

        print(f"\n  CSV report: {self.csv_path}")
        print()

    @staticmethod
    def _format_duration(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        if h > 0:
            return f"{h}h{m:02d}m{s:02d}s"
        return f"{m}m{s:02d}s"


def main():
    parser = argparse.ArgumentParser(description="Stress Test Runner")
    parser.add_argument("--duration", type=float, default=1.0, help="Duration in hours")
    parser.add_argument("--port", default=None, help="ESP32 COM port (omit for dry-run)")
    args = parser.parse_args()

    test = StressTest(args)
    test.run()


if __name__ == "__main__":
    main()
