# Plan — ROK Farm Automation

> File này là **plan động**, cập nhật liên tục mỗi session. Docs cố định nằm trong `docs/`.

## Current Phase: 7 — Action Execution Pipeline (in progress)
**Started:** 2026-05-15  
**Target:** End-to-end loop: vision → state → task → serial click → verify

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
- [x] Auto-capture templates via ESP32 HID (`tools/auto_capture_templates.py`)
- [x] `states/world_map` template — conf=1.000 (auto-captured via minimap nav)
- [ ] Thiếu: `states/march_screen`, `states/commander_select`, `popups/*` (cần better nav logic)

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

### Phase 5 — Polish ✅
- [x] Logging system — `logging_setup.py` (RotatingFileHandler + console + UI handler)
- [x] Error recovery toàn diện — capture retry, loop exception handling, vision fault isolation
- [x] Config validation — paths, ROI ranges, durations, active_window format, serial timeouts
- [x] requirements.txt final — added Pillow, pywin32, pinned mss>=9.0

### Phase 6 — Real-world Testing 🔄
#### Test Tools (done)
- [x] `tools/test_esp32.py` — ESP32 hardware suite: port detect, PING/PONG 10x, MOVE square, CLICK L/R, SCROLL, KEY, latency benchmark 50x, reconnect test
- [x] `tools/test_vision_live.py` — live vision: capture game → detect state → OpenCV overlay (debug rects, template scan, screenshot save)
- [x] `tools/test_full_loop.py` — end-to-end: vision→state→tasks→serial→HID, dry-run mode, configurable duration/strategy, detailed report
- [x] `tools/test_anti_detection.py` — visualize: Bézier mouse paths, timing histogram, session timeline, fatigue curve, profile stats
- [x] `tools/test_stress.py` — stress: multi-hour run, memory/CPU sampling every 10s, CSV export, leak detection (>50MB), thread stability
- [x] `tools/test_session_monitor.py` — session monitor: real-time console dashboard, state/action tracking, APM, serial health, fatigue display
- [x] `requirements.txt` — added psutil>=5.9.0

#### Manual Testing (cần hardware + game)
- [x] Kết nối ESP32 (COM27) → 8 PASS, 1 WARN (latency avg=70ms)
- [x] Auto-capture templates (ESP32 HID nav): city_view 1.000, world_map 1.000
- [x] Test vision pipeline → city_view conf=1.000 (fresh capture approach)
- [x] Test full loop dry-run 30s → 4 actions (collect, help, gather, train), state detect OK
- [x] Test full loop LIVE 60s (COM27) → 4 serial cmds, 100% ACK
- [x] Verify anti-detection → Bézier 56 steps/move, delay 1217ms±372ms
- [ ] Chạy farm 30 phút → `python -m tools.test_session_monitor --port COM27 --duration 30`
- [x] Stress test 5min → mem +9.8MB (PASS), 0 errors, 0 reconnects, threads stable
- [ ] Stress test 1h+ → cần chạy dài hơn
- [ ] Tune profiles: adjust speed/delay/break params dựa trên kết quả thực tế

#### Bugs Fixed
- [x] Template cache spam warnings → cache missing templates, warn chỉ 1 lần
- [x] city_view template low confidence (0.703→0.999) → re-captured từ game
- [x] Unicode Δ crash trên Windows cp1252 terminal → replaced in stress test
- [x] Auto-capture coords bug: frame coords → screen coords (ESP32 HID click ra desktop)
- [x] Template instability: game lighting/chat thay đổi → fresh capture + threshold 0.65

### Phase 7 — Action Execution Pipeline 🔄
*(Ref: Dylan-Zheng/ROK-Bot, 4x-game-agent, OSROKBOT — xem plan file)*
- [x] ESP32 firmware: `MOVETO` absolute mouse command (`USBHIDAbsoluteMouse`, coords 0-32767)
- [x] Wire serial `CommandBuffer` from UI → Orchestrator (`main.py` + `ui/app.py`)
- [x] `capture/screen_info.py` — screen resolution + `screen_to_hid()` coordinate mapping
- [x] `logic/action_executor.py` — ActionExecutor thread: queue consumer + coordinate pipeline
- [x] Handler: `_handle_dismiss_popup` — find close_btn or click center, verify popup gone
- [x] Handler: `_handle_collect_rewards` — click quest → claim loop → Escape → verify city_view
- [x] Handler: `_handle_alliance_help` — click flag → help all → Escape → verify city_view
- [x] Flash ESP32 firmware + test MOVETO via serial terminal (COM27, 10/10 pass, MOVETO 6/6 ACK)
- [x] Capture `templates/buttons/close_btn.png` từ game (conf=1.000, false-positive city=0.83)
- [ ] Capture `templates/buttons/claim_btn.png` từ game (defer — cần quest hoàn thành mới có nút Claim)
- [x] Test end-to-end: popup auto-dismiss (5/5 PASS — open mail → detect close_btn → click → verify city_view)
- [ ] Test end-to-end: collect rewards (blocked by claim_btn template)
- [ ] Thêm handlers: train, gather, heal (cần thêm templates + navigation logic)

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
| 2026-05-15 | ESP32 firmware flash OK qua COM26→COM27 | VID:PID 303A:1001 (JTAG/Serial), TinyUSB CDC works |
| 2026-05-15 | Re-capture city_view template | Game resolution thay đổi, old template conf=0.703 → new conf=0.999 |
| 2026-05-15 | Cache missing templates in TemplateCache | Avoid warning spam, mỗi missing template chỉ log 1 lần |
| 2026-05-15 | ESP32 HID cần screen coords (frame + window offset) | Frame coords click ra desktop, cần cộng window left/top |
| 2026-05-15 | Template threshold 0.8→0.65 | Game UI thay đổi (lighting, chat) → template confidence dao động |
| 2026-05-15 | Fresh capture trước mỗi session | Template bottom bar bị ảnh hưởng bởi chat/time-of-day |
| 2026-05-15 | USBHIDAbsoluteMouse + MOVETO command | Relative mouse bị drift, absolute chính xác hơn cho template→click |
| 2026-05-15 | Giữ cả MOVE (relative) + MOVETO (absolute) | Backward compat, MOVE dùng cho Bézier humanized paths |
| 2026-05-15 | Firmware: chỉ dùng USBHIDAbsoluteMouse | static init bug: chỉ mouse đầu tiên được đăng ký HID, AbsMouse track position cho MOVE relative |
| 2026-05-15 | close_btn threshold 0.9 | False positive ~0.83 trong city view, cần threshold cao hơn 0.8 để phân biệt |
| 2026-05-15 | Re-capture state templates cho resolution 1480x876 | Templates cũ 1037px wide không match, crop bottom-right 500x80 |
| 2026-05-15 | "Workflow with verification" pattern | Mỗi click phải verify kết quả, retry up to 3x (ref: 4x-game-agent) |
| 2026-05-15 | Tham khảo GitHub ROK bots | Dylan-Zheng, OSROKBOT, 4x-game-agent, Sunuba/roc — tất cả dùng ADB, mình unique ở HW HID |

## Blockers / Issues

_Chưa có_

## Ad-hoc Tasks

_Tasks phát sinh ngoài roadmap — thêm vào đây khi xuất hiện_

| Task | Status | Note |
|---|---|---|
| — | — | — |
