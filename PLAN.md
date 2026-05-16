# Plan — ROK Farm Automation

> File này là **plan động**, cập nhật liên tục mỗi session. Docs cố định nằm trong `docs/`.

## Current Phase: 8 — Gem Mine Detection Upgrade (in progress)
**Started:** 2026-05-16  
**Target:** k-NN self-learning classifier reduces false attempts on gem icon scan

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
- [x] Handler: `_handle_collect_rewards` — cải tiến: position fallback khi thiếu claim_btn template
- [x] Handler: `_handle_train_troops` — city → barracks → train → confirm → Escape → city
- [x] Handler: `_handle_heal_troops` — city → hospital → heal → Escape → city
- [x] Handler: `_handle_gather_resource` — vision-scan approach: drag map → template match → click → gather → march → city
- [x] Navigation helpers: `_navigate_to_city`, `_navigate_to_world_map`, `_click_at_window_relative`, `_press_escape`
- [x] Scan helpers: `_scan_for_template` (drag map in 8 directions), `_drag_map` (MOVETO + DRAG command)
- [x] Template directories: `templates/buildings/`, `templates/search/`, `templates/resources/`
- [x] Gem farming: `resource_type: "gem"` in `_handle_gather_resource` + `gem_farm` strategy
- [x] Capture gem templates from live game: `resources/gem_mine_close.png` (conf=1.000), `resources/gem_mine.png`, `resources/gem_mine_red.png`
- [x] Capture `templates/buttons/gather_btn.png` từ game ("Thu Thập", conf=1.000)
- [x] Re-crop `templates/buttons/gather_btn.png` từ popup gem thật (old crop false-positive on map line)
- [x] Capture `templates/buttons/march_btn.png` từ game ("Hành quân", conf=1.000)
- [x] Capture `templates/buttons/new_troop_btn.png` từ live troop panel ("Quân mới", conf=1.000)
- [x] Capture `templates/buttons/march_btn_orange.png` từ troop screen ("Hành quân", conf=1.000)
- [x] Capture `templates/buttons/city_btn.png` từ game (Space button, conf=1.000)
- [x] Debug click positioning: MOVETO accuracy verified ±1px (tools/debug_click_position.py)
- [x] Test end-to-end: gem farm flow (historical partial PASS: find gem mine → click → Thu Thập → Hành quân; needs current-session re-verify because final state detector returned unknown)
- [x] Test: 53 tests pass (`tests/test_action_executor.py`) — all 6 handlers + scan/drag helpers + gem tests + verified click
- [ ] Capture `templates/buttons/claim_btn.png` từ game (defer — cần quest hoàn thành mới có nút Claim)
- [ ] Capture building templates: `buildings/barracks.png`, `buildings/hospital.png`
- [ ] Capture action templates: `buttons/train_btn.png`, `buttons/heal_btn.png`
- [ ] Capture resource node templates: `resources/farm_node.png`, `resources/wood_node.png`, `resources/stone_node.png`, `resources/gold_node.png`
- [ ] Test end-to-end: collect rewards (needs claim_btn template from completed quest)
- [ ] Test end-to-end: train/heal (needs building + action button templates from game)
- [x] Verified click pattern: MOVETO → re-capture → verify template still present → CLICK (tránh click sai vị trí)
- [x] Action guard: per-template confidence + resource play-area gate before click (`tools/test_gem_farm_flow.py`, `logic/action_executor.py`)
- [x] Popup relative positioning: `_find_template_near` tìm gather_btn gần vị trí mine đã click
- [x] Re-verify gem farm flow in current live session via ESP32 HID with step-by-step evidence log (`docs/gem-flow-test-log.md`)
- [x] Single-mine gem march confirmed: gem mine → Thu Thập → Quân mới → orange Hành quân → route shown, queue 4/4
- [x] Gem search flow in `ActionExecutor`: normalize city/world/unknown → visible-gem check → controlled zoom/drag scan → verified resource click
- [x] Test: full suite 142 passed after gem search flow/world-map cue update
- [x] Live find-only preflight via ESP32 HID: found `resources/gem_mine_close` at frame `(870, 295)`, conf=0.702; no gather click sent
- [x] Live gem harvest via ESP32 HID: 1 troop successfully marched to gem mine (`continue_run1_after_march_020047.png`, queue shown 3/4)
- [x] Live two-mine gem harvest: 2/2 PASS via `test_gem_farm_flow.py --count 2` (both on same mine -- see bug below)
- [x] Live single-mine at new position: 1/1 PASS, gem_icon conf=0.924, different map location
- [x] Full flow rewrite: city -> world_map_city_btn -> zoom out 2x -> spiral scan 80% step -> click+verify -> gather -> march -> city
- [x] Gem type verification: after icon click zoom-in, check `gem_mine_close` visible to confirm gem (not wood/stone/gold)
- [x] Bug fix: `gem_icon` template false-positive on wood/gold nodes (conf 0.74-0.81); `gem_mine_close` check filters non-gem
- [x] Bug fix: infinite loop when same icon re-clicked -- now scan+verify stays on world map, tracks `clicked_positions` locally
- [x] `GEM_ICON_THRESHOLD` raised 0.72 -> 0.80 (gem real ~0.85-0.92, wood false positive ~0.74)
- [x] Collect gem icon samples in `templates/resources/gem_icon_samples/` — 39 samples collected (expanded from 11)
- [x] Analyze gem icon color: HSV H~38 (green), 72-88% green pixels in crystal region; current template (57x62) matches well
- [x] `vision/color_filter.py` — HSV color pre-filter: green hue check (primary) + white crystal check (fallback for tinted territory)
- [x] Integrated color filter into `test_gem_farm_flow.py` (`_find_all_gems`, `_find_all_icons`) — rejects non-gem icons before click
- [x] Color filter v2: added 3rd fallback `bright+hue` (bright>=85% AND max_hue>=35) for red-territory gems. 39/39 samples PASS (100%)
- [x] Template re-evaluated: cross-correlation ranking on 39 samples, best representative = `111537.png` (36x48, avg=0.8383). Replaced `gem_icon.png` (old 57x62 backup as `gem_icon_original.png`)
- [x] Integrated color filter + gem_icon scan into `action_executor.py` — `_handle_gather_gem` with icon scan + color filter + two-step verify
- [x] Analysis tools: `tools/generate_gem_template.py`, `tools/analyze_samples.py`, `tools/compare_templates.py`
- [x] Test: 143 tests pass (54 action executor tests including 6 gem-specific tests with color filter mocking)

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
| 2026-05-15 | Vision-scan thay search panel cho gather | ROK PC không có search hotkey, phải drag map + template match để tìm resource |
| 2026-05-15 | DRAG command cho map panning | MOVETO + DRAG(0,0,dx,dy,duration) — firmware đã có handle_drag, không cần PRESS/RELEASE riêng |
| 2026-05-15 | MOVETO accuracy ±1px verified | debug_click_position.py: screen_to_hid rounding error chỉ 1px, click hoạt động chính xác |
| 2026-05-15 | Gem farm flow: click mine → Thu Thập → Hành quân | 3-step UI flow, mỗi step cần template match riêng (gem_mine_close, gather_btn, march_btn) |
| 2026-05-15 | Tham khảo GitHub ROK bots | Dylan-Zheng, OSROKBOT, 4x-game-agent, Sunuba/roc — tất cả dùng ADB, mình unique ở HW HID |
| 2026-05-15 | Position fallback cho missing templates | Handlers dùng template-first, nếu chưa có thì click vị trí tương đối trong window |
| 2026-05-15 | Navigation helpers tách riêng | `_navigate_to_city` + `_navigate_to_world_map` dùng chung cho mọi handler |
| 2026-05-15 | gem_farm strategy dùng GATHER_RESOURCE với params | Gem mine là resource node trên world map, cùng flow với food/wood/stone/gold |
| 2026-05-15 | Re-crop gather_btn from real gem popup | Old `gather_btn.png` was a map-line/background crop and produced false-positive matches |
| 2026-05-15 | Add action confidence/play-area gate | Prevent low-confidence resource/button matches from driving ESP32 clicks |
| 2026-05-15 | Gem flow needs troop-panel step | After `Thu Thập`, click `Quân mới`, then orange `Hành quân`; blue march template is for a different map popup |

| 2026-05-15 | Verified click pattern | MOVETO → verify → CLICK, tránh click sai khi game state thay đổi giữa capture và click |
| 2026-05-15 | Popup relative positioning | Gather popup hiện tương đối với mine → `_find_template_near` tìm button trong bán kính 300px |
| 2026-05-16 | Gem search starts from unified resource-search state | StateDetector có thể mislabel world map; visible resource template được ưu tiên, unknown recovery dùng Space/Escape, zoom-out giới hạn 5 scroll để tránh kingdom view |
| 2026-05-16 | World map cue uses `city_btn` when detector returns unknown | World-map state template vẫn lệch trong live session; `city_btn` conf >= 0.75 phân biệt world map tốt hơn city view |
| 2026-05-16 | `gem_mine_v2` excluded from live click decisions | Produced false-positive on forest at conf=0.721; only confirmed gem templates should drive clicks |
| 2026-05-16 | Two-step click for gem harvest | Icon click (gem_icon at icon-zoom) only zooms camera; second click on mine structure (gem_mine_close) opens gather popup. Flow: icon→zoom→mine→popup→gather→march |
| 2026-05-16 | `gem_icon` (57x62) is the primary search template | White diamond icon visible at icon-zoom (2 scroll-outs from detail). Threshold 0.80 (raised from 0.72). `gem_mine_close` (80x70) for structure click after zoom-in |
| 2026-05-16 | All resource icons are similar white pentagons at icon-zoom | `gem_icon` template matches wood/stone/gold at conf 0.74-0.81; must verify with `gem_mine_close` after zoom-in |
| 2026-05-16 | Scan+verify pattern replaces separate find/click/verify steps | Click each icon on world map, zoom in, check gem structure, dismiss if wrong, zoom out, continue. Avoids city round-trip loop |
| 2026-05-16 | `world_map_city_btn` (94x94) for city-to-world-map navigation | Bottom-right button, conf=0.879, toggles city/world map view |
| 2026-05-16 | Spiral scan 80% coverage per drag | `DRAG_OVERLAP=0.20` means each drag covers 80% new area. Step ~710x408px on 1480x876 window |
| 2026-05-16 | HSV color pre-filter for gem icon discrimination | Three criteria: (1) green_pct>=30%, (2) white_pct>=45%, (3) bright>=85% + max_hue>=35. Covers normal, washed-out, and red-territory gems. 39/39 samples PASS |
| 2026-05-16 | Replace gem_icon template 57x62 -> 36x48 | Cross-correlation ranking on 39 samples: best representative `111537.png` (avg=0.8383). Old template too big, matched only 5/39 samples. Backup as `gem_icon_original.png` |
| 2026-05-16 | Gem flow integrated into action_executor | `_handle_gather_gem` separate from generic resource flow: icon scan + color filter + two-step verify. Matches proven test_gem_farm_flow.py approach |
| 2026-05-16 | k-NN classifier (HSV hist + HOG) for gem icon filtering | Template match + color filter not enough; all resource icons look similar at icon-zoom. k-NN learns from zoom-in verification results |
| 2026-05-16 | Stale training data causes false rejections | 30 samples from previous session had mislabeled gems (zoom-in verify missed gem_mine_close). Must start fresh or verify patch labels before trusting classifier |
| 2026-05-16 | Classifier confidence threshold 0.6 for rejection | Below 0.6 = uncertain, still click. Above 0.6 not_gem = skip. Cold start (<10 samples) = click everything |

### Phase 8 — Gem Mine Detection Upgrade (k-NN Self-Learning Classifier)
*(Thay the template matching + color filter o icon-zoom level -- qua nhieu false positive/negative)*

**Problem:** Tat ca resource icons (gem/gold/food/wood/stone) tren world map o icon-zoom deu la hinh kim cuong nho tren nen co xanh. Template matching + HSV color filter khong phan biet duoc vi terrain xanh lan vao crystal analysis. Ket qua: qua nhieu false attempt (click icon -> zoom in -> khong phai gem -> zoom out -> tiep).

**Solution:** k-NN classifier tu hoc tu zoom-in verification. Khong can install them gi (numpy + OpenCV only).

**IMPORTANT: Search button flow + gather/march flow giu nguyen.** Chi thay doi phan TIM MO (icon scan) tren world map.

#### Architecture

```
[Current flow - GIU NGUYEN]
city -> world_map_city_btn -> zoom out 2x -> SCAN MAP -> click icon -> zoom verify -> gather -> march -> city
                                                ^
                                          CHI THAY DOI PHAN NAY
```

**New scan pipeline:**
```
1. Template match gem_icon (threshold 0.80) -> candidate patches
2. k-NN classifier predict(patch) -> gem_score
   - Neu co data (>=10 samples): filter truoc khi click (gem_score > 0.6)
   - Neu chua co data: click tat ca (nhu hien tai)
3. Zoom-in verify (gem_mine_close template) -> TRUE/FALSE
4. Tu dong label: luu patch + label vao training data
   -> Cang chay cang chinh xac
```

#### Implementation Steps

- [x] **8.1** `vision/gem_classifier.py` — GemPatchClassifier class
  - Extract features tu icon patch 48x48: color histogram (HSV, 8x8x4 bins) + HOG (8x8 cell, 2x2 block)
  - `predict(patch) -> (label, confidence)` — k-NN (k=5, distance-weighted)
  - `add_sample(patch, is_gem: bool)` — accumulate training data in-memory
  - `save(path)` / `load(path)` — persist to `data/gem_classifier.npz`
  - Cold start: khi < 10 samples, return confidence=0 (bypass filter)

- [x] **8.2** `data/gem_classifier.npz` — persisted training data
  - Auto-created after first run
  - Format: features array + labels array
  - Load on startup if exists

- [x] **8.3** Integrate vao `test_gem_farm_flow.py`
  - `_find_all_icons()`: sau template match + color filter, them classifier filter
  - `_click_icon_and_verify()`: sau zoom-in verify, tu dong `add_sample(patch, is_gem)`
  - Log: `[LEARN] Added gem/not-gem sample #N, total=M`
  - Screenshot: luu patch vao `data/gem_patches/{gem,not_gem}/` de debug

- [x] **8.4** Integrate vao `action_executor.py`
  - `_scan_gem_icons()`: load classifier on init, filter candidates
  - `_verify_gem_after_icon_click()`: add_sample after verify
  - Save classifier to disk sau moi 10 samples moi

- [x] **8.5** Bootstrap tool: `tools/bootstrap_gem_classifier.py`
  - Doc tat ca patches tu `data/gem_patches/` (tu cac run truoc)
  - Train classifier offline
  - Export accuracy report (LOOCV)

- [x] **8.6** Test suite: `tests/test_gem_classifier.py`
  - 21 unit tests: feature extraction, predict, add_sample, save/load, cold start, incremental, auto-save
  - Full suite: 164 tests pass (21 new + 143 existing)

- [x] **8.7** Live test: 2 runs via `test_gem_farm_flow.py`
  - Run 1 (cold, --count 1): 3 attempts, gem found at #3 (conf=0.941). 3 samples collected (1 gem, 2 not_gem)
  - Run 2 (warm 3 samples, --count 2): Mine 1 at attempt 3, Mine 2 at attempt 7. Classifier rejected ~15 not_gem icons after warming (10 samples). 13 samples total (3 gem, 10 not_gem)
  - Both runs: 3/3 mines PASS, full flow city->scan->gather->march->city
  - Bug found+fixed: stale training data from previous sessions caused false rejections. Must start fresh or verify labels

#### Files Changed
| File | Change |
|---|---|
| `vision/gem_classifier.py` | NEW — k-NN classifier |
| `vision/color_filter.py` | Giu nguyen (van dung nhu pre-filter nhe) |
| `tools/test_gem_farm_flow.py` | Add classifier integration + auto-label |
| `logic/action_executor.py` | Add classifier vao `_scan_gem_icons` + `_verify_gem_after_icon_click` |
| `tools/bootstrap_gem_classifier.py` | NEW — offline training tool |
| `tests/test_gem_classifier.py` | NEW — unit tests |
| `data/gem_classifier.npz` | NEW — persisted model (auto-created) |
| `data/gem_patches/gem/` | NEW — labeled patches for debug |
| `data/gem_patches/not_gem/` | NEW — labeled patches for debug |

#### Key Constraints
- **Khong install them package** — chi numpy + OpenCV + scikit-learn (da co trong .venv)
- **Backward compatible** — khi classifier chua co data, flow hoat dong nhu cu
- **Search button flow khong doi** — chi thay doi phan scan icons tren map
- **Gather/march flow khong doi** — chi thay doi phan TRƯỚC khi click icon

---

## Blockers / Issues

- ~~2026-05-16: Second live gem harvest blocked~~ **RESOLVED 2026-05-16**: Root cause: clicking gem icon only zooms camera. Fix: two-step click (icon -> mine structure).
- ~~2026-05-16: `gem_icon` template false-positive on other resource types~~ **RESOLVED 2026-05-16**: Added HSV color pre-filter (`vision/color_filter.py`). Gem green hue (H~38) distinguished from wood/gold. Three-layer defense: (1) threshold 0.80, (2) color filter, (3) `gem_mine_close` verification after zoom-in.
- 2026-05-16: Icon-zoom detection accuracy too low — template matching + color filter can't distinguish gem from other resource icons on green terrain. Planned fix: k-NN self-learning classifier (Phase 8).

## Ad-hoc Tasks

_Tasks phát sinh ngoài roadmap — thêm vào đây khi xuất hiện_

| Task | Status | Note |
|---|---|---|
| — | — | — |
| Re-verify gem farm flow live via ESP32 HID | Done | Single-mine on new position PASS (2026-05-16). Full flow: city->world map->spiral->verify->gather->march->city |
| Collect gem icon samples for better template | Done | 11 samples collected. Analysis: current template sufficient, added HSV color filter instead of replacing template |
