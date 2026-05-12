# ESP32-S3 Firmware Design

> **AI Note:** Arduino framework trên PlatformIO. Hai USB interface: CDC (Serial nhận lệnh từ Python) + HID (Mouse+Keyboard output). Parse text command → execute HID action → ACK.

## Hardware

| Item | Spec |
|---|---|
| Board | ESP32-S3 DevKitC (N16R8) |
| USB | Native USB-OTG (GPIO19=D-, GPIO20=D+) |
| Framework | Arduino via PlatformIO |
| USB mode | CDC + HID composite device |

## PlatformIO Config

```ini
[env:esp32-s3-devkitc1-n16r8]
platform = espressif32
board = esp32-s3-devkitc1-n16r8
framework = arduino
build_flags =
    -DARDUINO_USB_MODE=1
    -DARDUINO_USB_CDC_ON_BOOT=1
monitor_speed = 115200
```

## USB Descriptors

Device presents as composite USB device:
1. **CDC ACM** — virtual serial port for Python commands
2. **HID Mouse** — absolute/relative mouse
3. **HID Keyboard** — standard 104-key keyboard

## Firmware Architecture

```
setup()
  ├── USB.begin()          # Init composite USB
  ├── USBHIDMouse.begin()  # Init HID mouse
  ├── USBHIDKeyboard.begin()
  └── Serial.begin(115200) # CDC serial

loop()
  ├── check_serial()       # Parse incoming commands
  ├── execute_command()     # Run HID action
  └── send_response()      # ACK/NACK back
```

## Command Handlers

| Command | HID Action | Implementation |
|---|---|---|
| `MOVE` | `Mouse.move(dx, dy)` | Relative move, split into steps if duration > 0 |
| `CLICK` | `Mouse.press()` → delay → `Mouse.release()` | Button: MOUSE_LEFT/RIGHT/MIDDLE |
| `DCLICK` | press→release→delay→press→release | Gap between clicks from param |
| `DRAG` | `Mouse.press()` → move steps → `Mouse.release()` | Combined move+click |
| `SCROLL` | `Mouse.move(0,0,scroll)` | Scroll wheel amount |
| `KEY` | `Keyboard.press()` → delay → `Keyboard.release()` | USB HID keycode |
| `COMBO` | `Keyboard.press(mod)` → `Keyboard.press(key)` → release all | Modifier bitmask |
| `PING` | — | Reply PONG immediately |
| `RESET` | Release all keys/buttons | Clear HID state |

## Mouse Movement (MOVE with duration)

ESP32 splits long moves into small steps to simulate smooth movement:

```cpp
void execute_move(int target_x, int target_y, int duration_ms) {
    int steps = duration_ms / STEP_INTERVAL_MS;  // ~5ms per step
    float dx = (float)target_x / steps;
    float dy = (float)target_y / steps;
    float accum_x = 0, accum_y = 0;
    for (int i = 0; i < steps; i++) {
        accum_x += dx; accum_y += dy;
        int mx = (int)accum_x; int my = (int)accum_y;
        Mouse.move(mx, my);
        accum_x -= mx; accum_y -= my;
        delay(STEP_INTERVAL_MS);
    }
}
```

## Modifier Bitmask (for COMBO)

| Bit | Modifier |
|---|---|
| 0x01 | Left Ctrl |
| 0x02 | Left Shift |
| 0x04 | Left Alt |
| 0x08 | Left GUI (Win) |

## Error Codes

| Code | Meaning |
|---|---|
| 1 | Unknown command |
| 2 | Invalid/missing params |
| 3 | Busy executing previous |

## Key Files

```
esp32-s3/
├── src/
│   └── main.cpp          # setup(), loop(), all handlers
├── include/
│   └── commands.h         # Command constants, parser structs
├── platformio.ini
└── test/                  # Serial loopback tests
```

## Flash & Test

```bash
# Build + upload
pio run -t upload

# Monitor serial
pio device monitor -b 115200

# Test handshake
# Send: <0,PING>\n → Expect: <0,PONG>\n
```
