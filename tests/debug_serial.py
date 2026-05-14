"""
Raw serial debug — sends PING and shows exactly what comes back.
Run: python -m tests.debug_serial [COM_PORT]
"""
import sys
import time

import serial
import serial.tools.list_ports


def list_ports():
    print("=== Available ports ===")
    for p in serial.tools.list_ports.comports():
        print(f"  {p.device:10s}  {p.description}")
        print(f"             VID:PID={p.vid:04X}:{p.pid:04X}" if p.vid else "")
        print(f"             hwid={p.hwid}")
    print()


def main():
    list_ports()

    port = sys.argv[1] if len(sys.argv) > 1 else None
    if not port:
        print("Usage: python -m tests.debug_serial COM_PORT")
        return

    print(f"=== Opening {port} at 115200 ===")
    try:
        ser = serial.Serial(port=port, baudrate=115200, timeout=0.5)
    except serial.SerialException as e:
        print(f"FAIL: {e}")
        return

    print(f"  port open: {ser.is_open}")
    print(f"  name: {ser.name}")
    print()

    print("=== Waiting 2s for ESP32 boot ===")
    time.sleep(2.0)

    in_waiting = ser.in_waiting
    print(f"  bytes waiting: {in_waiting}")
    if in_waiting > 0:
        boot_data = ser.read(in_waiting)
        print(f"  boot data (raw): {boot_data}")
        print(f"  boot data (text): {boot_data.decode('ascii', errors='replace')}")
    print()

    ser.reset_input_buffer()

    ping_cmd = b"<0,PING>\n"
    print(f"=== Sending PING: {ping_cmd} ===")
    ser.write(ping_cmd)
    ser.flush()

    print("=== Reading response (3s timeout) ===")
    start = time.monotonic()
    all_data = b""
    while time.monotonic() - start < 3.0:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            all_data += chunk
            print(f"  [{time.monotonic()-start:.2f}s] recv {len(chunk)} bytes: {chunk}")
        time.sleep(0.05)

    print()
    if all_data:
        print(f"=== Total received: {len(all_data)} bytes ===")
        print(f"  raw:  {all_data}")
        print(f"  text: {all_data.decode('ascii', errors='replace')}")
        print(f"  hex:  {all_data.hex(' ')}")
    else:
        print("=== No response received ===")
        print("  Possible causes:")
        print("  1. Wrong port — cable in UART port instead of USB port?")
        print("  2. Firmware not flashed — did 'pio run -t upload' succeed?")
        print("  3. ESP32 stuck in boot — try pressing RESET button on board")
        print("  4. USB mode mismatch — VID:PID 303A:1001 = JTAG/Serial, not TinyUSB CDC")

    print()
    print("=== Sending raw text test ===")
    ser.reset_input_buffer()
    test_cmds = [b"<1,RESET>\n", b"<2,MOVE,10,10,0>\n"]
    for cmd in test_cmds:
        print(f"  TX: {cmd.strip()}")
        ser.write(cmd)
        time.sleep(0.5)
        resp = ser.read(ser.in_waiting or 0)
        print(f"  RX: {resp if resp else b'(empty)'}")
        print()

    ser.close()
    print("Done.")


if __name__ == "__main__":
    main()
