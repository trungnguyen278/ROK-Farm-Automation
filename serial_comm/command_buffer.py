import logging
import threading
from queue import Queue, Empty
from dataclasses import dataclass

from .connection import SerialConnection, ACK_TIMEOUT
from .protocol import Response

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
QUEUE_MAX = 32


@dataclass
class PendingCommand:
    cmd: str
    params: tuple
    result: threading.Event
    response: Response | None = None
    success: bool = False


class CommandBuffer:
    def __init__(self, connection: SerialConnection):
        self._conn = connection
        self._queue: Queue[PendingCommand] = Queue(maxsize=QUEUE_MAX)
        self._worker: threading.Thread | None = None
        self._running = threading.Event()
        self._pending_path_ms = 0

    def start(self):
        if self._worker and self._worker.is_alive():
            return
        self._running.set()
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
        logger.info("Command buffer started")

    def stop(self):
        self._running.clear()
        if self._worker:
            self._worker.join(timeout=2.0)
            self._worker = None
        logger.info("Command buffer stopped")

    def send(self, cmd: str, *params, timeout: float = 5.0) -> bool:
        pending = PendingCommand(cmd=cmd, params=params, result=threading.Event())
        self._queue.put(pending)
        pending.result.wait(timeout=timeout)
        return pending.success

    def send_async(self, cmd: str, *params):
        pending = PendingCommand(cmd=cmd, params=params, result=threading.Event())
        try:
            self._queue.put_nowait(pending)
        except Exception:
            logger.warning("Command queue full, dropping: %s", cmd)

    def send_path(self, waypoints: list[tuple[int, int, int]],
                  drag: bool = False, timeout: float = 15.0) -> bool:
        """Send a trajectory to ESP32 for hardware-timed execution.

        waypoints: list of (hid_x, hid_y, delay_ms) in absolute HID coords.
        drag: if True, ESP32 does MDOWN before path and MUP after.
        Returns True if all commands succeeded.
        """
        if not self.send("PCLR"):
            return False
        total_ms = 0
        for hx, hy, ms in waypoints:
            clamped = min(ms, 255)
            if not self.send("PPT", hx, hy, clamped):
                return False
            total_ms += clamped
        cmd = "PDRAG" if drag else "PGO"
        # Store total path duration so _ack_timeout_for can use it
        self._pending_path_ms = total_ms
        result = self.send(cmd, timeout=timeout)
        self._pending_path_ms = 0
        return result

    def _worker_loop(self):
        while self._running.is_set():
            try:
                pending = self._queue.get(timeout=0.1)
            except Empty:
                continue

            self._execute_with_retry(pending)
            pending.result.set()

    def _ack_timeout_for(self, cmd: str, params: tuple) -> float:
        """Dynamic ACK timeout: DRAG/MOVE with duration need longer waits.
        PGO/PDRAG block ESP32 for entire path duration before ACK."""
        base = ACK_TIMEOUT
        if cmd == "MOVE":
            try:
                duration_ms = int(params[-1]) if params else 0
                base += duration_ms / 1000.0 + 0.2
            except (ValueError, IndexError):
                base += 1.0
        elif cmd in ("PGO", "PDRAG"):
            path_ms = getattr(self, "_pending_path_ms", 0)
            base += path_ms / 1000.0 + 1.0
        return base

    def _execute_with_retry(self, pending: PendingCommand):
        protocol = self._conn.protocol
        ack_timeout = self._ack_timeout_for(pending.cmd, pending.params)
        for attempt in range(1, MAX_RETRIES + 1):
            cmd_id, data = protocol.pack(pending.cmd, *pending.params)
            try:
                resp = self._conn.send_and_wait(data, cmd_id, timeout=ack_timeout)
            except ConnectionError:
                logger.warning("Connection lost during %s (attempt %d)", pending.cmd, attempt)
                if not self._conn.reconnect():
                    break
                continue

            if resp is None:
                logger.warning("Timeout for %s id=%d (attempt %d)", pending.cmd, cmd_id, attempt)
                continue

            pending.response = resp
            if resp.status == "ACK":
                pending.success = True
                return
            elif resp.status == "NACK":
                logger.warning("NACK for %s id=%d error=%s", pending.cmd, cmd_id, resp.params)
                pending.success = False
                return

        logger.error("All retries exhausted for %s", pending.cmd)
        pending.success = False
