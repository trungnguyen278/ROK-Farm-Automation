r"""Ask Google Search AI Mode a text question, from the command line.

The image probe (probe_ai_mode.py) without the image: same landing page,
same "read the reply after the echoed prompt" trick. Headless by default so
no browser window takes the foreground from a running farm.

    .venv\Scripts\python tools\dev\ask_ai_mode.py "question"
    .venv\Scripts\python tools\dev\ask_ai_mode.py "question" --headed
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.dev.probe_ai_mode import AI_MODE_URL, PROFILE_DIR  # noqa: E402


def ask(question: str, headless: bool = True, timeout_s: float = 150.0) -> str:
    from playwright.sync_api import sync_playwright

    anchor = question[-40:]
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR), channel="msedge", headless=headless,
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(AI_MODE_URL, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)
            page.locator("textarea").first.click()
            page.keyboard.type(question, delay=5)
            page.wait_for_timeout(400)
            page.keyboard.press("Enter")
            deadline = time.time() + timeout_s
            last, stable = "", 0
            while time.time() < deadline:
                page.wait_for_timeout(2000)
                body = page.inner_text("body")
                idx = body.rfind(anchor)
                cur = body[idx + len(anchor):].strip() if idx >= 0 else ""
                if cur and cur == last:
                    stable += 1
                    if stable >= 3:
                        break
                else:
                    stable = 0
                last = cur
            return last
        finally:
            ctx.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("question")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--timeout", type=float, default=150.0)
    args = ap.parse_args()
    t0 = time.time()
    reply = ask(args.question, headless=not args.headed, timeout_s=args.timeout)
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"round trip: {time.time() - t0:.1f}s\n")
    print(reply[:6000] or "(empty reply)")


if __name__ == "__main__":
    main()
