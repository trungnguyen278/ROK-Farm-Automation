---
name: project-gem-classifier
description: "Phase 8: k-NN self-learning classifier for gem icon detection at icon-zoom. DONE: all 8.1-8.7 steps complete, live-tested 3/3 mines PASS."
metadata: 
  node_type: memory
  type: project
  originSessionId: 9af3a5e5-ea0f-4bac-a16c-e7f7a5cf9497
---

## Phase 8: Gem Mine Detection Upgrade -- DONE (2026-05-16)

**Why:** Template matching + HSV color filter at icon-zoom level cannot distinguish gem icons from other resource types (all look like white diamonds on green terrain). Too many false attempts in live runs.

**How to apply:** Only changes the SCAN part of gem flow, not search button / gather / march.

### Implementation
- `vision/gem_classifier.py` -- GemPatchClassifier (k-NN, k=5, distance-weighted)
- Features: HSV histogram (8x8x4=256) + HOG (900 dims) = 1156-dim vector per 48x48 patch
- Cold start: < 10 samples = bypass (click everything, auto-label from verify)
- Auto-label: zoom-in gem_mine_close match -> label icon patch as gem/not_gem
- Persist: `data/gem_classifier.npz` + `data/gem_patches/{gem,not_gem}/`
- Integrated into: `test_gem_farm_flow.py`, `action_executor.py`
- Bootstrap tool: `tools/bootstrap_gem_classifier.py` (offline train from saved patches)
- Tests: 21 unit tests in `tests/test_gem_classifier.py`

### Live test results
- Run 1 (cold): 1/1 mine, gem at attempt 3. 3 samples collected.
- Run 2 (warm): 2/2 mines, classifier rejected ~15 not_gem icons. 13 total samples (3 gem, 10 not_gem).

### Key lesson: stale training data
30 samples from a previous session had mislabeled gems (zoom-in verify failed to find gem_mine_close on real gems -> labeled not_gem). Classifier then rejected real gems at 0.77-0.87 confidence. **Fix: delete stale model, start fresh.** Future: could add manual patch review or confidence calibration.

Related: [[project-gem-farm-flow]]
