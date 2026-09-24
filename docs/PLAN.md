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
| 2026-09-24 | The survey calibrates on its walks' reads only (the zoom's left out), on view outlines half a view or more from every edge, checking the prior after shifting it by the median miss but placing the provinces with it unshifted; the outline is looked for in the minimap's own box; the north walk starts two legs in from the east edge; a survey that worked clears the retry spacing | The operator's test (15:22, zones deleted): the farm found out by itself and surveyed at the start of the next mine -- 10 provinces, 99.5% of cells as before -- but in 8 minutes: the zoom's reads outnumbered the walks', the calibration kept 11 outlines of 12 and a spread walk ran out the time. Near an edge the map's edge cuts the outline (4-5 px off); a notch of zoom only shifts the camera point in it (-0.08,-0.95 px on the 14:50 walks, 0.13 px left after). The 14:50 walks alone now give 10 provinces with no spread walk: 99.5% of the saved split, 99.8% of the farm's own; by day 99.7% |
| 2026-09-24 | A map's size and zones are looked up in its book; any map with nothing saved -- the home kingdom included -- is surveyed once at the start of a mine (`MapMemory.needs_survey`), a known size (1200 at home) splitting the provinces whatever the walks made of it. Province borders (purple, P1...) and a faint tint on `!run` / `!map`; `reports.active_book()` takes only `<map>.json` books | Operator: "lay toa do thanh hien tai so voi db ... neu khong co thi thuc hien 1 lan", test it by deleting the saved data; and put the zones on the scan pictures. The provinces JSON a survey writes was, for a while after, the newest .json beside the book -- `!map` would have drawn it as the book |
| 2026-09-24 | Provinces are split inside the map's own square through the calibration, pulled in 5 px (`RIM_ERODE_PX`), not inside the dark land; the home calibration is checked at whatever zoom the walks ran | Second live trip (14:50): size right (1200, confident, 166 s) but 5 provinces. The minimap is see-through -- over the night theme its land is not dark, and the dark-land mask ran round the panel's margin; and the widest readable zoom came out a notch wider (legs of 125 tiles), so the prior, checked only on survey-sized outlines, was never checked (it fits there at 0.70 px). Rim pull-in measured against the saved split: 10 provinces day and night from 2 to 10 px, best at 5 (99.7% / 99.5% of cells); none: 9 by day, 8 by night |
| 2026-09-24 | The survey trip: the zoom out ends on 2 blank HUD reads in a row; a walk whose first two legs gain under half a measured leg (96 east, 77 north) zooms out again once; the whole trip has a 480 s budget and stops with what it has | The first live run of the whole trip (14:21) ran past 600 s and was killed mid-walk: one blank read had stopped the zoom out 2-3 notches short (view outline 12-14 px wide instead of 24), every leg moved a fraction of its 96 tiles and the walks ran to their caps. The farm came back through its own city round trip |
| 2026-09-24 | A KvK map gets its provinces in the same trip as its size (`MapEdgeMixin._survey_map`, `rok_farm/minimap.py`): the probe keeps the minimap crops, the home kingdom's calibration is taken when -- scaled to the map's size -- it places the map's own view outlines within 1 px, else a spread walk (3 columns, <= 60 legs) for a fit of its own; surveyed again every 6 h until size and provinces are both known, 3 tries a map. Out-of-reach marks now last `REACH_HALFLIFE_H` (18 h) | Operator: "lam di" to folding the minimap survey into the size trip. The home calibration held on S11001 next door (173,714 predicted at 246.5,38.5, seen 246.9,38.4); fitted on the north-east quarter alone the home kingdom's far corners came out 30-40 tiles off, so an own fit needs outlines over half the map both ways. The marks never expired, and one now closes a whole province -- a pass the alliance takes later would have kept it shut |
| 2026-09-24 | Zones from the minimap: `tools/dev/minimap_survey.py` keeps the minimap beside each HUD read along a zigzag at the widest readable zoom; `tools/dev/minimap_zones.py` fits tiles -> minimap pixels from the view outline and splits the median minimap along its province lines; `--save` writes `data/map_knowledge/<map>_provinces.png`. A deposit out of reach now closes its whole province (never the city's own); an unsurveyed map keeps the 30-tile disc | The minimap (top right, at readable and icon zoom, not in the far view) draws the kingdom the camera stands in with its province lines and the view as a white outline. Home kingdom, 43 reads at one zoom: projective fit 0.20 px median / 1.5 worst (affine 0.75 / 3.3 -- the minimap is a tilted view, 1200 tiles ~127 x 91 px). Lines by white top-hat >= 3: the land gave 0-2 in 85.5% of 10,723 px, the lines a flat tail 3-39+. Result: 10 provinces -- 6 on the rim, 3 round the centre, 1 centre, the standard home layout -- with the city 577,615 in the centre one. Far view dropped for this: tilted, held inside the kingdom, no coordinates |
| 2026-09-24 | Map size measured on a KvK map by walking east and north at the widest readable zoom until the HUD names another map or goes blank (`rok_farm/map_edge.py`), once per map at the start of a mine, believed only when both edges agree | The operator's lead was the far view's corner; live, the far view is held inside the kingdom (~40 legs moved nothing, frame change 3-11 a leg, so stillness cannot see the hold), but at readable zooms the world goes on: east of 4096 is #S11001 (X 1193 -> S11001 58), north is fog with an empty coordinate box. Home kingdom, three runs: 1200 from the east edge each time (estimates 1197, 1199), 1200 from the north in the run that knew fog; 96 tiles a leg east, 77 north; 184 s |
| 2026-09-24 | Map size per map id: a home kingdom (numeric id) is 1200; a KvK map (S-prefixed) is read up to 2400 and its book starts at 1200, stepping up one standard size (1440, 2400) on 5 positions past its edge within 10 min, the nearest of them deciding; the size is saved in the book, and a hand-written `"size"` is taken for a KvK map | With 1200 everywhere, a KvK city past 1200 would have had every HUD read thrown away as a misread. Logs: 18 of 18 reads with Y past 1150 in 5,002 steps were the digit collision (196 -> 1965), 13 of them under 2400 -- so the misread hold in `_map_sync`, not the bound, is what stands in front of a KvK book. Weak spot: a city just under 1200 on a larger map never shows the book the ground past it (the veto reaches 128 tiles); the farm warns once, and the corner probe below measures it instead |
| 2026-09-24 | Sweep target: the ring still drawn on distance from the city; the cell inside it weighed by distance from the camera (half every 30 tiles, was 80) and by lying ahead of the heading; a new run out of the city draws a fresh target | Operator: one run's path (tools/dev/run_map.py) crossed itself 16 times in 80 views. Sessions with mines ending at the first gem (measured return curve), 20 x 8 h each: crossings 0.82 -> 0.60 per 10 views, scans a mine 9.2 -> 8.5, march 51.0 -> 52.9 tiles, gems/h ~98%. Tidier variants (the path weighing the ring too, one turning direction per run = a spiral) marched 9-10% further, ~5% fewer gems at 6.2 s a tile each way; the operator ruled out a preset spiral anyway. Weighing unseen ground round a target ("chua di qua") changed nothing measurable |
| 2026-09-24 | `SWEEP_STALE_H` 6h -> 2h | `tools/dev/gem_return.py`, 634 views 01:30-07:55: empty cells showed a new gem on the next visit 1.5% after 2-10 min, 3.1% 10-30 min, 4.7% 30-60 min, 6.8% 60-120 min, 9.9% 2-4 h, against 6.2% on a first visit -- ground is as good as unseen after 1-2 h. Night only: re-measure in daylight and revert if the curve differs. Daylight, 542 views 08:00-12:55: first visit 6.2%, 2-10 min 4.0% (the noise floor: a gem missed in one view, a cell shifted by a read), 10-30 min 2.4%, 30-60 min 3.7%, 60-120 min 5.6%, 2-4 h 4.4% (5 of 113) -- back to ~90% of fresh ground within 1-2 h, so 2 h stands |
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
| Discord reports: !stats, !map, !runs, !run; !status as an embed | Done, live 2026-09-24 11:06 | rok_farm/reports.py, shared with tools/dev/gem_rate.py, track_map.py, run_map.py. Gems/h counts rises of the balance only (spending never counts against the farm). Since 2026-09-23: 125 gems/h over 12.2 h; night 00-06 152/h, morning 118/h. Across 09-11..09-24 the daily rate fell from 170-210/h (09-11..18) to 77-87/h (09-21..23) and came back to 137/h on 09-24 -- cause not looked into yet |
| Map types and zones | In progress (operator 2026-09-24: "lam di", KvK in ~1 month) | (1) Per-map size: done -- learned from positions, and measured once on a KvK map by `rok_farm/map_edge.py` (3 live runs on the home kingdom). (2) Zones: home kingdom from the minimap (10 provinces, `data/map_knowledge/4096_provinces.png`); a KvK map surveys its own in the size trip (`_survey_map`); an out-of-reach deposit closes its province for 18 h, never the city's own. Waiting on the operator to check the split (screenshots/minimap_zones/4096_*.png). Open: passes (level, blue/red) are only on the far view -- not needed while a province is closed as a whole; whether the minimap draws a 1440/2400 map in the home box is unseen (the trip checks it and fits its own if not). (3) No pass-pan case seen yet. Found on the way: kingdoms adjoin at readable zooms (4096 X 1199 -> S11001 X 0; S11001 Y 0 -> 4093 Y 1199), fog north of 4096 |
| Label-less icons after city->world + 3x zoom-out | Open | 2026-09-24 05:12 and 05:13, back to back: small icons without level labels, zoom gauge and per-scan hint both "icon", map steps normal (9/10/8 tiles) -- looks like an icon-LOD switch just past icon zoom, not a whole notch. Both entered by the corner click; the next (SPACE key) was fine. Two mines lost to the no-candidate give-up, recovered by the city round trip. Frames in screenshots/keep/too_far_out/ (m11, m12, and a normal m13 for comparison) |
| Map filter panel opening by itself | Open | ~22 incidents 2026-09-13 to 09-24 (template score >= 0.6 on saved NO_CANDIDATES / FILTER_PANEL_OPEN frames), about 2 a day, one mine each: 3 blank scans, then the city round trip clears it. 2026-09-24: 00:52 and 07:56, both the first mine after a farm restart (2 of the night's 5 restarts, each stopped right after "Mine N DONE"). The input before each incident shows no common key (ALT+TAB, SPACE, nothing) -- trigger still unknown; a clue: what a stop/start leaves behind (the kill mid-action, the board reset on connect, the startup ALT+TABs) |

## Blockers

| Date | Blocker | Note |
|---|---|---|
| 2026-09-24 | Anti-cheat: warning + SPEED RESTRICTION (10 h left at ~18:00 local); farm, watchdog and every survey script stopped | Judges UTC 09-23 (local 09-23 07:00 -> 09-24 07:00): 17.1 h online, 100 marches -- the heaviest day on record, mostly my overnight run (00:45-07:55) past the 08:00-23:00 ceiling. The restriction explains the five marches of 15:39-15:52 still out 2 h later (no gem after 15:52) and the watchdog's two "no mine in 50 min" relaunches. Do not farm under it; resume only on the operator's word, inside 08:00-23:00 |
| 2026-08-14 | Unattended restart may need an admin terminal | While the game runs, `launcher.exe` is not running (observed). If it does not reappear on game exit, relaunching it raises a UAC prompt that nobody is there to accept -- run the bot elevated for overnight sessions |

Resolved: the `.venv` blocker from 2026-06-14 is gone -- `.venv\Scripts\python`
is Python 3.12.10 with the project deps, and `pytest` now runs (5 passed).
