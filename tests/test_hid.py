"""
Test MOVE/CLICK HID commands on desktop (no game needed).
Run: python -m tests.test_hid [COM_PORT]
Warning: This will move your mouse and click!
"""
import sys
import time
import logging

from serial_comm import SerialConnection, CommandBuffer

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else None
    conn = SerialConnection(port=port)

    if not conn.connect():
        print("FAIL: Could not connect to ESP32")
        return

    buf = CommandBuffer(conn)
    buf.start()
    time.sleep(0.5)

    print("=== Test 1: MOVE relative (small square pattern) ===")
    moves = [(100, 0, 200), (0, 100, 200), (-100, 0, 200), (0, -100, 200)]
    all_ok = True
    for dx, dy, dur in moves:
        ok = buf.send("MOVE", dx, dy, dur)
        print(f"  MOVE({dx},{dy},{dur}ms): {'ACK' if ok else 'FAIL'}")
        if not ok:
            all_ok = False
        time.sleep(0.3)
    print("PASS: Square pattern complete" if all_ok else "FAIL: Some moves failed")

    print("\n=== Test 2: CLICK left ===")
    ok = buf.send("CLICK", "L", 80)
    print(f"{'PASS' if ok else 'FAIL'}: Left click")

    print("\n=== Test 3: SCROLL ===")
    ok1 = buf.send("SCROLL", -3)
    time.sleep(0.3)
    ok2 = buf.send("SCROLL", 3)
    print(f"{'PASS' if ok1 and ok2 else 'FAIL'}: Scroll down then up")

    print("\n=== Test 4: KEY press (space = keycode 0x2C) ===")
    ok = buf.send("KEY", 0x2C, 60)
    print(f"{'PASS' if ok else 'FAIL'}: Space key")

    print("\n=== Test 5: RESET ===")
    ok = buf.send("RESET")
    print(f"{'PASS' if ok else 'FAIL'}: Reset HID state")

    buf.stop()
    conn.disconnect()
    print("\nAll HID tests done.")


if __name__ == "__main__":
    main()
