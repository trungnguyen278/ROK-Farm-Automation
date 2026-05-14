# Plan — ROK Farm Automation

> File này là **plan động**, cập nhật liên tục mỗi session. Docs cố định nằm trong `docs/`.

## Current Phase: 4 — Anti-Detection (done) → next: Phase 5
**Started:** 2026-05-12  
**Target:** Mouse humanizer, timing engine, session manager, profile system

## Progress

### Phase 0 — Documentation ✅
- [x] README.md
- [x] CLAUDE.md (project memory)
- [x] docs/architecture.md
- [x] docs/serial-protocol.md
- [x] docs/esp32-firmware.md
- [x] docs/vision-system.md
- [x] docs/anti-detection.md
- [x] docs/state-machine.md
- [x] docs/config-reference.md
- [x] docs/development-guide.md

### Phase 1 — ESP32 Firmware + Serial Protocol ✅
- [x] ESP32 firmware `src/main.cpp` — command parser + HID handlers
- [x] ESP32 `include/commands.h` — constants, structs
- [x] Python `serial_comm/connection.py` — connect, heartbeat, reconnect
- [x] Python `serial_comm/protocol.py` — pack/parse commands
- [x] Python `serial_comm/command_buffer.py` — queue + sequential send
- [x] Test: PING/PONG handshake (`tests/test_handshake.py`)
- [x] Test: MOVE/CLICK trên desktop (`tests/test_hid.py`)

### Phase 1.5 — UI Dashboard ✅
- [x] `ui/app.py` — MainApp, tab manager, thread launcher
- [x] `ui/tab_control.py` — start/stop, strategy, ESP32 status, game launch
- [x] `ui/log_panel.py` — scrollable log widget (thread-safe)
- [x] `ui/status_bar.py` — state, session time, ESP32 status
- [x] `ui/utils.py` — LNK resolver, image conversion helpers
- [x] `ui/tab_monitor.py` — screenshot preview + vision overlay
- [x] `ui/tab_config.py` — config editor GUI, save/load
- [x] `ui/tab_profile.py` — profile editor GUI
- [x] `ui/tab_stats.py` — statistics, session history, export CSV
- [x] `main.py` — entry point
- [x] `config.yaml` + `profiles/*.json` — default config + 3 profiles
- [x] Test: UI launch OK (import + mainloop verified)

### Phase 2 — Vision ✅
- [x] `capture/screen_capture.py` — mss grab + ROI crop + win32gui window find
- [x] `vision/template_cache.py` — LRU OrderedDict, eviction, preload
- [x] `vision/template_matcher.py` — multi-scale matchTemplate + NMS + match_all/match_best
- [x] `vision/state_detector.py` — GameScreen enum + SCREEN_TEMPLATES mapping
- [x] Template directory structure (`templates/{buttons,popups,states,resources}/`)
- [x] Test: 15 tests pass (`tests/test_vision.py`) — cache, matcher, state detector
- [x] Template capture tool (`tools/capture_templates.py`) — zoom, pan, keyboard shortcuts
- [x] City view templates: 10 templates chụp từ game thật, all match 1.000 confidence
- [ ] Thêm templates cho world_map, popups, alliance... (tự động khi ESP32 HID kết nối)

### Phase 3 — Logic ✅
- [x] `config.py` — dataclass config loader from YAML + validation
- [x] `config.example.yaml` — annotated example config
- [x] `logic/state_machine.py` — GameState enum, StateMachine (transitions, listeners, timeout→ERROR)
- [x] `logic/task_scheduler.py` — Task, TaskType, TaskScheduler (heap, retry+backoff, dedup)
- [x] `logic/farm_strategies.py` — FarmStrategy, 3 strategies (basic_gather, war_prep, alliance_focus)
- [x] `main.py` — Orchestrator class (capture+logic threads, vision→state→tasks→actions pipeline)
- [x] `ui/app.py` — wired Orchestrator to UI start/stop/pause, state polling
- [x] Test: 36 tests pass (config, state machine, scheduler, strategies)

### Phase 4 — Anti-Detection ✅
- [x] `anti_detection/profile_loader.py` — load JSON, deep merge defaults, random pick
- [x] `anti_detection/mouse_humanizer.py` — Bézier paths, ease-in-out, overshoot, click offset, jitter
- [x] `anti_detection/timing_engine.py` — Gaussian delays, micro pauses, fatigue model
- [x] `anti_detection/session_manager.py` — farm/rest cycles, daily limit, active window, idle actions
- [x] `profiles/default.json` + `cautious.json` + `aggressive.json` — full spec with mouse/timing/session
- [x] Integrated into Orchestrator: timing delays, fatigue, session breaks, humanized clicks
- [x] Test: 38 tests pass (profile loader, humanizer, timing, session, variance comparison)

### Phase 5 — Polish 🔲
- [ ] Logging system
- [ ] Error recovery toàn diện
- [ ] Config validation
- [ ] requirements.txt final

### Phase 6 — Real-world Testing 🔲
- [ ] Kết nối ESP32 thật → verify PING/PONG, MOVE/CLICK trên desktop
- [ ] Mở game ROK → chụp templates cho tất cả screens (world_map, popups, alliance…)
- [ ] Test vision pipeline end-to-end: capture → detect state → đúng GameScreen
- [ ] Test full loop: vision → state machine → task scheduler → serial → HID action
- [ ] Verify anti-detection: quan sát mouse path (Bézier smooth?), timing (không đều?), session breaks
- [ ] Chạy farm thật 30 phút → monitor logs, stats, error recovery
- [ ] Stress test: chạy nhiều giờ liên tục → kiểm tra memory leak, crash, reconnect
- [ ] Tune profiles: adjust speed/delay/break params dựa trên kết quả thực tế
- [ ] Ghi lại bugs/issues phát sinh vào Blockers section

---

## Decisions Log

| Date | Decision | Why |
|---|---|---|
| 2026-05-12 | Docs trước code | Đảm bảo architecture rõ ràng, tránh refactor |
| 2026-05-12 | Text-based serial protocol | Dễ debug, monitor bằng terminal |
| 2026-05-12 | 3 thread model | Tách capture/logic/serial, tránh blocking |
| 2026-05-12 | Thêm UI dashboard (tkinter) | Full dashboard: control, monitor, config, profile, stats |
| 2026-05-12 | 4 thread model (UI trên main) | tkinter bắt buộc main thread → logic tách thành worker |
| 2026-05-12 | Thêm Pillow + pywin32 | Cần cho image display trong tkinter + .lnk resolve |
| 2026-05-14 | Hoãn templates còn lại đến khi có ESP32 HID | Tự động navigate game + chụp, không cần manual |

## Blockers / Issues

_Chưa có_

## Ad-hoc Tasks

_Tasks phát sinh ngoài roadmap — thêm vào đây khi xuất hiện_

| Task | Status | Note |
|---|---|---|
| — | — | — |
