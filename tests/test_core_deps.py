from pathlib import Path

import numpy as np


def test_protocol_pack_and_parse_ack():
    from serial_comm.protocol import Protocol

    protocol = Protocol()
    cmd_id, data = protocol.pack("CLICK", "L", 120)

    assert data == f"<{cmd_id},CLICK,L,120>\n".encode("ascii")

    response = protocol.parse_response(f"<{cmd_id},ACK>\n".encode("ascii"))
    assert response is not None
    assert response.cmd_id == cmd_id
    assert response.status == "ACK"


def test_required_templates_load():
    from vision.template_cache import TemplateCache

    cache = TemplateCache("templates")
    required = [
        "resources/gem_icon",
        "resources/gem_mine_close",
        "buttons/gather_btn",
        "buttons/new_troop_btn",
        "buttons/march_btn_orange",
        "buttons/march_btn",
        "buttons/city_btn",
        "buttons/world_map_city_btn",
        "ui/btn_confirm_reconnect",
    ]

    missing = [name for name in required if cache.get(name) is None]
    assert missing == []


def test_gem_classifier_model_loads():
    from vision.gem_classifier import GemPatchClassifier

    model_path = Path("data/gem_classifier.npz")
    assert model_path.exists()

    classifier = GemPatchClassifier()
    assert classifier.load(str(model_path))
    assert classifier.sample_count > 0

    patch = np.zeros((48, 48, 3), dtype=np.uint8)
    should_click, label, confidence = classifier.should_click(patch)

    assert isinstance(should_click, bool)
    assert label in {"gem", "not_gem", "unknown"}
    assert 0.0 <= confidence <= 1.0


def test_gem_runner_imports():
    import run_farm

    assert hasattr(run_farm, "GemFarmRunner")


def test_runner_satisfies_player_action_ctx():
    """PlayerActions drives the runner through the ctx protocol, so a mixin that
    goes missing during a refactor has to fail here, not mid-farm."""
    from anti_detection.player_actions import PlayerActionCtx
    from rok_farm.runner import GemFarmRunner

    # `cmd`/`win` are instance attributes assigned during setup, not class ones.
    instance_attrs = {"cmd", "win"}
    internals = {"_is_protocol", "_is_runtime_protocol", "_abc_impl"}
    required = [name for name in dir(PlayerActionCtx)
                if not name.startswith("__")
                and name not in instance_attrs | internals]

    missing = [name for name in required if not hasattr(GemFarmRunner, name)]
    assert missing == []
