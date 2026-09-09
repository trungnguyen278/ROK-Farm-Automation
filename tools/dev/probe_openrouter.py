r"""Check an OpenRouter key against a real screenshot, end to end.

Run this the moment a key exists -- it exercises exactly the path the runner
uses, so a pass here means layer 2 is ready.

    set OPENROUTER_API_KEY=sk-or-...
    .venv\Scripts\python tools\dev\probe_openrouter.py screenshots\shot.png
    .venv\Scripts\python tools\dev\probe_openrouter.py shot.png --model qwen/qwen3.7-flash
    .venv\Scripts\python tools\dev\probe_openrouter.py --live      (grab the game now)

The key is read from OPENROUTER_API_KEY or profiles/secrets.json:

    {"openrouter": "sk-or-..."}

profiles/*.json is gitignored (except default.json), so the key stays out of git.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import cv2

from rok_farm.config import OPENROUTER_MODELS
from rok_farm.vision_llm import (STATE_PROMPT, STATE_SCHEMA, OpenRouterProvider,
                                 VisionOracle, encode_frame, load_secret,
                                 parse_state)


def grab_live():
    from capture.screen_capture import ScreenCapture
    sc = ScreenCapture()
    if not sc.find_window():
        sys.exit("game window not found")
    frame = sc.grab_full()
    sc.close()
    if frame is None:
        sys.exit("capture returned no frame")
    return frame


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image", nargs="?", help="path to a screenshot")
    parser.add_argument("--live", action="store_true",
                        help="grab the current game frame instead")
    parser.add_argument("--model", action="append",
                        help="model id to try (repeatable); default is the config list")
    args = parser.parse_args()

    key = load_secret("OPENROUTER_API_KEY")
    if not key:
        print("No key found.")
        print("  set OPENROUTER_API_KEY=sk-or-...")
        print("  or put {\"openrouter\": \"sk-or-...\"} in profiles/secrets.json")
        sys.exit(1)
    print(f"key: {key[:8]}...{key[-4:]} ({len(key)} chars)")

    if args.live:
        frame = grab_live()
    elif args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            sys.exit(f"cannot read {args.image}")
    else:
        sys.exit("give an image path, or pass --live")
    print(f"frame: {frame.shape[1]}x{frame.shape[0]}")

    models = args.model or OPENROUTER_MODELS
    jpeg = encode_frame(frame)
    print(f"sent as: {len(jpeg) / 1024:.1f} KB JPEG\n")

    provider = OpenRouterProvider(api_key=key, models=models)
    oracle = VisionOracle([provider])

    for model in models:
        one = OpenRouterProvider(api_key=key, models=[model])
        t0 = time.time()
        try:
            reply = one.ask(jpeg, STATE_PROMPT, STATE_SCHEMA)
        except Exception as e:
            print(f"  [FAIL] {model:45s} {str(e)[:90]}")
            continue
        elapsed = time.time() - t0
        verdict = parse_state(reply or "", model)
        if verdict:
            print(f"  [ OK ] {model:45s} {elapsed:5.1f}s  "
                  f"view={verdict.view} overlay={verdict.overlay} "
                  f"covers_hud={verdict.covers_hud} conf={verdict.confidence}")
        else:
            print(f"  [WARN] {model:45s} {elapsed:5.1f}s  "
                  f"unparseable: {(reply or '')[:70]!r}")

    print("\nvia the oracle (budget + cache, as the runner uses it):")
    verdict = oracle.classify_state(frame)
    print(f"  {verdict}")


if __name__ == "__main__":
    main()
