"""A drag/tile pair is only worth fitting if drags alone moved the camera.

The first fit, 2026-09-23 on eight pairs: median error 21 tiles on moves of
47, leave-one-out up to 113. The pairs disagreed because the pixel total was
reset only on a coordinate read, while other things moved the camera without
adding a pixel -- and the very first pair started at 448,621, the city itself,
so it spanned a city-to-map toggle with no drag in it at all.
"""

import inspect

from rok_farm.flow_steps import GemFlowMixin


def test_every_non_drag_camera_move_dirties_the_pair():
    for name in ("_retreat_from_edge", "_recenter_edge_gem",
                 "_recenter_to_safe_zone", "_step_return_city"):
        src = inspect.getsource(getattr(GemFlowMixin, name))
        assert "_pan_dirty = True" in src, (
            f"{name} moves the camera without adding to the pixel total, and "
            f"does not say so -- the next pair would teach the fit a lie")


def test_a_node_click_dirties_the_pair():
    """Clicking a deposit centres the camera on it."""
    import rok_farm.flow_steps as fs
    src = inspect.getsource(fs)
    i = src.find("Clicking a node centres the camera on it")
    assert i != -1
    assert "_pan_dirty = True" in src[max(0, i - 200):i], (
        "the node click centres the camera and is not marked")


def test_a_dirty_pair_is_logged_without_pixels():
    """The calibration tool keys on 'after ... px'; a dirty pair must not
    carry that, or it slips straight into the fit."""
    src = inspect.getsource(GemFlowMixin._map_sync)
    i = src.find("_pan_dirty")
    assert i != -1, "the read no longer checks whether the pair is clean"
    assert "not a calibration pair" in src


def test_the_tool_ignores_the_pairs_collected_before_the_fix():
    from pathlib import Path
    from rok_farm import PROJECT_ROOT
    src = (PROJECT_ROOT / "tools" / "dev" / "pan_calibration.py").read_text(
        encoding="utf-8")
    assert "SINCE" in src, "the contaminated pairs are still eligible"
