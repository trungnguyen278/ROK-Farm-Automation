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

from rok_farm.config import (DELAY_AFTER_ESCAPE, DELAY_AFTER_SCROLL,
                             DELAY_DRAG_SETTLE, DELAY_MINE_CLICK,
                             DELAY_RECHECK, DELAY_VERIFY, DELAY_WORLD_MAP,
                             DELAY_ZOOM_IN_POLL, GATHER_BTN_THRESHOLD,
                             GEM_MINE_TEMPLATES, GEM_MINE_THRESHOLD,
                             MARCH_BTN_PCT, NEW_TROOP_BTN_PCT, TOGGLE_BTN_PCT,
                             ZOOM_POLL_MAX)
from rok_farm.logging_setup import FAIL, INFO, PASS, WARN
from rok_farm.screenshots import save_annotated, save_screenshot


class GemFlowMixin:
    """Per-mine flow steps. Mixed into GemFarmRunner."""

    def _mine_flow(self, idx: int) -> bool:
        tag = f"m{idx}"

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

        self.gathered_positions.append(gem.center)
        print(f"  [{INFO}] Marked gem at {gem.center} as gathered ({len(self.gathered_positions)} total)")

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

        if not reached:
            for toggle in range(3):
                print(f"  [{INFO}] City -> world map: toggle corner {TOGGLE_BTN_PCT} (try {toggle+1}/3)")
                self._click_pct(*TOGGLE_BTN_PCT, jitter_px=4)
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

        zs = self._zoom_scrolls()
        print(f"  [{PASS}] On world map, zooming out {zs}x...")
        self._scroll_at_center(-1, zs)
        self._wait(DELAY_AFTER_SCROLL)

        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, f"{tag}_icon_zoom")

        self._record(f"{tag}_world", True, f"City -> world map -> zoom out {zs}x")
        return True

    def _step_stay_and_rezoom(self, tag: str):
        """After march, stay on world map and zoom back out to icon level."""
        print(f"\n--- [{tag}] Step 7: Stay on world map, re-zoom ---\n")

        # We just marched, so we're on the world map. The post-march zoom-in
        # reads ambiguously (city_btn vs globe ~tie), so DON'T verify the state
        # here -- just wait for the zoom-in to settle, then zoom back out (which
        # restores a clean world-map view). No empty-click (could select a tile).
        self._wait(random.uniform(1.0, 2.5))

        # Zoom out to icon level, then let the wander scan move the camera. (No
        # separate camera-shift swipe here -- the scan already pans around.)
        self._scroll_at_center(-1, self._zoom_scrolls())
        self._wait(DELAY_AFTER_SCROLL)

        self._view_is_world = True  # stayed on the world map
        self._record(f"{tag}_rezoom", True, "Stayed on world map, re-zoomed")

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
        self._scroll_at_center(-1, self._zoom_scrolls())
        self._wait(DELAY_AFTER_SCROLL)

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
        max_empty_streak = 12
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

            if not icons and self._edge_gems:
                print(f"  [{INFO}] Scan {scan_count:2d}: {len(self._edge_gems)} edge gem(s), recentering...")
                icons = self._recenter_edge_gem(self._edge_gems[0])

            if not icons:
                empty_streak += 1
                # Panned out of the kingdom into fog? Bail early -- the camera is
                # off the map edge, no resources will ever appear here. Return to
                # city so the next mine re-centers on the player's city.
                if self._is_fog(frame):
                    print(f"  [{WARN}] Scan {scan_count:2d}: FOG (out of kingdom) -- "
                          f"return to city, restart")
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

    def _step_click_march(self, tag: str) -> bool:
        print(f"\n--- [{tag}] Step 6: Troop + March ---\n")

        # Deterministic deploy flow, all FIXED clicks (template detection is
        # flaky at night): gather -> "Quan moi" (new troop) -> "Hanh quan"
        # (march). We do NOT retry-click: a retry after a march that already
        # fired just clicks junk on the world map (and re-opens the deploy).
        # Muscle-memory pacing: these are memorised positions, and the measured
        # 3.6 s / 2.3 s gaps were slower than a real gem farmer by roughly 5x.
        with self._muscle_memory():
            print(f"  [{INFO}] New Troop (Quan moi) at fixed pct{NEW_TROOP_BTN_PCT}")
            self._click_pct(*NEW_TROOP_BTN_PCT, jitter_px=6)
            # Still wait for the commander panel to actually paint -- fast is
            # the goal, clicking into a panel that is not up yet is not.
            self._wait((0.28, 0.08))

            print(f"  [{INFO}] March (Hanh quan) at fixed pct{MARCH_BTN_PCT}")
            self._click_pct(*MARCH_BTN_PCT, jitter_px=6)

        # Trust the fixed clicks: the post-march world map zooms in on the troops
        # and reads ambiguously (city_btn ~tie globe), so verifying here is
        # unreliable and just wastes time. The OCR queue check next loop is the
        # real source of truth -- if the march didn't fire, the slot stays free
        # and we simply farm it again. Just let the march animation settle.
        self._wait(random.uniform(1.5, 2.5))
        print(f"  [{PASS}] March sent (fixed Quan moi + Hanh quan)")
        self._record(f"{tag}_march", True, "sent")
        frame2 = self._grab()
        if frame2 is not None:
            save_screenshot(frame2, f"{tag}_after_march")
        return True

    # --- Step 7: Return to city view ---

    def _step_return_city(self, tag: str):
        print(f"\n--- [{tag}] Return to city ---\n")

        # Always called from the world map (after a burst / scan-fail / fog), so
        # click the FIXED bottom-right corner to toggle to the city. We do NOT
        # gate on _on_world_map(): right after a march the world map reads
        # ambiguously (city_btn ~tie globe) and the guard falsely said "already
        # in city", so the toggle was skipped and we never returned.
        print(f"  [{INFO}] City toggle corner {TOGGLE_BTN_PCT}")
        self._click_pct(*TOGGLE_BTN_PCT, jitter_px=4)
        self._wait(DELAY_WORLD_MAP)
        self._view_is_world = False  # now in the city

        frame = self._grab()
        if frame is not None:
            save_screenshot(frame, f"{tag}_return_city")

        self._record(f"{tag}_return", True, "Returned to city")
