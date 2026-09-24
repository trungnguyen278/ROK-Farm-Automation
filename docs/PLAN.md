# PLAN

## Current Mode

CLI-first gem farm runner. The source of truth is `run_farm.py` at the repo root.

## Active Status

- [x] ESP32 HID firmware exists and is used by the runner.
- [x] Serial protocol and command buffer are kept.
- [x] Capture, vision, gem classifier, mouse humanizer, and default profile are kept.
- [x] Old tkinter UI/dashboard removed.
- [x] Old `main.py` orchestrator and generic `logic/` pipeline removed.
- [x] Old YAML config loader/config file removed from the active workflow.
- [x] Old phase-roadmap docs and screenshot dumps removed.
- [x] README/AGENTS/PLAN rewritten to match the current CLI workflow.
- [x] Python syntax compile check passes for retained `.py` files.
- [x] Repo restructured 2026-08-14: runner moved to `run_farm.py`, dev scripts to `tools/dev/`, logs/screenshots purged.
- [x] Spec written for the module split + game lifecycle: `docs/SPEC_REFACTOR.md` (2026-08-14).
- [x] Part 1: `run_farm.py` split into the `rok_farm/` mixin package (2026-08-14). 2491 lines -> 16 modules, largest 482.
- [x] Part 2: game lifecycle wired (auto-launch at setup, restart on recovery / long break, `--no-auto-launch` / `--no-restart` / `--launcher-path`).
- [x] Launcher Play button captured by the user (2026-08-14): `templates/launcher/play_btn.png` 358x115 + `play_btn_pct` [0.8655, 0.8299].
- [ ] Optional: capture the in-game exit confirm (`tools\capture_launcher_btn.py --exit-confirm`) so quitting is graceful instead of taskkill.
- [ ] Live pass on the lifecycle: one cold start from the launcher, one mid-run restart.
- [x] Spec written for screen-state detection: `docs/SPEC_STATE_ORACLE.md` (2026-08-14). Layer 1 local CV, layer 2 vision-model oracle behind an escalation gate.
- [x] `tools/dev/measure_state_signals.py` written (liveness, modal dim, view discriminators).
- [x] `ai_mode_web` proven working end to end (2026-08-14): `tools/dev/probe_ai_mode.py` returns correct structured JSON for a real game screenshot, free, headless, no login.
- [x] Calibrated on the live client at 1533x863 (`logs/state_signals.json`), six states: world map near and at icon zoom, city, gather popup, alliance panel, bag panel. Numbers and their consequences are in `rok_farm/config.py`.
- [x] Layer 1 done: `rok_farm/state_probe.py` + capture-thread liveness sampling, wired into `_client_looks_broken`, `_wait_until_in_city` and `_attempt_recovery`. 51 tests.
- [x] Layer 0 done (2026-08-14): `rok_farm/button_registry.py` + the `_click_match` guard + 13 tests. Fixed buttons learn their own position tolerance; an outlier match is refused instead of clicked.
- [x] Layer 2 provider layer done (2026-08-14): `rok_farm/vision_llm.py` with the OpenRouter provider + mock, budget/cache/fallbacks, 19 tests. Off until a key exists; `tools/dev/probe_openrouter.py` verifies a key when one arrives.
- [x] OpenRouter verified live 2026-08-14 with a real key: correct verdict on a live frame in **3.3s** (`view=world_map, overlay=none, covers_hud=false`), agreeing with layer 1.
- [x] `ai_mode_web` provider wired as the no-key fallback (2026-08-14): 43.0s headless through the oracle interface, same verdict as OpenRouter. Needs `pip install playwright`; reports itself unavailable without it.
- [x] Escalation gate wired: the oracle is only asked when layer 1 returns an unknown view or confidence < 0.6, and never when a modal is already detected locally.
- [x] Guarded grounding done (2026-08-14): `rok_farm/dismiss.py` closes an unknown popup -- learned templates first, then a grounding model, through danger-zone/position guards, verified by the dimming going away, and learned on success. 12 tests.
- [ ] Next live focus: run current gem flow and tune popup handling/detection only where the live runner needs it.

## Primary Command

```powershell
.venv\Scripts\python run_farm.py --port COM27 --count 2
```

Useful variants:

```powershell
.venv\Scripts\python run_farm.py --find-only
.venv\Scripts\python run_farm.py --port COM27 --loop --max-marches 5 --no-screenshots
.venv\Scripts\python run_farm.py --port COM27 --count 2 --auto-learn
```

## Keep List

| Area | Keep |
|---|---|
| Runner | `run_farm.py` (entry point) + `rok_farm/` (the runner) |
| Firmware | `esp32-s3/` |
| Host I/O | `capture/`, `serial_comm/` |
| Vision | `vision/`, `templates/`, `data/gem_classifier.npz`, `data/gem_patches/` |
| Behavior | `anti_detection/`, `profiles/default.json`, `data/mouse_training/` |
| Helpers | `tools/` (capture_templates, bootstrap/train_gem_classifier, generate_gem_template, record_mouse, train_mouse, resize_window) |
| Debug | `tools/dev/` (test_esp32, test_notification_listener, test_mouse_paths, test_loop_3actions, read_cursor) |

Note: `tools/dev/` holds occasional-use debug scripts only. `locate_ui.py` was deleted (2026-08-14): it was hardcoded to absolute screenshot paths that no longer exist. The fixed button positions it produced are already constants in `run_farm.py`.

## Decisions

| Date | Decision | Reason |
|---|---|---|
| 2026-09-24 | Sweep target: the ring still drawn on distance from the city; the cell inside it weighed by distance from the camera (half every 30 tiles, was 80) and by lying ahead of the heading; a new run out of the city draws a fresh target | Operator: one run's path (tools/dev/run_map.py) crossed itself 16 times in 80 views. Sessions with mines ending at the first gem (measured return curve), 20 x 8 h each: crossings 0.82 -> 0.60 per 10 views, scans a mine 9.2 -> 8.5, march 51.0 -> 52.9 tiles, gems/h ~98%. Tidier variants (the path weighing the ring too, one turning direction per run = a spiral) marched 9-10% further, ~5% fewer gems at 6.2 s a tile each way; the operator ruled out a preset spiral anyway. Weighing unseen ground round a target ("chua di qua") changed nothing measurable |
| 2026-09-24 | `SWEEP_STALE_H` 6h -> 2h | `tools/dev/gem_return.py`, 634 views 01:30-07:55: empty cells showed a new gem on the next visit 1.5% after 2-10 min, 3.1% 10-30 min, 4.7% 30-60 min, 6.8% 60-120 min, 9.9% 2-4 h, against 6.2% on a first visit -- ground is as good as unseen after 1-2 h. Night only: re-measure in daylight and revert if the curve differs |
| 2026-09-24 | Every refused Gather backs out like the duplicate path: dismiss the popup (a click on empty ground), undo the zoom, pan away | Mines 37-41 (07:38-07:40) all refused one gem deposit's popup left open at the top of the screen (button y 0.350-0.358, text unreadable); mine 42 met the deposit afresh and marched to it. 28 refusals in the log since 2026-09-13 |
| 2026-09-24 | The scan acts on the per-scan zoom hint: two "close" reads in a row, the gauge agrees, scroll out (`CLOSE_HINT_SCANS`, at most `ZOOM_FIX_ROUNDS` a mine) | A dud click at 03:04:28 zoomed in and its zoom-out did not land; the hint said close on all 18 following scans and only the empty-streak limit asked the gauge, 66 s later. 304 scans 01:52-04:00: that one run, no lone close read |
| 2026-09-24 | World-map gate on the castle glyph 0.70 -> 0.85 (`SPACE_CASTLE_MIN`); the state probe judges the frame it is given | `tools/dev/castle_scores.py`: 1162 real verdicts at 0.95-1.00, 160 false at 0.719-0.783 (loading screen, maintenance notice, city HUD), none between. After a relaunch the probe matched the buttons on the stale frame of the session before the quit and printed "Game world is up" over a loading screen at 12%; that and the 0.72 corner cost two mines at 01:41 and one each on 09-22 16:31, 19:55 and 09-23 17:41 |
| 2026-09-24 | While a sweep target is set, the target alone steers (pull 0.35-0.70 a scan); the book's heading score only chooses when there is no target; no city trip to steer | Over 394 pans the book overrode 293 scans, 231 of them away from the target, so pans went toward it 42% of the time (mean cosine -0.12, `tools/dev/steer_check.py`) and the city road was bolted on to fetch the camera back. Operator: the city trip is the quick fix for a wrong zoom, not a way to steer. Held to +-40 deg the book still made the camera circle the seen ground; with the target alone the simulated walk reaches the gap in a median 6 scans (198/200 seeds, `tests/test_steer_follows_sweep.py`) |
| 2026-09-23 | Pan geometry measured by `tools/dev/pan_survey.py`, never inside the farm flow | In-flow drag/tile pairs fitted to a 21-tile median error: node clicks, recentres and city trips move the camera without a drag. The survey (icon zoom, pointer kept inside the window, width/height as two half drags) found: tile axes = screen axes, screen down = -Y, perspective 1.82/1.54/1.36 tiles/100px at rows 0.25/0.50/0.75, one frame ~31/24/17 x 19 tiles, no carry-on after a moving release. `tools/dev/zoom_check.py` confirms it on 173 past farm clicks: median 0.5 tiles, scale 1.01 |
| 2026-09-23 | Steering converts screen headings to map headings (`pan_model.tile_heading`) | The book was read at +sin(heading): every vertical heading scored and vetoed the ground behind the camera |
| 2026-09-23 | Drags steer from the real cursor each step, but the ending is left to vary | Open-loop relative drags came out 0.76-1.77x the aim and 3/40 left the window. Operator: keep the error as a variable so the game cannot see it -- no settle-onto-target nudge |
| 2026-09-23 | Position read every scan with recognition-only OCR (15ms vs 520ms, 59/59 agree); the book records every cell of each view, at icon zoom only | One cell per four scans left most seen ground "unexplored" |
| 2026-09-23 | City learned on the first frame after the city->world toggle | The map recentres on the city (577,615) every time; the old "first read after a trip" came up to four scans late and learned 3 different cities in a day |
| 2026-09-23 | Sweep: lean each scan toward a random, weighted gap near the city; redraw every 6 scans | Operator: keep the trajectory so near ground is not skipped after going far, but never a fixed route |
| 2026-09-23 | Let Windows lock; the farm dismisses the lock screen with ENTER (no password), never types a character | Operator: "de may khoa cung duoc ma cho no that"; whoever does not want it changes Windows settings. Play is never clicked at the stored position unless the launcher is confirmed in front |
| 2026-09-23 | Template scales matched on a thread pool; the dead gather recheck removed; zoom-in wait is a 3.6s window | Icon scan 669->160ms, zoom poll 1063->364ms; the recheck found the popup 0 times in 1,148 |
| 2026-08-14 | Split `run_farm.py` into `rok_farm/` mixins, not composition objects | One runtime object keeps every `self._x` call site and the `PlayerActions` ctx protocol working; the move stays mechanical and reviewable |
| 2026-08-14 | Keep alt-tab (not game restart) for the ~15min march wait | The "troops returned" toast only fires while the game runs in the background; quitting would force a blind timer and add a login event every 15min |
| 2026-08-14 | Restart the game only on recovery or a long break (>=30min) | Matches how a real player behaves and recovers a broken client without a suspicious login cadence |
| 2026-08-14 | Resolve the launcher path (env -> profiles/paths.json -> Start Menu shortcut -> registry), never hardcode | The install lives on a per-machine path (`D:\Game\Rise of Kingdoms` here) |
| 2026-08-14 | Screen state: local CV first, vision model only on low confidence | Local is free and instant; the model is for the cases templates genuinely cannot answer |
| 2026-08-14 | `ai_mode_web` is the default state provider -- PROVEN, not assumed | Driving AI Mode with Playwright works end to end on a real game screenshot: no login, no CAPTCHA, image attached by synthetic paste, one-line JSON returned correctly (10.1s headed / 27.2s headless). Recipe kept in `tools/dev/probe_ai_mode.py` |
| 2026-08-14 | Grounding stays on the API path, never on `ai_mode_web` | Measured: asked for the panel's X at truth (777,125), got (758,214) -- 1.9% off in X but 15.5% in Y, landing on a research node inside the panel. Fast (6.1s) but not click-accurate |
| 2026-08-15 | A model-derived click is verified by RESULT, never trusted -- and NO provider is accurate enough to skip that | Five runs on one identical frame with two X buttons: gemini gave 0.9%, 8.5%, 8.8% error (wrong X twice), AI Mode gave 15.5% then 0.2%. An earlier note here claimed gemini was reliable and AI Mode was not; that was one sample each and it was wrong. The API path leads on latency (2s vs 30s), not accuracy |
| 2026-08-15 | Grounding is coarse-then-fine: crop around the first answer and ask again | Single-shot picked the wrong X 4 times in 5, and the bias is systematic, so consensus converges on the wrong button. Refining inside a crop moved three 90px-out answers to within 1-4px of truth. Two calls, ~3.5s |
| 2026-08-15 | `DISMISS_DANGER_MARGIN` 0.10 -> 0.05 | At 0.10 the cordon around the deploy button refused a correctly located close button 1px from truth. 0.10 fences a 306x172px box around a much smaller button |
| 2026-08-15 | The modal precondition, not the model, is what stops a bogus click | On a frame with no panel the model answered `found=false` 3 times in 4 and returned a point once. `_dismiss_modal` never asks unless the dim ratio already says the game is covered |
| 2026-08-14 | Grounding uses its own model list, separate from the state models | `qwen3.7-flash` and `gpt-5-nano` returned nothing at all for a locate request that `gemini-2.5-flash-lite` answered in 1.7s |
| 2026-08-14 | OpenRouter: cheap PAID model first, free ones only as backup | Measured free-first: nemotron:free took an upstream 504 after ~120s and gemma:free returned 429, making one call 127.8s. Paid-first: 3.3s. qwen costs ~half a cent a day at the 20/hour cap |
| 2026-08-14 | No `confidence` field in the oracle schema; parser tolerates truncation | A small model ran a number away until max_tokens cut the JSON off mid-field, wasting a correct answer. Fewer fields, plus field-by-field regex salvage |
| 2026-08-14 | `overlay` means BLOCKING, and the prompt says so explicitly | The first prompt returned `event_popup`/`chat` for a playable world map, because ROK always shows a chat log and toasts -- the flow would have kept trying to clear nothing |
| 2026-08-15 | NO frame-motion "client froze" detector -- built, measured, deleted | Six states measured. The world map at icon zoom, where the bot spends most of its time, reads 0.001 -- a healthy screen identical to a dead one. The gather popup reads 0.088. Two thresholds (0.15, then 0.02) were each falsified by the next state measured, and the action on "frozen" is to restart the game mid-farm. No fallback anchor exists either: the HUD clock is hidden in the compact mode used at icon zoom. Real freezes still surface via the window check, capture returning nothing, or the consecutive-failure counter |
| 2026-08-14 | City/world decided by the absolute `world_map_city_btn` score, not the two-template margin | Measured on the world map the old margin was 0.035 (nearly a coin flip); the absolute score separates 0.742 world vs 0.958 city -- 6x wider |
| 2026-08-14 | Fixed buttons get a learned position gate, enforced in `_click_match` | Detection is stateless, and two paths matched the whole frame and clicked the result (`gather_btn`, `btn_confirm_reconnect`). The three hand-added regions in the code were reactive patches for the same class of bug; the registry generalises them and each button calibrates its own tolerance |
| 2026-08-14 | Allow model-derived coordinates, but only to DISMISS, and only through the guardrails | Current models do real grounding (`box_2d`), and an unknown popup has no other source of truth; a wrong click can march troops, so intent whitelist + danger-zone rejection + pre/post-click checks + learn-the-button |
| 2026-06-14 | Treat the gem farm flow script as the main app | User mainly runs this and does not need UI complexity |
| 2026-08-14 | Rename runner to `run_farm.py` at repo root; anchor its paths to the repo root | Name `test_*` hid that it is the app; anchored paths let it run from any cwd |
| 2026-08-14 | Delete `tools/exp_*.py` calibration experiments | Thresholds they produced are already in `vision/color_filter.py` and the runner |
| 2026-08-14 | Move runner screenshots to `screenshots/gem_farm_test/` | Keeps `tools/` source-only; matches the dir `player_actions` already writes to |
| 2026-06-14 | Remove tkinter UI, old orchestrator, and generic `logic/` pipeline | They were stale and not part of the current live flow |
| 2026-06-14 | Remove old `config.yaml` workflow | Current runner takes CLI args directly and does not use the old config loader |
| 2026-06-14 | Remove old docs/roadmap and replace with concise README/AGENTS/PLAN | Old docs described phases and UI that no longer reflect the repo |
| 2026-06-14 | Keep classifier patches and mouse training data | They are useful for improving the current runner |

## Ad-hoc Tasks

| Task | Status | Note |
|---|---|---|
| Clean repo around current gem flow | Done | Removed UI/orchestrator/docs/debug dumps; kept runner dependencies |
| Smoke-test retained dependencies | Partial | `py_compile` passes; runtime smoke/pytest blocked by local Python env |
| Re-check live gem run | Pending | Use COM port from the actual ESP32 session |
| Restructure repo layout | Done | 2026-08-14: root entry point, `tools/dev/` split, 15MB of logs/screenshots removed |
| Split the runner into modules | Done | 2026-08-14: `rok_farm/` mixin package, verbatim method move, pytest + pyflakes clean |
| Game lifecycle (launch/restart) | Code done | 2026-08-14: Play button captured; still needs a live cold start + a mid-run restart |
| Pan survey + map geometry | Done | 2026-09-23: `tools/dev/pan_survey.py` (`--analyse-only` re-fits `data/pan_survey.json`), model in `rok_farm/pan_model.py`, checked by `tools/dev/zoom_check.py` |
| Scan speed (parallel matching, no recheck, fast OCR) | Done, live | 2026-09-23 14:50: mine appears 1.75-2.4s after the icon click (was ~4.5s) |
| Sweep toward near gaps | Deployed 2026-09-23 | Watch the "sweep: target" debug lines and march distances over the next days |
| Lock screen handling | Done, live | 2026-09-23 14:49: farm found LockApp in front, ENTER, unlocked, launched the game |
| Ring-by-ring band (frontier + 24) | Done, live 2026-09-24 00:45 | The jump home that came with it was removed 2026-09-24 01:30 (see Decisions); a camera past the band now pans back. Measure with `tools/dev/steer_check.py --since "2026-09-24 01:30"` -- expect well over 50% of pans toward the target |
| Near-first sweep, tile memory | Done, live | 2026-09-23 16:20-18:25 on a cleaned book: coverage filled around the city first (tools/dev/track_map.py), both tile skips fired live, 0 duplicate deposits, 11 done / 2 failed in the last 1h40 |
| Map types and zones | Pending (operator: "de luc nao ranh xu ly tiep") | Researched 2026-09-23: home kingdom 1200x1200 in 4 fixed zone layouts (kingdom number mod 4, rotations; images on zoe-rok.com); KvK maps 1440 or 2400 (per Google AI Mode, unverified). Open: (1) the 1200 bound in queue_ocr/pan_model/map_memory is wrong for KvK (S-prefixed ids) -- per-map size; (2) which layout K4096 is (mod 4 = 0) and turning its image into zone polygons in 0-1199, so an unreachable deposit disables its whole zone instead of a 30-tile disc; (3) no pass-pan case seen yet -- check the first *_UNREACHABLE frame. Operator's lead for (2), 2026-09-24: read the zones straight from the game -- the minimap top right when zoomed out, or zoom out to the limit for the whole kingdom |
| Label-less icons after city->world + 3x zoom-out | Open | 2026-09-24 05:12 and 05:13, back to back: small icons without level labels, zoom gauge and per-scan hint both "icon", map steps normal (9/10/8 tiles) -- looks like an icon-LOD switch just past icon zoom, not a whole notch. Both entered by the corner click; the next (SPACE key) was fine. Two mines lost to the no-candidate give-up, recovered by the city round trip. Frames in screenshots/keep/too_far_out/ (m11, m12, and a normal m13 for comparison) |
| Map filter panel opening by itself | Open | ~22 incidents 2026-09-13 to 09-24 (template score >= 0.6 on saved NO_CANDIDATES / FILTER_PANEL_OPEN frames), about 2 a day, one mine each: 3 blank scans, then the city round trip clears it. 2026-09-24: 00:52 and 07:56, both the first mine after a farm restart (2 of the night's 5 restarts, each stopped right after "Mine N DONE"). The input before each incident shows no common key (ALT+TAB, SPACE, nothing) -- trigger still unknown; a clue: what a stop/start leaves behind (the kill mid-action, the board reset on connect, the startup ALT+TABs) |

## Blockers

| Date | Blocker | Note |
|---|---|---|
| 2026-08-14 | Unattended restart may need an admin terminal | While the game runs, `launcher.exe` is not running (observed). If it does not reappear on game exit, relaunching it raises a UAC prompt that nobody is there to accept -- run the bot elevated for overnight sessions |

Resolved: the `.venv` blocker from 2026-06-14 is gone -- `.venv\Scripts\python`
is Python 3.12.10 with the project deps, and `pytest` now runs (5 passed).
