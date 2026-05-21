---
name: project-rok-overview
description: "ROK Farm Automation project - architecture overview, current status Phase 7 action execution"
metadata: 
  node_type: memory
  type: project
  originSessionId: f908e428-fbab-4cac-a403-837dc972657a
---

## Project: ROK Farm Automation

Automates repetitive actions in Rise of Kingdoms (PC) using computer vision + hardware HID.

### Architecture Flow
```
Game Window -> Screen Capture (mss) -> OpenCV -> Python Logic -> Serial -> ESP32-S3 -> USB HID
```

### Current Status (2026-05-16)
- **Phase 7**: Action Execution Pipeline -- gem farm flow working E2E
- ESP32-S3 firmware flashed, COM27, MOVETO/CLICK/DRAG/SCROLL all working
- Vision pipeline: template matching with multi-scale, state detection
- Gem farm flow: city -> world map -> spiral scan -> verify gem type -> gather -> march -> city
- Key remaining: better gem icon template (collect samples), other resource types, long-duration testing

### Key Files
- `tools/test_gem_farm_flow.py` -- E2E gem farm test via ESP32 HID
- `logic/action_executor.py` -- ActionExecutor with handlers for all action types
- `vision/template_matcher.py` -- multi-scale matchTemplate + NMS
- `templates/resources/` -- gem_icon, gem_mine_close, gem_mine
- `templates/buttons/` -- gather_btn, march_btn_orange, new_troop_btn, city_btn, world_map_city_btn

**How to apply:** Read PLAN.md for detailed progress. Game window is 1480x876. ESP32 on COM27.
