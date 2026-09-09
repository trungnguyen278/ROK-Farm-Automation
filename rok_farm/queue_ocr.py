"""March queue OCR -- reads the "x/5" counter in the top-right corner.

RapidOCR is preferred; pytesseract is the fallback. With neither installed the
runner falls back to its internal completed-march counter.
"""

from __future__ import annotations

import random
import re
import time

import json

import cv2

from rok_farm import PROJECT_ROOT
from rok_farm.logging_setup import INFO, logger
from rok_farm.screenshots import save_screenshot

try:
    from rapidocr_onnxruntime import RapidOCR
    _ocr_engine = RapidOCR()
    _OCR_BACKEND = "rapidocr"
except ImportError:
    _ocr_engine = None
    try:
        import pytesseract
        _OCR_BACKEND = "pytesseract"
    except ImportError:
        _OCR_BACKEND = None


class QueueMixin:
    """March queue reading. Mixed into GemFarmRunner."""

    def _detect_march_queue(self, retries: int = 3) -> tuple[int, int] | None:
        """Read march queue (e.g. '1/5') via OCR. Returns (used, total) or None.

        A single OCR pass misses often (frame timing, faint text), which made the
        turn-1 'is the queue already full' check unreliable. Retry across a few
        fresh frames; on total failure save the ROI crop so the region can be
        verified against the actual queue indicator.
        """
        if _OCR_BACKEND is None:
            return None

        last_roi = None
        last_text = ""
        for attempt in range(max(1, retries)):
            if attempt > 0:
                time.sleep(random.uniform(0.25, 0.45))
            frame = self._grab()
            if frame is None:
                continue
            # Queue "x/5" counter sits at client ~(0.97, 0.15); box measured at
            # x[0.948,0.997] y[0.137,0.168]. Hug it (the old y 0.15-0.26 started
            # below the digits and ran down into terrain -> intermittent misses).
            fh, fw = frame.shape[:2]
            x1 = int(fw * 0.92)
            y1 = int(fh * 0.10)
            x2 = fw
            y2 = int(fh * 0.21)
            roi = frame[y1:y2, x1:x2]
            last_roi = roi

            try:
                texts = []
                if _OCR_BACKEND == "rapidocr":
                    result, _ = _ocr_engine(roi)
                    if result:
                        sorted_r = sorted(result, key=lambda r: r[0][0][0])
                        texts = [''.join(r[1] for r in sorted_r)]
                else:
                    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                    _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)
                    binary = cv2.resize(binary, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
                    raw = pytesseract.image_to_string(
                        binary, config='--psm 7 -c tessedit_char_whitelist=0123456789/')
                    texts = [raw.strip()]

                for text in texts:
                    last_text = text
                    logger.debug("Queue OCR (try %d/%d): '%s'", attempt + 1, retries, text)
                    m = re.search(r'(\d)\s*/\s*(\d)', text)
                    if m:
                        used, total = int(m.group(1)), int(m.group(2))
                        if 0 <= used <= total <= 9:
                            return used, total
            except Exception as e:
                logger.debug("Queue OCR error: %s", e)

        # All retries failed -- save the ROI so the crop position can be verified.
        if last_roi is not None and last_roi.size > 0:
            path = save_screenshot(last_roi, "queue_roi_miss")
            logger.debug("Queue OCR failed after %d tries (last text='%s'); saved %s",
                         retries, last_text, path)
        return None


# --- Map position (the "#3560 X:7 Y:86" readout, top-left of the HUD) ---
# Crop chosen by measurement, not by eye: three candidates were scored against
# 60 saved frames and this one read 60/60 while being the smallest, so it is the
# cheapest to OCR inside the scan loop.
POS_ROI = (0.02, 0.000, 0.22, 0.035)
# Anchored on the "#" and tolerant of a letter prefix: the KvK map prints
# "#S11465 X:227 Y:155" while the home kingdom prints "#3560 X:7 Y:86", and
# keeping the letter is what stops two different maps sharing one book.
_POS_RE = re.compile(r"#\s*([A-Za-z]{0,2}\d{3,6})\D{0,3}X[:\s]*(\d{1,4})"
                     r"\D{0,3}Y[:\s]*(\d{1,4})", re.IGNORECASE)


class MapPositionMixin:
    """Reads where on the world map the camera is. Mixed into GemFarmRunner."""

    def _read_map_position(self, frame=None) -> tuple[str, int, int] | None:
        """Return (map_id, x, y) or None.

        map_id is what separates the home kingdom from a KvK map, so the learned
        map books never mix -- no configuration, it just reads what the HUD says.
        """
        if _OCR_BACKEND != "rapidocr" or _ocr_engine is None:
            return None
        if frame is None:
            frame = self._grab()
        if frame is None:
            return None
        fh, fw = frame.shape[:2]
        x1, y1, x2, y2 = POS_ROI
        roi = frame[int(fh * y1):int(fh * y2), int(fw * x1):int(fw * x2)]
        if roi.size == 0:
            return None
        try:
            result, _ = _ocr_engine(roi)
            if not result:
                return None
            text = "".join(r[1] for r in sorted(result, key=lambda r: r[0][0][0]))
        except Exception as e:
            logger.debug("Map position OCR error: %s", e)
            return None
        m = _POS_RE.search(text)
        if not m:
            logger.debug("Map position unparsed: %r", text[:40])
            return None
        return m.group(1), int(m.group(2)), int(m.group(3))


# --- Deploy panel: march time and gathering speed -------------------------
# Read from the frame captured BETWEEN the "Quan moi" and "Hanh quan" clicks,
# and parsed AFTER the march has already been sent -- the deploy chain is
# muscle-memory paced and must not wait on OCR (see
# feedback_speed_matches_familiarity). Capture cheap, compute later.
_T_RE = re.compile(r"(\d{1,2}):([0-5]\d):([0-5]\d)")
# Two different buffs are shown and one of them is decimal
# ("+187%" and "+49.5%"); the old integer-only pattern silently
# dropped the second, so half the information was never captured.
_PCT_RE = re.compile(r"\+\s?(\d{1,3}(?:[.,]\d{1,2})?)\s?%")
_TROOP_RE = re.compile(r"(\d[\d.,]{1,9})\s*/\s*(\d[\d.,]{2,12})")
# Thousands separators are dots in this locale ("30.000"), so a bare \d{1,4}
# silently truncated 30.000 to 30. Capture the separated form too.
_LOAD_RE = re.compile(r"tr[oọ]ng\s*t[aả]i\D{0,4}(\d[\d.,]{0,9})", re.IGNORECASE)


class DeployPanelMixin:
    """Reads the numbers the deploy panel shows. Mixed into GemFarmRunner."""

    # Generous crop of the panel area rather than tight boxes per field: the
    # panel is centred and its rows shift with commander art, so hunting for
    # patterns in one OCR pass is steadier than guessing a rectangle per value.
    PANEL_ROI = (0.20, 0.13, 0.82, 0.86)

    def _parse_deploy_panel(self, frame) -> dict | None:
        """march seconds, gather-speed bonuses, troop count/capacity, load."""
        if _OCR_BACKEND != "rapidocr" or _ocr_engine is None or frame is None:
            return None
        fh, fw = frame.shape[:2]
        x1, y1, x2, y2 = self.PANEL_ROI
        roi = frame[int(fh * y1):int(fh * y2), int(fw * x1):int(fw * x2)]
        if roi.size == 0:
            return None
        try:
            result, _ = _ocr_engine(roi)
        except Exception as e:
            logger.debug("Deploy panel OCR error: %s", e)
            return None
        if not result:
            return None
        text = " ".join(r[1] for r in result)

        out: dict = {"raw": text[:200]}
        m = _T_RE.search(text)
        if m:
            h, mi, sec = (int(g) for g in m.groups())
            out["march_seconds"] = h * 3600 + mi * 60 + sec
        pcts = [float(v.replace(",", ".")) for v in _PCT_RE.findall(text)]
        if pcts:
            out["bonus_pct"] = pcts
        m = _TROOP_RE.search(text)
        if m:
            def _n(v):
                return int(v.replace(".", "").replace(",", ""))
            try:
                out["troops"], out["capacity"] = _n(m.group(1)), _n(m.group(2))
            except ValueError:
                pass
        m = _LOAD_RE.search(text)
        if m:
            try:
                out["load"] = int(m.group(1).replace(".", "").replace(",", ""))
            except ValueError:
                pass
        return out or None

    def _log_deploy_panel(self, tag: str):
        """Parse the stored panel frame and log it. Runs AFTER the march click.

        Purely observational for now -- it builds the dataset needed to predict
        when a march will come home, which is what a continuous-deploy mode
        would need (see project_continuous_march_idea). Nothing acts on it yet.
        """
        frame = getattr(self, "_deploy_frame", None)
        if frame is None:
            return
        info = self._parse_deploy_panel(frame)
        if not info:
            logger.info("Deploy panel: nothing parsed")
            return
        march = info.get("march_seconds")
        logger.info("Deploy panel: march=%ss bonuses=%s troops=%s/%s load=%s",
                    march, info.get("bonus_pct"), info.get("troops"),
                    info.get("capacity"), info.get("load"))
        if march:
            est = self.predict_gather_seconds(info)
            extra = f", gather bonus {info['bonus_pct']}" if info.get("bonus_pct") else ""
            if est:
                total = 2 * march + est
                extra += (f" -> est. gather {est / 60:.0f}m, "
                          f"home in ~{total / 60:.0f}m")
            print(f"  [{INFO}] March time {march // 60}m{march % 60:02d}s{extra}")
        self.note_march_sent(info)
        # Keep the frame so the parse can be checked against what was on screen.
        save_screenshot(frame, f"{tag}_deploy_panel")


# --- Gather-time model -----------------------------------------------------
# Total round trip = travel out + gather + travel back. Travel is read straight
# off the panel; gather is NOT derivable from it, because the base gathering
# rate and the node's remaining amount are not shown. So it is MEASURED instead
# of assumed: record what the panel said at deploy, wait for the return toast,
# and the difference is the gather time.
#
# Attribution is the catch -- up to five marches are out at once and the toast
# does not say which one came home. So samples are only taken when exactly ONE
# march is outstanding. Slower to collect, but unambiguous, which matters more:
# a model fitted on mis-attributed pairs would be confidently wrong.
GATHER_DATA = PROJECT_ROOT / "data" / "gather_times.json"

# Gems gathered per hour with NO gathering bonus. Not in any guide the web
# turned up -- supplied by the operator from play experience. The panel's LEFT
# percentage is the gathering-speed buff; the RIGHT one is bonus max load and is
# already baked into the "Trong tai" number, so it must not be applied again.
GEM_BASE_PER_HOUR = 20.0


class GatherModelMixin:
    """Learns how long a mine actually takes. Mixed into GemFarmRunner."""

    def note_march_sent(self, info: dict | None):
        """Remember a deploy so its return can be timed."""
        if not info or not info.get("march_seconds"):
            return
        self._open_marches = getattr(self, "_open_marches", [])
        est = self.predict_gather_seconds(info)
        self._open_marches.append({
            "t_sent": time.time(),
            "est_home": (time.time() + 2 * info["march_seconds"] + est)
                        if est else None,
            "march_s": info["march_seconds"],
            "bonus": (info.get("bonus_pct") or [None])[0],
            "bonus_all": info.get("bonus_pct"),
            "load": info.get("load"),
            "troops": info.get("troops"),
        })
        logger.info("Gather model: %d march(es) outstanding",
                    len(self._open_marches))

    def note_troops_returned(self, n: int = 1):
        """A return toast fired. Close out a march if attribution is certain."""
        open_m = getattr(self, "_open_marches", [])
        if not open_m:
            return
        if len(open_m) != 1 or n != 1:
            # Ambiguous: several could have come home. Drop the oldest without
            # recording rather than guess which one the toast meant.
            open_m.pop(0)
            logger.debug("Gather model: ambiguous return, sample discarded")
            return
        m = open_m.pop(0)
        total = time.time() - m["t_sent"]
        gather = total - 2 * m["march_s"]
        if gather <= 0:
            logger.debug("Gather model: implausible gather %.0fs, discarded", gather)
            return
        # Deliberately NOT normalised by a buff. The panel shows two different
        # percentages (e.g. +187% and +49.5%) and nothing on screen says which
        # one is gathering speed -- a web search for the base-rate formula turned
        # up strategy guides only, no usable constant. Dividing by the wrong one
        # would bake a wrong model in permanently, so store the raw observation
        # plus BOTH percentages and let a fit decide later which correlates.
        rate = m["load"] / gather if m.get("load") else None
        print(f"  [{INFO}] Mine took {gather / 60:.1f} min to gather "
              f"(round trip {total / 60:.1f} min, travel {2 * m['march_s'] / 60:.1f} min)")
        logger.info("Gather sample: gather=%.0fs total=%.0fs march=%ss "
                    "bonus=%s load=%s load/s=%s",
                    gather, total, m["march_s"], m["bonus"], m["load"],
                    f"{rate:.2f}" if rate else None)
        self._append_gather_sample({
            "gather_s": round(gather),
            "total_s": round(total),
            "march_s": m["march_s"],
            "bonus_pct": m["bonus"],
            "bonus_all": m.get("bonus_all"),
            "load": m["load"],
            "troops": m["troops"],
            "load_per_sec": round(rate, 5) if rate else None,
        })

    @staticmethod
    def _append_gather_sample(sample: dict):
        try:
            GATHER_DATA.parent.mkdir(parents=True, exist_ok=True)
            data = []
            if GATHER_DATA.exists():
                data = json.loads(GATHER_DATA.read_text(encoding="utf-8"))
            data.append(sample)
            GATHER_DATA.write_text(json.dumps(data, indent=1), encoding="utf-8")
        except Exception as e:
            logger.warning("Could not store gather sample: %s", e)

    def predict_gather_seconds(self, info: dict | None) -> float | None:
        """How long this mine will take to gather, in seconds.

        Closed form now that the base rate is known. The deploy panel's LEFT
        percentage is the gathering-speed buff; the right one is bonus max load
        and is ALREADY included in the "Trong tai" figure, so applying it here
        too would double-count it.
        """
        load = info.get("load") if info else None
        bonuses = (info or {}).get("bonus_pct") or []
        if not load or not bonuses:
            return None
        speed_pct = bonuses[0]              # left-most = gathering speed
        per_hour = GEM_BASE_PER_HOUR * (1.0 + speed_pct / 100.0)
        if per_hour <= 0:
            return None
        return load / per_hour * 3600.0


    def seconds_until_first_return(self) -> float | None:
        """How long until the earliest outstanding march gets home, or None.

        None means at least one march has no estimate, so the caller must not
        plan around a number it does not have.
        """
        open_m = getattr(self, "_open_marches", [])
        if not open_m:
            return None
        homes = [m.get("est_home") for m in open_m]
        if not homes or any(h is None for h in homes):
            return None
        return max(0.0, min(homes) - time.time())

    def sync_open_marches(self, used: int):
        """Trim the outstanding-march list to what the queue badge actually says.

        The list only ever shrank inside the toast handler, and the planned-wait
        path skips that entirely -- so entries for marches that came home hours
        ago piled up, their est_home sat in the past, and
        seconds_until_first_return() answered 0 forever. The wait logic then
        degenerated to "stay put for 0 minutes" every cycle, silently.

        The badge is the authority on HOW MANY are out, so reconcile against it
        and drop the ones due home earliest -- those are the ones that left.
        """
        open_m = getattr(self, "_open_marches", [])
        if used < 0 or len(open_m) <= used:
            return
        open_m.sort(key=lambda m: m.get("est_home") or 0)
        dropped = len(open_m) - used
        self._open_marches = open_m[dropped:]
        logger.info("Queue says %d out; dropped %d stale march record(s)",
                    used, dropped)
