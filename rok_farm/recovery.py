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

    # A reconnect dialog is not a state the client holds indefinitely. Measured
    # event of 2026-08-18: the popup was already on screen at 07:22:12 and the
    # client process was gone by 07:28:15, so it survived AT MOST 363s
    # unanswered -- and likely less, since it was up before the bot first looked.
    # The old hesitation rolled 300-900s a fifth of the time and 900-1800s
    # another fifth, so two rolls in five could outlive the dialog. One did: the
    # client died mid-sleep, the bot slept on for another eleven minutes, and
    # the farm produced nothing for over an hour.
    #
    # The pre-confirm hesitation now stays inside the only survival bound there
    # is evidence for. The anti-detect point -- never answering a network popup
    # in two seconds flat -- is kept through the spread below, and the "player
    # walked away" flavour moves to AFTER the reconnect, where the client is
    # alive and idling costs nothing but time.
    RECONNECT_MAX_HESITATION = 120.0

    def _check_reconnect_popup(self) -> bool:
        """Check and dismiss network disconnect popup. Call when flow seems stuck."""
        frame = self.sc.grab_full()
        if frame is None:
            return False
        m = self.matcher.match_single(frame, "ui/btn_confirm_reconnect")
        if m and m.confidence >= 0.75:
            seen_at = time.time()
            roll = random.random()
            if roll < 0.55:
                delay = random.uniform(1.0, 5.0)
            elif roll < 0.85:
                delay = random.uniform(10.0, 45.0)
            else:
                delay = random.uniform(45.0, self.RECONNECT_MAX_HESITATION)
            logger.info("Reconnect: popup seen, hesitating %.0fs before confirm", delay)
            if not self._sleep_while_client_alive(delay, "reconnect hesitation"):
                # The client died while we hesitated. Say so loudly: this is the
                # measurement that bounds RECONNECT_MAX_HESITATION, and it is
                # the only way that number ever gets refined.
                logger.warning("Reconnect: client died %.0fs after the popup was "
                               "first seen (hesitation was %.0fs)",
                               time.time() - seen_at, delay)
                return False
            # Re-verify before clicking: the client may have retried by itself,
            # or swapped the dialog for a login screen, while we waited.
            frame = self.sc.grab_full()
            m = (self.matcher.match_single(frame, "ui/btn_confirm_reconnect")
                 if frame is not None else None)
            if not m or m.confidence < 0.75:
                logger.info("Reconnect: popup gone on its own after %.0fs",
                            time.time() - seen_at)
                return False
            logger.info("Reconnect: confirming after %.0fs on screen",
                        time.time() - seen_at)
            print(f"  [{WARN}] Network disconnect popup (conf={m.confidence:.3f}), clicking confirm...")
            # Honour the result: the button registry can refuse a match that
            # landed far from where this button has ever been, and reporting a
            # dismissal that never happened would send the caller on blind.
            if not self._click_match(m):
                print(f"  [{WARN}] Confirm click was refused -- popup left alone")
                return False
            time.sleep(random.uniform(3.0, 8.0))
            # Here is where "I stepped away when the connection dropped" now
            # lives. Same idea as the long delays this replaced, but on the far
            # side of the confirm click: the client is reconnected and sitting
            # safely in the city, so a long idle costs farming time instead of
            # the whole session. Still interruptible -- nothing on this thread
            # should ever block past the client's own lifetime again.
            if random.random() < 0.20:
                afk = random.uniform(120.0, 600.0)
                logger.info("Reconnect: idling %.0fs after reconnect (was AFK)", afk)
                print(f"  [{INFO}] Back online -- idling {afk / 60:.1f} min before farming")
                self._sleep_while_client_alive(afk, "post-reconnect AFK")
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
