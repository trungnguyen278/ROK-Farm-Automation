"""
Test PING/PONG handshake with ESP32.
Run: python -m tests.test_handshake [COM_PORT]
"""
import sys
import logging

from serial_comm import SerialConnection

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else None
    conn = SerialConnection(port=port)

    print("=== Test 1: Connect + Handshake (PING/PONG + RESET) ===")
    if conn.connect():
        print("PASS: Handshake successful")
    else:
        print("FAIL: Handshake failed")
        return

    print("\n=== Test 2: Heartbeat (is_alive) ===")
    if conn.is_alive():
        print("PASS: ESP32 is alive")
    else:
        print("FAIL: Heartbeat check failed")

    print("\n=== Test 3: Multiple PINGs ===")
    protocol = conn.protocol
    all_ok = True
    for i in range(5):
        ping = protocol.pack_with_id(0, "PING")
        resp = conn.send_and_wait(ping, 0, timeout=1.0)
        if resp and resp.status == "PONG":
            print(f"  PING {i+1}/5: PONG received")
        else:
            print(f"  PING {i+1}/5: FAIL")
            all_ok = False
    print("PASS: All PINGs answered" if all_ok else "FAIL: Some PINGs missed")

    conn.disconnect()
    print("\nAll handshake tests done.")


if __name__ == "__main__":
    main()
