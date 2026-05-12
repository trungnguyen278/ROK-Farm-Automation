# Vision System

> **AI Note:** 3 file: screen_capture (mss grab + ROI), template_matcher (OpenCV matchTemplate multi-scale), template_cache (LRU). Capture thread chạy riêng, throttle analysis 2-5fps.

## Screen Capture

```python
# capture/screen_capture.py
class ScreenCapture:
    def __init__(self, window_title: str = "Rise of Kingdoms")
    def find_window(self) -> dict          # returns {left, top, width, height}
    def grab_full(self) -> np.ndarray      # full window BGR
    def grab_roi(self, roi: ROI) -> np.ndarray  # cropped region

ROI = namedtuple('ROI', ['x', 'y', 'w', 'h', 'name'])
```

**ROI zones** (defined in config.yaml, relative to window):
| Zone | Purpose | Approx region |
|---|---|---|
| `top_bar` | Resources, power | top 5% |
| `center` | Main game area | middle 70% |
| `bottom_bar` | Action buttons | bottom 10% |
| `popup` | Dialog/popup area | center 40% |
| `minimap` | Minimap | bottom-right corner |

## Template Matching

```python
# vision/template_matcher.py
class TemplateMatcher:
    def __init__(self, cache: TemplateCache, threshold: float = 0.8)
    def match_single(self, frame: np.ndarray, template_name: str) -> Match | None
    def match_all(self, frame: np.ndarray, template_name: str) -> list[Match]
    def match_best(self, frame: np.ndarray, template_names: list[str]) -> Match | None

Match = namedtuple('Match', ['name', 'x', 'y', 'w', 'h', 'confidence', 'center'])
```

**Multi-scale matching:**
```python
scales = [0.8, 0.9, 1.0, 1.1, 1.2]  # handle resolution differences
for scale in scales:
    resized = cv2.resize(template, None, fx=scale, fy=scale)
    result = cv2.matchTemplate(frame, resized, cv2.TM_CCOEFF_NORMED)
    # keep best match across scales
```

## Template Cache

```python
# vision/template_cache.py
class TemplateCache:
    def __init__(self, template_dir: str, max_size: int = 100)
    def get(self, name: str) -> np.ndarray       # load + cache
    def preload(self, names: list[str])           # batch preload
    def clear(self)
```

Templates stored as: `templates/{category}/{name}.png`
```
templates/
├── buttons/       # ok.png, cancel.png, attack.png, ...
├── popups/        # march_confirm.png, scout_report.png, ...
├── states/        # city_view.png, world_map.png, ...
└── resources/     # food_icon.png, wood_icon.png, ...
```

## State Detector

```python
# vision/state_detector.py
class StateDetector:
    def __init__(self, matcher: TemplateMatcher)
    def detect(self, frame: np.ndarray) -> GameScreen

class GameScreen(Enum):
    UNKNOWN = "unknown"
    CITY_VIEW = "city_view"
    WORLD_MAP = "world_map"
    MARCH_SCREEN = "march_screen"
    POPUP_DIALOG = "popup_dialog"
    COMMANDER_SELECT = "commander_select"
    ALLIANCE_SCREEN = "alliance_screen"
```

Detection logic: match state templates against frame, return highest confidence match above threshold.

## Capture Thread Loop

```python
def capture_loop(capture, detector, result_queue, stop_event):
    while not stop_event.is_set():
        frame = capture.grab_full()
        state = detector.detect(frame)
        result_queue.put(VisionResult(frame, state, time.time()))
        time.sleep(0.2)  # ~5fps analysis
```
