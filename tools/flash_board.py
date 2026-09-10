r"""Put the firmware on an ESP32-S3 board, without anyone installing PlatformIO.

The images in firmware/ are built and committed by `pio run` in esp32-s3/; this
writes them with esptool, which is a pip package, so the end user's whole
toolchain is `pip install -r requirements.txt`.

It is meant to be run by someone who has never flashed a microcontroller, so it
diagnoses instead of failing:

  * nothing plugged in     -> waits, and says which socket on the board to use
  * wrong socket           -> the S3 has two. The right one is UART/COM; the
                              other enumerates as USB-JTAG (303A:1001) and
                              cannot be flashed this way.
  * a charge-only cable    -> looks identical to nothing plugged in, so that is
                              named as the likely cause rather than leaving the
                              user staring at "no board found"
  * already flashed        -> answers PING with PONG, so we skip by default

Run:
    .venv\Scripts\python tools\flash_board.py            # detect, flash if needed
    .venv\Scripts\python tools\flash_board.py --force    # flash even if alive
    .venv\Scripts\python tools\flash_board.py --check    # report, change nothing
    .venv\Scripts\python tools\flash_board.py --wait 120 # wait for a plug-in
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import serial.tools.list_ports

from rok_farm import PROJECT_ROOT as ROOT  # frozen-aware; == _HERE from source

FIRMWARE_DIR = ROOT / "firmware"
MANIFEST = FIRMWARE_DIR / "manifest.json"

# The UART bridge we flash through.
CH340 = (0x1A86, 0x7523)
# Some boards ship an FTDI or CP210x bridge instead of the CH340.
OTHER_BRIDGES = {(0x10C4, 0xEA60), (0x0403, 0x6001), (0x1A86, 0x55D4)}
# The S3's own USB. In download mode it is a serial-JTAG device; running our
# firmware it leaves the COM list and becomes the HID below.
NATIVE_USB = (0x303A, 0x1001)
# What the firmware pretends to be once it is running.
HID_VID, HID_PID = 0x046D, 0xC52B


# ---------------------------------------------------------------- detection

class Board:
    def __init__(self, port, kind):
        self.port = port  # serial.tools.list_ports_common.ListPortInfo
        self.kind = kind  # "bridge" | "native"

    @property
    def device(self) -> str:
        return self.port.device

    def __str__(self):
        return f"{self.device} ({self.port.description})"


def scan() -> tuple[list[Board], list[Board]]:
    """(flashable bridges, native-USB ports) currently present."""
    bridges, native = [], []
    for p in serial.tools.list_ports.comports():
        ident = (p.vid, p.pid)
        if ident == CH340 or ident in OTHER_BRIDGES:
            bridges.append(Board(p, "bridge"))
        elif ident == NATIVE_USB:
            native.append(Board(p, "native"))
    return bridges, native


def hid_present() -> bool:
    """True when a device with the firmware's spoofed HID identity is attached.

    This is the only proof the board is acting as a mouse. UART can answer PONG
    while the HID half never enumerated -- that exact split is what the
    usb_reattach() in the firmware's setup() works around, and it is worth
    reporting separately rather than folding into one "works" flag.
    """
    try:
        import winreg
    except ImportError:
        return False
    key_path = r"SYSTEM\CurrentControlSet\Enum\USB\VID_{:04X}&PID_{:04X}".format(
        HID_VID, HID_PID)
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
            n_sub = winreg.QueryInfoKey(k)[0]
            return n_sub > 0
    except OSError:
        return False


def firmware_alive(port: str) -> bool:
    """Ask the board to identify itself over UART. True on PONG."""
    try:
        from serial_comm.connection import SerialConnection
    except Exception:
        return False
    conn = SerialConnection(port=port)
    try:
        return bool(conn.connect())
    except Exception:
        return False
    finally:
        with contextlib.suppress(Exception):
            conn.disconnect()


# ---------------------------------------------------------------- flashing

def load_manifest() -> dict:
    if not MANIFEST.is_file():
        raise SystemExit(
            f"No firmware manifest at {MANIFEST}.\n"
            "The packaged app ships one. From a source checkout, build it:\n"
            "    cd esp32-s3 && pio run")
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    missing = [p["file"] for p in data["parts"]
               if not (FIRMWARE_DIR / p["file"]).is_file()]
    if missing:
        raise SystemExit(
            f"The manifest lists images that are not in {FIRMWARE_DIR}: {missing}")
    return data


def flash(device: str, manifest: dict, baud: int = 460800) -> bool:
    """Write every image in the manifest. True on success."""
    import esptool

    argv = [
        "--chip", manifest.get("chip", "esp32s3"),
        "--port", device,
        "--baud", str(baud),
        "--before", "default_reset",
        "--after", "hard_reset",
        "write_flash",
        "-z",
        "--flash_mode", manifest.get("flash_mode", "qio"),
        "--flash_freq", manifest.get("flash_freq", "80m"),
        "--flash_size", manifest.get("flash_size", "16MB"),
    ]
    for part in manifest["parts"]:
        argv += [part["offset"], str(FIRMWARE_DIR / part["file"])]

    print("[flash] esptool " + " ".join(argv))
    try:
        esptool.main(argv)
        return True
    except SystemExit as e:  # esptool exits non-zero on failure
        return (e.code or 0) == 0
    except Exception as e:
        print(f"[flash] failed: {type(e).__name__}: {e}")
        return False


# ---------------------------------------------------------------- top level

def wait_for_board(seconds: float) -> Board | None:
    """Poll until a flashable board shows up, explaining what is wrong meanwhile."""
    deadline = time.monotonic() + seconds
    said_native = said_nothing = False
    while time.monotonic() < deadline:
        bridges, native = scan()
        if bridges:
            return bridges[0]
        if native and not said_native:
            print("[wait] Found the board's NATIVE USB socket (USB-JTAG).\n"
                  "       Move the cable to the board's OTHER socket, the one\n"
                  "       labelled UART/COM. Only that one can be flashed.")
            said_native = True
        elif not native and not said_nothing:
            print("[wait] No board yet. Plug the ESP32-S3 into the UART/COM socket.\n"
                  "       If it already is, the cable is very likely charge-only.\n"
                  "       A data cable is required and the two look identical --\n"
                  "       try a different cable before anything else.")
            said_nothing = True
        time.sleep(1.0)
    return None


def describe() -> None:
    bridges, native = scan()
    print(f"USB bridges (flashable): {[str(b) for b in bridges] or 'none'}")
    print(f"Native USB (USB-JTAG)  : {[str(b) for b in native] or 'none'}")
    print(f"HID {HID_VID:04X}:{HID_PID:04X} attached : {hid_present()}")
    for b in bridges:
        alive = "responds to PING" if firmware_alive(b.device) else "no answer"
        print(f"Firmware on {b.device:<6}     : {alive}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Flash the ESP32-S3 HID firmware")
    ap.add_argument("--port", help="COM port; default is auto-detect")
    ap.add_argument("--force", action="store_true",
                    help="flash even when the board already answers PING")
    ap.add_argument("--check", action="store_true",
                    help="report what is attached and exit, changing nothing")
    ap.add_argument("--wait", type=float, default=30.0,
                    help="seconds to wait for a board to be plugged in (default 30)")
    ap.add_argument("--baud", type=int, default=460800)
    args = ap.parse_args()

    if args.check:
        describe()
        return 0

    if args.port:
        board = next((b for b in scan()[0] if b.device == args.port), None)
        if board is None:
            print(f"[flash] {args.port} is not a flashable port right now.")
            describe()
            return 2
    else:
        bridges, _ = scan()
        board = bridges[0] if bridges else wait_for_board(args.wait)
        if board is None:
            print("[flash] No board found. Nothing was changed.")
            return 2

    print(f"[flash] Board: {board}")

    if not args.force and firmware_alive(board.device):
        print("[flash] It already runs our firmware (answered PING with PONG).")
        print(f"[flash] HID attached: {hid_present()}")
        print("[flash] Nothing to do. Pass --force to write it again anyway.")
        return 0

    manifest = load_manifest()
    total_kb = sum(p["size"] for p in manifest["parts"]) // 1024
    print(f"[flash] Writing {len(manifest['parts'])} images ({total_kb} KB)...")
    if not flash(board.device, manifest, baud=args.baud):
        print("[flash] esptool reported a failure. The board is most likely still\n"
              "        in its previous state. Try again; if it keeps failing, hold\n"
              "        the BOOT button down while plugging the cable in.")
        return 1

    print("[flash] Written. Waiting for it to boot and re-enumerate...")
    # It reboots, brings USB up, and may re-attach once. Poll rather than sleep
    # on a guess -- the same race the firmware's usb_reattach() works around.
    ok = False
    for _ in range(12):
        time.sleep(1.0)
        if firmware_alive(board.device):
            ok = True
            break

    print(f"[flash] Answers PING : {ok}")
    print(f"[flash] HID attached : {hid_present()}")
    if not ok:
        print("[flash] Flashed, but it is not answering. Unplug and replug it once.")
        return 1
    print("[flash] Done. The board is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
