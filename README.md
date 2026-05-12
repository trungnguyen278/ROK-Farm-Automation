# ROK Farm Automation

Tự động hóa Rise of Kingdoms (PC) bằng computer vision + hardware HID.  
Python nhận diện game qua OpenCV → ra quyết định → gửi lệnh qua Serial → ESP32-S3 phát USB HID thật.

## Kiến trúc

```
Game Window → mss capture → OpenCV match → State Machine → Anti-Detection → Serial → ESP32 → USB HID
```

| Layer | Tech | Role |
|---|---|---|
| Screen Capture | `mss` | Chụp cửa sổ game, crop ROI |
| Vision | `OpenCV` | Template matching nhận diện UI |
| Logic | Python | State machine + task scheduler |
| Anti-Detection | Python + numpy | Bézier mouse, timing Gaussian, session patterns |
| Communication | `pyserial` | UART protocol với ESP32 |
| HID Output | ESP32-S3 | USB Mouse + Keyboard thật |

## Anti-Detection (5 layers)

1. **Hardware HID** — OS thấy USB device thật, không phải software injection
2. **Mouse path** — Bézier curve + overshoot + jitter, không đi thẳng
3. **Timing** — Gaussian delays, micro-pauses, không đều đặn
4. **Session** — Farm/nghỉ cycles, fatigue simulation, daily schedule
5. **Profile** — Random behavior personality mỗi session

## Quick Start

```bash
# 1. Flash ESP32-S3
cd esp32-s3 && pio run -t upload

# 2. Python setup
python -m venv venv && venv\Scripts\activate
pip install mss opencv-python pyserial pyyaml numpy

# 3. Config
copy config.example.yaml config.yaml
# Sửa COM port + window title

# 4. Run
python main.py
```

## Yêu cầu

**Phần cứng:** ESP32-S3 DevKitC + cáp USB-C  
**Phần mềm:** Python 3.10+ | PlatformIO | ROK trên PC (BlueStacks/native)

## Trạng thái

Đang ở giai đoạn **documentation** — chưa có code implementation.

## Roadmap

| Phase | Nội dung | Status |
|---|---|---|
| 0 | Documentation & design | **In progress** |
| 1 | ESP32 firmware + serial protocol | Pending |
| 2 | Screen capture + template matching | Pending |
| 3 | State machine + task scheduler | Pending |
| 4 | Anti-detection engine | Pending |
| 5 | Profiles, config UI, logging | Pending |

## Documentation

| Doc | Nội dung |
|---|---|
| [Architecture](docs/architecture.md) | System design, threads, module map |
| [Serial Protocol](docs/serial-protocol.md) | UART protocol spec Python↔ESP32 |
| [ESP32 Firmware](docs/esp32-firmware.md) | Firmware design, HID commands |
| [Vision System](docs/vision-system.md) | Capture + template matching |
| [Anti-Detection](docs/anti-detection.md) | All 5 layers detailed |
| [State Machine](docs/state-machine.md) | States, transitions, scheduler |
| [Config Reference](docs/config-reference.md) | All config.yaml options |
| [Development Guide](docs/development-guide.md) | Setup, build, test |
