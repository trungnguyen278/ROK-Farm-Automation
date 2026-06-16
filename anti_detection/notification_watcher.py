"""Read Windows toast notifications via UserNotificationListener.

Used by the gem farm flow to detect the ROK "quan cua ban da tro ve thanh pho"
(your troops returned to the city) toast while the bot is alt-tabbed away --
without screen capture or OCR. Matching is on the toast BODY text, so it is
independent of the character name (which the player can change anytime).

Why notifications instead of screen capture:
  - The toast is a Windows OS overlay outside the game window; the game-window
    capture backend (WGC/MSS bound to the ROK window) never sees it.
  - The toast only fires when ROK is NOT the foreground window, which is exactly
    the alt-tabbed-away state we wait in.

Standalone test:
    .venv\\Scripts\\python -m anti_detection.notification_watcher
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata

logger = logging.getLogger(__name__)

try:
    from winsdk.windows.ui.notifications.management import (
        UserNotificationListener,
        UserNotificationListenerAccessStatus,
    )
    from winsdk.windows.ui.notifications import NotificationKinds

    _WINSDK_OK = True
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover - platform dependent
    _WINSDK_OK = False
    _IMPORT_ERR = e


# Constant phrase in the "troops returned to city" toast. The character-name
# prefix ("<name> than men, ") varies, this tail does not.
RETURN_KEYWORDS = ("tro ve thanh pho", "trở về thành phố")
# Optional app-name hint (case-insensitive substring), used only for logging.
ROK_APP_HINTS = ("kingdom",)


def _norm(s: str) -> str:
    # NFC so composed/decomposed Vietnamese diacritics compare equal, regardless
    # of how Windows hands us the toast text vs. our source literals.
    return unicodedata.normalize("NFC", (s or "")).lower()


class NotificationWatcher:
    """Polls the Windows notification store for the ROK troops-returned toast."""

    def __init__(self, keywords=RETURN_KEYWORDS, app_hints=ROK_APP_HINTS):
        self._keywords = tuple(_norm(k) for k in keywords)
        self._app_hints = tuple(_norm(a) for a in app_hints)
        self._listener = None
        self._available = False
        self._baseline_ids: set[int] = set()

    @property
    def available(self) -> bool:
        return self._available

    # -- lifecycle -----------------------------------------------------------

    def setup(self) -> bool:
        """Request notification access. Returns True if usable."""
        if not _WINSDK_OK:
            logger.warning("winsdk unavailable, notification watch disabled: %s",
                           _IMPORT_ERR)
            return False
        try:
            self._listener = UserNotificationListener.current

            async def _req():
                return await self._listener.request_access_async()

            status = asyncio.run(_req())
            if status != UserNotificationListenerAccessStatus.ALLOWED:
                logger.warning(
                    "Notification access not ALLOWED (status=%s). Enable via "
                    "Settings > Privacy & security > Notifications.", status)
                return False
            self._available = True
            logger.info("NotificationWatcher ready (access allowed)")
            return True
        except Exception as e:
            logger.warning("NotificationWatcher setup failed: %s", e)
            return False

    # -- reading -------------------------------------------------------------

    def _read_all(self) -> list[tuple[int, str, str]]:
        """Return [(id, app_name, body_text), ...] for current toasts."""
        async def _go():
            notifs = await self._listener.get_notifications_async(
                NotificationKinds.TOAST)
            out = []
            for n in notifs:
                try:
                    app = n.app_info.display_info.display_name
                except Exception:
                    app = ""
                lines = []
                try:
                    for binding in n.notification.visual.bindings:
                        for t in binding.get_text_elements():
                            if t.text:
                                lines.append(t.text)
                except Exception:
                    pass
                out.append((n.id, app or "", " ".join(lines)))
            return out

        try:
            return asyncio.run(_go())
        except Exception as e:
            logger.debug("read notifications failed: %s", e)
            return []

    def _is_return(self, body: str) -> bool:
        b = _norm(body)
        return any(k in b for k in self._keywords)

    # -- public API ----------------------------------------------------------

    def snapshot_baseline(self) -> None:
        """Record current toast ids so only NEW ones count as returns.

        Call right before alt-tabbing away.
        """
        if not self._available:
            return
        self._baseline_ids = {nid for nid, _, _ in self._read_all()}
        logger.debug("notif baseline: %d existing toast(s)", len(self._baseline_ids))

    def check_returned(self, remove: bool = True) -> int:
        """Count NEW troops-returned toasts since the last baseline snapshot.

        Matched toasts are added to the baseline (so they are counted once) and,
        if `remove`, dismissed from the notification store to keep it clean.
        Returns the number of new returns detected this call.
        """
        if not self._available:
            return 0
        count = 0
        for nid, app, body in self._read_all():
            if nid in self._baseline_ids:
                continue
            if self._is_return(body):
                count += 1
                self._baseline_ids.add(nid)
                logger.info("troops-returned toast id=%s app='%s' body='%s'",
                            nid, app, body[:80])
                if remove:
                    try:
                        self._listener.remove_notification(nid)
                    except Exception as e:
                        logger.debug("remove_notification(%s) failed: %s", nid, e)
        return count


def _selftest():
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    w = NotificationWatcher()
    ok = w.setup()
    print(f"setup: {ok}")
    if not ok:
        return
    rows = w._read_all()
    print(f"current toasts: {len(rows)}")
    rok = [r for r in rows if any(h in _norm(r[1]) for h in w._app_hints)]
    print(f"ROK-app toasts: {len(rok)}")
    for nid, app, body in rok:
        print(f"  id={nid} app='{app}' return={w._is_return(body)}")
        print(f"     body: {body}")
    w.snapshot_baseline()
    print(f"baseline ids: {len(w._baseline_ids)}")
    print(f"check_returned (no remove): {w.check_returned(remove=False)}")


if __name__ == "__main__":
    _selftest()
