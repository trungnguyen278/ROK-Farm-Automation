"""
Find ESP32-S3 CDC serial port.
Run: python -m tests.find_esp32
"""
import serial.tools.list_ports


def main():
    print("Available serial ports:\n")
    found = False
    for p in serial.tools.list_ports.comports():
        marker = ""
        desc = p.description or ""
        if "ESP32" in desc or "USB" in desc or "CDC" in desc:
            marker = "  <-- likely ESP32-S3"
            found = True
        print(f"  {p.device:10s}  {desc}{marker}")
        if p.manufacturer:
            print(f"             manufacturer: {p.manufacturer}")
        if p.vid is not None:
            print(f"             VID:PID = {p.vid:04X}:{p.pid:04X}")
        print()

    if not found:
        print("No ESP32-S3 detected. Make sure:")
        print("  1. Cable is in the USB port (not UART/COM port)")
        print("  2. Firmware is flashed")
        print("  3. Driver is installed")


if __name__ == "__main__":
    main()
