"""Layer 0: a fixed button that matches far from its own history is refused.

No game and no network needed -- the registry is fed synthetic detections.
"""

import pytest

from rok_farm import config as cfg
from rok_farm.button_registry import ButtonRegistry

GATHER = "buttons/gather_btn"
GEM = "resources/gem_icon"
WIN = {"left": 100, "top": 50, "width": 1000, "height": 800}


@pytest.fixture
def registry(tmp_path):
    return ButtonRegistry(path=tmp_path / "registry.json")


def feed(reg, template, pct, times):
    for _ in range(times):
        reg.record(template, pct)


def test_empty_registry_never_blocks(registry):
    """A first run has no history, so nothing may be refused."""
    ok, why = registry.check(GATHER, (0.9, 0.1))
    assert ok, why


def test_warmup_records_without_rejecting(registry):
    feed(registry, GATHER, (0.50, 0.60), cfg.REGISTRY_WARMUP - 1)
    ok, why = registry.check(GATHER, (0.05, 0.95))
    assert ok, "still warming up, must not reject"
    assert "warmup" in why


def test_rejects_an_outlier_after_warmup(registry):
    feed(registry, GATHER, (0.50, 0.60), cfg.REGISTRY_WARMUP + 5)
    ok, _ = registry.check(GATHER, (0.50, 0.60))
    assert ok, "the button's own position must stay acceptable"

    ok, why = registry.check(GATHER, (0.05, 0.95))
    assert not ok, "a match on the far side of the window must be refused"
    assert "from mean" in why


def test_small_drift_is_accepted(registry):
    """Real detections jitter by a few pixels; that must not be refused."""
    for i in range(cfg.REGISTRY_WARMUP + 5):
        registry.record(GATHER, (0.50 + 0.002 * (i % 3), 0.60 - 0.002 * (i % 2)))
    ok, why = registry.check(GATHER, (0.515, 0.585))
    assert ok, why


def test_moving_templates_are_not_policed(registry):
    """Gem icons move with the world -- they must never be gated."""
    feed(registry, GEM, (0.5, 0.5), cfg.REGISTRY_WARMUP + 5)
    ok, why = registry.check(GEM, (0.02, 0.98))
    assert ok
    assert why == "not policed"
    assert registry.stats(GEM) is None, "moving templates must not be recorded"


def test_radius_has_a_floor(registry):
    """A button seen at the exact same spot every time still needs slack."""
    feed(registry, GATHER, (0.50, 0.60), cfg.REGISTRY_WARMUP + 5)
    assert registry.radius(GATHER) == pytest.approx(cfg.REGISTRY_MIN_RADIUS)
    ok, _ = registry.check(GATHER, (0.50 + cfg.REGISTRY_MIN_RADIUS / 2, 0.60))
    assert ok


def test_survives_a_round_trip_to_disk(registry, tmp_path):
    feed(registry, GATHER, (0.50, 0.60), cfg.REGISTRY_WARMUP + 5)
    registry.save()

    reloaded = ButtonRegistry(path=tmp_path / "registry.json")
    assert reloaded.stats(GATHER)["n"] == cfg.REGISTRY_WARMUP + 5
    ok, _ = reloaded.check(GATHER, (0.05, 0.95))
    assert not ok, "history must still gate after a reload"


def test_window_pct_conversion():
    pct = ButtonRegistry.to_window_pct(600, 450, WIN)
    assert pct == pytest.approx((0.5, 0.5))
    assert ButtonRegistry.to_window_pct(600, 450, None) is None
