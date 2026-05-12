# Plan — ROK Farm Automation

> File này là **plan động**, cập nhật liên tục mỗi session. Docs cố định nằm trong `docs/`.

## Current Phase: 1 — ESP32 Firmware + Serial Protocol
**Started:** 2026-05-12  
**Target:** Firmware + Python serial comm hoạt động end-to-end

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

### Phase 2 — Vision 🔲
- [ ] `capture/screen_capture.py`
- [ ] `vision/template_cache.py`
- [ ] `vision/template_matcher.py`
- [ ] `vision/state_detector.py`
- [ ] Chụp template screenshots từ game
- [ ] Test: match template trên screenshot tĩnh

### Phase 3 — Logic 🔲
- [ ] `config.py` + `config.yaml` + `config.example.yaml`
- [ ] `logic/state_machine.py`
- [ ] `logic/task_scheduler.py`
- [ ] `logic/farm_strategies.py`
- [ ] `main.py` — threading orchestrator
- [ ] Test: state transitions với mock vision

### Phase 4 — Anti-Detection 🔲
- [ ] `anti_detection/mouse_humanizer.py`
- [ ] `anti_detection/timing_engine.py`
- [ ] `anti_detection/session_manager.py`
- [ ] `anti_detection/profile_loader.py`
- [ ] `profiles/default.json` + `cautious.json` + `aggressive.json`
- [ ] Test: so sánh raw vs humanized output

### Phase 5 — Polish 🔲
- [ ] Logging system
- [ ] Error recovery toàn diện
- [ ] Config validation
- [ ] requirements.txt final

---

## Decisions Log

| Date | Decision | Why |
|---|---|---|
| 2026-05-12 | Docs trước code | Đảm bảo architecture rõ ràng, tránh refactor |
| 2026-05-12 | Text-based serial protocol | Dễ debug, monitor bằng terminal |
| 2026-05-12 | 3 thread model | Tách capture/logic/serial, tránh blocking |

## Blockers / Issues

_Chưa có_

## Ad-hoc Tasks

_Tasks phát sinh ngoài roadmap — thêm vào đây khi xuất hiện_

| Task | Status | Note |
|---|---|---|
| — | — | — |
