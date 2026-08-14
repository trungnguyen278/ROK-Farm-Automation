r"""Gem farm runner -- entry point.

Flow per mine:
  1. From city view -> click world map button (bottom-right) -> zoom out 2x
  2. Random wander scan map for gem_icon (white diamond)
  3. Click gem icon -> game auto-zooms into mine area
  4. Click on actual gem mine structure to open gather popup
  5. Click "Thu Thap" (gather_btn)
  6. Select "New Troop" if troop panel appears, then click "March"
  7. Return to city view for next mine

Everything lives in the `rok_farm` package; this file only parses CLI args.

Run: .venv\Scripts\python run_farm.py --port COM27 --count 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from rok_farm import config as cfg
from rok_farm.find_only import run_find_only
from rok_farm.runner import GemFarmRunner


def main():
    parser = argparse.ArgumentParser(description="ROK gem farm runner")
    parser.add_argument("--port", default="COM27")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--find-only", action="store_true",
                        help="Vision-only scan: capture current frame, run template match + color filter, no ESP32")
    parser.add_argument("--auto-learn", action="store_true",
                        help="Enable auto-labeling for classifier (default: OFF)")
    parser.add_argument("--loop", action="store_true",
                        help="Loop until march queue is full (uses --max-marches as limit)")
    parser.add_argument("--max-marches", type=int, default=5,
                        help="Max march slots (default: 5)")
    parser.add_argument("--no-screenshots", action="store_true",
                        help="Disable saving screenshots (for overnight runs)")
    parser.add_argument("--zoom-scrolls", type=int, default=None,
                        help="Override ICON_ZOOM_SCROLLS (default: random 2-3)")
    parser.add_argument("--account-id", type=str, default="default",
                        help="Account identifier for persistent persona (default: 'default')")
    parser.add_argument("--actions", type=str, default=None,
                        help="Override distraction action pool (comma-separated, e.g. alt_tab,chat,mail)")
    parser.add_argument("--recalibrate", action="store_true",
                        help="Force re-measuring mouse MOVETO/scale (the startup cursor jerk); "
                             "otherwise the cached value from the persona is reused")
    parser.add_argument("--no-mail-alliance", action="store_true",
                        help="Disable the mail + alliance gift check in the city phase")
    parser.add_argument("--no-initial-alttab", action="store_true",
                        help="Skip the startup alt-tab into the game (on by default; "
                             "needed because the terminal is foreground when launched)")
    parser.add_argument("--launcher-path", type=str, default=None,
                        help="Path to launcher.exe; otherwise ROK_LAUNCHER_PATH, "
                             "profiles/paths.json, the Start Menu shortcut, then the registry")
    parser.add_argument("--no-auto-launch", action="store_true",
                        help="Never start the game; fail at setup if its window is missing")
    parser.add_argument("--no-restart", action="store_true",
                        help="Never quit/relaunch the game (a broken client falls back "
                             "to the old long break)")
    parser.add_argument("--no-oracle", action="store_true",
                        help="Never ask a vision model what is on screen "
                             "(it is off anyway when no API key is configured)")
    parser.add_argument("--oracle-provider", type=str, default=None,
                        choices=["openrouter", "ai_mode_web", "mock"],
                        help="Force one vision provider (default: whichever key exists)")
    parser.add_argument("--oracle-model", action="append", default=None,
                        help="Vision model id to try, repeatable; overrides the "
                             "default list in config.py")
    args = parser.parse_args()

    if args.no_screenshots:
        cfg.SAVE_SCREENSHOTS = False
    if args.zoom_scrolls is not None:
        cfg.ICON_ZOOM_SCROLLS = args.zoom_scrolls

    if args.find_only:
        run_find_only()
        return

    actions_list = args.actions.split(",") if args.actions else None
    runner = GemFarmRunner(
        port=args.port, count=args.count, auto_learn=args.auto_learn,
        loop=args.loop, max_marches=args.max_marches,
        account_id=args.account_id,
        actions_override=actions_list,
        recalibrate=args.recalibrate,
        skip_mail_alliance=args.no_mail_alliance,
        initial_alttab=not args.no_initial_alttab,
        auto_launch=not args.no_auto_launch,
        allow_restart=not args.no_restart,
        launcher_path=args.launcher_path,
        oracle_provider=args.oracle_provider,
        oracle_models=args.oracle_model,
        use_oracle=not args.no_oracle,
    )
    runner.run()


if __name__ == "__main__":
    main()
