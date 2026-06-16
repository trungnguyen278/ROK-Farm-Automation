r"""Quick test: read Windows toast notifications via UserNotificationListener.

Verifies winsdk can request access and read ROK "troops returned" toasts.

Run: .venv\Scripts\python -m tools.test_notification_listener
"""

import asyncio
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from winsdk.windows.ui.notifications.management import (
    UserNotificationListener,
    UserNotificationListenerAccessStatus,
)
from winsdk.windows.ui.notifications import NotificationKinds


async def main():
    listener = UserNotificationListener.current

    status = await listener.request_access_async()
    print(f"Access status: {status}")
    if status != UserNotificationListenerAccessStatus.ALLOWED:
        print("  -> NOT allowed. Enable: Settings > Privacy & security > "
              "Notifications > 'Let apps access notifications' (and allow Python).")
        return

    notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
    print(f"Current toast notifications: {len(notifs)}")

    for i, n in enumerate(notifs):
        try:
            app = n.app_info.display_info.display_name
        except Exception:
            app = "?"
        lines = []
        try:
            visual = n.notification.visual
            for binding in visual.bindings:
                for t in binding.get_text_elements():
                    lines.append(t.text)
        except Exception as e:
            lines = [f"<text read error: {e}>"]
        body = " | ".join(lines)
        print(f"  [{i}] id={n.id} app='{app}'")
        print(f"      text: {body}")


if __name__ == "__main__":
    asyncio.run(main())
