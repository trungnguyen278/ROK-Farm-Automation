r"""Ask Google Search AI Mode about an image, from the command line.

This is the working recipe behind the `ai_mode_web` provider, kept as a probe so
the mechanics can be re-checked whenever Google changes the page.

    .venv\Scripts\python tools\dev\probe_ai_mode.py shot.png "what is this?"
    .venv\Scripts\python tools\dev\probe_ai_mode.py shot.png --state
    .venv\Scripts\python tools\dev\probe_ai_mode.py shot.png --state --headless

Measured 2026-08-14: no login, no CAPTCHA, ~6-10 s round trip, and it follows a
"reply with one line of JSON" instruction reliably.

Three mechanics matter and are easy to get wrong:
  * land on the AI Mode URL with NO `q=` -- any query jumps past the landing page
    into the follow-up chat UI, where the compose box behaves differently;
  * attach by dispatching a synthetic ClipboardEvent carrying a File, which fires
    the same handler as Ctrl+V without touching the OS clipboard;
  * the page echoes the prompt back, so the reply must be read from AFTER the
    echo or a regex matches our own question.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

AI_MODE_URL = "https://www.google.com/search?udm=50"
PROFILE_DIR = PROJECT_ROOT / "data" / "ai_mode_profile"

STATE_QUESTION = (
    "Day la anh chup man hinh game Rise of Kingdoms tren PC. "
    "Tra loi DUNG 1 dong JSON, khong giai thich, khong markdown: "
    '{"view":"city|world_map|loading|unknown",'
    '"overlay":"none|modal|event_popup|reward|chat",'
    '"covers_hud":true|false}'
)

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


def ask(image: Path, question: str, headless: bool = False,
        timeout_s: float = 120.0) -> str:
    from playwright.sync_api import sync_playwright

    data_url = "data:image/png;base64," + base64.b64encode(
        image.read_bytes()).decode()
    # The page repeats the prompt; anchor on its tail to find where the reply
    # starts. Use a chunk long enough to be unique on the page.
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
            page.wait_for_timeout(300)
            if page.evaluate(PASTE_JS, ["textarea", data_url]) != "dispatched":
                return ""
            page.wait_for_timeout(3500)

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
                    if stable >= 3:      # unchanged ~6s -> generation finished
                        break
                else:
                    stable = 0
                last = cur
            return last
        finally:
            ctx.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("image")
    parser.add_argument("question", nargs="?", default=None)
    parser.add_argument("--state", action="store_true",
                        help="use the standard screen-state question")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()

    image = Path(args.image)
    if not image.exists():
        sys.exit(f"no such image: {image}")
    question = STATE_QUESTION if args.state else args.question
    if not question:
        sys.exit("give a question, or pass --state")

    t0 = time.time()
    reply = ask(image, question, headless=args.headless, timeout_s=args.timeout)
    print(f"round trip: {time.time() - t0:.1f}s\n")
    print(reply[:2000] or "(empty reply)")

    m = re.search(r'\{[^{}]*"view"\s*:\s*"[a-z_]+"[^{}]*\}', reply)
    if m:
        try:
            print(f"\nparsed: {json.loads(m.group(0))}")
        except Exception as e:
            print(f"\nJSON found but not parseable: {e}")


if __name__ == "__main__":
    main()
