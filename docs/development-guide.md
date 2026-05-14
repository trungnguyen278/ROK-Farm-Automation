# Development Guide

> **AI Note:** Setup 2 phần: Python host (pip) + ESP32 firmware (PlatformIO). Dev workflow: firmware trước → test serial → rồi Python modules theo roadmap phase.

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.10+ | Host application |
| PlatformIO CLI | latest | ESP32 firmware build/upload |
| Git | latest | Version control |
| ROK | PC client or BlueStacks | Target game |

## 1. ESP32 Firmware Setup

```bash
# Install PlatformIO CLI
pip install platformio

# Build firmware
cd esp32-s3
pio run

# Upload to ESP32-S3
pio run -t upload

# Test serial (monitor)
pio device monitor -b 115200
# Type: <0,PING>  → expect: <0,PONG>
```

## 2. Python Host Setup

```bash
# Create venv
python -m venv venv
venv\Scripts\activate        # Windows

# Install dependencies
pip install -r requirements.txt
```

### requirements.txt
```
mss>=9.0
opencv-python>=4.8
pyserial>=3.5
pyyaml>=6.0
numpy>=1.24
Pillow>=10.0
pywin32>=306
```

## 3. Config

```bash
# Copy example config
copy config.example.yaml config.yaml

# Edit COM port (find in Device Manager)
# Edit window_title if using BlueStacks
```

## 4. Run

```bash
python main.py
# or with specific config
python main.py --config my_config.yaml
```

## Project Structure After Implementation

```
rok-automation/
├── main.py
├── config.py                  # Config loader + validation
├── config.yaml
├── config.example.yaml
├── requirements.txt
├── ui/
│   ├── __init__.py
│   ├── app.py                 # MainApp(tk.Tk), tab manager
│   ├── tab_control.py         # Start/stop, strategy select
│   ├── tab_monitor.py         # Screenshot + vision overlay
│   ├── tab_config.py          # Config editor GUI
│   ├── tab_profile.py         # Profile editor GUI
│   ├── tab_stats.py           # Statistics, charts
│   ├── log_panel.py           # Scrollable log widget
│   ├── status_bar.py          # Bottom status bar
│   └── utils.py               # LNK resolver, image helpers
├── capture/
│   ├── __init__.py
│   └── screen_capture.py
├── vision/
│   ├── __init__.py
│   ├── template_matcher.py
│   ├── state_detector.py
│   └── template_cache.py
├── logic/
│   ├── __init__.py
│   ├── state_machine.py
│   ├── task_scheduler.py
│   └── farm_strategies.py
├── anti_detection/
│   ├── __init__.py
│   ├── mouse_humanizer.py
│   ├── timing_engine.py
│   ├── session_manager.py
│   └── profile_loader.py
├── serial_comm/
│   ├── __init__.py
│   ├── connection.py
│   ├── protocol.py
│   └── command_buffer.py
├── profiles/
│   ├── default.json
│   ├── cautious.json
│   └── aggressive.json
├── templates/
│   ├── buttons/
│   ├── popups/
│   ├── states/
│   └── resources/
├── esp32-s3/
│   ├── src/main.cpp
│   ├── include/commands.h
│   └── platformio.ini
├── logs/
├── tests/
├── docs/
└── CLAUDE.md
```

## Development Order (follow roadmap phases)

| Phase | Modules | Test |
|---|---|---|
| 1 | esp32-s3/src/main.cpp, serial_comm/* | PING/PONG, MOVE/CLICK trên desktop |
| 2 | capture/*, vision/* | Template match screenshot tĩnh |
| 3 | logic/*, config.py, main.py | State transitions với mock vision |
| 4 | anti_detection/* | So sánh output raw vs humanized |
| 5 | profiles/*, logging, error recovery | Full integration test |

## Testing Tips

```bash
# Test serial without game (move mouse on desktop)
python -c "
from serial_comm.connection import SerialConnection
conn = SerialConnection('COM3')
conn.connect()
conn.send('MOVE', 100, 100, 500)
"

# Test vision with static screenshot
python -c "
from vision.template_matcher import TemplateMatcher
m = TemplateMatcher()
result = m.match_single(cv2.imread('test.png'), 'buttons/ok')
print(result)
"
```
