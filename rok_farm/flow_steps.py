"""The gem farm flow itself, step 1..7 for a single mine.

    1. city -> world map at icon zoom
    2. wander-scan for gem icons, click + verify each candidate
    3. click "Thu Thap" (gather)
    4. new troop -> march
    5. stay on the world map and re-zoom for the next mine
"""

from __future__ import annotations

import math
import random
import time

from vision.color_filter import is_gem_mine_color
from vision.template_matcher import Match

from rok_farm.config import (DELAY_AFTER_ESCAPE, DELAY_DRAG_SETTLE,
                             DELAY_MINE_CLICK,
                             DELAY_RECHECK, DELAY_VERIFY, DELAY_WORLD_MAP,
                             DELAY_ZOOM_IN_POLL, GATHER_BTN_THRESHOLD,
                             GEM_MINE_TEMPLATES, GEM_MINE_THRESHOLD,
                             MARCH_BTN_MAX_OFFSET, MARCH_BTN_PCT,
                             NEW_TROOP_BTN_PCT, TOGGLE_BTN_PCT,
                             ZOOM_POLL_MAX)
from rok_farm.logging_setup import FAIL, INFO, PASS, WARN, logger
from rok_farm.map_memory import MapMemory
from rok_farm.screenshots import save_annotated, save_screenshot

# How close two HUD coordinate readings must be to mean the same deposit.
# Exact for now, on purpose: a missed duplicate costs one march, but a wrong
# match would refuse a genuinely new deposit for the rest of the session. Every
# march logs its distance to the nearest already-marched site, so if duplicates
# turn out to land a tile apart, the data says so and this can grow.
SITE_MATCH_TILES = 0


class GemFlowMixin:
    """Per-mine flow steps. Mixed into GemFarmRunner."""

    # How often the city <-> world toggle uses the SPACE shortcut instead of
    # clicking the corner button. The button is literally labelled "Space", so a
    # player who knows the game uses both -- and hitting the same corner pixel
    # every single time, hundreds of times a day, is a pattern worth breaking.
    # Deliberately low: the click is the muscle-memory default and the thing the
    # tuned positions and the button registry are built around.
    TOGGLE_SPACE_CHANCE = 0.18

    def _toggle_view(self, label: str):
        """Switch between city and world map, by button or by keybind."""
        if random.random() < self.TOGGLE_SPACE_CHANCE:
            print(f"  [{INFO}] {label}: SPACE key")
            self.cmd.send("KEY", "SPACE", random.randint(40, 90))
        else:
            print(f"  [{INFO}] {label}: corner {TOGGLE_BTN_PCT}")
            self._click_pct(*TOGGLE_BTN_PCT, jitter_px=4)

    # --- world-map memory -------------------------------------------------

    # OCR is not free, so the position is not read on every single pan. Every
    # few scans is plenty: the camera moves less than a cell most steps, and the
    # decisive moments (a gem, a wall) are read regardless of the cadence.
    MAP_READ_EVERY = 4

    def _map_sync(self, frame, found: bool, force: bool = False,
                  scan_count: int = 0):
        """Read the HUD position, open the right book, file what we just saw."""
        if not force and scan_count % self.MAP_READ_EVERY:
            return getattr(self, "_last_map_xy", None)
        pos = self._read_map_position(frame)
        if pos is None:
            return getattr(self, "_last_map_xy", None)
        map_id, x, y = pos
        # The map id is STICKY. Measured 2026-09-08 on the KvK map: the OCR
        # returns a structurally valid but wrong id in about 8% of reads
        # ("4093" against a HUD plainly showing "#S11465"), and narrowing the
        # crop does not help because it is a digit misread, not stray UI. Acting
        # on a single reading meant the book was swapped mid-run, over and over,
        # so nothing ever accumulated. Switching worlds is rare; misreading is
        # not -- so demand several consecutive agreeing reads before believing
        # the world changed, and ignore the one-off entirely.
        if self.mapmem is not None and self.mapmem.map_id != map_id:
            self._map_id_votes = getattr(self, "_map_id_votes", [])
            self._map_id_votes.append(map_id)
            if len(self._map_id_votes) < 3 or len(set(self._map_id_votes[-3:])) != 1:
                logger.debug("Ignoring map id %s (have %s, votes %s)",
                             map_id, self.mapmem.map_id, self._map_id_votes[-3:])
                return getattr(self, "_last_map_xy", None)
            self._map_id_votes = []
        else:
            self._map_id_votes = []
        if self.mapmem is None or self.mapmem.map_id != map_id:
            # Different map id = different world (home kingdom vs KvK), so a
            # different book. No configuration: the HUD says which one.
            self.mapmem = MapMemory(map_id)
            print(f"  [{INFO}] Map book opened -- {self.mapmem.stats()}")
        self.mapmem.note_position(x, y)
        self.mapmem.record_scan(x, y, found)
        self._last_map_xy = (x, y)
        return self._last_map_xy

    def _steer_heading(self, heading: float):
        """Nudge the wander toward ground the book likes, away from walls.

        Deliberately a nudge and not a command: unexplored ground scores 0, so
        the bot still wanders into places it has never been. It only overrides
        the random walk when the book has something clearly better to say --
        otherwise a couple of unlucky scans would pin it in one corner forever.
        """
        pos = getattr(self, "_last_map_xy", None)
        if pos is None or self.mapmem is None:
            return heading
        x, y = pos
        cands = [heading + d for d in
                 (0.0, 0.7, -0.7, 1.4, -1.4, 2.2, -2.2, math.pi)]
        scored = [(self.mapmem.heading_score(x, y, h), h) for h in cands]
        best_score, best = max(scored, key=lambda t: t[0])
        if best_score > scored[0][0] + 1.0:
            logger.debug("steer: %.0f -> %.0f deg (score %.1f > %.1f)",
                         math.degrees(heading) % 360,
                         math.degrees(best) % 360, best_score, scored[0][0])
            return best
        return heading

    def _mine_flow(self, idx: int) -> bool:
        tag = f"m{idx}"

        # Focus first, before anything is clicked. The operator uses this machine
        # too, and the moment they alt-tab away every click lands in THEIR window
        # while WGC keeps feeding us a perfect game frame -- observed 2026-08-19
        # 08:31, three "City -> world map" toggles in a row that changed nothing
        # because the game was behind the window the human had switched to.
        # Checking only in _tab_back and before the deploy chain was too narrow.
        self._ensure_game_focused(f"start of mine {idx}")

        # Step 1: Get to world map at icon-zoom level
        # If already on world map (from previous mine), skip city detour
        if not self._step_to_world_map(tag):
            return False

        # Step 2+3+4: Wander scan, clicking each icon to verify gem type
        gem = self._step_scan_and_verify_gem(tag)
        if gem is None:
            return False

        # Step 5: Click "Thu Thap" (gather)
        if not self._step_click_gather(tag):
            return False

        # Step 6: Select troop + click "March"
        if not self._step_click_march(tag):
            return False

        if self._pending_site:
            mid, sx, sy = self._pending_site
            self._marched_sites.append((mid, sx, sy, time.time()))
            print(f"  [{INFO}] Marched to {sx}:{sy} "
                  f"({len(self._marched_sites)} deposit(s) this session)")
            logger.info("Marched to deposit %s %d:%d", mid, sx, sy)
            self._pending_site = None

        # Step 7: prep for the next march by re-zooming to icon level on the
        # world map -- but only if a slot is still free. If this march just
        # filled the queue, the next loop iteration heads back to the city, so
        # re-zooming/panning here would be wasted motion.
        if self.loop:
            queue = self._detect_march_queue()
            if queue and queue[0] >= queue[1]:
                print(f"  [{INFO}] Queue full ({queue[0]}/{queue[1]}) after march -- "
                      f"skip re-zoom, heading to city next")
                return True
        self._step_stay_and_rezoom(tag)
        return True

    # --- Step 1: City view -> world map -> icon zoom ---

    def _step_to_world_map(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 1: Ensure world map @ icon-zoom ---\n")

        # If we stayed on the world map after the last march (mid-burst), TRUST
        # that -- don't re-detect/toggle. The post-march corner button reads
        # city_btn ~tied with the globe, so re-detection would falsely think
        # "city" and toggle away unnecessarily.
        reached = self._view_is_world
        if reached:
            print(f"  [{INFO}] Staying on world map (tracked) -- no toggle")
        else:
            # Fresh state (after city / alt-tab) reads cleanly -- detect/toggle.
            reached = self._on_world_map() or self._wait_until_world_map(timeout=2.0)

        toggled_from_city = False
        if not reached:
            for toggle in range(3):
                toggled_from_city = True
                self._toggle_view(f"City -> world map (try {toggle+1}/3)")
                if self._wait_until_world_map(timeout=4.0):
                    reached = True
                    break
                self._check_reconnect_popup()

        if not reached:
            print(f"  [{FAIL}] Not on world map after toggling")
            self._view_is_world = False
            frame = self._grab()
            if frame is not None:
                save_screenshot(frame, f"{tag}_world_fail")
            self._record(f"{tag}_world", False, "World map nav failed")
            return False

        self._view_is_world = True

        # On the world map. If already at icon-zoom with gems, scan; else zoom.
        frame = self._grab()
        gems = self._find_all_gems(frame) if frame is not None else []
        if gems:
            print(f"  [{PASS}] Already on world map icon-zoom, {len(gems)} gem(s)")
            self._record(f"{tag}_world", True, f"Already icon-zoom, {len(gems)} gems")
            return True

        # Zoom out ONLY when we just came from the city. The world map opens
        # zoomed in close, so that first zoom-out is what reaches icon level --
        # but firing it every time we merely FAIL TO SEE A GEM is what ratcheted
        # the view out to 0.35x template scale over a night. Barren ground looks
        # exactly like wrong zoom to a gem detector, so "no gems" must not be
        # read as "zoom out more".
        if toggled_from_city:
            zs = self._zoom_scrolls()
            print(f"  [{PASS}] Came from the city, zooming out {zs}x to icon level")
            self._scroll_at_center(-1, zs)
            self._wait_zoom_settled()
        else:
            print(f"  [{PASS}] Already on the world map -- leaving the zoom alone")

        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, f"{tag}_icon_zoom")

        self._record(f"{tag}_world", True, "City -> world map -> icon zoom")
        return True

    def _step_stay_and_rezoom(self, tag: str):
        """After march, stay on world map and zoom back out to icon level."""
        print(f"\n--- [{tag}] Step 7: Stay on world map, re-zoom ---\n")

        # We just marched, so we're on the world map. The post-march zoom-in
        # reads ambiguously (city_btn vs globe ~tie), so DON'T verify the state
        # here -- just wait for the zoom-in to settle, then zoom back out (which
        # restores a clean world-map view). No empty-click (could select a tile).
        self._wait(random.uniform(1.0, 2.5))

        # Zoom out AND pan a full screen away -- the same treatment a dud mine
        # gets in _return_to_icon_zoom, and for the same reason. "The scan pans
        # around anyway" was not good enough: the scan's FIRST frame is grabbed
        # before it pans, and the game has just centred the camera on the mine
        # we marched to, so that mine is sitting in the middle of it. Its frame
        # coordinates have changed with the zoom, so `clicked_positions` (frame
        # space) does not recognise it, and it gets clicked again -- measured
        # 2026-08-18 over 18 mid-burst transitions: 2 landed within 120px of the
        # mine just gathered (69px and 106px, i.e. the same rock), several more
        # within 200px. It is also a poor look: a real player does not re-farm
        # the node their troops are still marching to.
        self._return_to_icon_zoom()

        self._view_is_world = True  # stayed on the world map
        self._record(f"{tag}_rezoom", True, "Stayed on world map, re-zoomed")

    def _fog_confirmed(self, frame) -> bool:
        """Fog, but confirmed on a second frame a beat later.

        One frame is not enough evidence to abandon a map. The world map streams
        its terrain in, and a frame caught mid-load is a flat colour fill with no
        minimap drawn yet -- lap_var 0.1 -- which the featureless branch reads as
        out-of-kingdom. Measured 2026-08-18 09:09: the bot gave up on X:90 Y:140,
        ordinary farmland beside its own city, on exactly such a frame; the very
        next frame from the same spot was normal terrain full of nodes.

        Real out-of-kingdom void does not resolve into terrain a second later, so
        asking twice costs one second on a path that is rare anyway, and removes
        the entire class of transition/loading false alarms. Cheap insurance
        against the error the whole detector is tuned to avoid.
        """
        if not self._is_fog(frame):
            return False
        self._wait((0.9, 0.25))
        second = self._grab()
        if second is None:
            return False
        if self._is_fog(second):
            return True
        print(f"  [{INFO}] Fog vanished on re-check -- the view was still loading")
        logger.info("fog: first frame said fog, second did not -- treated as a "
                    "mid-load frame, NOT abandoning the map")
        return False

    def _retreat_from_edge(self, heading: float, swipes: int = 3):
        """Walk the camera back inland along `heading` after a fog bail.

        Same swipe mechanics the wander uses (drag opposite to the direction you
        want the camera to travel), just committed and in one direction, so the
        next mine does not start life staring at the same void.
        """
        cx, cy = self._center_screen()
        ww, wh = self.win["width"], self.win["height"]
        margin = 80
        print(f"  [{INFO}] Retreating inland {swipes} screen(s) "
              f"(heading {math.degrees(heading) % 360:.0f} deg)")
        for _ in range(max(1, swipes)):
            dx_f, dy_f = math.cos(heading), math.sin(heading)
            half_x = int((ww // 2 - margin) * random.uniform(0.85, 1.0))
            half_y = int((wh // 2 - margin) * random.uniform(0.85, 1.0))
            sx, sy = self._clamp_to_play_area(cx + int(dx_f * half_x),
                                              cy + int(dy_f * half_y))
            ex, ey = self._clamp_to_play_area(cx - int(dx_f * half_x),
                                              cy - int(dy_f * half_y))
            self._human_drag(sx, sy, ex, ey,
                             speed_factor=random.uniform(4.0, 5.5), easing="in")
            self._wait(DELAY_DRAG_SETTLE)
            heading += random.gauss(0, 0.12)
        # Hand the new bearing to the next mine -- it is the whole point.
        self._wander_heading = heading

    def _recenter_edge_gem(self, edge_match: Match) -> list[Match]:
        """Drag map to roughly center an edge gem, then re-scan."""
        cx, cy = self._center_screen()
        mx, my = edge_match.center
        sx, sy = self._screen_xy(mx, my)

        dx = cx - sx + random.randint(-60, 60)
        dy = cy - sy + random.randint(-40, 40)

        self._human_drag(cx, cy, cx + dx, cy + dy)
        self._wait(DELAY_DRAG_SETTLE, 1.0)

        frame = self._grab()
        if frame is None:
            return []
        return self._find_all_icons(frame)

    def _recenter_to_safe_zone(self, icon: Match) -> Match | None:
        """If icon is in no-click zone, drag map to move it to center."""
        sx, sy = self._screen_xy(*icon.center)
        if not self._in_no_click_zone(sx, sy):
            return icon
        cx, cy = self._center_screen()
        drag_dy = sy - cy
        drag_dx = sx - cx
        print(f"  [{INFO}] Icon at ({sx},{sy}) in no-click zone, dragging map to recenter")
        self._human_drag(cx - drag_dx // 3, cy - drag_dy // 3,
                         cx + drag_dx, cy + drag_dy)
        time.sleep(random.uniform(0.3, 0.6))
        frame = self._grab()
        if frame is None:
            return None
        icons = self._find_all_icons(frame)
        if icons:
            return icons[0]
        return None

    def _click_icon_and_verify(self, icon: Match, tag: str, attempt: int, icon_frame=None) -> bool:
        """Click an icon, wait for zoom-in, verify it's a gem mine. Returns True if gem popup opens."""
        sx, sy = self._screen_xy(*icon.center)
        print(f"  [{INFO}] [{attempt}] Clicking icon conf={icon.confidence:.3f} at {icon.center} -> screen ({sx},{sy})")

        # Save icon patch for classifier labeling
        if icon_frame is not None:
            icon_patch = self._extract_icon_patch(icon_frame, icon)
        else:
            icon_patch = None

        self._click(sx, sy)

        # Adaptive zoom-in wait: the game zooms into the mine after the icon
        # click. Poll for the mine structure (or an already-open gather popup)
        # instead of a fixed sleep, so a fast zoom continues immediately and a
        # slow one still gets up to ZOOM_POLL_MAX tries before giving up.
        frame = None
        mine = None
        g_raw = None
        for _poll in range(ZOOM_POLL_MAX):
            self._wait(DELAY_ZOOM_IN_POLL)
            frame = self._grab()
            if frame is None:
                continue
            mine = None
            for tpl in GEM_MINE_TEMPLATES:
                m = self._match_verify(frame, tpl, self.fast_matcher, GEM_MINE_THRESHOLD)
                if (m and m.confidence >= GEM_MINE_THRESHOLD
                        and (mine is None or m.confidence > mine.confidence)):
                    mine = m
            g_raw = self._match_verify(frame, "buttons/gather_btn", self.fast_matcher,
                                       GATHER_BTN_THRESHOLD)
            g_early = g_raw.confidence if g_raw else 0.0
            if mine is not None or g_early >= GATHER_BTN_THRESHOLD:
                break

        if frame is None:
            return False
        save_screenshot(frame, f"{tag}_attempt_{attempt:02d}")

        is_gem = mine is not None
        g_conf = g_raw.confidence if g_raw else 0.0
        g = g_raw if g_conf >= GATHER_BTN_THRESHOLD else None
        print(f"  [{INFO}] [{attempt}] gather_btn conf={g_conf:.3f} (threshold={GATHER_BTN_THRESHOLD}, pass={g is not None})")

        if self.auto_learn and icon_patch is not None and icon_patch.size > 0:
            n = self.classifier.add_sample(icon_patch, is_gem)
            label_str = "gem" if is_gem else "not_gem"
            stats = self.classifier.get_stats()
            print(f"  [LEARN] Added {label_str} sample #{n}, total={stats['total']} (gem={stats['gem']}, not_gem={stats['not_gem']})")

        # Check occupation before proceeding (bright green march/mining indicators)
        if is_gem:
            occupied, occ_info = self._is_mine_occupied(frame, mine)
            if occupied:
                save_screenshot(frame, f"{tag}_occupied_{attempt:02d}")
                print(f"  [{WARN}] [{attempt}] Mine occupied ({occ_info}) -- skipping")
                return False

            raw = self._raw_frame if self._raw_frame is not None else frame
            has_line, line_info = self._has_incoming_march(raw, mine)
            if has_line:
                save_screenshot(frame, f"{tag}_march_line_{attempt:02d}")
                print(f"  [{WARN}] [{attempt}] Incoming march at mine ({line_info}) -- skipping")
                return False

            is_gem_color, color_info = is_gem_mine_color(frame, mine.x, mine.y, mine.w, mine.h)
            if not is_gem_color:
                save_screenshot(frame, f"{tag}_mine_color_warn_{attempt:02d}")
                print(f"  [{WARN}] [{attempt}] Mine color suspect ({color_info}) -- continuing (icon filter passed)")
            else:
                print(f"  [{INFO}] [{attempt}] Mine color OK ({color_info})")

        if g and is_gem:
            print(f"  [{PASS}] [{attempt}] Gem mine confirmed + popup open (gather conf={g.confidence:.3f})")
            return True

        if g and not is_gem:
            print(f"  [{WARN}] [{attempt}] Popup open but NOT gem -- dismissing")
            self._press_escape()
            self._wait(DELAY_AFTER_ESCAPE)
            return False

        if is_gem and not g:
            self._wait(DELAY_RECHECK)
            frame_recheck = self._grab()
            if frame_recheck is not None:
                save_screenshot(frame_recheck, f"{tag}_recheck_{attempt:02d}")
                g_re_raw = self._match_verify(frame_recheck, "buttons/gather_btn",
                                              self.matcher, GATHER_BTN_THRESHOLD)
                g_re_conf = g_re_raw.confidence if g_re_raw else 0.0
                print(f"  [{INFO}] [{attempt}] re-check gather_btn conf={g_re_conf:.3f}")
                if g_re_conf >= GATHER_BTN_THRESHOLD:
                    print(f"  [{PASS}] [{attempt}] Popup detected on re-check (conf={g_re_conf:.3f})")
                    return True

            print(f"  [{INFO}] [{attempt}] Gem confirmed, clicking mine structure...")
            msx, msy = self._screen_xy(*mine.center)
            msx += mine.w // 5
            msy -= mine.h // 5
            self._click(msx, msy)
            self._wait(DELAY_MINE_CLICK)
            frame2 = self._grab()
            if frame2 is not None:
                save_screenshot(frame2, f"{tag}_after_mine_click_{attempt:02d}")
                g2_raw = self._match_verify(frame2, "buttons/gather_btn",
                                            self.matcher, GATHER_BTN_THRESHOLD)
                g2_conf = g2_raw.confidence if g2_raw else 0.0
                print(f"  [{INFO}] [{attempt}] after mine click gather_btn conf={g2_conf:.3f}")
                if g2_conf >= GATHER_BTN_THRESHOLD:
                    print(f"  [{PASS}] [{attempt}] Popup opened after mine click!")
                    return True
            print(f"  [{WARN}] [{attempt}] Gem confirmed but popup won't open")
            return False

        # Neither gem structure nor popup -- not a gem mine
        print(f"  [{WARN}] [{attempt}] Not a gem mine")
        return False

    def _return_to_icon_zoom(self, heading: float | None = None):
        """After a failed icon click, zoom back out AND move on.

        Clicking an icon zooms the game onto that mine, so zooming back out
        leaves the camera centred on it. The wander then pans only 0.5-0.75 of
        the HALF screen -- overlap that exists so gems are not skipped -- which
        leaves the just-failed mine still in view and still the most prominent
        icon. Its frame coordinates have changed though, so `clicked_positions`
        (which is in frame space) no longer recognises it and the flow clicks
        the same mine again. Observed: the same mine attempted four times.

        Panning a full screen away breaks that loop, and matches what a player
        does after a dud -- go somewhere else, not circle the same rock.
        """
        # This one IS a real zoom-out: clicking an icon makes the game zoom in
        # on that mine, so coming back out by the same amount returns to icon
        # level. It is paired with a zoom-in that actually happened, which is
        # what makes it safe -- unlike the unconditional one above.
        self._scroll_at_center(-1, self._zoom_scrolls())
        self._wait_zoom_settled()

        cx, cy = self._center_screen()
        ww, wh = self.win["width"], self.win["height"]
        if heading is None:
            heading = getattr(self, "_wander_heading", random.uniform(0, 2 * math.pi))
        # Leave at an angle to the search heading so we do not simply retrace
        # the ground the wander already covered.
        heading += random.uniform(-math.pi / 3, math.pi / 3)
        # pct > 1 of the half-screen reach: one swipe shifts the map by roughly
        # a full screen, which is what it takes to put a centred mine outside
        # the view rather than merely near its edge.
        pct = random.uniform(1.0, 1.35)
        dx = int((ww // 2 - 80) * pct * math.cos(heading))
        dy = int((wh // 2 - 80) * pct * math.sin(heading))
        sx, sy = self._clamp_to_play_area(cx + dx // 2, cy + dy // 2)
        ex, ey = self._clamp_to_play_area(cx - dx // 2, cy - dy // 2)
        self._human_drag(sx, sy, ex, ey, speed_factor=random.uniform(3.6, 5.0))
        self._wait(DELAY_DRAG_SETTLE)

    def _step_scan_and_verify_gem(self, tag: str) -> Match | None:
        print(f"\n--- [{tag}] Step 2: Scan + verify gem mines ---\n")

        ww = self.win["width"]
        wh = self.win["height"]
        margin = 80
        cx, cy = self._center_screen()

        wander_heading = getattr(self, '_wander_heading', random.uniform(0, 2 * math.pi))
        scan_count = 0
        scan_speed = random.uniform(3.6, 5.0)
        _speed_target = random.uniform(3.6, 7.0)
        max_scans = 60
        max_attempts = 10
        empty_streak = 0
        # 12 sat exactly on the observed ceiling, which is the tell that it was
        # censoring the data rather than describing it. Over 374 finds in the
        # log the streak-before-a-find decayed 24, 18, 14, 19, 9, 8 across
        # lengths 6..11 and then dropped to a hard 0 at 12 -- not a natural
        # tail, just the cutoff. Finds at 12-14 were unobservable, so 18 is set
        # to actually run the experiment; report.py counts scan_giveup, so the
        # next run says whether anything lands past 11.
        max_empty_streak = 18
        max_icons_per_frame = 2
        attempt = 0
        SKIP_RADIUS = 80
        clicked_positions: list[tuple[int, int, int]] = []

        print(f"  [{INFO}] Wander scan (margin={margin})")

        # Check current frame first
        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, f"{tag}_scan_00")
            icons = self._find_all_icons(frame)
            if not icons and self._edge_gems:
                print(f"  [{INFO}] {len(self._edge_gems)} edge gem(s) on initial frame, recentering...")
                icons = self._recenter_edge_gem(self._edge_gems[0])
            tried_this_frame = 0
            for icon in icons:
                if attempt >= max_attempts or tried_this_frame >= max_icons_per_frame:
                    break
                if any(abs(icon.center[0]-px) < r and abs(icon.center[1]-py) < r
                       for px, py, r in clicked_positions):
                    continue
                raw = self._raw_frame if self._raw_frame is not None else frame
                occupied, occ_info = self._check_icon_occupied(raw, icon)
                if occupied:
                    print(f"  [{WARN}] Icon at {icon.center} occupied ({occ_info}) -- skip")
                    clicked_positions.append((*icon.center, SKIP_RADIUS))
                    continue
                icon = self._recenter_to_safe_zone(icon)
                if icon is None:
                    continue
                attempt += 1
                tried_this_frame += 1
                clicked_positions.append((*icon.center, SKIP_RADIUS))
                if self._click_icon_and_verify(icon, tag, attempt, icon_frame=frame):
                    self._record(f"{tag}_find", True, f"Gem found at attempt {attempt} (no drag)")
                    return icon
                self._return_to_icon_zoom()

        # Random wander scan (human-like, not spiral)
        while scan_count < max_scans and attempt < max_attempts:
            scan_count += 1

            if self._check_session() == "break":
                return None

            turn = random.gauss(0, 0.4)
            if random.random() < 0.15:
                turn = random.uniform(-math.pi / 2, math.pi / 2)
            if random.random() < 0.05:
                turn = random.uniform(-math.pi, math.pi)
            wander_heading += turn
            wander_heading = self._steer_heading(wander_heading)

            dx_f = math.cos(wander_heading)
            dy_f = math.sin(wander_heading)

            if random.random() < 0.12:
                _speed_target = random.uniform(3.6, 7.0)
            scan_speed += (_speed_target - scan_speed) * random.uniform(0.08, 0.15)

            # Pan a CONTROLLED total distance per scan step, split across 1-2
            # swipes. The total is a fraction of the half-screen reach (not
            # per-swipe), so 1 vs 2 swipes covers the same ground -- consecutive
            # scans then overlap instead of jumping too far and skipping gems.
            num_swipes = random.choices([1, 2], weights=[45, 55])[0]
            total_pct = random.uniform(0.50, 0.75)
            per_pct = total_pct / num_swipes
            half_x = int((ww // 2 - margin) * per_pct)
            half_y = int((wh // 2 - margin) * per_pct)
            for _sw in range(num_swipes):
                jx = random.randint(-25, 25)
                jy = random.randint(-20, 20)
                sx = cx + int(dx_f * half_x) + jx
                sy = cy + int(dy_f * half_y) + jy
                ex = cx - int(dx_f * half_x) + jx
                ey = cy - int(dy_f * half_y) + jy
                sx, sy = self._clamp_to_play_area(sx, sy)
                ex, ey = self._clamp_to_play_area(ex, ey)
                self._human_drag(sx, sy, ex, ey, speed_factor=scan_speed, easing="in")
                if _sw < num_swipes - 1:
                    # mid-sequence: barely pause -- we haven't arrived yet, so
                    # there's nothing new to load; no big delay needed.
                    time.sleep(random.uniform(0.05, 0.15))
                    wander_heading += random.gauss(0, 0.15)
                    dx_f = math.cos(wander_heading)
                    dy_f = math.sin(wander_heading)

            # Let the map settle once so the captured frame isn't mid-pan.
            self._wait(DELAY_DRAG_SETTLE)
            if random.random() < 0.08:
                time.sleep(random.uniform(0.8, 1.8))

            frame = self._grab()
            if frame is None:
                continue

            save_screenshot(frame, f"{tag}_scan_{scan_count:02d}")

            icons = self._find_all_icons(frame)
            self._map_sync(frame, bool(icons), scan_count=scan_count)

            if not icons and self._edge_gems:
                print(f"  [{INFO}] Scan {scan_count:2d}: {len(self._edge_gems)} edge gem(s), recentering...")
                icons = self._recenter_edge_gem(self._edge_gems[0])

            if not icons:
                empty_streak += 1
                # Panned out of the kingdom into fog? Bail early -- the camera is
                # off the map edge, no resources will ever appear here. Return to
                # city so the next mine re-centers on the player's city.
                if self._fog_confirmed(frame):
                    print(f"  [{WARN}] Scan {scan_count:2d}: FOG (out of kingdom) -- "
                          f"turn back inland, then return to city")
                    # Strongest terrain evidence available: mark it permanently.
                    # Mountains and the map void do not move, so unlike the
                    # reach book this is never expired.
                    xy = self._map_sync(frame, False, force=True)
                    if xy and self.mapmem:
                        self.mapmem.record_wall(*xy)
                        self.mapmem.save()
                    # Turning the camera around matters more than the city trip.
                    # The world map REMEMBERS its camera across a city
                    # round-trip, so "return to city, restart" recentres
                    # nothing: measured 2026-08-18, a bail at X:0 was followed
                    # by the next mine opening at X:1 and bailing again, and 4
                    # of the 5 bails that day sat at X<=7. The heading also
                    # persists across mines (`_wander_heading`), so without this
                    # the bot re-enters at the same edge pointing the same way
                    # and burns another mine discovering the same fog.
                    back = wander_heading + math.pi + random.uniform(-0.35, 0.35)
                    self._retreat_from_edge(back)
                    self._step_return_city(tag)
                    return None
                print(f"  [ -- ] Scan {scan_count:2d}/{max_scans}: no icons "
                      f"(spd={scan_speed:.1f}x, empty={empty_streak})")
                if empty_streak >= max_empty_streak:
                    if self._check_reconnect_popup():
                        empty_streak = 0
                        continue
                    print(f"  [{WARN}] {max_empty_streak} consecutive empty scans -- "
                          f"restarting from city")
                    self._step_return_city(tag)
                    return None
                continue

            empty_streak = 0
            print(f"  [{INFO}] Scan {scan_count:2d}/{max_scans}: {len(icons)} icon(s)")
            tried_this_frame = 0
            for icon in icons:
                if attempt >= max_attempts or tried_this_frame >= max_icons_per_frame:
                    break
                if any(abs(icon.center[0]-px) < r and abs(icon.center[1]-py) < r
                       for px, py, r in clicked_positions):
                    print(f"  [ -- ] Skip already-clicked icon at {icon.center}")
                    continue
                raw = self._raw_frame if self._raw_frame is not None else frame
                occupied, occ_info = self._check_icon_occupied(raw, icon)
                if occupied:
                    print(f"  [{WARN}] Icon at {icon.center} occupied ({occ_info}) -- skip")
                    clicked_positions.append((*icon.center, SKIP_RADIUS))
                    continue
                icon = self._recenter_to_safe_zone(icon)
                if icon is None:
                    continue
                attempt += 1
                tried_this_frame += 1
                clicked_positions.append((*icon.center, SKIP_RADIUS))
                if self._click_icon_and_verify(icon, tag, attempt, icon_frame=frame):
                    self._wander_heading = wander_heading
                    self._record(f"{tag}_find", True, f"Gem at attempt {attempt}, scan {scan_count}")
                    return icon
                self._return_to_icon_zoom(wander_heading)

        self._wander_heading = wander_heading
        print(f"  [{FAIL}] No gem mine after {scan_count} scans, {attempt} icons checked")
        self._record(f"{tag}_find", False, f"{attempt} icons checked, none were gem")
        return None

    # --- Step: Click gather button ---

    def _step_click_gather(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 5: Click Gather ---\n")

        max_retries = random.randint(3, 6)
        for attempt in range(max_retries):
            frame = self._grab()
            if frame is None:
                self._wait(DELAY_RECHECK)
                continue
            if random.random() < 0.1:
                time.sleep(random.uniform(1.0, 3.0))

            m_raw = self.matcher.match_single(frame, "buttons/gather_btn")
            m_conf = m_raw.confidence if m_raw else 0.0
            m = m_raw if m_conf >= GATHER_BTN_THRESHOLD else None

            if m:
                print(f"  [{PASS}] gather_btn: conf={m.confidence:.3f}")
                save_annotated(frame, m, f"{tag}_gather_found")

                # Identify the deposit BEFORE opening the deploy panel: that
                # panel covers the top-left corner where the coordinates live.
                # Clicking a node centres the camera on it, so the HUD readout
                # here is the node's own tile -- no pixel-to-tile calibration
                # needed. An army still marching does not mark its target as
                # occupied, so without this the same deposit gets a second
                # march minutes later (mines 2 and 3 on 2026-09-09 21:12, both
                # reporting march=356s to the second).
                self._pending_site = None
                site = self._read_map_position(frame)
                if site:
                    seen, dist = self._marched_before(site)
                    if seen:
                        print(f"  [{WARN}] Deposit {site[1]}:{site[2]} already "
                              f"marched this session -- backing out")
                        logger.info("Duplicate deposit %s -- not marching again",
                                    site)
                        self._record(f"{tag}_gather", False, "duplicate deposit")
                        return False
                    self._pending_site = site
                    if dist is not None:
                        # Feeds the tolerance decision with real numbers instead
                        # of a guess: if duplicates keep landing 1 tile apart,
                        # SITE_MATCH_TILES needs to grow.
                        logger.info("Deposit %d:%d, nearest already marched is "
                                    "%d tile(s) away", site[1], site[2], dist)

                if self._click_match(m):
                    print(f"  [{PASS}] Gather clicked!")
                    self._wait(DELAY_VERIFY)
                    frame2 = self._grab()
                    if frame2 is not None:
                        save_screenshot(frame2, f"{tag}_after_gather")
                    self._record(f"{tag}_gather", True, f"conf={m.confidence:.3f}")
                    return True

            print(f"  [{INFO}] gather_btn not found (attempt {attempt+1}/5)")
            self._wait(DELAY_RECHECK)

        if self._check_reconnect_popup():
            return self._step_click_gather(tag)
        print(f"  [{FAIL}] gather_btn not found")
        self._record(f"{tag}_gather", False, "Not found")
        return False

    def _marched_before(self, site):
        """(already marched?, tiles to the nearest one already marched).

        Exact-match only for now. Under-blocking is the safe direction: a
        missed duplicate costs one march, while a wrong block would refuse a
        genuinely new deposit forever. The distance is logged on every march so
        the real spread decides whether a tolerance is needed, rather than a
        number picked here.
        """
        mid, x, y = site
        nearest = None
        for m2, x2, y2, _when in self._marched_sites:
            if m2 != mid:
                continue
            d = max(abs(x - x2), abs(y - y2))
            nearest = d if nearest is None else min(nearest, d)
            if d <= SITE_MATCH_TILES:
                return True, d
        return False, nearest

    def _step_click_march(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 6: Troop + March ---\n")

        # Deterministic deploy flow, all FIXED clicks (template detection is
        # flaky at night): gather -> "Quan moi" (new troop) -> "Hanh quan"
        # (march). We do NOT retry-click: a retry after a march that already
        # fired just clicks junk on the world map (and re-opens the deploy).
        # Muscle-memory pacing: these are memorised positions, and the measured
        # 3.6 s / 2.3 s gaps were slower than a real gem farmer by roughly 5x.
        # Cheapest possible insurance in the most expensive place: if the game
        # is not in front, the whole deploy chain clicks into another window and
        # the march is lost silently.
        self._ensure_game_focused("before deploy chain")

        # Do NOT assume the Gather click opened the deploy panel. Measured
        # 2026-08-19 12:57: gather_btn matched at 0.926, the click landed within
        # 1px, "Gather clicked!" was printed -- and the panel never appeared.
        # The chain then fired "Quan moi" at a fixed spot on the bare world map,
        # which closed whatever was left, and the March poll spent 6s staring at
        # an empty map (march_btn_TIMEOUT_125655.png). Same mistake as the March
        # button: believing a UI transition happened because we asked for it.
        if not self._wait_for_troop_panel():
            print(f"  [{FAIL}] Deploy panel never opened after Gather -- "
                  f"not firing the chain into the map")
            self._record(f"{tag}_march", False, "deploy panel did not open")
            return False

        with self._muscle_memory():
            print(f"  [{INFO}] New Troop (Quan moi) at fixed pct{NEW_TROOP_BTN_PCT}")
            self._click_pct(*NEW_TROOP_BTN_PCT, jitter_px=6)
            # Wait for the commander panel to ACTUALLY paint. The old fixed
            # 0.28s was a guess at how long that takes, and clicking into a
            # panel that is not up yet is precisely how a march fails in
            # silence -- which is what the queue badge caught on 2026-08-18,
            # three mines in a row with the New Troop click landing correctly.
            # The templates are only a readiness gate: the click itself stays on
            # the memorised fixed position, because template detection is flaky
            # at night and the fixed positions are what the pacing is tuned for.
            self._wait_for_march_button()

            print(f"  [{INFO}] March (Hanh quan) at fixed pct{MARCH_BTN_PCT}")
            self._click_pct(*MARCH_BTN_PCT, jitter_px=6)

        # Let the march animation settle. NOTE: the game moves the camera to the
        # marching troop by itself here, so a post-march frame showing somewhere
        # other than where we were scanning is the game doing that, NOT a bug --
        # do not read camera jumps in these screenshots as a fault.
        self._wait(random.uniform(1.5, 2.5))

        print(f"  [{PASS}] March sent (fixed Quan moi + Hanh quan)")
        self._record(f"{tag}_march", True, "sent")
        # Now that the march is away and nothing is time-critical, read the
        # numbers off the panel frame captured between the two clicks.
        self._log_deploy_panel(tag)
        frame2 = self._grab()
        if frame2 is not None:
            save_screenshot(frame2, f"{tag}_after_march")
        return True

    def _wait_for_troop_panel(self, timeout: float = 4.0) -> bool:
        """Is the panel with the "Quan moi" button actually up?

        Position-checked like the March gate, because `new_troop_btn` can match
        weakly elsewhere on a busy map and a false pass here is exactly what
        sends the chain clicking into open ground.
        """
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            self._wait((0.12, 0.04))
            frame = self._grab()
            if frame is None:
                continue
            m = self._match_verify(frame, "buttons/new_troop_btn",
                                   self.fast_matcher, 0.70)
            if m is None or m.confidence < 0.70:
                continue
            fw, fh = frame.shape[1], frame.shape[0]
            at = (m.center[0] / fw, m.center[1] / fh)
            off = math.hypot(at[0] - NEW_TROOP_BTN_PCT[0],
                             at[1] - NEW_TROOP_BTN_PCT[1])
            if off > MARCH_BTN_MAX_OFFSET:
                logger.debug("Troop gate: ignoring match at (%.3f,%.3f), "
                             "%.3f away", *at, off)
                continue
            logger.info("Deploy panel up after %.2fs (conf=%.3f)",
                        time.monotonic() - start, m.confidence)
            return True
        logger.warning("Deploy panel did not open within %.1fs", timeout)
        return False

    def _wait_for_march_button(self, timeout: float = 6.0) -> float:
        """Block until the March button is painted, or `timeout`. Returns seconds.

        Diagnostic as much as fix: it logs how long the panel really took, so
        the 0.28s that used to be assumed here becomes a measured number over
        many mines instead of a guess. A timeout is logged loudly and still
        falls through to the fixed click -- if the panel never appears, the
        march was lost for a different reason and the queue check will say so.
        """
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            self._wait((0.10, 0.03))
            frame = self._grab()
            if frame is None:
                continue
            for tpl in ("buttons/march_btn_orange", "buttons/march_btn"):
                m = self._match_verify(frame, tpl, self.fast_matcher, 0.70)
                if m is not None and m.confidence >= 0.70:
                    # WHERE it matched decides whether it is the button at all.
                    # Measured 2026-08-18: every lost march passed this gate on
                    # `march_btn` matching at (1283,250) -- pct (0.837,0.291),
                    # up in the troop list, 0.505 of the window away from the
                    # button we click. Meanwhile the real "HANH QUAN" button was
                    # still fading in, so it matched too weakly to be seen. The
                    # click then landed on a panel that had not become
                    # interactive. Successful marches matched at (0.652,0.758),
                    # 0.006 away -- so the two cases are separated by two orders
                    # of magnitude and a generous radius still splits them.
                    fw, fh = frame.shape[1], frame.shape[0]
                    at = (m.center[0] / fw, m.center[1] / fh)
                    off = math.hypot(at[0] - MARCH_BTN_PCT[0],
                                     at[1] - MARCH_BTN_PCT[1])
                    if off > MARCH_BTN_MAX_OFFSET:
                        logger.debug("March gate: ignoring %s at (%.3f,%.3f), "
                                     "%.3f from the click point", tpl, *at, off)
                        continue
                    took = time.monotonic() - start
                    # Keep the frame the click is about to be aimed at. Saving
                    # it here would cost PNG-write time inside the muscle-memory
                    # deploy chain, so it is only written later, and only when
                    # the queue says the march did not fire -- the one case
                    # where the panel's real state is worth seeing.
                    self._deploy_frame = frame
                    self._deploy_seen = (tpl, m.confidence, m.center)
                    logger.info("March button painted after %.2fs (%s conf=%.3f) "
                                "at %s vs fixed click %s",
                                took, tpl, m.confidence, m.center, MARCH_BTN_PCT)
                    return took
        took = time.monotonic() - start
        # Keep the evidence. A timeout here means either the panel never opened
        # (so the fixed click below lands on nothing and the march is lost) or
        # it opened somewhere unexpected -- and those need completely different
        # fixes. Without the frame it is guesswork, and this path is rare enough
        # that writing a PNG costs nothing overall.
        frame = self._grab()
        if frame is not None:
            path = save_screenshot(frame, "march_btn_TIMEOUT")
            logger.warning("March button did not appear within %.1fs -- clicking "
                           "the fixed position anyway; screen saved to %s",
                           timeout, path)
        else:
            logger.warning("March button did not appear within %.1fs -- clicking "
                           "the fixed position anyway (no frame to save)", timeout)
        return took

    def _reconcile_queue(self):
        """Read the march queue ONCE, after the burst and before tabbing away.

        This replaced per-march verification, for two reasons. Reading the badge
        inside the deploy chain put an OCR pause in the one place that has to
        stay fast (it is memorised muscle memory, see
        [[feedback_speed_matches_familiarity]]). And comparing the badge before
        and after a single march is unreliable anyway: a gathering troop coming
        home in the same window cancels the increment, so a real march reads as
        a failure.

        Here neither problem exists. The burst is finished, nothing is about to
        be clicked, and the queue simply SHOULD be full -- so a shortfall is
        real information. Purely diagnostic: it never fails a mine.
        """
        queue = self._detect_march_queue()
        if not queue:
            logger.info("Queue reconcile: OCR gave no reading")
            return
        used, total = queue
        self._queue_before_mine = used
        self.sync_open_marches(used)
        if used >= total:
            print(f"  [{PASS}] Queue reconciled: {used}/{total} -- burst is full")
            logger.info("Queue reconcile: %d/%d full", used, total)
        else:
            print(f"  [{WARN}] Queue {used}/{total} after the burst -- "
                  f"{total - used} slot(s) never filled")
            logger.warning("Queue reconcile: %d/%d, %d slot(s) unfilled",
                           used, total, total - used)

    def _verify_march_fired(self, tries: int = 3):
        """Did the march-queue badge go up? True / False / None if unknowable.

        None means the question could not be answered -- no 'before' reading
        this mine, or the OCR never landed -- and the caller then keeps the old
        behaviour of trusting the clicks rather than failing a good march on a
        missing measurement.
        """
        before = getattr(self, "_queue_before_mine", None)
        if before is None:
            logger.debug("March verify: no queue reading before this mine")
            return None

        saw_a_reading = False
        for attempt in range(tries):
            queue = self._detect_march_queue(retries=2)
            if queue:
                saw_a_reading = True
                used, total = queue
                if used > before:
                    logger.info("March verified: queue %d/%d (was %d)",
                                used, total, before)
                    self._queue_before_mine = used
                    return True
            if attempt < tries - 1:
                self._wait(random.uniform(0.7, 1.3))

        if not saw_a_reading:
            logger.warning("March verify: queue OCR never landed, trusting the clicks")
            return None
        logger.warning("March verify: queue still %d after the deploy chain", before)
        return False

    # --- Step 7: Return to city view ---

    def _step_return_city(self, tag: str):
        print(f"\n--- [{tag}] Return to city ---\n")

        # Always called from the world map (after a burst / scan-fail / fog), so
        # click the FIXED bottom-right corner to toggle to the city. We do NOT
        # gate on _on_world_map(): right after a march the world map reads
        # ambiguously (city_btn ~tie globe) and the guard falsely said "already
        # in city", so the toggle was skipped and we never returned.
        self._toggle_view("World map -> city")
        self._wait(DELAY_WORLD_MAP)
        self._view_is_world = False  # now in the city

        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, f"{tag}_return_city")

        self._record(f"{tag}_return", True, "Returned to city")
