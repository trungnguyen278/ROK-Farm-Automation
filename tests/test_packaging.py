"""The packaged app's contracts: role dispatch, console input, first-run .env.

These lock down three things that were each broken once and whose breakage is
invisible until someone non-technical is already stuck:

  * roles.matches() -- the bot and watchdog find a running farm by scanning
    command lines. Get it wrong and !start launches a SECOND farm on top of a
    live one, two boards' worth of input into one client.
  * ui.ask() -- EOF used to come back as an empty string, so the menu looped
    forever at full speed; and a UTF-8 BOM (PowerShell prepends one to
    anything it pipes) made every menu choice miss.
  * the wizard's .env -- written by one module, read by another. If they
    disagree about the file, remote control silently never works.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ui
from rok_farm import roles


# ------------------------------------------------------------------- roles

def test_every_role_has_a_script():
    for role in roles.SCRIPTS:
        assert (roles.PROJECT_ROOT / roles.SCRIPTS[role]).is_file(), role


def test_command_from_source_runs_the_script():
    cmd = roles.command("farm")
    assert cmd[0].lower().endswith("python.exe")
    assert cmd[1].endswith("farm_full.py")


def test_command_passes_arguments_as_strings():
    assert roles.command("watchdog", 1234)[-1] == "1234"


def test_unknown_role_is_refused():
    with pytest.raises(KeyError):
        roles.command("definitely-not-a-role")


def test_matches_finds_its_own_role_from_source():
    assert roles.matches("farm", ["python.exe", r"c:\x\farm_full.py"])
    assert not roles.matches("watchdog", ["python.exe", r"c:\x\farm_full.py"])


def test_matches_ignores_an_empty_cmdline():
    assert not roles.matches("farm", None)
    assert not roles.matches("farm", [])


def test_matches_frozen_compares_the_role_word_exactly(monkeypatch):
    """Frozen, every role shares one exe name, so argv[1] is the whole signal.

    Substring matching here is what would let "report" match a --report flag,
    or "bot" match a path containing "bot".
    """
    monkeypatch.setattr(roles, "FROZEN", True)
    assert roles.matches("bot", [r"c:\app\ROK Farm.exe", "bot"])
    assert not roles.matches("bot", [r"c:\robot\ROK Farm.exe", "farm"])
    assert not roles.matches("report", [r"c:\app\ROK Farm.exe", "farm",
                                        "--report"])


# ---------------------------------------------------------------------- ui

def _stdin(monkeypatch, text):
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def test_ask_returns_the_typed_line(monkeypatch):
    _stdin(monkeypatch, "5\n")
    assert ui.ask("pick") == "5"


def test_ask_strips_a_utf8_bom(monkeypatch):
    """PowerShell prepends a BOM to anything it pipes into a child process."""
    _stdin(monkeypatch, "\ufeff5\n")
    assert ui.ask("pick") == "5"


def test_ask_strips_a_mojibake_bom(monkeypatch):
    """The same BOM, as an 8-bit stdin would have decoded it."""
    _stdin(monkeypatch, "\u00ef\u00bb\u00bf5\n")
    assert ui.ask("pick") == "5"


def test_ask_falls_back_to_the_default_on_an_empty_line(monkeypatch):
    _stdin(monkeypatch, "\n")
    assert ui.ask("pick", default="7") == "7"


def test_ask_raises_closed_on_eof(monkeypatch):
    """Not an empty string: the menu loops forever on one, and did."""
    _stdin(monkeypatch, "")
    with pytest.raises(ui.Closed):
        ui.ask("pick")


def test_pause_survives_a_missing_console(monkeypatch):
    _stdin(monkeypatch, "")
    ui.pause()          # must not raise


def test_confirm_accepts_vietnamese_yes(monkeypatch):
    _stdin(monkeypatch, "c\n")          # "có"
    assert ui.confirm("ok?") is True


def test_confirm_uses_the_default_on_enter(monkeypatch):
    _stdin(monkeypatch, "\n")
    assert ui.confirm("ok?", default=False) is False


def test_fold_makes_vietnamese_safe_for_a_cp1252_console():
    folded = ui.fold("Cài đặt lần đầu — mạch ESP32")
    assert folded.isascii()
    assert "Cai dat lan dau" in folded


# ------------------------------------------------------------------ wizard

def test_wizard_writes_an_env_the_bot_can_read(tmp_path, monkeypatch):
    from app import wizard
    monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
    _stdin(monkeypatch, "\n".join(["y", "FAKE.token", "12345", "67890"]) + "\n")

    assert wizard.setup_discord() is True
    env = tmp_path / ".env"
    assert env.is_file()

    from tools.remote.discord_bot import load_env
    for key in ("DISCORD_BOT_TOKEN", "DISCORD_OWNER_ID", "DISCORD_CHANNEL_ID"):
        monkeypatch.delenv(key, raising=False)
    load_env(env)
    assert os.environ["DISCORD_BOT_TOKEN"] == "FAKE.token"
    assert os.environ["DISCORD_OWNER_ID"] == "12345"
    assert os.environ["DISCORD_CHANNEL_ID"] == "67890"


def test_wizard_refuses_to_save_without_an_owner_id(tmp_path, monkeypatch):
    """An unset owner is the one field that must not be skipped: the bot
    refuses to start rather than expose an unlocked control surface."""
    from app import wizard
    monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
    _stdin(monkeypatch, "\n".join(["y", "FAKE.token", "", ""]) + "\n")

    assert wizard.setup_discord() is False
    assert not (tmp_path / ".env").exists()


def test_wizard_leaves_a_configured_env_alone(tmp_path, monkeypatch):
    from app import wizard
    monkeypatch.setattr(wizard, "PROJECT_ROOT", tmp_path)
    env = tmp_path / ".env"
    env.write_text("DISCORD_BOT_TOKEN=keep\nDISCORD_OWNER_ID=1\n",
                   encoding="utf-8")
    before = env.read_text(encoding="utf-8")

    _stdin(monkeypatch, "n\n")          # "re-enter it?" -> no
    assert wizard.setup_discord() is True
    assert env.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------- firmware

def test_shipped_firmware_manifest_matches_its_images():
    """firmware/ is committed and is what the app flashes; a manifest that
    disagrees with the bytes beside it would brick a board halfway."""
    import hashlib
    import json

    from tools.flash_board import FIRMWARE_DIR, MANIFEST

    if not MANIFEST.is_file():
        pytest.skip("firmware/ not built in this checkout")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["chip"] == "esp32s3"

    offsets = set()
    for part in manifest["parts"]:
        image = FIRMWARE_DIR / part["file"]
        assert image.is_file(), part["file"]
        data = image.read_bytes()
        assert len(data) == part["size"], part["file"]
        assert hashlib.sha256(data).hexdigest() == part["sha256"], part["file"]
        offsets.add(int(part["offset"], 16))

    # The bootloader, the partition table, the OTA selector and the app. A
    # missing boot_app0 (0xe000) leaves the bootloader pointing at a stale
    # slot on a board that was flashed before -- it went missing once.
    assert offsets == {0x0, 0x8000, 0xe000, 0x10000}
