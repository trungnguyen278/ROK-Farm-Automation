"""Layer 2 wiring, exercised with a mock provider -- no key, no network.

The properties that matter here are the defensive ones: the oracle must never
raise into the farm loop, must respect its own budget, and must survive a
provider that ignores the JSON schema and answers in prose.
"""

import numpy as np

from rok_farm.vision_llm import (MockProvider, OpenRouterProvider, StateVerdict,
                                 VisionOracle, dhash, encode_frame, parse_state)


def frame(w=1533, h=862, seed=0):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


# --- parsing -----------------------------------------------------------------

def test_parses_clean_json():
    v = parse_state('{"view":"city","overlay":"modal","covers_hud":false,'
                    '"confidence":0.9}', "mock")
    assert (v.view, v.overlay, v.covers_hud) == ("city", "modal", False)
    assert v.blocked is True


def test_parses_json_buried_in_prose():
    """OpenRouter documents that strict schema mode is not honoured everywhere."""
    reply = ('Sure! Here is the answer:\n```json\n'
             '{"view":"world_map","overlay":"none","covers_hud":false,'
             '"confidence":0.7}\n```\nHope this helps.')
    v = parse_state(reply, "mock")
    assert v.view == "world_map"
    assert v.blocked is False


def test_unknown_labels_are_clamped():
    v = parse_state('{"view":"inventory","overlay":"banner","covers_hud":true}',
                    "mock")
    assert v.view == "unknown"
    assert v.overlay == "none"


def test_truncated_reply_is_salvaged():
    """Observed live: a model answered correctly, then ran a number away until
    max_tokens cut the JSON off mid-field."""
    reply = ('{"view":"world_map","overlay":"none","covers_hud":false,'
             '"confidence":0.9590909090909091e+237242972356543856')
    v = parse_state(reply, "openrouter")
    assert v is not None
    assert (v.view, v.overlay, v.covers_hud) == ("world_map", "none", False)


def test_truncated_reply_without_a_view_is_still_rejected():
    assert parse_state('{"overlay":"modal","covers_hud":tr', "mock") is None


def test_garbage_returns_none():
    assert parse_state("no json here at all", "mock") is None
    assert parse_state("", "mock") is None


# --- frame preparation -------------------------------------------------------

def test_encode_downscales_and_shrinks():
    jpeg = encode_frame(frame())
    assert jpeg[:2] == b"\xff\xd8"          # JPEG magic
    assert len(jpeg) < 1533 * 862 * 3       # far smaller than the raw frame


def test_dhash_is_stable_and_discriminating():
    a = frame(seed=1)
    assert dhash(a) == dhash(a.copy())
    assert dhash(a) != dhash(frame(seed=2))


# --- oracle ------------------------------------------------------------------

def test_no_provider_means_disabled():
    oracle = VisionOracle([])
    assert oracle.enabled is False
    assert oracle.classify_state(frame()) is None


def test_happy_path():
    oracle = VisionOracle([MockProvider()])
    v = oracle.classify_state(frame())
    assert isinstance(v, StateVerdict)
    assert v.view == "city" and v.source == "mock"


def test_identical_frame_is_served_from_cache():
    mock = MockProvider()
    oracle = VisionOracle([mock], cache_seconds=60)
    f = frame()
    oracle.classify_state(f)
    second = oracle.classify_state(f)
    assert mock.calls == 1, "a repeat of the same screen must not spend a call"
    assert second.source == "cache"


def test_min_gap_blocks_a_second_different_frame():
    mock = MockProvider()
    oracle = VisionOracle([mock])
    assert oracle.classify_state(frame(seed=1)) is not None
    assert oracle.classify_state(frame(seed=2)) is None, "min gap must hold"
    assert mock.calls == 1


def test_hourly_cap_is_enforced():
    mock = MockProvider()
    oracle = VisionOracle([mock])
    oracle._budget.min_gap_s = 0
    oracle._budget.max_per_hour = 3
    for i in range(5):
        oracle.classify_state(frame(seed=i))
    assert mock.calls == 3


def test_provider_failure_never_raises():
    oracle = VisionOracle([MockProvider(fail=True)])
    oracle._budget.min_gap_s = 0
    assert oracle.classify_state(frame()) is None


def test_disables_itself_after_repeated_failures():
    oracle = VisionOracle([MockProvider(fail=True)])
    oracle._budget.min_gap_s = 0
    for i in range(3):
        oracle.classify_state(frame(seed=i))
    assert oracle.enabled is False
    assert oracle.classify_state(frame(seed=99)) is None


def test_falls_through_to_a_working_provider():
    broken, working = MockProvider(fail=True), MockProvider()
    oracle = VisionOracle([broken, working])
    v = oracle.classify_state(frame())
    assert v is not None and broken.calls == 1 and working.calls == 1


def test_unparseable_reply_counts_as_an_error():
    mock = MockProvider(reply="I cannot help with that.")
    oracle = VisionOracle([mock])
    assert oracle.classify_state(frame()) is None


# --- openrouter provider -----------------------------------------------------

def test_openrouter_without_a_key_is_unavailable(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr("rok_farm.vision_llm.load_secret", lambda *a: None)
    assert OpenRouterProvider().available() is False


def test_openrouter_with_a_key_is_available():
    assert OpenRouterProvider(api_key="sk-test").available() is True


def test_openrouter_builds_a_valid_request(monkeypatch):
    """No network: capture what would have been sent and check its shape."""
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = __import__("json").loads(req.data.decode())

        class R:
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
            def read(self):
                return b""
        import io
        payload = ('{"choices":[{"message":{"content":'
                   '"{\\"view\\":\\"city\\",\\"overlay\\":\\"none\\",'
                   '\\"covers_hud\\":false,\\"confidence\\":0.8}"}}]}')
        return io.BytesIO(payload.encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    provider = OpenRouterProvider(api_key="sk-test", models=["some/model"])
    reply = provider.ask(b"\xff\xd8fake", "prompt", {"name": "s", "schema": {}})

    assert "openrouter.ai" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    content = captured["body"]["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert captured["body"]["response_format"]["type"] == "json_schema"
    assert parse_state(reply, "openrouter").view == "city"


def test_openrouter_tries_the_next_model_on_failure(monkeypatch):
    tried = []

    def fake_post(self, model, data_url, prompt, schema):
        tried.append(model)
        if len(tried) == 1:
            raise RuntimeError("model unavailable")
        return '{"view":"city","overlay":"none","covers_hud":false,"confidence":1}'

    monkeypatch.setattr(OpenRouterProvider, "_post", fake_post)
    provider = OpenRouterProvider(api_key="sk-test",
                                  models=["first/model", "second/model"])
    reply = provider.ask(b"\xff\xd8fake", "prompt")
    assert tried == ["first/model", "second/model"]
    assert parse_state(reply, "openrouter") is not None
