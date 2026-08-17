"""Vision: what is on the current frame.

Template lookups, the world-map/city discrimination, gem-icon filtering, and the
"is this mine already taken" checks (pickaxe icon + march lines). Nothing here
sends input; callers decide what to do with a Match.
"""

from __future__ import annotations

import random
import time

import cv2
import numpy as np

from vision.color_filter import is_gem_icon_color
from vision.template_matcher import Match

from rok_farm.config import (BUTTON_THRESHOLD, DARK_TERRAIN_THRESH,
                             FOG_HUE_STD_MAX, FOG_LAP_VAR_MAX, MARCH_TEMPLATES,
                             OCCUPIED_TEMPLATES, OCCUPIED_THRESHOLD,
                             SAFE_ZONE_MARGIN, VERIFY_ROI)
from rok_farm.logging_setup import INFO, logger


class DetectMixin:
    """Frame detection helpers. Mixed into GemFarmRunner."""

    # --- Template helpers ---

    def _find(self, template: str, threshold: float = 0.65) -> Match | None:
        frame = self._grab()
        if frame is None:
            return None
        m = self.matcher.match_single(frame, template)
        if m and m.confidence >= threshold:
            return m
        return None

    def _find_on_frame(self, frame, template: str, threshold: float = 0.65) -> Match | None:
        m = self.matcher.match_single(frame, template)
        if m and m.confidence >= threshold:
            return m
        return None

    def _match_verify(self, frame, template: str, matcher, min_conf: float,
                      roi=VERIFY_ROI) -> Match | None:
        """Match in the center ROI first (fast); fall back to a full-frame match
        if the ROI gives nothing strong enough. The mine/gather auto-center after
        zoom-in so the ROI normally hits; the fallback covers off-center cases
        (click drift, or a mine near the map edge that can't fully center).
        Returns a Match in full-frame coords."""
        fh, fw = frame.shape[:2]
        rx1, ry1, rx2, ry2 = roi
        x1, y1 = int(fw * rx1), int(fh * ry1)
        x2, y2 = int(fw * rx2), int(fh * ry2)
        crop = frame[y1:y2, x1:x2]
        if crop.size:
            m = matcher.match_single(crop, template)
            if m is not None and m.confidence >= min_conf:
                ax, ay = m.x + x1, m.y + y1
                return Match(m.name, ax, ay, m.w, m.h, m.confidence,
                             (ax + m.w // 2, ay + m.h // 2))
        # ROI weak/empty -> search the whole frame.
        return matcher.match_single(frame, template)

    # Real city/world toggle button lives in the bottom-right corner. A rare
    # event icon at the TOP-right looks like city_btn and was matching as the
    # best result, fooling the "are we on the world map" check -> nav fails.
    _CITY_BTN_REGION = (0.82, 0.78, 1.0, 1.0)  # x1, y1, x2, y2 in frame pct

    def _find_city_btn(self, frame=None, threshold: float = 0.70) -> Match | None:
        """Return the world-map 'back to city' button (only present ON the WORLD
        MAP), matched in the bottom-right corner. The CITY view shows a 'world
        map' globe button in the SAME corner, so require city_btn to OUT-score
        world_map_city_btn.

        Matches on the RAW (un-normalized) frame: these are HUD icons, and the
        night desaturation that helps gem matching WEAKENS the button match
        (measured: city_btn 0.83 raw vs 0.74 desaturated, margin +0.12 vs +0.02).
        Raw gives a clear city-vs-world margin even at night.
        """
        # Grab a FRESH frame every call. Poll callers (_wait_until_world_map)
        # don't refresh between checks, so reusing a cached _raw_frame made a
        # city->world toggle invisible: the view switched but this kept reading
        # the pre-toggle frame and reported "city" forever.
        self._grab()
        frame = self._raw_frame
        if frame is None:
            return None
        fh, fw = frame.shape[:2]
        rx1, ry1, rx2, ry2 = self._CITY_BTN_REGION
        x1, y1 = int(fw * rx1), int(fh * ry1)
        x2, y2 = int(fw * rx2), int(fh * ry2)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        # The two bottom-right "Space" buttons are identical apart from their
        # inner glyph -- a CASTLE means we are on the world map (the button
        # returns to the city), a MAP means we are in the city. Matching the
        # whole button was dominated by the shared disc + "Space" text and scored
        # ~equally in both states (measured: world_map_city_btn hit 0.96 on the
        # castle button it should NOT match). Match just the glyphs instead:
        # castle out-scoring map is the world map. (measured margins: city
        # map 0.85 vs castle 0.64; world castle 0.99 vs map 0.00.)
        castle = self.matcher.match_single(crop, "buttons/space_castle")
        city = self.matcher.match_single(crop, "buttons/space_map")
        cc = castle.confidence if castle else 0.0
        mm = city.confidence if city else 0.0
        on_world = bool(castle and cc >= threshold and cc > mm)
        logger.debug("space_castle=%.3f vs space_map=%.3f -> %s",
                     cc, mm, "WORLD" if on_world else "city/none")
        if on_world:
            ax, ay = castle.x + x1, castle.y + y1
            return Match(castle.name, ax, ay, castle.w, castle.h,
                         castle.confidence,
                         (ax + castle.w // 2, ay + castle.h // 2))
        return None

    def _on_world_map(self, frame=None) -> bool:
        """True if currently on the world map (the bottom-right Space button
        shows the castle glyph, not the map glyph)."""
        return self._find_city_btn(frame, threshold=0.70) is not None

    def _wait_until_world_map(self, timeout: float = 4.0) -> bool:
        """Poll for the world-map state until timeout -- lets a city<->world or
        post-march transition animation settle before we judge the state."""
        start = time.time()
        while time.time() - start < timeout:
            if self._on_world_map():
                return True
            time.sleep(random.uniform(0.4, 0.8))
        return False

    # The "Quan moi" (New Troop) button sits on the RIGHT, next to the army /
    # troop-count list -- NOT bottom-center. Searching the whole frame matched a
    # look-alike mid-map (clicked the wrong spot), so restrict to the right side.
    _NEW_TROOP_REGION = (0.70, 0.12, 1.0, 0.60)  # x1, y1, x2, y2 in frame pct

    def _find_new_troop_btn(self, frame=None, threshold: float = BUTTON_THRESHOLD) -> Match | None:
        """Match new_troop_btn only in the right-side troop panel region."""
        if frame is None:
            frame = self._grab()
        if frame is None:
            return None
        fh, fw = frame.shape[:2]
        rx1, ry1, rx2, ry2 = self._NEW_TROOP_REGION
        x1, y1 = int(fw * rx1), int(fh * ry1)
        x2, y2 = int(fw * rx2), int(fh * ry2)
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        m = self.matcher.match_single(crop, "buttons/new_troop_btn")
        if m and m.confidence >= threshold:
            ax, ay = m.x + x1, m.y + y1
            return Match(m.name, ax, ay, m.w, m.h, m.confidence,
                         (ax + m.w // 2, ay + m.h // 2))
        return None

    def _find_all_gems(self, frame) -> list[Match]:
        matches = self.matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
        gem_thr = self._gem_icon_threshold()
        result = []
        edge_gems = []
        for m in matches:
            if m.confidence < gem_thr:
                continue
            patch = self._extract_icon_patch(frame, m)
            should, label, clf_conf = self.classifier.should_click(patch)
            if not should:
                logger.info("Classifier REJECT at %s: %s (%.2f)", m.center, label, clf_conf)
                continue
            is_gem_color, color_info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            if not is_gem_color:
                logger.info("color REJECT at %s conf=%.3f: %s", m.center, m.confidence, color_info.get("reason",""))
                continue
            ok, zone_info = self._is_clickable_zone(frame, m)
            if not ok:
                if zone_info.startswith("edge"):
                    logger.info("gem_icon at EDGE %s conf=%.3f -- will recenter", m.center, m.confidence)
                    edge_gems.append(m)
                else:
                    logger.info("gem_icon zone REJECT at %s conf=%.3f: %s", m.center, m.confidence, zone_info)
                continue
            logger.debug("gem_icon OK at %s: color=%s clf=%s(%.2f)", m.center, color_info.get("reason",""), label, clf_conf)
            result.append(m)
        self._edge_gems = edge_gems
        return result

    # --- Step 2/3/4: Wander scan + click icon + verify gem type ---

    def _extract_icon_patch(self, frame, m: Match) -> np.ndarray:
        """Extract icon patch from frame for classifier input."""
        fh, fw = frame.shape[:2]
        x1 = max(0, m.x)
        y1 = max(0, m.y)
        x2 = min(fw, m.x + m.w)
        y2 = min(fh, m.y + m.h)
        return frame[y1:y2, x1:x2].copy()

    def _is_clickable_zone(self, frame, m: Match) -> tuple[bool, str]:
        """Check if icon is in a clickable area (not edge/fog/dark terrain)."""
        fh, fw = frame.shape[:2]
        cx, cy = m.center

        margin_x = int(fw * SAFE_ZONE_MARGIN)
        margin_y = int(fh * SAFE_ZONE_MARGIN)
        if cx < margin_x or cx > fw - margin_x or cy < margin_y or cy > fh - margin_y:
            return False, f"edge({cx},{cy})"

        pad = max(m.w, m.h) * 2
        y1 = max(0, cy - pad)
        y2 = min(fh, cy + pad)
        x1 = max(0, cx - pad)
        x2 = min(fw, cx + pad)
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty"

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        ir = max(m.w, m.h) // 2
        mask = np.ones(gray.shape, dtype=bool)
        ly, lx = cy - y1, cx - x1
        mask[max(0, ly - ir):min(gray.shape[0], ly + ir),
             max(0, lx - ir):min(gray.shape[1], lx + ir)] = False
        terrain = gray[mask]
        if terrain.size == 0:
            return False, "no_terrain"

        med = float(np.median(terrain))
        if med < DARK_TERRAIN_THRESH:
            return False, f"dark({med:.0f})"

        return True, f"ok({med:.0f})"

    def _is_fog(self, frame) -> bool:
        """True if the play area is outside the kingdom.

        Out-of-kingdom looks different depending on where and when you leave it
        -- gray cloud, blue sea, beige sand in afternoon light -- so colour
        cannot identify it. Being FEATURELESS can: no trees, rocks or resource
        nodes to raise the detail measure, or a single flat hue across the whole
        view. Real terrain fails both (see the measured ranges in config).

        The flow bails back to the city on a hit: a camera 139-265 km off the
        map will never find a node, and a bot that keeps panning out there does
        not look like a player.
        """
        fh, fw = frame.shape[:2]
        roi = frame[int(fh * 0.25):int(fh * 0.72), int(fw * 0.20):int(fw * 0.80)]
        if roi.size == 0:
            return False
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        hue_std = float(hsv[:, :, 0].std())

        if lap_var < FOG_LAP_VAR_MAX:
            logger.info("fog: featureless (lap=%.1f hue_std=%.2f)", lap_var, hue_std)
            return True
        if hue_std < FOG_HUE_STD_MAX:
            logger.info("fog: single flat hue (hue_std=%.2f lap=%.1f)", hue_std, lap_var)
            return True
        return False

    def _find_all_icons(self, frame) -> list[Match]:
        """Find all resource icons (gem_icon template) on frame, sorted by confidence desc."""
        matches = self.matcher.match_all(frame, "resources/gem_icon", overlap_thresh=0.3)
        gem_thr = self._gem_icon_threshold()
        result = []
        edge_gems = []
        for m in matches:
            if m.confidence < gem_thr:
                continue
            patch = self._extract_icon_patch(frame, m)
            should_click, label, clf_conf = self.classifier.should_click(patch)
            if not should_click:
                print(f"  [ -- ] Classifier reject at {m.center} conf={m.confidence:.3f}: {label} ({clf_conf:.2f})")
                continue
            is_gem_color, color_info = is_gem_icon_color(frame, m.x, m.y, m.w, m.h)
            if not is_gem_color:
                print(f"  [ -- ] Color reject at {m.center} conf={m.confidence:.3f}: {color_info.get('reason','')}")
                continue
            ok, zone_info = self._is_clickable_zone(frame, m)
            if not ok:
                if zone_info.startswith("edge"):
                    print(f"  [{INFO}] Edge gem at {m.center} conf={m.confidence:.3f} -- will recenter")
                    edge_gems.append(m)
                else:
                    print(f"  [ -- ] Zone reject icon at {m.center} conf={m.confidence:.3f}: {zone_info}")
                continue
            if label != "unknown":
                print(f"  [{INFO}] Classifier: {label} ({clf_conf:.2f}) at {m.center}")
            result.append(m)
        self._edge_gems = edge_gems
        noticed = [m for m in result if random.random() > 0.08]
        if len(noticed) < len(result):
            logger.debug("Missed %d icon(s) (simulated inattention)", len(result) - len(noticed))
        return sorted(noticed, key=lambda m: -m.confidence)

    def _has_march_line(self, frame, icon: Match) -> tuple[bool, str]:
        """Detect march lines converging on an icon (troops en-route).

        Multi-color detection:
        1. White/bright lines (V>200, S<50)
        2. Teal/cyan lines (H 75-105) -- player's own marches
        3. Green lines (H 50-84) -- gathering marches

        A valid march line must be long (>2x icon) and have an endpoint
        near the icon center.
        """
        fh, fw = frame.shape[:2]
        cx, cy = icon.center
        icon_r = max(icon.w, icon.h)

        pad = icon_r * 5
        y1 = max(cy - pad, 0)
        y2 = min(cy + pad, fh)
        x1 = max(cx - pad, 0)
        x2 = min(cx + pad, fw)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty"

        icon_lx = cx - x1
        icon_ly = cy - y1
        min_len = icon_r * 3
        near_r = icon_r * 2

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        white_mask = (
            (hsv[:, :, 2] > 200) & (hsv[:, :, 1] < 50)
        ).astype(np.uint8) * 255

        cyan_mask = (
            (hsv[:, :, 0] >= 75) & (hsv[:, :, 0] <= 105) &
            (hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 130)
        ).astype(np.uint8) * 255

        green_mask = (
            (hsv[:, :, 0] >= 50) & (hsv[:, :, 0] <= 74) &
            (hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 130)
        ).astype(np.uint8) * 255

        combined = cv2.bitwise_or(white_mask, cv2.bitwise_or(cyan_mask, green_mask))

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        closed = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel, iterations=1)

        lines = cv2.HoughLinesP(closed, 1, np.pi / 180,
                                threshold=35, minLineLength=min_len, maxLineGap=15)
        if lines is None:
            return False, "no lines"

        for line in lines:
            lx1, ly1, lx2, ly2 = line[0]
            length = np.sqrt((lx2 - lx1) ** 2 + (ly2 - ly1) ** 2)
            if length < min_len:
                continue

            angle = abs(np.degrees(np.arctan2(ly2 - ly1, lx2 - lx1)))
            if angle < 15 or angle > 165 or (75 < angle < 105):
                continue

            d1 = np.sqrt((lx1 - icon_lx) ** 2 + (ly1 - icon_ly) ** 2)
            d2 = np.sqrt((lx2 - icon_lx) ** 2 + (ly2 - icon_ly) ** 2)
            if min(d1, d2) > near_r:
                continue

            # Identify which color matched for logging
            ep_x = lx1 if d1 < d2 else lx2
            ep_y = ly1 if d1 < d2 else ly2
            ep_x = max(0, min(ep_x, roi.shape[1] - 1))
            ep_y = max(0, min(ep_y, roi.shape[0] - 1))
            h_val = hsv[ep_y, ep_x, 0]
            s_val = hsv[ep_y, ep_x, 1]
            color_tag = "white" if s_val < 50 else ("cyan" if h_val >= 75 else "green")

            info = f"{color_tag} len={length:.0f} endpt={min(d1,d2):.0f} angle={angle:.0f}"
            return True, info

        return False, "no march lines"

    def _check_icon_occupied(self, frame, icon: Match) -> tuple[bool, str]:
        """Check for march lines converging on the icon at icon-zoom level."""
        has_line, line_info = self._has_march_line(frame, icon)
        if has_line:
            return True, f"march_line({line_info})"
        return False, "free"

    def _is_mine_occupied(self, frame, mine_match: Match) -> tuple[bool, str]:
        """Check whether the mine already has a gathering "pickaxe" icon on it.

        Primary: template-match the colored pickaxe icon (green/red/blue) in a
        TIGHT region around THIS mine, so a different mine's icon farther away is
        not picked up. Fallback (if templates absent): compact bright color blob.
        """
        mine_cx, mine_cy = mine_match.center
        fh, fw = frame.shape[:2]
        mh = mine_match.h

        # --- Primary: pickaxe icon templates, restricted to around this mine ---
        tx1 = max(0, mine_cx - mh)
        tx2 = min(fw, mine_cx + mh)
        ty1 = max(0, mine_cy - int(mh * 1.8))
        ty2 = min(fh, mine_cy + int(mh * 0.4))
        tcrop = frame[ty1:ty2, tx1:tx2]
        if tcrop.size:
            for tpl in OCCUPIED_TEMPLATES:
                m = self.matcher.match_single(tcrop, tpl)
                if m and m.confidence >= OCCUPIED_THRESHOLD:
                    return True, f"pickaxe {tpl.split('/')[-1]} conf={m.confidence:.2f}"

        # --- Fallback: compact bright color blob above the mine ---
        y1 = max(0, mine_cy - mh * 3)
        y2 = max(0, mine_cy - mh // 3)
        x1 = max(0, mine_cx - mh)
        x2 = min(fw, mine_cx + mh)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty ROI"

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        sat_bright = (hsv[:, :, 1] > 150) & (hsv[:, :, 2] > 150)

        green_mask = sat_bright & (hsv[:, :, 0] >= 35) & (hsv[:, :, 0] <= 85)
        red_mask = sat_bright & ((hsv[:, :, 0] < 10) | (hsv[:, :, 0] > 170))
        blue_mask = sat_bright & (hsv[:, :, 0] >= 90) & (hsv[:, :, 0] <= 135)

        combined = (green_mask | red_mask | blue_mask).astype(np.uint8) * 255
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        min_area = 15 * 15
        max_area = 45 * 45
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < min_area or area > max_area:
                continue
            x, y, w, h = cv2.boundingRect(cnt)
            if max(w, h) > 48:
                continue
            aspect = max(w, h) / max(min(w, h), 1)
            if aspect > 1.8:
                continue
            fill = area / max(w * h, 1)
            if fill < 0.55:
                continue
            cx_blob = x + w // 2
            cy_blob = y + h // 2
            h_val = hsv[cy_blob, cx_blob, 0]
            color = "green" if 35 <= h_val <= 85 else ("red" if h_val < 10 or h_val > 170 else "blue")
            info = f"icon {color} area={area} size={w}x{h}"
            return True, info

        return False, "no icon"

    def _has_incoming_march(self, frame, mine_match: Match) -> tuple[bool, str]:
        """Detect march lines pointing toward the mine using HoughLinesP.

        Color-percentage approach fails because map terrain (grass, water)
        shares hue ranges with march lines. Instead we:
        1. Build color masks for march-line colors (white/cyan/green)
        2. Use HoughLinesP to find actual line segments
        3. Only flag lines that have an endpoint near the mine center
        """
        mine_cx, mine_cy = mine_match.center
        fh, fw = frame.shape[:2]
        mine_r = max(mine_match.w, mine_match.h)
        pad = mine_r * 4

        y1 = max(0, mine_cy - pad)
        y2 = min(fh, mine_cy + pad)
        x1 = max(0, mine_cx - pad)
        x2 = min(fw, mine_cx + pad)

        roi = frame[y1:y2, x1:x2]
        if roi.size == 0:
            return False, "empty"

        mine_lx = mine_cx - x1
        mine_ly = mine_cy - y1
        # The march line is DASHED, so segments are short -- use a shorter min
        # length (was 2*r, which a dashed line never reaches as one segment).
        min_len = mine_r
        near_r = mine_r * 2

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        white_mask = (
            (hsv[:, :, 2] > 200) & (hsv[:, :, 1] < 50)
        ).astype(np.uint8) * 255

        cyan_mask = (
            (hsv[:, :, 0] >= 75) & (hsv[:, :, 0] <= 115) &
            (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 150)
        ).astype(np.uint8) * 255

        green_mask = (
            (hsv[:, :, 0] >= 50) & (hsv[:, :, 0] <= 74) &
            (hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 150)
        ).astype(np.uint8) * 255

        combined = cv2.bitwise_or(white_mask, cv2.bitwise_or(cyan_mask, green_mask))

        # Dilate to bridge the gaps between dashes so HoughLinesP sees a line.
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        cleaned = cv2.dilate(combined, kernel, iterations=1)

        lines = cv2.HoughLinesP(cleaned, 1, np.pi / 180,
                                threshold=30, minLineLength=int(min_len), maxLineGap=40)
        if lines is None:
            return False, "no lines"

        for line in lines:
            lx1, ly1, lx2, ly2 = line[0]
            length = np.sqrt((lx2 - lx1) ** 2 + (ly2 - ly1) ** 2)
            if length < min_len:
                continue

            d1 = np.sqrt((lx1 - mine_lx) ** 2 + (ly1 - mine_ly) ** 2)
            d2 = np.sqrt((lx2 - mine_lx) ** 2 + (ly2 - mine_ly) ** 2)
            if min(d1, d2) > near_r:
                continue

            ep_x = lx1 if d1 < d2 else lx2
            ep_y = ly1 if d1 < d2 else ly2
            ep_x = max(0, min(ep_x, roi.shape[1] - 1))
            ep_y = max(0, min(ep_y, roi.shape[0] - 1))
            h_val = hsv[ep_y, ep_x, 0]
            s_val = hsv[ep_y, ep_x, 1]
            color_tag = "white" if s_val < 50 else ("cyan" if h_val >= 75 else "green")

            info = f"{color_tag} len={length:.0f} endpt={min(d1,d2):.0f}"
            return True, info

        return False, "no march lines"

    # --- Step: Click march ---

    def _find_march_btn(self, frame) -> Match | None:
        """Find march button via template matching."""
        for tpl in MARCH_TEMPLATES:
            m = self._find_on_frame(frame, tpl, threshold=0.65)
            if m:
                return m
        return None

    def _is_troop_panel_open(self, frame) -> bool:
        """Check if troop selection panel is still visible."""
        m = self._find_new_troop_btn(frame, threshold=0.85)
        return m is not None
