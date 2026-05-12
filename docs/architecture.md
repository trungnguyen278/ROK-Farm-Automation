# Architecture

> **AI Note:** System gồm 6 module chạy trên 3 thread. Python host xử lý vision+logic, gửi lệnh qua Serial tới ESP32-S3 phát HID. Mọi action đều qua Anti-Detection trước khi gửi.

## System Flow

```
Game Window → mss capture → OpenCV match → State Machine → Anti-Detection → Serial → ESP32 → USB HID
```

## Threads

| Thread | Responsibilities | Communication |
|---|---|---|
| Main | State machine, task scheduler, decision | Reads vision results, writes action queue |
| Capture | Screen grab (30-60fps), vision analysis (2-5fps) | Publishes results via `queue.Queue` |
| Serial | Send commands, wait ACK, heartbeat | Consumes action queue |

## Module Map

```
main.py                          # Entry point, thread orchestrator
capture/screen_capture.py        # mss grab, ROI crop
vision/template_matcher.py       # OpenCV matchTemplate, multi-scale
vision/state_detector.py         # Determine current game screen
vision/template_cache.py         # LRU cache for loaded templates
logic/state_machine.py           # Game state transitions
logic/task_scheduler.py          # Priority queue, retry with backoff
logic/farm_strategies.py         # Task definitions per farm type
anti_detection/mouse_humanizer.py  # Bézier paths, jitter, overshoot
anti_detection/timing_engine.py    # Gaussian delays, micro-pauses
anti_detection/session_manager.py  # Break cycles, fatigue, daily schedule
anti_detection/profile_loader.py   # Load behavior profile JSON
serial_comm/connection.py        # pyserial connect, auto-reconnect
serial_comm/protocol.py          # Pack/parse commands, ACK handling
serial_comm/command_buffer.py    # Queue commands, sequential send
profiles/*.json                  # Behavior parameter sets
templates/*.png                  # OpenCV template images
config.yaml                      # Global config
```

## Error Recovery

| Layer | Error | Action |
|---|---|---|
| Capture | Window gone | Retry 30s, then alert |
| Vision | No match | Return None → state machine stays |
| Serial | Disconnect | Auto-reconnect, exponential backoff |
| Serial | No ACK | Retry 3x, then skip |
| Logic | Unknown state | Enter idle, wait for known state |

## Anti-Detection Stack (5 layers, independent)

1. **Hardware** — ESP32 HID = real USB device to OS
2. **Movement** — Bézier curves, overshoot, jitter
3. **Timing** — Gaussian delays, micro-pauses
4. **Session** — Farm/rest cycles, fatigue simulation
5. **Profile** — Randomized behavior personality per session
