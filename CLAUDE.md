# ROK Farm Automation — Project Context

## Workflow Rules
1. **Mỗi session:** Đọc `PLAN.md` trước khi làm bất kỳ task nào
2. **Sau mỗi task xong:** Update `PLAN.md` ngay (tick checkbox, thêm decision/blocker nếu có)
3. **Task phát sinh:** Thêm vào bảng Ad-hoc Tasks trong `PLAN.md`
4. **Khi code:** Chỉ cần đọc doc liên quan đến module đang code (xem Docs Index bên dưới), không đọc hết
5. **Ngôn ngữ:** Giao tiếp tiếng Việt, code + comments tiếng Anh
6. **UI positions:** KHÔNG estimate tọa độ nút bấm từ screenshot. Nếu cần template/position cho bất kỳ nút nào → yêu cầu user chụp screenshot và cung cấp

## What is this
Automation tool for Rise of Kingdoms (PC). Python host does screen capture + OpenCV vision + decision logic, sends commands via Serial to ESP32-S3 which emits real USB HID (mouse/keyboard). OS sees a real input device → undetectable at driver level.

## Current Status
- **Phase:** Phase 0 docs done → sắp bắt đầu Phase 1
- **Exists:** README.md, CLAUDE.md, PLAN.md, docs/ (8 files), empty PlatformIO project
- **Next:** Phase 1 (ESP32 firmware + serial protocol)
- **Live plan:** Xem [PLAN.md](PLAN.md) — cập nhật tiến độ, decisions, blockers, ad-hoc tasks

## Architecture (TL;DR)
```
Game Window → mss → OpenCV → State Machine → Anti-Detection → Serial → ESP32-S3 → USB HID
                                    ↕
                          tkinter Dashboard (control, monitor, config, stats)
```
4 threads: UI/Main (tkinter), Capture (grab+vision), Logic (state machine+scheduler), Serial (send+ACK).

## Module Map
```
main.py                            — entry point, orchestrator
ui/app.py                          — tkinter MainApp, tab manager
ui/tab_control.py                  — start/stop, strategy, ESP32 status
ui/tab_monitor.py                  — screenshot + vision overlay
ui/tab_config.py                   — config editor GUI
ui/tab_profile.py                  — profile editor GUI
ui/tab_stats.py                    — statistics, charts, export CSV
ui/log_panel.py                    — scrollable log widget
ui/status_bar.py                   — bottom status bar
ui/utils.py                        — LNK resolver, image helpers
capture/screen_capture.py          — mss, ROI crop
vision/template_matcher.py         — OpenCV matchTemplate, multi-scale
vision/state_detector.py           — detect current game screen
vision/template_cache.py           — LRU cache loaded templates
logic/state_machine.py             — game state transitions
logic/task_scheduler.py            — priority queue, retry+backoff
logic/farm_strategies.py           — per-farm-type task defs
anti_detection/mouse_humanizer.py  — Bézier, jitter, overshoot
anti_detection/timing_engine.py    — Gaussian delays, micro-pauses
anti_detection/session_manager.py  — break cycles, fatigue, daily schedule
anti_detection/profile_loader.py   — load behavior profile JSON
serial_comm/connection.py          — pyserial, auto-reconnect
serial_comm/protocol.py            — pack/parse commands, ACK
serial_comm/command_buffer.py      — queue + sequential send
profiles/*.json                    — behavior parameter sets
templates/*.png                    — OpenCV template images
config.yaml                        — global config
esp32-s3/                          — PlatformIO firmware project
```

## Tech Stack
Python 3.10+ | mss | opencv-python | pyserial | pyyaml | numpy | Pillow | pywin32
ESP32-S3 DevKitC | PlatformIO | Arduino framework | USB HID libs
UI: tkinter (built-in) + Pillow (image display) + pywin32 (LNK/window management)

## Serial Protocol (Python ↔ ESP32)
Format: `<CMD,param1,param2,...>\n` → ESP32 replies `<ACK,cmd_id>\n` or `<NACK,cmd_id,error>\n`
Commands: MOVE, CLICK, DRAG, SCROLL, KEY, COMBO, PING/PONG
Baud: 115200 | Heartbeat: PING every 2s

## Anti-Detection (5 independent layers)
1. Hardware HID — real USB device
2. Movement — Bézier curves + overshoot + micro-jitter
3. Timing — Gaussian delays (800-2000ms), micro-pauses (2-5s)
4. Session — farm 15-40min → rest 5-15min, fatigue sim
5. Profile — randomized behavior personality per session

## Roadmap
1. ~~Docs~~ → **Phase 1:** ESP32 firmware + serial protocol
2. **Phase 2:** Screen capture + template matching
3. **Phase 3:** State machine + task scheduler
4. **Phase 4:** Anti-detection engine integration
5. **Phase 5:** Profiles, config UI, logging, error recovery

## Conventions
- Language: Python (host), C++ Arduino (firmware)
- Config: YAML for global, JSON for profiles
- Comms: All serial commands are text-based, newline-terminated
- Threading: queue.Queue for inter-thread, threading.Event for signals
- Error: Auto-reconnect serial, retry 3x with backoff, idle on unknown state

## Template Images (templates/)
UI action code uses `cv2.matchTemplate` on these. If adding a new action that clicks a game UI element, ask user to capture the template.
```
buttons/city_btn.png               — world map city button
ui/mail_tab_personal.png           — mail tab "CA NHAN"
ui/mail_tab_reports.png            — mail tab "BAO CAO"
ui/mail_tab_alliance.png           — mail tab "LIEN MINH"
ui/mail_tab_system.png             — mail tab "HE THONG"
ui/mail_read_all_btn.png           — "Doc va nhan tat" button
ui/mail_close_btn.png              — mail panel X close button
```

## Docs Index
- [docs/architecture.md](docs/architecture.md) — system design, threads, module map
- [docs/serial-protocol.md](docs/serial-protocol.md) — full protocol spec
- [docs/esp32-firmware.md](docs/esp32-firmware.md) — firmware design, HID commands
- [docs/vision-system.md](docs/vision-system.md) — capture + template matching
- [docs/anti-detection.md](docs/anti-detection.md) — all 5 layers detailed
- [docs/state-machine.md](docs/state-machine.md) — states, transitions, scheduler
- [docs/config-reference.md](docs/config-reference.md) — all config options
- [docs/ui-dashboard.md](docs/ui-dashboard.md) — tkinter dashboard design, tabs, threading
- [docs/development-guide.md](docs/development-guide.md) — setup, build, test
