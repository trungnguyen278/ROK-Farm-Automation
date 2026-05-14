# Architecture

> **AI Note:** System gồm 7 module chạy trên 4 thread. tkinter UI trên main thread, logic/capture/serial trên workers. Mọi action đều qua Anti-Detection trước khi gửi serial.

## System Flow

```
Game Window → mss capture → OpenCV match → State Machine → Anti-Detection → Serial → ESP32 → USB HID
                                  ↕
                        tkinter Dashboard (control, monitor, config, stats)
```

## Threads

| Thread | Responsibilities | Communication |
|---|---|---|
| Main (UI) | tkinter event loop, dashboard display | `after()` polls queues for updates |
| Logic | State machine, task scheduler, decision | Reads vision results, writes action queue |
| Capture | Screen grab (30-60fps), vision analysis (2-5fps) | Publishes results via `queue.Queue` |
| Serial | Send commands, wait ACK, heartbeat | Consumes action queue |

> tkinter **must** run on main thread. Logic thread tách ra thành worker.

## Module Map

```
main.py                          # Entry point, launches UI + worker threads
ui/app.py                        # MainApp(tk.Tk), tab manager, startup
ui/tab_control.py                # Start/stop, strategy, ESP32 status
ui/tab_monitor.py                # Screenshot + vision overlay
ui/tab_config.py                 # Config editor, save/load
ui/tab_profile.py                # Profile editor
ui/tab_stats.py                  # Statistics, charts, export
ui/log_panel.py                  # Scrollable log widget
ui/status_bar.py                 # Bottom status bar
ui/utils.py                      # LNK resolver, image conversion
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
