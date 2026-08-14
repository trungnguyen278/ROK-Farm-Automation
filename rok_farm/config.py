"""All tuned constants for the gem farm runner.

Values here were measured against the live client at 1533px content width; see
the comment above each block for how it was derived. Two names are rebound at
runtime by the CLI (SAVE_SCREENSHOTS, ICON_ZOOM_SCROLLS), so read those through
the module (`cfg.ICON_ZOOM_SCROLLS`), never with `from config import ...`.
"""

from __future__ import annotations

from rok_farm import PROJECT_ROOT

# --- Paths ---
TEMPLATE_DIR = str(PROJECT_ROOT / "templates")
SCREENSHOT_DIR = PROJECT_ROOT / "screenshots" / "gem_farm_test"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
PATHS_FILE = PROJECT_ROOT / "profiles" / "paths.json"
REGISTRY_FILE = PROJECT_ROOT / "data" / "button_registry.json"
# API keys live outside the repo history: profiles/*.json is gitignored except
# default.json. Environment variables take precedence over this file.
SECRETS_FILE = PROJECT_ROOT / "profiles" / "secrets.json"

# --- Runtime knobs (rebound by main(); always read via the module) ---
SAVE_SCREENSHOTS = True
ICON_ZOOM_SCROLLS = 0

# --- Thresholds ---
GEM_ICON_THRESHOLD = 0.72
# Night gate. With the desaturate normalization a real gem matches ~0.73, while
# terrain noise sits ~0.62-0.65, so gate at 0.70 to drop the noise.
GEM_ICON_THRESHOLD_NIGHT = 0.70

# Out-of-kingdom fog is a smooth low-detail gray cloud. Measured: fog lap_var~8,
# sat~13; terrain lap_var~440-580, sat~155-160 -- huge gap, generous thresholds.
FOG_LAP_VAR_MAX = 60.0
FOG_SAT_MAX = 55.0
BUTTON_THRESHOLD = 0.70
GATHER_BTN_THRESHOLD = 0.65
WORLD_MAP_BTN_THRESHOLD = 0.75
GEM_MINE_THRESHOLD = 0.60
OCCUPY_ICON_PCT = 1.0
SAFE_ZONE_MARGIN = 0.08
DARK_TERRAIN_THRESH = 70
DRAG_OVERLAP = 0.20

MARCH_TEMPLATES = ["buttons/march_btn_orange", "buttons/march_btn"]
GEM_MINE_TEMPLATES = ["resources/gem_mine_close", "resources/gem_mine"]

# "Occupied" gathering icon: a colored circle with a white pickaxe shown on top
# of a mine that someone is already gathering. Three colors by alliance relation
# (green = own/ally, blue, red = other). Matched ONLY in a tight region around
# the detected mine so a different mine's icon farther away isn't picked up.
OCCUPIED_TEMPLATES = ["resources/occupied_green", "resources/occupied_red",
                      "resources/occupied_blue"]
OCCUPIED_THRESHOLD = 0.62

# Deploy-flow buttons at FIXED client positions (measured from screenshots).
# Clicked directly instead of template-matched: detection fails at night, and a
# wrong/missed click here marches nothing while looking like success.
NEW_TROOP_BTN_PCT = (0.852, 0.294)   # "Quan moi" (new troop), right side
MARCH_BTN_PCT = (0.656, 0.763)       # "Hanh quan" (march), in the commander panel
# Bottom-right corner toggles city <-> world. Clicked at this FIXED spot: the
# template-matched position can land just off the hit-area (observed: matched
# click didn't toggle, fixed corner did), and detection is flaky at night.
TOGGLE_BTN_PCT = (0.95, 0.93)

# After clicking a gem icon the game auto-centers on the mine, so the mine
# structure (~0.52,0.45) and its gather popup land in the middle. The post-click
# verify matches this region FIRST (much faster than the whole 1533x862 frame
# for big templates), then falls back to a full-frame match if the ROI misses --
# so an off-center mine (click drift, or a mine near the map edge that can't
# fully center) is still found, just a touch slower that once. Margin is wide.
VERIFY_ROI = (0.18, 0.18, 0.82, 0.75)  # x1, y1, x2, y2 in frame pct

# Longest a single gem-farm march (out + gather + back) realistically takes.
# Used as the cap when waiting alt-tabbed for the "troops returned" toast.
MAX_MARCH_MINUTES = 15

# Target game client width; the window is resized to this at startup (same as
# `python -m anti_detection.player_actions`) so template scales stay consistent.
TARGET_CONTENT_W = 1533
# Seconds counted down at startup so the user can get ready before the bot acts.
COUNTDOWN_SECONDS = 5

# --- Window layout ---
TITLE_BAR_H = 40

# --- Time delays (center, spread) --- focused-player speed ---
DELAY_AFTER_CLICK = (0.15, 0.06)
DELAY_AFTER_ESCAPE = (0.18, 0.07)
DELAY_AFTER_SCROLL = (0.30, 0.10)
DELAY_ZOOM_IN = (1.5, 0.3)
# Poll step while waiting for the mine to zoom in (see _click_icon_and_verify):
# we re-check up to ZOOM_POLL_MAX times so a fast zoom proceeds immediately
# instead of always paying the full DELAY_ZOOM_IN sleep.
DELAY_ZOOM_IN_POLL = (0.45, 0.12)
ZOOM_POLL_MAX = 3
DELAY_MINE_CLICK = (0.30, 0.10)
DELAY_RECHECK = (0.15, 0.05)
DELAY_VERIFY = (0.35, 0.12)
DELAY_DRAG_SETTLE = (0.40, 0.12)
DELAY_WORLD_MAP = (1.5, 0.5)
DELAY_BETWEEN_MINES = (1.0, 0.4)
DELAY_DRAG_PRE = (0.08, 0.04)
DELAY_DRAG_POST = (0.25, 0.10)
DELAY_MICRO_PAUSE = (0.40, 0.15)

# --- Game process lifecycle ---
# The game client is only quit/relaunched for recovery or a LONG break. The
# ~15min march wait stays an alt-tab: the "troops returned" Windows toast is
# emitted by the running client while it sits in the background, so quitting
# would trade a real signal for a blind timer (and add a login event every
# 15 minutes, which is a far louder pattern server-side).
AUTO_LAUNCH_GAME = True          # start the game at setup if the window is missing
RESTART_ON_RECOVERY = True       # relaunch a broken client instead of retrying blind
RESTART_AFTER_FAILS = 8          # consecutive mine failures before a restart
RESTART_BREAK_MINUTES = 30.0     # session break >= this -> quit the game for it
MAX_RESTARTS_PER_HOUR = 3        # guard against a restart loop
WINDOW_LOST_TIMEOUT = 60.0       # window missing this long -> broken client
FRAME_STALL_TIMEOUT = 45.0       # no fresh frame this long -> broken client
GAME_LAUNCH_TIMEOUT = 180.0      # launcher Play -> game window
CITY_READY_TIMEOUT = 300.0       # game window -> city view usable
LAUNCHER_WINDOW_TIMEOUT = 90.0   # launcher.exe start -> its window appears
LAUNCHER_UAC_TIMEOUT = 120.0     # extra grace while the user accepts the UAC prompt
QUIT_TIMEOUT = 30.0              # graceful exit before taskkill
RESTART_COOLDOWN = (20.0, 60.0)  # random pause between quit and relaunch

# --- Layer 1: local screen-state probe ---
# Measured on the live client at 1533x863, 2026-08-14
# (tools/dev/measure_state_signals.py, results in logs/state_signals.json):
#
#   state             frame activity   dim ratio   city_btn   world_map_city_btn
#   world map (near)      0.867           1.064      0.777          0.742
#   city                  0.504           1.178      0.612          0.958
#   gather popup          0.088           1.188      0.908          0.618
#   alliance panel        0.021           4.775      0.586          0.367
#   bag panel             0.008           4.971      0.482          0.444
#   world map (icon zoom) 0.001           1.131      0.787          0.754
#   the same, at NIGHT    n/a             1.045      0.844          0.662
#
# The dim ratio separates with a wide margin and no ambiguity: everything
# uncovered lands at 1.05-1.19, every full modal at 4.78-4.97. MODAL_RATIO_MIN
# sits in the empty space between.
#
# The night row is why this is a RATIO and not a brightness. Same camera
# position, same icons, night lighting: border brightness fell 134.1 -> 76.0, a
# 44% drop that any absolute threshold would have tripped over, while the ratio
# barely moved (1.131 -> 1.045) because the darkening divides out. The view
# discriminators also held: city_btn 0.844 still clears its gate and
# world_map_city_btn 0.662 still misses the city gate.
MODAL_RATIO_MIN = 1.8       # centre/border brightness; 1.19 uncovered vs 4.78 modal

# --- Why there is no frame-difference "client froze" detector ---
# There was one, and the measurements above killed it. The idea was that a live
# view animates while a crashed one repeats a frame. It does not hold here:
#
#   * the world map at icon zoom -- the view the bot spends MOST of its time in
#     while scanning for gems -- reads 0.001, i.e. completely static;
#   * the gather popup, which appears in every single mine, reads 0.088;
#   * an open panel reads 0.008.
#
# So a healthy, extremely common screen is indistinguishable from a dead client,
# and the action on "dead" is to restart the game. Two successive attempts to
# pick a safe threshold (0.15, then 0.02) were both falsified by the next state
# measured. There is also no always-animating anchor to fall back on: the HUD
# clock disappears in compact mode, which is exactly the mode used at icon zoom.
#
# A real freeze is still caught, just later and by evidence that means something:
# the window vanishing, capture returning nothing at all (FRAME_STALL_TIMEOUT),
# or RESTART_AFTER_FAILS consecutive mine failures -- a frozen client fails every
# mine. Do not reintroduce the pixel-motion version without a signal that is
# actually guaranteed to move.

# The city/world discriminator. The old margin comparison is fragile: on the
# world map city_btn beat world_map_city_btn by only 0.035. The ABSOLUTE score of
# world_map_city_btn separates 6x better (0.958 city vs 0.742 world), so gate on
# that instead.
CITY_WMCB_MIN = 0.85        # world_map_city_btn >= this -> we are in the city
WORLD_CITY_BTN_MIN = 0.70   # city_btn >= this while wmcb is low -> world map

# --- Layer 2: vision-model oracle ---
# Called only when the local layers cannot tell what is on screen. The budget is
# ours, not the provider's: free tiers change without notice, so the bot caps
# itself rather than discovering a quota wall mid-run.
# Layer 1 confidence below this, or a view it could not name at all, is what
# escalates to the model. Everything above stays local, free and instant.
ORACLE_ESCALATE_BELOW = 0.6
ORACLE_MAX_PER_HOUR = 20
ORACLE_MIN_GAP_S = 30.0
ORACLE_TIMEOUT_S = 20.0
ORACLE_MAX_ERRORS = 3        # consecutive failures -> disable for this run
ORACLE_MAX_WIDTH = 768       # one image tile; the cheapest unit these APIs bill
ORACLE_JPEG_QUALITY = 80

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
# Tried in order. The cheap PAID model leads on purpose. Measured 2026-08-14 on
# a live frame: nemotron:free took an upstream 504 after ~120s, gemma:free
# answered 429, and qwen answered correctly in ~4s -- the free tier turned one
# call into 127.8s. At 258 tokens an image and the 20/hour cap above, qwen costs
# roughly half a cent a day, so the free models are only worth having as backup.
# IDs verified against the public /api/v1/models listing on 2026-08-14.
OPENROUTER_MODELS = [
    "qwen/qwen3.7-flash",                    # ~$0.03/M prompt, fast and reliable
    "nvidia/nemotron-nano-12b-v2-vl:free",   # free backup
    "google/gemma-4-31b-it:free",
]
# Wall clock for the whole provider chain. The per-request socket timeout is not
# enough on its own: OpenRouter trickles bytes while waiting on a slow upstream,
# so the socket never goes idle and a dead model can hold the call for minutes.
ORACLE_TOTAL_DEADLINE_S = 30.0

# The free, no-key fallback: Google Search AI Mode driven in a browser. Needs
# `pip install playwright` and an installed Edge, both optional -- without them
# the provider simply reports itself unavailable. Measured ~27s headless.
AI_MODE_PROFILE_DIR = PROJECT_ROOT / "data" / "ai_mode_profile"
AI_MODE_TIMEOUT_S = 90.0

# --- Closing an unknown popup (rok_farm/dismiss.py) ---
# The only path where a model-derived coordinate becomes a click, hence the
# guardrails. Measured: a grounding model put the close button within ~1% of the
# frame; Google Search AI Mode was 15.5% out and would have hit a research node.
LEARNED_CLOSE_DIR = PROJECT_ROOT / "templates" / "ui" / "learned"
DISMISS_CROP_PCT = 0.02      # half-size of the crop saved when a button works

# Coarse-then-fine grounding. One call is measurably not enough: on a frame with
# two X buttons, five single-shot calls picked the wrong one four times, and
# repeating the call does not help because the bias is systematic (a consensus
# of five converged on the wrong button). Cropping around the coarse answer and
# asking again does fix it -- the crop spans both candidates and the zoom makes
# the difference visible. Measured: three coarse answers 90px out all came back
# within 1-4px of truth. The crop must be wide enough to include the real target
# when the coarse answer lands on a neighbour.
GROUNDING_CROP_PCT = 0.15    # half-width of the crop, as a fraction of the frame
GROUNDING_ZOOM = 2.5         # upscale before the second look
DISMISS_MAX_Y_PCT = 0.60     # close buttons live in the upper part of a panel
# Exclusion radius around each deploy button. Was 0.10 and that was too greedy:
# a correctly located panel close button at (0.759, 0.215) sits 0.093 / 0.079
# from NEW_TROOP_BTN_PCT, so the guard refused the single most accurate answer
# grounding has produced (1px from truth). At 1533px wide, 0.10 fences off a
# 306x172px box around a button perhaps a third that size. 0.05 still keeps a
# ~77x43px cordon while leaving legitimate close buttons clickable.
# MARCH_BTN_PCT is at y=0.763 and is already excluded by DISMISS_MAX_Y_PCT.
DISMISS_DANGER_MARGIN = 0.05

# --- Button position registry ---
# A fixed UI button lands in the same place every time, so a detection far from
# where that button has always been is a false positive. Each button learns its
# own tolerance from its own history; see rok_farm/button_registry.py.
REGISTRY_ENABLED = True
REGISTRY_WARMUP = 10        # detections recorded before rejection kicks in
REGISTRY_SIGMA = 4.0        # reject beyond this many combined std devs
REGISTRY_MIN_RADIUS = 0.06  # of the window: floor, so a tight history stays usable

GAME_PROCESS_NAME = "MASS.exe"       # the Unity client itself
LAUNCHER_PROCESS_NAME = "launcher.exe"
GAME_WINDOW_TITLE = "Rise of Kingdoms"
