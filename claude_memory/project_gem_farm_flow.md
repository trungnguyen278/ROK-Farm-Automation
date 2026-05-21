---
name: project-gem-farm-flow
description: "Gem farm flow architecture - city->world map->spiral scan->color filter->verify gem type->gather->march. Templates, thresholds, color filter criteria."
metadata: 
  node_type: memory
  type: project
  originSessionId: f908e428-fbab-4cac-a403-837dc972657a
---

## Gem Farm Flow (action_executor.py + test_gem_farm_flow.py)

Full E2E flow per mine:
1. City view -> click `world_map_city_btn` (bottom-right, conf>=0.75) -> world map
2. Zoom out 2x (`SCROLL -5` x2) to reach icon-zoom level
3. Spiral scan map with 80% coverage per drag (`DRAG_OVERLAP=0.20`)
4. For each resource icon found (`gem_icon` template, threshold 0.80):
   - HSV color filter: reject non-gem icons (wood/gold/stone) before clicking
   - Click icon -> game zooms in to resource area
   - Verify gem type: check `gem_mine_close` (80x70) visible on zoomed-in frame
   - If NOT gem: dismiss popup (Escape), zoom out 2x, continue scanning
   - If gem: click mine structure -> popup opens -> gather -> new troop -> march
5. Return to city view via `city_btn`

**Why:** `gem_icon` template (white pentagon) matches ALL resource types at icon-zoom. Three-layer defense needed: threshold + color + structure verify.

**How to apply:** `_handle_gather_gem` in action_executor.py is the production path. `test_gem_farm_flow.py` is the live debug/test tool with same logic.

### Key templates
- `resources/gem_icon` (36x48) — white pentagon icon at icon-zoom. Threshold 0.80. Replaced 2026-05-16 from 57x62 via cross-correlation ranking on 39 samples. Backup: `gem_icon_original.png`.
- `resources/gem_mine_close` (80x70) — 3D mine structure after zoom-in. Threshold 0.60.
- `buttons/world_map_city_btn` (94x94) — bottom-right city/world toggle. Threshold 0.75.
- `buttons/gather_btn` (164x62) — "Thu Thap" button in popup. Threshold 0.70-0.80.
- `buttons/new_troop_btn` (146x51) — troop selection. Threshold 0.80.
- `buttons/march_btn_orange` (198x55) — march confirmation. Threshold 0.80.

### Color filter (`vision/color_filter.py`)
Three-layer defense against false positives:
1. Template threshold >= 0.80
2. HSV color pre-filter on crystal region (top 60%, center 60% of icon):
   - Primary: green_pct >= 30% (gem crystal H~38 green vs wood H~15 brown)
   - Fallback 1: white_pct >= 45% (bright, low-sat crystal -- handles washed-out territory)
   - Fallback 2: bright_pct >= 85% AND max_hue >= 35 (red territory: crystal bright but hue shifted to orange, still reaches into green range)
3. Two-step verify: click icon -> zoom in -> check `gem_mine_close` structure

Validated on 39 samples: 100% PASS (was 97.4% before fallback 2).

### Known issues
- `gem_mine_red` (45x45) causes false positives on shrines -- excluded from active templates
- `gem_mine_v2` (200x200) too large for normal zoom -- excluded
