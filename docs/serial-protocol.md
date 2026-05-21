# Serial Protocol Spec

> **AI Note:** Text-based protocol qua UART 115200. Format `<CMD,params>\n`. Mỗi command có ID tự tăng. ESP32 phải ACK/NACK mỗi lệnh. Python chờ ACK rồi mới gửi tiếp.

## Physical Layer

| Param | Value |
|---|---|
| Interface | USB CDC (ESP32-S3 native USB) |
| Baud rate | 115200 |
| Data bits | 8 |
| Parity | None |
| Stop bits | 1 |
| Line ending | `\n` (0x0A) |

## Frame Format

### Python → ESP32 (Command)
```
<CMD_ID,COMMAND,param1,param2,...>\n
```

### ESP32 → Python (Response)
```
<CMD_ID,ACK>\n              # Success
<CMD_ID,NACK,ERROR_CODE>\n  # Failure
```

## Commands

| Command | Params | Example | Description |
|---|---|---|---|
| `MOVE` | dx,dy,duration_ms | `<12,MOVE,50,-30,150>` | Relative mouse move (delta px) over duration |
| `MOVETO` | x,y | `<13,MOVETO,16383,16383>` | Absolute mouse move (0-32767 coords, maps to screen) |
| `CLICK` | button,hold_ms | `<14,CLICK,L,80>` | Click button (L/R/M) hold for ms |
| `DCLICK` | button,gap_ms | `<15,DCLICK,L,95>` | Double click with gap between |
| `MDOWN` | button | `<16,MDOWN,L>` | Press mouse button (hold) |
| `MUP` | button | `<17,MUP,L>` | Release mouse button |
| `DRAG` | x1,y1,x2,y2,dur_ms | `<18,DRAG,5000,5000,20000,15000,300>` | Absolute drag from->to (0-32767 coords) |
| `SCROLL` | amount | `<19,SCROLL,-3>` | Scroll (negative=down) |
| `KEY` | name,hold_ms | `<20,KEY,ESC,60>` | Press key by name (ESC/TAB/SPACE/F1-F12/etc) |
| `COMBO` | key1,key2,...,hold_ms | `<21,COMBO,ALT,TAB,100>` | Key combo (last numeric param = hold ms) |
| `IDLE` | on_off | `<22,IDLE,1>` | Suppress idle HID noise (1=suppress, 0=resume) |
| `PING` | — | `<0,PING>` | Heartbeat check (responds PONG) |
| `RESET` | — | `<1,RESET>` | Release all buttons/keys, clear idle suppress |

## Responses

| Response | Meaning |
|---|---|
| `<CMD_ID,ACK>` | Command executed successfully |
| `<CMD_ID,NACK,1>` | Unknown command |
| `<CMD_ID,NACK,2>` | Invalid params |
| `<CMD_ID,NACK,3>` | Busy (previous command still executing) |
| `<0,PONG>` | Heartbeat reply |

## Timing

| Event | Value |
|---|---|
| ACK timeout | 500ms |
| Retry count | 3 |
| Heartbeat interval | 2000ms |
| Heartbeat timeout | 5000ms (→ reconnect) |
| Command queue max | 32 |

## Handshake (on connect)

```
Python: <0,PING>\n
ESP32:  <0,PONG>\n
Python: <1,RESET>\n
ESP32:  <1,ACK>\n
→ Ready
```

## Python Implementation Notes

```python
# connection.py
class SerialConnection:
    def __init__(self, port: str, baud: int = 115200)
    def connect(self) -> bool
    def disconnect(self)
    def is_alive(self) -> bool          # heartbeat check

# protocol.py
class Protocol:
    cmd_counter: int                     # auto-increment ID
    def pack(self, cmd: str, *params) -> bytes
    def parse_response(self, line: bytes) -> tuple[int, str, list]

# command_buffer.py  
class CommandBuffer:
    queue: Queue[Command]                # thread-safe
    def send(self, cmd: str, *params) -> bool  # blocking, waits ACK
    def send_async(self, cmd: str, *params)    # queue for serial thread
```

## ESP32 Parser Pseudocode

```
on serial_available:
    line = read_until('\n')
    strip '<' and '>'
    parts = split(',')
    cmd_id = parts[0]
    command = parts[1]
    params = parts[2:]
    execute(cmd_id, command, params)
    send_response(cmd_id, "ACK")
```
