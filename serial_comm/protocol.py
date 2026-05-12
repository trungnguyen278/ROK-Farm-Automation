import threading
from dataclasses import dataclass


@dataclass
class Response:
    cmd_id: int
    status: str  # "ACK", "NACK", "PONG"
    params: list[str]


class Protocol:
    def __init__(self):
        self._counter = 2  # 0,1 reserved for handshake
        self._lock = threading.Lock()

    def pack(self, cmd: str, *params) -> tuple[int, bytes]:
        with self._lock:
            cmd_id = self._counter
            self._counter += 1

        parts = [str(cmd_id), cmd] + [str(p) for p in params]
        frame = "<" + ",".join(parts) + ">\n"
        return cmd_id, frame.encode("ascii")

    def pack_with_id(self, cmd_id: int, cmd: str, *params) -> bytes:
        parts = [str(cmd_id), cmd] + [str(p) for p in params]
        frame = "<" + ",".join(parts) + ">\n"
        return frame.encode("ascii")

    def parse_response(self, line: bytes) -> Response | None:
        text = line.decode("ascii", errors="ignore").strip()
        if not text.startswith("<") or not text.endswith(">"):
            return None

        inner = text[1:-1]
        parts = inner.split(",")
        if len(parts) < 2:
            return None

        try:
            cmd_id = int(parts[0])
        except ValueError:
            return None

        status = parts[1]
        params = parts[2:]
        return Response(cmd_id=cmd_id, status=status, params=params)
