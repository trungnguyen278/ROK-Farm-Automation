import time
import logging
import threading

import serial
import serial.tools.list_ports

from .protocol import Protocol, Response

logger = logging.getLogger(__name__)

ACK_TIMEOUT = 0.5
HEARTBEAT_INTERVAL = 2.0
HEARTBEAT_TIMEOUT = 5.0
RECONNECT_DELAY = 2.0
MAX_RECONNECT_ATTEMPTS = 5


class SerialConnection:
    def __init__(self, port: str | None = None, baud: int = 115200):
        self._port = port
        self._baud = baud
        self._serial: serial.Serial | None = None
        self._protocol = Protocol()
        self._connected = threading.Event()
        self._lock = threading.Lock()

    @property
    def protocol(self) -> Protocol:
        return self._protocol

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @staticmethod
    def auto_detect_port() -> str | None:
        for p in serial.tools.list_ports.comports():
            if "ESP32" in (p.description or "") or "USB" in (p.description or ""):
                return p.device
        return None

    def connect(self) -> bool:
        port = self._port or self.auto_detect_port()
        if not port:
            logger.error("No serial port specified and auto-detect failed")
            return False

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=self._baud,
                timeout=ACK_TIMEOUT,
            )
            # Opening the port makes the CH340 auto-reset the ESP32. Drive the
            # reset lines to the APP-boot combination (GPIO0 high) so the board
            # never comes up in the ROM download mode -- there it answers nothing
            # on UART and its native USB shows up as USB-Serial-JTAG instead of
            # our HID. Then POLL the handshake: a single fixed 2.5 s wait raced
            # the boot + USB re-enumeration and often missed the first PONG.
            self._app_boot_reset()
            if not self._handshake_with_retries():
                self._serial.close()
                self._serial = None
                return False

            self._port = port
            self._connected.set()
            logger.info("Connected to %s", port)
            return True

        except serial.SerialException as e:
            logger.error("Connection failed: %s", e)
            return False

    def disconnect(self):
        self._connected.clear()
        with self._lock:
            if self._serial and self._serial.is_open:
                # Closing a handle whose device was yanked raises; that must not
                # abort a reconnect, which is exactly when it happens.
                try:
                    self._serial.close()
                except Exception as e:
                    logger.debug("Serial close failed (device gone?): %s", e)
            self._serial = None
        logger.info("Disconnected")

    def reconnect(self) -> bool:
        self.disconnect()
        for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
            logger.info("Reconnect attempt %d/%d", attempt, MAX_RECONNECT_ATTEMPTS)
            if self.connect():
                return True
            time.sleep(RECONNECT_DELAY)
        logger.error("All reconnect attempts failed")
        return False

    def send(self, data: bytes):
        with self._lock:
            if not self._serial or not self._serial.is_open:
                raise ConnectionError("Serial port not open")
            self._serial.write(data)

    def readline(self, timeout: float | None = None) -> bytes | None:
        with self._lock:
            if not self._serial or not self._serial.is_open:
                return None
            if timeout is not None:
                old_timeout = self._serial.timeout
                self._serial.timeout = timeout
            try:
                line = self._serial.readline()
            finally:
                if timeout is not None:
                    self._serial.timeout = old_timeout
        return line if line else None

    def send_and_wait(self, data: bytes, expected_id: int, timeout: float = ACK_TIMEOUT) -> Response | None:
        self.send(data)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            line = self.readline(timeout=max(0.01, remaining))
            if not line:
                continue
            resp = self._protocol.parse_response(line)
            if resp and resp.cmd_id == expected_id:
                return resp
        return None

    def is_alive(self) -> bool:
        try:
            ping = self._protocol.pack_with_id(0, "PING")
            resp = self.send_and_wait(ping, 0, timeout=HEARTBEAT_TIMEOUT)
            return resp is not None and resp.status == "PONG"
        except (ConnectionError, serial.SerialException):
            return False

    def _app_boot_reset(self):
        """Pulse EN with GPIO0 held high so the board boots the app, not the ROM
        bootloader. Same sequence used to recover the board over UART."""
        try:
            self._serial.setDTR(False)   # GPIO0 high -> normal (app) boot
            self._serial.setRTS(True)    # EN low: hold the chip in reset
            time.sleep(0.15)
            self._serial.setRTS(False)   # EN high: release -> boot
        except Exception as e:
            logger.debug("Reset pulse failed (non-fatal): %s", e)

    def _handshake_with_retries(self, attempts: int = 7,
                                delay: float = 0.8) -> bool:
        """Poll the handshake while the board boots and re-enumerates USB.

        The board needs ~2-4 s after a reset; retrying a cheap PING beats betting
        on one fixed sleep. The full handshake (with RESET) runs once PONG lands.
        """
        for i in range(attempts):
            time.sleep(delay)
            try:
                self._serial.reset_input_buffer()
            except Exception:
                pass
            ping = self._protocol.pack_with_id(0, "PING")
            resp = self.send_and_wait(ping, 0, timeout=1.0)
            if resp and resp.status == "PONG":
                return self._handshake()
            logger.debug("No PONG yet (%d/%d), board still booting",
                         i + 1, attempts)
        logger.error("Handshake failed: no PONG after %d attempts", attempts)
        return False

    def _handshake(self) -> bool:
        ping = self._protocol.pack_with_id(0, "PING")
        resp = self.send_and_wait(ping, 0, timeout=2.0)
        if not resp or resp.status != "PONG":
            logger.error("Handshake failed: no PONG")
            return False

        reset = self._protocol.pack_with_id(1, "RESET")
        resp = self.send_and_wait(reset, 1, timeout=1.0)
        if not resp or resp.status != "ACK":
            logger.error("Handshake failed: RESET not ACK'd")
            return False

        logger.info("Handshake OK")
        return True
