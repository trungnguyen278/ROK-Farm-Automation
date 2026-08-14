"""Getting unstuck: ESC back-out and the network reconnect popup.

Recovery never clicks blind -- a stray click on the world map can march troops.
ESC is pressed only while a panel is actually open (checked before each press,
because ESC on a clean view opens the profile panel).
"""

from __future__ import annotations

import random
import time

from rok_farm.config import WORLD_MAP_BTN_THRESHOLD
from rok_farm.logging_setup import INFO, WARN, logger


class RecoveryMixin:
    """Stuck-state recovery. Mixed into GemFarmRunner."""

    def _on_clean_view(self) -> bool:
        """True if on a clean city/world view with no panel open.

        An open panel covers the bottom-right toggle button, so seeing that
        button (city_btn on the world map, world_map_city_btn in the city) means
        we have fully backed out -- and another ESC here would open the profile.
        City resource icons are a fallback signal for the city view.
        """
        frame = self._grab()
        if frame is None:
            return False
        if self._find_city_btn(frame, threshold=0.70):
            return True
        if self._find_on_frame(frame, "buttons/world_map_city_btn",
                               threshold=WORLD_MAP_BTN_THRESHOLD):
            return True
        if (self._find_on_frame(frame, "ui/city_food", threshold=0.72)
                or self._find_on_frame(frame, "ui/city_wood", threshold=0.72)):
            return True
        return False

    def _check_reconnect_popup(self) -> bool:
        """Check and dismiss network disconnect popup. Call when flow seems stuck."""
        frame = self.sc.grab_full()
        if frame is None:
            return False
        m = self.matcher.match_single(frame, "ui/btn_confirm_reconnect")
        if m and m.confidence >= 0.75:
            roll = random.random()
            if roll < 0.30:
                time.sleep(random.uniform(1.0, 5.0))
            elif roll < 0.60:
                delay = random.uniform(30, 120)
                logger.info("Reconnect: delayed %.0fs (brief AFK)", delay)
                time.sleep(delay)
            elif roll < 0.80:
                delay = random.uniform(300, 900)
                logger.info("Reconnect: long delay %.0fs (extended AFK)", delay)
                time.sleep(delay)
                frame = self.sc.grab_full()
                m = self.matcher.match_single(frame, "ui/btn_confirm_reconnect") if frame is not None else None
                if not m or m.confidence < 0.75:
                    return False
            else:
                delay = random.uniform(900, 1800)
                logger.info("Reconnect: very long delay %.0fs (simulating player left)", delay)
                time.sleep(delay)
                frame = self.sc.grab_full()
                m = self.matcher.match_single(frame, "ui/btn_confirm_reconnect") if frame is not None else None
                if not m or m.confidence < 0.75:
                    return False
            print(f"  [{WARN}] Network disconnect popup (conf={m.confidence:.3f}), clicking confirm...")
            # Honour the result: the button registry can refuse a match that
            # landed far from where this button has ever been, and reporting a
            # dismissal that never happened would send the caller on blind.
            if not self._click_match(m):
                print(f"  [{WARN}] Confirm click was refused -- popup left alone")
                return False
            time.sleep(random.uniform(3.0, 8.0))
            return True
        return False

    def _attempt_recovery(self):
        """Recover from repeated failures by backing out with the ESC key ONLY.

        Never click randomly or in sequence -- a stray click could march troops
        or open junk. ESC closes one panel per press; stop the moment we reach a
        clean city/world view, because pressing ESC with nothing open would open
        the profile panel. (We check 'clean' BEFORE each press, so we only ever
        press ESC while something is actually open; if a press accidentally opens
        the profile, the next press closes it and then we stop.)
        """
        print(f"  [{WARN}] Recovery: ESC back-out (no clicking)")
        for attempt in range(4):
            if self._on_clean_view():
                print(f"  [{INFO}] Recovery: clean view reached after {attempt} ESC press(es)")
                break
            # _on_clean_view answers from templates alone, so it also says "not
            # clean" when the view IS clean but the buttons simply did not match.
            # The dim ratio is a positive signal instead of an absent one: an
            # undimmed background means nothing is covering the game, and ESC
            # there would open the profile panel.
            state = self._resolve_state(reason="ESC back-out")
            if not state.blocked and state.view in ("city", "world_map"):
                print(f"  [{INFO}] Recovery: nothing is covering the game "
                      f"({state.note}) -- not pressing ESC")
                break
            self.cmd.send("KEY", "ESC", random.randint(40, 90))
            self._wait(random.uniform(0.6, 1.2))
        # A network disconnect popup needs its confirm button, not ESC -- handle
        # it with a targeted (not random) click.
        if self._check_reconnect_popup():
            print(f"  [{WARN}] Recovery: dismissed reconnect popup")
            time.sleep(random.uniform(3.0, 6.0))
            return

        # Still covered after all that: a popup ESC does not close and no
        # template knows. This is the one case worth locating a close button
        # for -- see rok_farm/dismiss.py for the guardrails it goes through.
        if self._probe_state().blocked and self._dismiss_modal():
            print(f"  [{INFO}] Recovery: closed an unknown popup")
            time.sleep(random.uniform(1.0, 3.0))
