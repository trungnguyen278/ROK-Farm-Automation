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
| `MOVE` | x,y,duration_ms | `<12,MOVE,500,300,150>` | Move mouse to (x,y) over duration |
| `CLICK` | button,hold_ms | `<13,CLICK,L,80>` | Click button (L/R/M) hold for ms |
| `DCLICK` | button,gap_ms | `<14,DCLICK,L,95>` | Double click with gap between |
| `DRAG` | x1,y1,x2,y2,dur_ms | `<15,DRAG,100,200,500,400,300>` | Drag from→to |
| `SCROLL` | amount | `<16,SCROLL,-3>` | Scroll (negative=down) |
| `KEY` | keycode,hold_ms | `<17,KEY,32,60>` | Press key (USB HID keycode) |
| `COMBO` | mod,keycode | `<18,COMBO,1,4>` | Modifier+key (1=Ctrl, key=A) |
| `PING` | — | `<0,PING>` | Heartbeat check |
| `RESET` | — | `<1,RESET>` | Reset ESP32 state |

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
