"""Layer 2: ask a vision model what is on screen, when layer 0/1 cannot tell.

This is the escalation path, not a component of the normal loop. It is wrapped in
a budget because free tiers move without notice, and every failure mode returns
None so the caller simply keeps today's behaviour -- **the farm loop must never
block on the network.**

Providers implement one small protocol, so the backend is a runtime choice:

    openrouter   one key, many vision models          (built here)
    mock         canned answers                       (built here, for tests)
    ai_mode_web  free, proven, see tools/dev/probe_ai_mode.py   (next)
    gemini/openai                                     (later)

No new dependency: requests/httpx are not in this project, so the HTTP call goes
through urllib from the standard library.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

import cv2
import numpy as np

from rok_farm.config import (AI_MODE_PROFILE_DIR, AI_MODE_TIMEOUT_S,
                             ORACLE_JPEG_QUALITY, ORACLE_MAX_ERRORS,
                             ORACLE_MAX_PER_HOUR, ORACLE_MAX_WIDTH,
                             ORACLE_MIN_GAP_S, ORACLE_TIMEOUT_S,
                             ORACLE_TOTAL_DEADLINE_S, OPENROUTER_MODELS,
                             OPENROUTER_URL, SECRETS_FILE)
from rok_farm.logging_setup import logger

# --- The question ------------------------------------------------------------

STATE_PROMPT = (
    "This is a screenshot of the PC game Rise of Kingdoms. "
    "Answer with ONE line of JSON and nothing else, no markdown, no explanation.\n"
    '"view": the underlying screen -- city (your own base, buildings in a grid), '
    "world_map (terrain, troops, other players' cities), loading, login, unknown.\n"
    '"overlay": ONLY a dialog or panel that COVERS the game and has to be closed '
    "before playing continues -- modal, event_popup, reward, reconnect. "
    "Report \"none\" if the game world is playable. The permanent chat log in the "
    "bottom-left corner, floating toast banners, quest trackers and the normal "
    "HUD are NOT overlays; they are always on screen. Use \"chat\" only when the "
    "chat window is opened up over the game.\n"
    '"covers_hud": true only when the top resource bar AND the bottom-right '
    "buttons are both hidden by something.\n"
    '{"view":"...","overlay":"...","covers_hud":false}'
)

STATE_SCHEMA = {
    "name": "screen_state",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "view": {"type": "string",
                     "enum": ["city", "world_map", "loading", "login", "unknown"]},
            "overlay": {"type": "string",
                        "enum": ["none", "modal", "event_popup", "reward",
                                 "reconnect", "chat"]},
            "covers_hud": {"type": "boolean"},
        },
        # No "confidence" field on purpose. A small model asked for one ran the
        # digits away -- "0.9590909090909091e+23724297235654385656..." -- until
        # it hit max_tokens, truncating an otherwise correct answer into
        # unparseable JSON. The three fields above are what the flow acts on.
        "required": ["view", "overlay", "covers_hud"],
        "additionalProperties": False,
    },
}

VIEWS = set(STATE_SCHEMA["schema"]["properties"]["view"]["enum"])
OVERLAYS = set(STATE_SCHEMA["schema"]["properties"]["overlay"]["enum"])

# --- Locating the dismiss control -------------------------------------------
# Only ever used to CLOSE something. Measured on a real frame (panel X at
# 777,125 in a 1024x576 shot): gemini-2.5-flash-lite answered (768,118) in 1.7s
# -- 0.9% / 1.2% of the frame, comfortably inside the button. qwen3.7-flash and
# gpt-5-nano both returned nothing, and Google Search AI Mode was 15.5% out
# vertically, landing on a research node. So grounding runs on a model known to
# do it, and the guardrails in dismiss.py apply regardless.

DISMISS_PROMPT = (
    "This is a screenshot of the game Rise of Kingdoms. A panel or popup is "
    "open over the game. Locate its CLOSE button -- the X, usually in the "
    "top-right corner of the panel. "
    "Reply with ONE line of JSON and nothing else. Coordinates are normalised "
    "to 0-1000 over the image width and height. If there is no close button, "
    'answer {"found":false,"x":0,"y":0}. '
    '{"found":true,"x":0,"y":0}'
)

DISMISS_SCHEMA = {
    "name": "close_button",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "found": {"type": "boolean"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        },
        "required": ["found", "x", "y"],
        "additionalProperties": False,
    },
}

GROUNDING_MODELS = ["google/gemini-2.5-flash-lite"]


@dataclass(frozen=True)
class StateVerdict:
    view: str
    overlay: str
    covers_hud: bool
    confidence: float
    source: str
    raw: str = ""

    @property
    def blocked(self) -> bool:
        """Something is covering the game and the flow should clear it first."""
        return self.overlay != "none"


# --- Keys --------------------------------------------------------------------

def load_secret(*names: str) -> str | None:
    """First hit wins: environment, then profiles/secrets.json (gitignored)."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value.strip()
    try:
        if SECRETS_FILE.exists():
            # utf-8-sig, not utf-8: a file written by PowerShell's
            # `Out-File -Encoding utf8` carries a BOM, and plain utf-8 chokes on it.
            data = json.loads(SECRETS_FILE.read_text(encoding="utf-8-sig"))
            for name in names:
                for key in (name, name.lower(), name.lower().replace("_api_key", "")):
                    if data.get(key):
                        return str(data[key]).strip()
    except Exception as e:
        logger.warning("Cannot read %s: %s", SECRETS_FILE, e)
    return None


# --- Frame preparation -------------------------------------------------------

def encode_frame(frame: np.ndarray, max_width: int = ORACLE_MAX_WIDTH,
                 quality: int = ORACLE_JPEG_QUALITY) -> bytes:
    """Downscale to one image tile and JPEG-encode -- the cheapest unit billed."""
    h, w = frame.shape[:2]
    if w > max_width:
        scale = max_width / w
        frame = cv2.resize(frame, (max_width, int(h * scale)),
                           interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame,
                           [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return buf.tobytes() if ok else b""


def dhash(frame: np.ndarray, size: int = 8) -> str:
    """Perceptual hash, so a near-identical screen reuses the cached verdict."""
    small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (size + 1, size),
                       interpolation=cv2.INTER_AREA)
    bits = small[:, 1:] > small[:, :-1]
    return "".join("1" if b else "0" for b in bits.flatten())


_FIELD_RE = {
    "view": re.compile(r'"view"\s*:\s*"([a-z_]+)"', re.I),
    "overlay": re.compile(r'"overlay"\s*:\s*"([a-z_]+)"', re.I),
    "covers_hud": re.compile(r'"covers_hud"\s*:\s*(true|false)', re.I),
}


def parse_state(text: str, source: str) -> StateVerdict | None:
    """Read a verdict out of a reply, however mangled.

    Three levels of tolerance, because these replies come from small models:
      1. the whole reply as JSON (what a schema-honouring provider returns);
      2. the first JSON object embedded in prose -- OpenRouter documents that
         strict mode is not honoured by every provider;
      3. field-by-field regex, which salvages a TRUNCATED reply. Observed live:
         a model answered correctly and then ran the digits of a number away
         until it hit max_tokens, leaving the JSON unclosed.
    """
    if not text:
        return None

    data = None
    candidates = [text.strip()]
    m = re.search(r'\{[^{}]*"view"\s*:.*?\}', text, re.S)
    if m:
        candidates.insert(0, m.group(0))
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            break
        except Exception:
            data = None

    if data is None:
        found = {k: r.search(text) for k, r in _FIELD_RE.items()}
        if not found["view"]:
            return None
        logger.info("Oracle reply was not valid JSON; recovered the fields by regex")
        data = {
            "view": found["view"].group(1),
            "overlay": found["overlay"].group(1) if found["overlay"] else "none",
            "covers_hud": bool(found["covers_hud"]
                               and found["covers_hud"].group(1).lower() == "true"),
        }

    view = str(data.get("view", "unknown")).lower()
    overlay = str(data.get("overlay", "none")).lower()
    if view not in VIEWS or overlay not in OVERLAYS:
        logger.info("Oracle returned unknown labels: %s / %s", view, overlay)
        view = view if view in VIEWS else "unknown"
        overlay = overlay if overlay in OVERLAYS else "none"
    return StateVerdict(view=view, overlay=overlay,
                        covers_hud=bool(data.get("covers_hud", False)),
                        confidence=1.0 if view != "unknown" else 0.0,
                        source=source, raw=text[:300])


# --- Providers ---------------------------------------------------------------

class VisionProvider(Protocol):
    name: str
    supports_grounding: bool

    def available(self) -> bool: ...
    def ask(self, jpeg: bytes, prompt: str, schema: dict | None = None) -> str | None: ...


class OpenRouterProvider:
    """One key, many vision models. Falls through the model list on failure."""

    name = "openrouter"
    supports_grounding = True    # via GROUNDING_MODELS, not the state models

    def __init__(self, api_key: str | None = None,
                 models: list[str] | None = None,
                 grounding_models: list[str] | None = None,
                 timeout: float = ORACLE_TIMEOUT_S):
        self._key = api_key or load_secret("OPENROUTER_API_KEY")
        self._models = list(models or OPENROUTER_MODELS)
        self._grounding_models = list(grounding_models or GROUNDING_MODELS)
        self._timeout = timeout

    def ask_grounding(self, jpeg: bytes, prompt: str,
                      schema: dict | None = None) -> str | None:
        """Same call, but restricted to models that can actually point at things.

        Measured: gemini-2.5-flash-lite lands within ~1% of the frame, while the
        cheap text-shaped models returned nothing at all for the same request.
        """
        saved = self._models
        self._models = self._grounding_models
        try:
            return self.ask(jpeg, prompt, schema)
        finally:
            self._models = saved

    def available(self) -> bool:
        return bool(self._key)

    def ask(self, jpeg: bytes, prompt: str, schema: dict | None = None) -> str | None:
        if not self.available() or not jpeg:
            return None
        data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
        deadline = time.time() + ORACLE_TOTAL_DEADLINE_S
        last_error = None
        for model in self._models:
            if time.time() >= deadline:
                logger.info("OpenRouter chain gave up at %s: %.0fs deadline spent",
                            model, ORACLE_TOTAL_DEADLINE_S)
                break
            try:
                return self._post(model, data_url, prompt, schema)
            except Exception as e:
                last_error = e
                logger.info("OpenRouter model %s failed: %s", model, str(e)[:120])
        if last_error:
            raise last_error
        return None

    def _post(self, model: str, data_url: str, prompt: str,
              schema: dict | None) -> str:
        body: dict = {
            "model": model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            # The answer is one short JSON object. A tight ceiling also bounds
            # the damage when a small model starts repeating itself.
            "max_tokens": 120,
        }
        if schema:
            body["response_format"] = {"type": "json_schema", "json_schema": schema}

        req = urllib.request.Request(
            OPENROUTER_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
                # Optional attribution headers OpenRouter documents.
                "HTTP-Referer": "https://github.com/local/rok-farm",
                "X-Title": "ROK Farm Automation",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            payload = json.load(resp)
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError(f"no choices in response: {str(payload)[:160]}")
        return choices[0].get("message", {}).get("content", "") or ""


class AiModeWebProvider:
    """Google Search AI Mode, driven in a browser. Free, no key, no quota.

    Proven end to end on a real game screenshot (see tools/dev/probe_ai_mode.py
    for the standalone version and the measurements). Three mechanics are easy
    to get wrong and all three are load-bearing:

      * land on the AI Mode URL with NO `q=` -- any query jumps past the landing
        page into the follow-up chat UI, where the compose box differs;
      * attach by dispatching a synthetic ClipboardEvent carrying a File, which
        fires the same handler as Ctrl+V without touching the OS clipboard;
      * read the reply from AFTER the echoed prompt, because the page repeats
        the question and a naive search matches our own words.

    Runs headless so the game keeps the foreground -- the bot's clicks go to
    whatever is in front. Measured ~27 s headless against ~10 s headed, which is
    fine for a fallback that only runs when no API key is configured.

    Needs `pip install playwright` plus an installed Edge; both are optional, so
    `available()` reports False rather than failing the run when they are absent.
    """

    name = "ai_mode_web"
    supports_grounding = False   # it answers, but not accurately enough to click

    URL = "https://www.google.com/search?udm=50"
    PASTE_JS = """
    async ([selector, dataUrl]) => {
      const el = document.querySelector(selector);
      if (!el) return 'no target';
      el.focus();
      const blob = await (await fetch(dataUrl)).blob();
      const dt = new DataTransfer();
      dt.items.add(new File([blob], 'screen.png', {type: 'image/png'}));
      const ev = new ClipboardEvent('paste', {clipboardData: dt, bubbles: true,
                                              cancelable: true});
      el.dispatchEvent(ev); document.dispatchEvent(ev);
      return 'dispatched';
    }
    """

    def __init__(self, profile_dir=AI_MODE_PROFILE_DIR, headless: bool = True,
                 timeout_s: float = AI_MODE_TIMEOUT_S):
        self._profile = profile_dir
        self._headless = headless
        self._timeout = timeout_s

    def available(self) -> bool:
        import importlib.util
        return importlib.util.find_spec("playwright") is not None

    def ask(self, jpeg: bytes, prompt: str, schema: dict | None = None) -> str | None:
        from playwright.sync_api import sync_playwright

        data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()
        # Flatten first: keyboard.type() sends a newline as Enter, which submits
        # the search box, so a multi-line prompt would fire off its own first
        # line as the whole question.
        flat_prompt = " ".join(prompt.split())
        anchor = flat_prompt[-40:]   # tail of our own prompt, echoed by the page
        self._profile.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=str(self._profile), channel="msedge",
                headless=self._headless, viewport={"width": 1280, "height": 900},
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                page.goto(self.URL, wait_until="domcontentloaded", timeout=45000)
                page.wait_for_timeout(4000)

                page.locator("textarea").first.click()
                page.wait_for_timeout(300)
                if page.evaluate(self.PASTE_JS, ["textarea", data_url]) != "dispatched":
                    return None
                page.wait_for_timeout(3500)

                page.locator("textarea").first.click()
                page.keyboard.type(flat_prompt, delay=5)
                page.wait_for_timeout(400)
                page.keyboard.press("Enter")

                deadline = time.time() + self._timeout
                last, stable = "", 0
                while time.time() < deadline:
                    page.wait_for_timeout(2000)
                    body = page.inner_text("body")
                    idx = body.rfind(anchor)
                    current = body[idx + len(anchor):].strip() if idx >= 0 else ""
                    if current and current == last:
                        stable += 1
                        if stable >= 3:      # unchanged ~6s -> generation finished
                            break
                    else:
                        stable = 0
                    last = current
                return last or None
            finally:
                ctx.close()


class MockProvider:
    """Canned answers, so the wiring is testable without a key or a network."""

    name = "mock"
    supports_grounding = False

    def __init__(self, reply: str | None = None, fail: bool = False,
                 latency: float = 0.0):
        self.reply = reply if reply is not None else (
            '{"view":"city","overlay":"modal","covers_hud":false,'
            '"confidence":0.9}')
        self.fail = fail
        self.latency = latency
        self.calls = 0

    def available(self) -> bool:
        return True

    def ask(self, jpeg: bytes, prompt: str, schema: dict | None = None) -> str | None:
        self.calls += 1
        if self.latency:
            time.sleep(self.latency)
        if self.fail:
            raise RuntimeError("mock failure")
        return self.reply


# --- The oracle --------------------------------------------------------------

@dataclass
class _Budget:
    max_per_hour: int = ORACLE_MAX_PER_HOUR
    min_gap_s: float = ORACLE_MIN_GAP_S
    max_errors: int = ORACLE_MAX_ERRORS
    calls: list[float] = field(default_factory=list)
    last_call: float = 0.0
    errors: int = 0
    disabled: bool = False

    def allows(self, now: float) -> tuple[bool, str]:
        if self.disabled:
            return False, "disabled after repeated errors"
        if now - self.last_call < self.min_gap_s:
            return False, f"min gap {self.min_gap_s:.0f}s not elapsed"
        self.calls = [t for t in self.calls if now - t < 3600]
        if len(self.calls) >= self.max_per_hour:
            return False, f"hourly cap {self.max_per_hour} reached"
        return True, "ok"

    def record_call(self, now: float):
        self.calls.append(now)
        self.last_call = now

    def record_error(self):
        self.errors += 1
        if self.errors >= self.max_errors:
            self.disabled = True
            logger.warning("Vision oracle disabled after %d consecutive errors",
                           self.errors)

    def record_success(self):
        self.errors = 0


class VisionOracle:
    """Budget, cache and provider selection around the raw providers."""

    def __init__(self, providers: list[VisionProvider] | None = None,
                 cache_seconds: float = 60.0):
        self._providers = [p for p in (providers or []) if p.available()]
        self._budget = _Budget()
        self._cache: dict[str, tuple[float, StateVerdict]] = {}
        self._cache_seconds = cache_seconds
        self.last_latency = 0.0

    @property
    def enabled(self) -> bool:
        return bool(self._providers) and not self._budget.disabled

    @property
    def provider_names(self) -> list[str]:
        return [p.name for p in self._providers]

    def classify_state(self, frame: np.ndarray) -> StateVerdict | None:
        """Ask what is on screen. Returns None whenever it cannot answer, and the
        caller must treat that as 'no new information', never as an error."""
        if frame is None or not self.enabled:
            return None

        key = dhash(frame)
        now = time.time()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self._cache_seconds:
            verdict = cached[1]
            logger.debug("Oracle cache hit: %s/%s", verdict.view, verdict.overlay)
            return StateVerdict(verdict.view, verdict.overlay, verdict.covers_hud,
                                verdict.confidence, "cache", verdict.raw)

        allowed, why = self._budget.allows(now)
        if not allowed:
            logger.debug("Oracle skipped: %s", why)
            return None

        jpeg = encode_frame(frame)
        if not jpeg:
            return None

        self._budget.record_call(now)
        for provider in self._providers:
            started = time.time()
            try:
                text = provider.ask(jpeg, STATE_PROMPT, STATE_SCHEMA)
            except Exception as e:
                logger.warning("Oracle provider %s failed: %s", provider.name,
                               str(e)[:160])
                continue
            self.last_latency = time.time() - started
            verdict = parse_state(text or "", provider.name)
            if verdict:
                self._budget.record_success()
                self._cache[key] = (now, verdict)
                logger.info("Oracle[%s] %.1fs -> view=%s overlay=%s covers_hud=%s",
                            provider.name, self.last_latency, verdict.view,
                            verdict.overlay, verdict.covers_hud)
                return verdict
            logger.info("Oracle provider %s returned an unparseable reply: %r",
                        provider.name, (text or "")[:120])

        self._budget.record_error()
        return None

    def locate_dismiss(self, frame: np.ndarray) -> tuple[int, int] | None:
        """Frame pixel coordinates of a panel's close button, or None.

        Never cached: the answer is only valid for the popup currently on
        screen. Callers must still run it through the guardrails in dismiss.py
        -- accuracy was good in testing, but "good" is not "safe to click on
        trust".
        """
        if frame is None or not self.enabled:
            return None
        provider = next((p for p in self._providers if p.supports_grounding), None)
        if provider is None:
            logger.info("No grounding-capable provider configured")
            return None

        now = time.time()
        allowed, why = self._budget.allows(now)
        if not allowed:
            logger.debug("Grounding skipped: %s", why)
            return None
        jpeg = encode_frame(frame)
        if not jpeg:
            return None

        self._budget.record_call(now)
        try:
            reply = provider.ask_grounding(jpeg, DISMISS_PROMPT, DISMISS_SCHEMA)
        except Exception as e:
            logger.warning("Grounding call failed: %s", str(e)[:160])
            self._budget.record_error()
            return None

        m = re.search(r'\{[^{}]*"x"\s*:.*?\}', reply or "", re.S)
        if not m:
            logger.info("Grounding reply had no JSON: %r", (reply or "")[:120])
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None
        if not data.get("found"):
            logger.info("Grounding: no close button reported")
            return None

        h, w = frame.shape[:2]
        try:
            x = int(float(data["x"]) / 1000.0 * w)
            y = int(float(data["y"]) / 1000.0 * h)
        except (KeyError, TypeError, ValueError):
            return None
        self._budget.record_success()
        logger.info("Grounding: close button at (%d,%d) of %dx%d", x, y, w, h)
        return x, y


def build_oracle(provider_name: str | None = None,
                 models: list[str] | None = None) -> VisionOracle:
    """Assemble the oracle from whatever is usable on this machine.

    Default order is API first, browser second: an API key answers in ~3s while
    the browser path takes ~27s, so the free provider is the fallback, not the
    front door. `available()` filters out whatever is not configured.
    """
    candidates: list[VisionProvider] = []
    if provider_name == "mock":
        candidates.append(MockProvider())
    else:
        if provider_name in (None, "openrouter"):
            candidates.append(OpenRouterProvider(models=models))
        if provider_name in (None, "ai_mode_web"):
            candidates.append(AiModeWebProvider())
    oracle = VisionOracle(candidates)
    if oracle.provider_names:
        logger.info("Vision oracle providers: %s", oracle.provider_names)
    else:
        logger.info("Vision oracle: no provider available (no key) -- layer 2 off")
    return oracle
