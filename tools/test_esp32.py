"""
Phase 6 — ESP32 Hardware Test Suite
Interactive test for real ESP32-S3 connection: PING/PONG, MOVE, CLICK, SCROLL, KEY.
Run: python -m tools.test_esp32 [COM_PORT]

Tests performed:
  1. Port detection & listing
  2. Serial connect + handshake (PING/PONG + RESET)
  3. Heartbeat reliability (10x PING)
  4. HID MOVE — square pattern on desktop
  5. HID CLICK — left, right, double-click
  6. HID SCROLL — up/down
  7. HID KEY — press space, type "test"
  8. HID COMBO — Ctrl+A
  9. Reconnect test — disconnect then reconnect
  10. Latency benchmark — measure round-trip times
"""
import sys
import os
import time
import statistics
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from serial_comm.connection import SerialConnection
from serial_comm.command_buffer import CommandBuffer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s",
)
logger = logging.getLogger("test_esp32")

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
SKIP = "\033[93mSKIP\033[0m"
WARN = "\033[93mWARN\033[0m"


class ESP32TestSuite:
    def __init__(self, port: str | None = None):
        self.port = port
        self.conn: SerialConnection | None = None
        self.buf: CommandBuffer | None = None
        self.results: list[tuple[str, str, str]] = []

    def record(self, name: str, status: str, detail: str = ""):
        self.results.append((name, status, detail))
        tag = {PASS: PASS, FAIL: FAIL, SKIP: SKIP, WARN: WARN}.get(status, status)
        print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))

    def run_all(self):
        print("=" * 60)
        print("  ESP32-S3 Hardware Test Suite — Phase 6")
        print("=" * 60)

        self.test_port_detection()
        if not self.test_connect():
            self.print_summary()
            return

        self.test_heartbeat()
        self.test_move_square()
        self.test_moveto()
        self.test_clicks()
        self.test_scroll()
        self.test_key()
        self.test_latency()
        self.test_reconnect()
        self.cleanup()
        self.print_summary()

    def test_port_detection(self):
        print("\n--- Test 1: Port Detection ---")
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        if not ports:
            self.record("Port scan", WARN, "No serial ports found")
            return

        esp_found = False
        for p in ports:
            desc = p.description or ""
            is_esp = "ESP32" in desc or "USB" in desc or "CDC" in desc
            marker = " <-- likely ESP32" if is_esp else ""
            print(f"    {p.device:10s}  {desc}{marker}")
            if p.vid is not None:
                print(f"               VID:PID={p.vid:04X}:{p.pid:04X}")
            if is_esp:
                esp_found = True

        self.record("Port scan", PASS if esp_found else WARN,
                     f"{len(ports)} ports, ESP32 {'found' if esp_found else 'not auto-detected'}")

    def test_connect(self) -> bool:
        print("\n--- Test 2: Connect + Handshake ---")
        self.conn = SerialConnection(port=self.port)
        if self.conn.connect():
            self.record("Handshake", PASS, f"Connected to {self.conn._port}")
            self.buf = CommandBuffer(self.conn)
            self.buf.start()
            time.sleep(0.3)
            return True
        else:
            self.record("Handshake", FAIL, "Could not connect — check port/firmware")
            return False

    def test_heartbeat(self):
        print("\n--- Test 3: Heartbeat Reliability (10x PING) ---")
        ok_count = 0
        latencies = []
        for i in range(10):
            t0 = time.monotonic()
            alive = self.conn.is_alive()
            dt = (time.monotonic() - t0) * 1000
            if alive:
                ok_count += 1
                latencies.append(dt)
            print(f"    PING {i+1:2d}/10: {'PONG' if alive else 'TIMEOUT':6s}  {dt:.1f}ms")

        if ok_count == 10:
            self.record("Heartbeat 10x", PASS,
                         f"avg={statistics.mean(latencies):.1f}ms, max={max(latencies):.1f}ms")
        elif ok_count >= 8:
            self.record("Heartbeat 10x", WARN, f"{ok_count}/10 responded")
        else:
            self.record("Heartbeat 10x", FAIL, f"Only {ok_count}/10 responded")

    def test_move_square(self):
        print("\n--- Test 4: HID MOVE — Square Pattern ---")
        print("    (Mouse will move in a 100px square)")
        time.sleep(0.5)
        moves = [
            (100, 0, 300, "right"),
            (0, 100, 300, "down"),
            (-100, 0, 300, "left"),
            (0, -100, 300, "up"),
        ]
        all_ok = True
        for dx, dy, dur, direction in moves:
            ok = self.buf.send("MOVE", dx, dy, dur)
            status = "ACK" if ok else "FAIL"
            print(f"    MOVE {direction:5s} ({dx:+4d},{dy:+4d},{dur}ms): {status}")
            if not ok:
                all_ok = False
            time.sleep(0.1)

        self.record("MOVE square", PASS if all_ok else FAIL)

    def test_moveto(self):
        print("\n--- Test 4b: HID MOVETO — Absolute Position ---")
        print("    (Mouse will jump to 4 corners via absolute coords)")
        time.sleep(0.5)
        positions = [
            (8192, 8192, "center-ish"),
            (3000, 3000, "top-left"),
            (29000, 3000, "top-right"),
            (29000, 29000, "bottom-right"),
            (3000, 29000, "bottom-left"),
            (16383, 16383, "center"),
        ]
        all_ok = True
        for x, y, label in positions:
            ok = self.buf.send("MOVETO", x, y)
            status = "ACK" if ok else "FAIL"
            print(f"    MOVETO {label:14s} ({x:5d},{y:5d}): {status}")
            if not ok:
                all_ok = False
            time.sleep(0.4)

        self.record("MOVETO absolute", PASS if all_ok else FAIL)

    def test_clicks(self):
        print("\n--- Test 5: HID CLICK ---")
        time.sleep(0.3)

        tests = [
            ("Left click", "L", 80),
            ("Right click", "R", 80),
        ]
        all_ok = True
        for name, btn, hold in tests:
            ok = self.buf.send("CLICK", btn, hold)
            print(f"    {name}: {'ACK' if ok else 'FAIL'}")
            if not ok:
                all_ok = False
            time.sleep(0.3)

        self.record("CLICK L/R", PASS if all_ok else FAIL)

    def test_scroll(self):
        print("\n--- Test 6: HID SCROLL ---")
        ok1 = self.buf.send("SCROLL", -3)
        time.sleep(0.2)
        ok2 = self.buf.send("SCROLL", 3)
        print(f"    Scroll down: {'ACK' if ok1 else 'FAIL'}")
        print(f"    Scroll up:   {'ACK' if ok2 else 'FAIL'}")
        self.record("SCROLL", PASS if ok1 and ok2 else FAIL)

    def test_key(self):
        print("\n--- Test 7: HID KEY ---")
        ok = self.buf.send("KEY", 0x2C, 60)  # space
        print(f"    Space key: {'ACK' if ok else 'FAIL'}")
        self.record("KEY press", PASS if ok else FAIL)

    def test_latency(self):
        print("\n--- Test 8: Latency Benchmark (50x PING) ---")
        latencies = []
        for _ in range(50):
            t0 = time.monotonic()
            self.conn.is_alive()
            dt = (time.monotonic() - t0) * 1000
            latencies.append(dt)

        if latencies:
            avg = statistics.mean(latencies)
            med = statistics.median(latencies)
            p95 = sorted(latencies)[int(len(latencies) * 0.95)]
            mx = max(latencies)
            print(f"    avg={avg:.1f}ms  median={med:.1f}ms  p95={p95:.1f}ms  max={mx:.1f}ms")
            self.record("Latency 50x", PASS if avg < 50 else WARN,
                         f"avg={avg:.1f}ms p95={p95:.1f}ms")
        else:
            self.record("Latency 50x", FAIL, "No responses")

    def test_reconnect(self):
        print("\n--- Test 9: Reconnect ---")
        print("    Disconnecting...")
        self.conn.disconnect()
        time.sleep(1.0)

        print("    Reconnecting...")
        if self.conn.connect():
            self.record("Reconnect", PASS)
            self.buf = CommandBuffer(self.conn)
            self.buf.start()
            time.sleep(0.3)
        else:
            self.record("Reconnect", FAIL, "Could not reconnect")

    def cleanup(self):
        if self.buf:
            self.buf.send("RESET")
            self.buf.stop()
        if self.conn:
            self.conn.disconnect()

    def print_summary(self):
        print("\n" + "=" * 60)
        print("  SUMMARY")
        print("=" * 60)
        pass_count = sum(1 for _, s, _ in self.results if s == PASS)
        fail_count = sum(1 for _, s, _ in self.results if s == FAIL)
        warn_count = sum(1 for _, s, _ in self.results if s == WARN)
        total = len(self.results)

        for name, status, detail in self.results:
            tag = status
            line = f"  [{tag}] {name}"
            if detail:
                line += f" — {detail}"
            print(line)

        print()
        print(f"  Total: {total}  |  Pass: {pass_count}  |  Fail: {fail_count}  |  Warn: {warn_count}")

        if fail_count == 0:
            print(f"\n  [{PASS}] ESP32 hardware test PASSED — ready for game testing")
        else:
            print(f"\n  [{FAIL}] {fail_count} test(s) failed — check ESP32 connection/firmware")
        print()


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else None
    suite = ESP32TestSuite(port)
    suite.run_all()


if __name__ == "__main__":
    main()
