# Plan: Action Execution Pipeline

> Mục tiêu: wire end-to-end loop **vision → state → task → serial click → verify** để bot thực sự thao tác được trong game.

## 1. GitHub Reference Projects

ROK là game lâu đời, nhiều bot đã open-source. Tất cả đều target **Android emulator (ADB)** — dự án mình unique ở PC client + hardware HID (ESP32-S3).

### 1.1 Dự án chính cần đọc code

| Project | URL | Tech | Tham khảo gì |
|---------|-----|------|--------------|
| **Dylan-Zheng/Rise-of-Kingdoms-Bot** | https://github.com/Dylan-Zheng/Rise-of-Kingdoms-Bot | Python, OpenCV, Pytesseract, ADB | **Task sequences đầy đủ nhất:** claim quests, VIP rewards, gifts, collect city resources, gather world map, donate tech, train troops, captcha pass, attack barbs, mystery merchant. **Xem action sequences để copy logic click flow cho mỗi task** |
| **OSROKBOT** | https://github.com/GabrielAgrela/OSROKBOT | Python, OpenCV, PyAutoGUI, ChatGPT | **State machine pattern rõ ràng:** action → verify → next state. Lyceum quiz, farm RSS, farm barbs, captcha detection. MIT license. **Xem cách tổ chức state machine configs** |
| **4x-game-agent** | https://github.com/sonpiaz/4x-game-agent | Python, LLM, OCR, YAML | **Architecture 5 layer tham khảo:** (1) Pixel classify <100ms (2) State machine + popup handling (3) World model + timer predictions (4) Scripted tap sequences with verification (5) LLM vision fallback ~$0.004/call. **"Workflow with verification" pattern là must-have** |
| **Sunuba/roc** | https://github.com/Sunuba/roc | Python | **Template naming checklist:** `ask_help_button`, `btnSearch`, `help_others`, `isHome`, `isOutSide`, `red_cross_hospital`, `returning`, `search_plus_button`, `verify_button`. **Danh sách UI elements cần capture** |

### 1.2 Anti-detection reference

| Project | URL | Tham khảo gì |
|---------|-----|--------------|
| **HumanCursor** | https://github.com/riflosnake/HumanCursor | Bezier motion với variable speed, acceleration, curvature. Bypass bot detection. Tham khảo cho `mouse_humanizer.py` |
| **human_mouse** | https://github.com/sarperavci/human_mouse | Ultra-realistic Bezier + spline interpolation |

### 1.3 Key takeaways

- **Pattern chung:** template matching + state machine + "click → verify → retry/next"
- **Dylan-Zheng** có click flow chi tiết nhất — copy logic cho collect, train, help, gather
- **4x-game-agent** có "workflow with verification" pattern — mỗi click PHẢI verify kết quả trước khi tiếp tục
- **Sunuba/roc** có danh sách UI elements cần capture — dùng làm checklist
- Mình unique ở hardware HID via ESP32-S3 — stealth level cao hơn tất cả (ADB detectable, pyautogui detectable, HID = real device)

### 1.4 Việc cần làm với GitHub repos

- [ ] Đọc code `Dylan-Zheng`: folder cấu trúc action sequences, xem cách define click flows cho từng task
- [ ] Đọc code `OSROKBOT`: cách organize state machine configs, action → verify pattern
- [ ] Đọc code `4x-game-agent`: 5-layer architecture, workflow verification, popup handling strategy
- [ ] Đọc code `Sunuba/roc`: danh sách template names, lấy checklist UI elements cần chụp
- [ ] So sánh template matching approach giữa các projects, chọn cải tiến nào áp dụng được

---

## 2. Current State (đã build xong)

```
Game Window → mss → OpenCV → State Machine → Anti-Detection → Serial → ESP32-S3 → USB HID
                                    ↕
                          tkinter Dashboard
```

- Vision: detect city_view + world_map (2 state templates)
- Logic: state machine + task scheduler + 3 strategies
- Anti-detection: Bezier mouse, Gaussian timing, session breaks, fatigue
- Serial: ESP32 connected (COM27), PING/PONG/MOVE/CLICK working
- UI: 5-tab dashboard

**Vấn đề:** System nhìn được game, biết đang ở đâu, tạo tasks — nhưng KHÔNG biết bấm gì và KHÔNG có đường nối đến ESP32 để bấm.

---

## 3. Implementation Steps

### Step 1: ESP32 Firmware — MOVETO (Absolute Mouse) ✅

ESP32 firmware thêm `USBHIDAbsoluteMouse` + command `MOVETO` (coords 0-32767).
Giữ `MOVE` (relative) cho Bezier humanized paths.

Files: `esp32-s3/src/main.cpp`, `esp32-s3/include/commands.h`

### Step 2: Wire Serial to Orchestrator ✅

`MainApp` truyền `CommandBuffer` + `TemplateMatcher` → `Orchestrator` → `ActionExecutor`.

Files: `main.py`, `ui/app.py`

### Step 3: Screen Resolution Helper ✅

`capture/screen_info.py` — map screen pixels → HID absolute (0-32767).

### Step 4: ActionExecutor + Handlers ✅ (skeleton)

`logic/action_executor.py` — thread đọc `action_queue`, dispatch handlers:

| Handler | Flow | Templates cần |
|---------|------|---------------|
| `dismiss_popup` | find close_btn → click → verify not popup | `buttons/close_btn` |
| `collect_rewards` | click quest_btn → claim loop → Escape → verify city | `buttons/quest_btn` ✅, `buttons/claim_btn` |
| `alliance_help` | click flag → help all → Escape → verify city | `buttons/flag` ✅, `buttons/help_all_btn` |

Coordinate pipeline: `Template Match (frame px) → +window offset → screen px → ×32767/resolution → HID absolute`

### Step 5: Flash + Test MOVETO 🔜

- [ ] PlatformIO build + flash ESP32
- [ ] Test MOVETO qua serial terminal: `<2,MOVETO,16383,16383>` → cursor giữa màn hình
- [ ] Test MOVETO + CLICK combo

### Step 6: Capture Button Templates 🔜

Chạy `python -m tools.capture_templates` để chụp:
- [ ] `templates/buttons/close_btn.png` — nút X đóng popup
- [ ] `templates/buttons/claim_btn.png` — nút claim quest
- [ ] `templates/buttons/help_all_btn.png` — nút help all alliance

### Step 7: End-to-End Test 🔜

- [ ] Mở game → chạy app → connect ESP32 → start
- [ ] Game popup → auto-dismiss
- [ ] Quest available → auto-collect
- [ ] Alliance help → auto-help

### Step 8: Thêm Handlers (sau khi Step 7 OK)

*(Tham khảo click flows từ Dylan-Zheng/Rise-of-Kingdoms-Bot)*

| Handler | Cần thêm | Complexity |
|---------|----------|------------|
| `train_troops` | Template barracks/training button, training panel | Medium |
| `heal_troops` | Template hospital, heal button | Medium |
| `gather_resource` | Navigate to world map, find resource node, march sequence | High |
| `upgrade_building` | Click building, upgrade button, resource check | High |

---

## 4. Architecture Diagram (after pipeline wired)

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator                              │
│                                                              │
│  Capture Thread     Logic Thread        Action Thread        │
│  ┌──────────┐      ┌──────────────┐    ┌────────────────┐   │
│  │ mss grab │─────▶│ StateDetector│    │ ActionExecutor │   │
│  │ + vision │      │ StateMachine │    │                │   │
│  └──────────┘      │ TaskScheduler│    │ click_template │   │
│                    │ FarmStrategy │    │ frame→screen   │   │
│                    └──────┬───────┘    │ screen→HID     │   │
│                           │            │ verify state   │   │
│                    action_queue        └───────┬────────┘   │
│                           │                    │            │
│                           └────────────────────┘            │
│                                        │                    │
│                              Anti-Detection                 │
│                           (timing + humanizer)              │
└────────────────────────────────┬────────────────────────────┘
                                 │ CommandBuffer
                                 ▼
                           Serial (COM27)
                                 │
                                 ▼
                         ESP32-S3 USB HID
                        (MOVETO + CLICK)
                                 │
                                 ▼
                            Game Window
```

---

## 5. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Template không match do lighting/UI thay đổi | Threshold 0.65, fresh capture mỗi session, fallback center-click |
| MOVETO coordinates sai (DPI scaling) | `SetProcessDPIAware()` trong screen_info.py |
| Popup bất ngờ chặn action flow | Global popup check trước mỗi handler step |
| ESP32 disconnect giữa chừng | CommandBuffer auto-retry 3x, reconnect logic |
| Game detect bot (anti-cheat) | 5-layer anti-detection: HW HID + Bezier + Gaussian timing + session breaks + profile randomization |
