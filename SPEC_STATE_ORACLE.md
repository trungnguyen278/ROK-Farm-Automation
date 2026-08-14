# SPEC: Screen State Detection

Two layers answering one question: **what is on screen right now?**

1. Local CV probes -- free, instant, no network. Handle the normal case.
2. A vision-model oracle -- provider-agnostic, called only when layer 1 is
   unsure. Rare by design.

## The problem, measured

| Situation | What the bot sees today |
|---|---|
| Clean world map | `city_btn` 0.536-0.574 against a 0.70 gate -- below its own threshold |
| Research panel open | all four ready-templates 0.000 -- indistinguishable from a dead client |
| Client frozen | still delivers identical frames, so "no frame" never fires |
| Event popup after login | no detection at all |

The decision the bot actually needs is narrow: *is something covering the HUD*,
*is the client still alive*, and *city or world map*. Naming the popup does not
change the action -- every modal closes the same way.

## Coordinates from a model: allowed, for dismissing only

Current models do real grounding -- the Gemini docs document object detection
returning `box_2d` normalised to 0-1000 -- so asking "where is the close button"
is a supported operation, not guesswork.

It is still the riskiest thing in this system: a wrong click in ROK can march
troops or spend gems. So the grounding path is fenced in:

1. **Intent whitelist.** A model-derived coordinate may only produce a *dismiss*
   click (close / X / "Thoat"). It may never produce a gameplay click. Gameplay
   buttons keep using captured positions and templates, unchanged.
2. **Danger-zone rejection.** A box overlapping the deploy region
   (`NEW_TROOP_BTN_PCT`, `MARCH_BTN_PCT` and a margin around them) is discarded
   outright, whatever the model says.
3. **Pre-click sanity check**, local and free. Crop the returned box and require
   it to look like a close button: area under `CLOSE_BOX_MAX_AREA_PCT` (3% of the
   frame), aspect ratio within 0.6-1.7, and sitting in the upper half. A box that
   fails is discarded without clicking.
4. **Post-click verification.** Compare the frame before and after. If nothing
   changed, the click missed -- log it, do not retry the same point, do not
   escalate to clicking around. One shot per unknown popup.
5. **Learn it.** When a dismiss click is verified to have worked, save the crop
   as `templates/ui/learned/close_<hash>.png` plus its position as a percentage
   of the window. The next time that popup appears, local template matching
   handles it for free.

Point 5 is the point of the whole feature: the model bootstraps the
button set the bot is missing today, and the API call count trends toward zero.
It reuses the auto-learn pattern already proven by the gem classifier.

---

## Layer 0 -- the button registry (no model involved)

This one needs no AI at all and should ship first: **a fixed UI button lands in
the same place every time, so a detection far from where that button has always
been is a false positive.**

### Why it is needed

Detection today is stateless -- each `_find*` call matches a template on one
frame and returns the best hit above threshold, with no memory of where that
button has been before. Three places already have hand-added static regions
(`_CITY_BTN_REGION`, `_NEW_TROOP_REGION`, the tight crop in `_is_mine_occupied`),
each added reactively after a specific misfire; the comment on the first one
records exactly that -- a rare event icon in the top-right was out-scoring the
real `city_btn`.

Two paths still match the whole frame and click the result:

| Path | Template | Consequence of a false positive |
|---|---|---|
| `flow_steps.py` `_step_click_gather` | `buttons/gather_btn` | clicks an arbitrary point on the world map |
| `recovery.py` `_check_reconnect_popup` | `ui/btn_confirm_reconnect` | same, while already in a confused state |

### How it works

`data/button_registry.json`, one entry per template that is UI-fixed:

```json
{
  "buttons/gather_btn": {
    "n": 47,
    "mean": [0.515, 0.605],
    "std":  [0.021, 0.034],
    "last_seen": "2026-08-14T18:22:04"
  }
}
```

- Every accepted detection records its centre as a fraction of the window.
- The first `REGISTRY_WARMUP` detections (default 10) only record -- no
  rejection, so the registry bootstraps itself from a normal run.
- After warmup, a detection further than `max(REGISTRY_MIN_RADIUS,
  REGISTRY_SIGMA * std)` from the mean is rejected as a misfire and logged.
  `REGISTRY_MIN_RADIUS` (default 0.06 of the window) is the floor so a button
  with a very tight history does not become impossible to re-detect.

Each button therefore calibrates its own tolerance: a truly fixed button ends up
with a tight gate, one that moves with a popup ends up with a loose one. No
hand-tuned regions, and it covers every button uniformly instead of only the
three that have already burned us.

### Where it is enforced

`_click_match` in `input_hid.py` -- both clicking paths above already funnel
through it, so the check lives in exactly one place.

Buttons that legitimately move (`resources/gem_icon`, the mine templates) are
simply never registered; the registry only holds templates declared UI-fixed.

### With a model on top

The same registry is what the grounding path writes into: a dismiss click that is
verified to have worked stores the crop as a new template plus its position, so
an unknown popup becomes a known button and the next occurrence is handled
locally for free.

---

## Layer 1 -- `rok_farm/state_probe.py`

```python
@dataclass
class ScreenState:
    view: str        # "city" | "world_map" | "loading" | "unknown"
    overlay: str     # "none" | "modal" | "reconnect" | "unknown"
    alive: bool
    confidence: float
    source: str      # "local" | "<provider>" | "cache"
    note: str
```

### 1a. Liveness -- is the client running or frozen?

Sample 3 frames ~0.5 s apart, downscale to 160x90 gray, take the mean absolute
difference between consecutive frames. A live ROK view always animates (water,
flags, troops, cloud shadows); a frozen or crashed client repeats one frame.

Declare `alive=False` only after `LIVENESS_SAMPLES` consecutive quiet windows
(default 3, i.e. ~15 s) -- one quiet sample is not enough, a paused menu can be
almost static.

`LIVENESS_MIN_DIFF` -- **to be measured**, see "Calibration" below.

This replaces today's `_client_looks_broken` frame-stall check, which only fires
when capture returns *nothing*; a frozen client still returns frames and is
invisible to it.

### 1b. Modal detect -- is something covering the HUD?

ROK dims the background behind a modal. Compare the mean brightness of the outer
10% ring against the centre box (0.28-0.72 x, 0.22-0.78 y):

```
ratio = centre_brightness / border_brightness
```

Modal open -> bright panel over a dimmed background -> ratio well above 1.
Clean view -> ratio near 1.

`MODAL_RATIO_MIN` -- **to be measured**.

### 1c. View vote

`city_btn` vs `world_map_city_btn` in the bottom-right corner, as today, plus the
unused `templates/states/{city_view,world_map}` as a second opinion. Confidence
is the margin between the two candidates; a margin under `VIEW_TIE_MARGIN` (0.06)
is a tie -> `view="unknown"`, which is what escalates.

### Calibration (run before the thresholds are written into config)

`tools/dev/measure_state_signals.py`, with the game open, in three states the
user drives manually: clean city, clean world map, any panel open. It prints
liveness diff and the dim ratio for each. Thresholds go into `config.py` with the
measured numbers in a comment, matching how `FOG_LAP_VAR_MAX` and the night
thresholds are documented.

---

## Layer 2 -- `rok_farm/vision_llm.py`

### Providers

One protocol, three backends, chosen by whichever key exists:

```python
class VisionProvider(Protocol):
    name: str
    supports_grounding: bool
    def ask(self, jpeg: bytes, prompt: str, schema: dict) -> dict | None
```

| Provider | Auth | Default model | Notes |
|---|---|---|---|
| `openrouter` | `OPENROUTER_API_KEY` | see below | **built 2026-08-14**, one key many models |
| `mock` | none | -- | **built**, canned answers for tests |
| `gemini` | `GEMINI_API_KEY` / `GOOGLE_API_KEY` | `gemini-3.5-flash-lite` | grounding (`box_2d`) supported |
| `openai` | `OPENAI_API_KEY` | `gpt-5-mini` | |

OpenRouter model order, ids verified against the public `/api/v1/models`
listing on 2026-08-14 (243 of 411 models accept image input):

```python
OPENROUTER_MODELS = [
    "qwen/qwen3.7-flash",                    # ~$0.03/M prompt, fast and reliable
    "nvidia/nemotron-nano-12b-v2-vl:free",   # free backup
    "google/gemma-4-31b-it:free",
]
```

**The cheap paid model leads on purpose.** Measured on a live frame, free-first:

| Model | Result |
|---|---|
| `nemotron:free` | upstream 504 after ~120 s |
| `gemma-4:free` | HTTP 429 |
| `qwen3.7-flash` | correct answer in ~4 s |

One call took **127.8 s** that way; with the paid model first it takes **3.3 s**.
At 258 tokens an image and the 20/hour cap, qwen costs roughly half a cent a day,
so the free tier is a false economy here -- worth keeping only as backup.

A socket timeout does not bound this on its own: OpenRouter trickles bytes while
waiting on a slow upstream, so the connection never goes idle. Hence
`ORACLE_TOTAL_DEADLINE_S`, a wall clock across the whole model chain.

### Two lessons from the live replies

1. **No `confidence` field.** Asked for one, a small model ran the digits away --
   `"confidence":0.9590909090909091e+23724297235654385656...` -- until it hit
   `max_tokens`, truncating an otherwise correct answer into unparseable JSON.
   The three fields the flow acts on are enough.
2. **`overlay` had to be defined as *blocking*.** The first version returned
   `event_popup` and `chat` for a perfectly playable world map, because ROK
   always shows a chat log and floating toasts. The prompt now says explicitly
   that the chat log, toasts, quest trackers and the HUD are not overlays --
   otherwise the flow would keep trying to clear things that need no clearing.

`parse_state` tolerates all three failure levels: whole-reply JSON, a JSON object
embedded in prose, and finally field-by-field regex to salvage a truncated reply.
| `gemini_web` | browser cookies | Gemini web app | no key, see caveats |
| `ai_mode_web` | browser profile | Google Search AI Mode | free, no grounding, see below |
| `mock` | none | -- | canned answers, for tests |

Keys come from the environment or `profiles/secrets.json` (already gitignored by
`profiles/*.json`). Preference order is configurable; the first available wins.
Nothing available -> layer 2 is simply off and everything falls back to layer 1.

`gemini_web` uses the `gemini_webapi` package, which reuses the
`__Secure-1PSID` / `__Secure-1PSIDTS` cookies from a logged-in browser and
refreshes them in the background. It costs nothing and needs no key, but it is
reverse-engineered: it breaks when Google changes the web app, the cookies expire
and need a re-login, and it drives a real Google account. Treat it as the
fallback, not the default.

### The `ai_mode_web` provider -- PROVEN WORKING, 2026-08-14

Google Search AI Mode takes an image plus a question. No published wrapper
exposes that (the free ones -- `PleasePrompto/google-ai-mode-skill` 291*,
`.../google-ai-mode-mcp` 148*, `Dark2C/Google-AI-Mode-API-Wrapper`,
`XD06/google-ai-mode` -- are text-query only; the rest are paid scraping SDKs),
so we drive the page ourselves. **Validated end to end against a real game
screenshot**, not assumed:

| Step | Result |
|---|---|
| Land on `https://www.google.com/search?udm=50` with no query | works |
| Login required | **no** |
| CAPTCHA | **none seen** |
| Attach the frame | works -- synthetic `ClipboardEvent('paste')` carrying a `File`, no OS clipboard needed. Google echoes "Bạn đã gửi: 1 hình ảnh" |
| Structured output | works -- asked for one line of JSON, got exactly that |
| Round trip, headed | **10.1 s** state, **6.1 s** grounding |
| Round trip, headless | **27.2 s**, same answer -- no visible window, no focus stolen |

Headless is the mode to run in: the game keeps the foreground, which matters
because the bot's clicks go to whatever is in front.

Verified answer on a frame showing the city with the research panel open:

```json
{"view":"city","overlay":"modal","covers_hud":false}
```

All three fields correct, including `covers_hud:false` (the resource bar was
still visible above the panel).

Mechanics that matter for the implementation -- all four were found the hard way:

- Use the landing URL with **no** `q=`. Any `?q=...` jumps past the landing page
  into the follow-up chat UI, where the compose box behaves differently.
- Paste into `textarea` (there is no `textarea[name=q]` on the AI Mode page).
- The reply must be extracted from *after* the echoed question -- the page
  repeats the prompt, so a naive regex matches our own schema literal.
- **Flatten the prompt before typing it.** `keyboard.type()` sends a newline as
  Enter, which submits the box; a multi-line prompt fires its own first line off
  as the whole question and the call comes back empty. This one only surfaced
  when the provider was driven through the oracle interface rather than the
  standalone tool, whose prompt happened to be single-line.

Wired and measured through the real oracle interface, 2026-08-14: **43.0 s**
headless including browser start, `view=world_map overlay=none covers_hud=false`
-- the same verdict OpenRouter gave in 3.3 s and layer 1 gave for free.

| | `ai_mode_web` | official API |
|---|---|---|
| Money | free | ~nothing at a few calls/hour |
| Latency | 6-10 s headed, 27 s headless | ~1-2 s |
| Footprint | an Edge process beside the game | an HTTP call |
| Output | prose, but reliably steerable to one JSON line | JSON against a schema |
| Grounding | answers, but not click-accurate (below) | `box_2d`, purpose-built |
| Failure mode | CAPTCHA, DOM changes | quota errors |

### Grounding, measured (2026-08-14)

Same frame each time -- the city with the research panel open, its X at (777,125)
in a 1024x576 shot:

| Provider / model | Answer | Error | Time |
|---|---|---|---|
| `google/gemini-2.5-flash-lite`, run 1 | (768, 118) | 0.9% / 1.2% | 1.7 s |
| `google/gemini-2.5-flash-lite`, run 2 | (690, 120) | 8.5% / 0.9% | 2.2 s |
| `qwen/qwen3.7-flash` | nothing | -- | 4.8 s |
| `openai/gpt-5-nano` | nothing | -- | 2.1 s |
| Google AI Mode | (758, 214) | 1.9% / 15.5% | 6.1 s |

Two things follow, and both are load-bearing:

1. **Grounding runs only on a model that can do it.** The cheap text-shaped
   models returned nothing at all for the same request, so `GROUNDING_MODELS` is
   a separate list from the state models.
2. **Post-click verification is mandatory, not a nicety.** Run 2 was not a
   hallucination -- it landed on a *different real* X, the one belonging to the
   banner strip above the panel, because that frame has two close buttons in the
   top-right. Clicking it would have closed the banner and left the panel up. A
   system that trusted the coordinate would have believed it succeeded; one that
   re-reads the dim ratio sees the panel is still there, stops, and does not
   learn the wrong button.

Run-to-run variance on an identical image is the point: this is a probabilistic
answer being turned into a physical click, so it is checked by result.

### Grounding on `ai_mode_web`: answers, but do not click it

Measured on the same frame, asking for the panel's X button (truth at 777,125 in
a 1024x576 frame):

```
model: X=758 Y=214    error dx=-19 (1.9% of width), dy=+89 (15.5% of height)
```

Horizontally near-perfect, vertically off by enough to land on a **research node
inside the panel** instead of the close button -- see the marked comparison in
the session notes. A blind click there would have opened a research detail; the
same error next to the deploy panel would march troops.

n=1, so this is not an accuracy rate. It is enough to settle the design
question though:

- `ai_mode_web` is used for **state only**.
- Grounding runs on the API path, and the guardrails in "Coordinates from a
  model" stay mandatory regardless of provider -- this measurement is exactly
  why the pre-click and post-click checks exist.

### Two request kinds

Frame downscaled to <= 768 px wide, JPEG q80 -- one image tile, the cheapest unit
these APIs bill.

**A. State** (any provider):

```json
{
  "view":       "city | world_map | loading | login | unknown",
  "overlay":    "none | modal | event_popup | reward | reconnect | chat",
  "covers_hud": true,
  "confidence": 0.0,
  "note":       "<= 12 words"
}
```

**B. Locate the dismiss control** (grounding-capable providers only, and only
after A reported an overlay):

```json
{
  "found":  true,
  "box_2d": [ymin, xmin, ymax, xmax],
  "kind":   "x_button | close_button | outside_tap",
  "confidence": 0.0
}
```

`box_2d` is normalised 0-1000 as the Gemini docs define it, converted back to
window pixels locally. Every guardrail in "Coordinates from a model" applies to
the result before anything is clicked.

### When it is called (the escalation gate)

Only when layer 1 returns `confidence < ORACLE_ESCALATE_BELOW` **and** the budget
allows, at these points:

1. `_wait_until_in_city` -- templates all miss: popup, still loading, or dead?
2. `_client_looks_broken` -- before spending a game restart on a false alarm.
3. `_attempt_recovery` -- confirm a modal is really open before pressing ESC.
   This makes ESC *safer*: today `_on_clean_view` fails open when templates miss.
4. `_find_city_btn` tie -- city and world map read within `VIEW_TIE_MARGIN`.
5. **Unknown overlay with no matching close template** -- request B, then the
   guarded dismiss click, then learn the button. This is the case the bot cannot
   handle at all today.

### Budget and failure

Free tiers move without notice (Google cut theirs in Dec 2025 and no longer
publishes the numbers), so the bot enforces its own ceiling rather than trusting
the provider's:

```python
ORACLE_MAX_PER_HOUR = 20
ORACLE_MIN_GAP_S    = 30.0
ORACLE_TIMEOUT_S    = 8.0
ORACLE_MAX_ERRORS   = 3      # consecutive failures -> disable for the run
```

- dHash cache: same frame within `ORACLE_CACHE_S` (60 s) reuses the verdict.
- Any error, timeout, quota rejection or malformed JSON -> return `None`. The
  caller keeps today's behaviour. **The farm loop never blocks on the network.**
- Every call is logged with provider, latency, verdict and the frame it judged,
  so the value of the escalation can be audited afterwards.

### Privacy

Frames are screenshots of the game and they leave the machine when layer 2 runs.
Layer 2 is off unless a key is configured.

---

## Config + CLI

```python
STATE_ORACLE_ENABLED    = True    # honoured only when a provider is available
ORACLE_PROVIDER_ORDER   = ("gemini", "openrouter", "openai", "gemini_web")
ORACLE_ESCALATE_BELOW   = 0.6
ORACLE_ALLOW_GROUNDING  = True    # request B + the guarded dismiss click
LIVENESS_SAMPLES        = 3
VIEW_TIE_MARGIN         = 0.06
CLOSE_BOX_MAX_AREA_PCT  = 0.03

REGISTRY_ENABLED        = True
REGISTRY_WARMUP         = 10      # detections recorded before rejection starts
REGISTRY_SIGMA          = 4.0
REGISTRY_MIN_RADIUS     = 0.06    # of the window, floor for the reject radius
```

```text
--no-oracle              never call a vision model this run
--oracle-provider NAME   force one provider
--no-grounding           state questions only, never a model-derived click
```

## Build order

1. **Layer 0, the button registry.** No model, no network, fixes a live exposure
   (two full-frame matches that get clicked). Ships first.
2. `tools/dev/measure_state_signals.py` + calibrate the layer-1 thresholds on the
   live client (clean city / clean world map / panel open).
3. Layer 1 and its wiring. This alone should fix the frozen-client blind spot and
   the 300 s `_wait_until_in_city` timeout.
4. Layer 2: provider interface + `mock` + the proven `ai_mode_web` provider,
   behind the escalation gate and the budget.
5. **Parked until an API key exists:** grounding for unknown popups. The
   interface is built in step 4 so the provider can be dropped in later;
   `ai_mode_web` is not accurate enough to click from (measured above).

Layers 0 and 1 have to earn their keep before any network call is wired in -- if
they settle the common cases, layer 2 stays as rare as intended.

## Acceptance

- With no provider: behaviour identical to today, zero network calls, tests green.
- Frozen client (game suspended) is detected within ~15 s, where today it is not
  detected at all.
- With a panel open, `_wait_until_in_city` reports "modal" rather than timing out
  after 300 s.
- Oracle disabled after `ORACLE_MAX_ERRORS` failures, and never called more than
  `ORACLE_MAX_PER_HOUR` times.
- A mock provider covers the wiring in tests, so no key is needed to run them.
- A model-derived click never lands in the deploy region: covered by a unit test
  feeding a poisoned box through the guardrails.
- A dismissed unknown popup appears in `data/button_registry.json` and is closed
  locally, with no API call, the second time it shows up.
- Layer 0: after warmup, a `gather_btn` match planted far from its recorded
  cluster is rejected by `_click_match` and never clicked -- unit test with a
  synthetic registry, no game needed.
- Layer 0 never blocks a first run: with an empty registry every detection is
  accepted and recorded.
