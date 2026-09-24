"""Shared test fixtures."""

import sys

import pytest


@pytest.fixture(autouse=True)
def _bot_log_stays_out_of_the_real_one(tmp_path, monkeypatch):
    """Tests must not write the live Discord bot's log.

    Importing tools.remote.discord_bot points session_control's notes at the
    bot's log file, so every later test that calls do_start with fake
    processes wrote "Farm started (pid 1234)" into logs/overnight/
    discord_bot.log -- nine times on 2026-09-24 alone, between real lines.
    """
    bot = sys.modules.get("tools.remote.discord_bot")
    if bot is not None:
        monkeypatch.setattr(bot, "LOGDIR", tmp_path)
        monkeypatch.setattr(bot, "BOT_LOG", tmp_path / "discord_bot.log")
