"""Measure what a drag buys on the world map -- a survey, not a farm step.

The operator's spec, 2026-09-23:
  * map movement against drag distance, counting only drags whose pointer
    stays inside the game window;
  * how much ground one window holds: drag the window's full width and full
    height, each as TWO half drags so the pointer never works at the window's
    edge (where a press can miss or land on something), without the title bar;
  * separately from the farm flow, where other camera moves spoil the pairs.

The farm had been logging drag/tile pairs from inside its scan. The first fit
of them, eight pairs, came out at a median error of 21 tiles on moves of 47:
node clicks, recentres, retreats and city trips all moved the camera without
adding a pixel. Here nothing moves the camera but the drag being measured, and
every pair is read before and after that one drag.

Two drag styles:
  hold  slow, and held still before the release. A release while the pointer
        is still moving may carry the map on; a held one cannot, so this is
        the pure geometry -- tiles per pixel -- and the view footprint.
  farm  the scan's own drag: its swipe sizes, speed 3.6-7x, released moving.
        Its gain over the hold fit is what the scan really covers per pixel.

Horizontal legs run at three heights. Were the map drawn in perspective, a
drag near the top would cover more ground than the same drag near the bottom
and a frame would hold a trapezoid; the three rows say whether it does.

Every group returns to where it started, so the camera ends where it began.
Needs the farm stopped -- it holds the board.

    .venv\\Scripts\\python tools\\dev\\pan_survey.py            # full survey
    .venv\\Scripts\\python tools\\dev\\pan_survey.py --dry-run  # OCR check only
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from capture.screen_info import get_cursor_pos  # noqa: E402
from rok_farm.config import ZOOM_OUT_QUIET_DIFF  # noqa: E402

OUT = ROOT / "data" / "pan_survey.json"

# Never let the pointer work closer than this to the client's border. The
# half-window legs keep a quarter window in hand anyway; this is the check
# that refuses a leg if the geometry ever says otherwise.
EDGE_PX = 60

# Heights (fraction of the client) the horizontal legs run at. Spread wide
# because the first run found perspective: 1.55 tiles/100px at row 0.34 and
# 1.32 at 0.66, so the ground under a row depends on the row.
H_ROWS = (0.25, 0.50, 0.75)

# Vertical spans (rows, press -> release) besides the full-height pair: the
# same perspective makes the upper half of the screen hold more ground than
# the lower, and only separate spans can tell the two halves apart.
V_SPANS = ((0.50, 0.18), (0.82, 0.50))

# One drag cannot move the camera further than this. The position OCR has a
# known Y misread (623 read as 5544) that two agreeing reads do not catch,
# because both reads misread the same glyphs; the first run had two.
OUTLIER_TILES = 60

# A release this far from the aim means the drag did not do what it was
# asked, whatever the tiles say. The closed-loop drag lands within a few px.
RELEASE_ERR_MAX = 40


def inside(win, x, y, margin=EDGE_PX) -> bool:
    return (win["left"] + margin <= x <= win["left"] + win["width"] - margin
            and win["top"] + margin <= y <= win["top"] + win["height"] - margin)


def wait_still(r, cap=4.0) -> float:
    """Until two looks in a row show the map not moving, capped."""
    import cv2
    t0 = time.monotonic()
    prev, quiet = None, 0
    while time.monotonic() - t0 < cap:
        frame = r._grab()
        cur = r._settle_patch(frame) if frame is not None else None
        if cur is not None:
            if prev is not None:
                if float(np.mean(cv2.absdiff(prev, cur))) < ZOOM_OUT_QUIET_DIFF:
                    quiet += 1
                    if quiet >= 2:
                        break
                else:
                    quiet = 0
            prev = cur
        time.sleep(random.uniform(0.07, 0.11))
    return time.monotonic() - t0


def read_pos(r, tries=6):
    """(map_id, x, y) once two fresh reads agree, else None.

    Two agreeing reads because the position OCR has known single-read
    misreads (a Y of 182 read as 1822); a leg built on one would poison the
    fit. Fresh frames: the capture hands back alternating buffers.
    """
    last = None
    for _ in range(tries):
        time.sleep(random.uniform(0.18, 0.3))
        pos = r._read_map_position(r._grab())
        if pos is not None and pos == last:
            return pos
        last = pos
    return None


def group_legs(kind, frac, win, total_px, style, rng):
    """Four legs: the full length out as two halves, then back as two.

    The two halves sum to exactly total_px -- the window's width or height,
    as the operator asked -- but are not identical, and each point wobbles a
    little off the axis. A fixed pair of identical axis-aligned drags forty
    times over is a pattern; this is the same measurement without one.
    """
    cx = win["left"] + win["width"] // 2
    cy = win["top"] + win["height"] // 2
    a = total_px / 2 + rng.uniform(-0.03, 0.03) * total_px
    halves = [a, total_px - a]
    out_sign = rng.choice((-1, 1))
    legs = []
    for sign in (out_sign, -out_sign):
        for h in halves:
            wob = rng.uniform(-0.012, 0.012)
            if kind == "h":
                y = win["top"] + int(win["height"] * frac)
                sx, ex = cx - sign * h / 2, cx + sign * h / 2
                sy = y + int(wob * win["height"])
                ey = y - int(wob * win["height"])
            else:
                x = win["left"] + int(win["width"] * frac)
                sy, ey = cy - sign * h / 2, cy + sign * h / 2
                sx = x + int(wob * win["width"])
                ex = x - int(wob * win["width"])
            legs.append({"kind": kind, "row": frac, "style": style,
                         "sx": int(sx), "sy": int(sy),
                         "ex": int(ex), "ey": int(ey)})
    return legs


def span_legs(win, r1, r2, style, rng):
    """One vertical drag from row r1 to row r2 and one back."""
    x = win["left"] + win["width"] // 2
    legs = []
    for a, b in ((r1, r2), (r2, r1)):
        wob = int(rng.uniform(-0.012, 0.012) * win["width"])
        legs.append({"kind": "v", "row": round((a + b) / 2, 3), "style": style,
                     "sx": x + wob, "sy": win["top"] + int(win["height"] * a),
                     "ex": x - wob, "ey": win["top"] + int(win["height"] * b)})
    return legs


def farm_legs(win, rng):
    """Legs sized like the scan's own swipes, both axes, out and back."""
    margin = 80
    legs = []
    for kind in ("h", "v"):
        half = (win["width"] // 2 - margin) if kind == "h" else (win["height"] // 2 - margin)
        for sign in (1, -1):
            for _ in range(2):
                # flow_steps: total_pct 0.50-0.75 of the half reach over 1-2
                # swipes, so a single swipe spans 0.25-0.75 of it, and a
                # swipe runs from +per to -per around the centre.
                per = half * rng.uniform(0.25, 0.75)
                cx = win["left"] + win["width"] // 2
                cy = win["top"] + win["height"] // 2
                if kind == "h":
                    sx, ex, sy, ey = cx + sign * per, cx - sign * per, cy, cy
                else:
                    sx, ex, sy, ey = cx, cx, cy + sign * per, cy - sign * per
                legs.append({"kind": kind, "row": 0.5, "style": "farm",
                             "sx": int(sx), "sy": int(sy),
                             "ex": int(ex), "ey": int(ey)})
    return legs


def run_leg(r, leg, before):
    win = r.win
    if not (inside(win, leg["sx"], leg["sy"]) and inside(win, leg["ex"], leg["ey"])):
        leg["ok"] = False
        leg["why"] = "a point is outside the window margin"
        return before
    r._moveto(leg["sx"], leg["sy"])
    time.sleep(random.uniform(0.12, 0.3))
    c0 = get_cursor_pos()
    if leg["style"] == "hold":
        r._human_drag(c0[0], c0[1], leg["ex"], leg["ey"],
                      speed_factor=random.uniform(1.0, 1.4),
                      hold_ms=random.randint(320, 480))
    else:
        r._human_drag(c0[0], c0[1], leg["ex"], leg["ey"],
                      speed_factor=random.uniform(3.6, 7.0), easing="in")
    c1 = get_cursor_pos()
    leg["press"] = list(c0)
    leg["release"] = list(c1)
    leg["dpx"] = c1[0] - c0[0]
    leg["dpy"] = c1[1] - c0[1]
    leg["release_err_px"] = int(max(abs(c1[0] - leg["ex"]), abs(c1[1] - leg["ey"])))
    # Rows the pointer actually pressed and released on: under perspective
    # the ground a drag covers depends on WHERE on screen it ran.
    leg["press_row"] = round((c0[1] - win["top"]) / win["height"], 4)
    leg["release_row"] = round((c1[1] - win["top"]) / win["height"], 4)
    # The operator's condition: only drags that stayed in the window count.
    leg["in_window"] = inside(win, *c0, margin=0) and inside(win, *c1, margin=0)
    leg["settle_s"] = round(wait_still(r), 3)
    after = read_pos(r)
    leg["before"] = list(before) if before else None
    leg["after"] = list(after) if after else None
    if not before or not after:
        leg["ok"] = False
        leg["why"] = "position unreadable"
    elif after[0] != before[0]:
        leg["ok"] = False
        leg["why"] = f"map id changed {before[0]} -> {after[0]}"
    elif not leg["in_window"]:
        leg["ok"] = False
        leg["why"] = "pointer left the window"
    elif leg["release_err_px"] > RELEASE_ERR_MAX:
        leg["ok"] = False
        leg["why"] = f"released {leg['release_err_px']}px from the aim"
    elif (abs(after[1] - before[1]) > OUTLIER_TILES
          or abs(after[2] - before[2]) > OUTLIER_TILES):
        leg["ok"] = False
        leg["why"] = (f"impossible jump {after[1] - before[1]:+d},"
                      f"{after[2] - before[2]:+d} -- an OCR misread")
        # Do not chain the next leg from a misread either.
        after = None
    else:
        leg["ok"] = True
        leg["dX"] = after[1] - before[1]
        leg["dY"] = after[2] - before[2]
    tag = (f"{leg['style']:4s} {leg['kind']}@{leg['row']:.2f} "
           f"drag {leg['dpx']:+5d},{leg['dpy']:+5d}px")
    if leg["ok"]:
        print(f"  {tag} -> {leg['dX']:+4d},{leg['dY']:+4d} tiles "
              f"(settle {leg['settle_s']:.2f}s)")
    else:
        print(f"  {tag} -> DISCARDED: {leg['why']}")
    time.sleep(random.uniform(0.4, 1.3))
    # After a misread the chain restarts from a fresh reading, never from the
    # bad one and never from a stale one.
    return after or read_pos(r)


def roundtrip_check(r, rng) -> dict:
    """Does the world map come back on the city after a trip to the city?

    The homing code assumes it does -- it learns the city from the first
    reading after a trip. A comment from 2026-08-18 says the opposite (a fog
    bail at X:0, a city trip, and the next mine opened at X:1), and on
    2026-09-22/23 the "city" was learned as 448:621, 532:625 and 498:664 while
    a fresh launch opened the map at 575,615. So: move a window away, go to
    the city and back, and read.
    """
    win = r.win
    start = read_pos(r)
    pos = start
    for leg in group_legs("h", 0.5, win, win["width"], "hold", rng)[:2]:
        pos = run_leg(r, leg, pos)
    away = read_pos(r)
    r._toggle_view("survey: to the city")
    time.sleep(rng.uniform(2.5, 4.0))
    r._toggle_view("survey: back to the world map")
    r._wait_until_world_map(timeout=5.0)
    wait_still(r)
    back = read_pos(r)
    # The map opens close in when entered from the city. Leave it at icon
    # zoom for whatever runs next, the way step 1 does after a city trip.
    r._scroll_at_center(-1, r._zoom_scrolls())
    r._wait_zoom_settled()
    out = {"start": start, "away": away, "back": back,
           "gauge_after": r.read_zoom_gauge()}

    def near(a, b, tol=4):
        return (a is not None and b is not None and a[0] == b[0]
                and abs(a[1] - b[1]) <= tol and abs(a[2] - b[2]) <= tol)

    if near(back, away):
        out["verdict"] = "remembers the camera"
    elif near(back, start):
        out["verdict"] = "recentres on the start (the city, if it started there)"
    else:
        out["verdict"] = "neither -- see the numbers"
    print(f"\n== city round trip ==\n  start {start}, a window away {away}, "
          f"after city and back {back}: {out['verdict']}")
    return out


def _line(xs, ys):
    """Least-squares a + b*x, returned as (a, b)."""
    A = np.vstack([np.ones(len(xs)), np.asarray(xs, float)]).T
    (a, b), *_ = np.linalg.lstsq(A, np.asarray(ys, float), rcond=None)
    return float(a), float(b)


def analyse(legs, win):
    """Fit the per-row scales and turn them into what one window holds.

    The game pans by keeping the ground under the pointer under the pointer,
    and the camera is tilted, so the ground per pixel depends on the row:
        kx(r) = ax + bx * (0.5 - r)   tiles per px, horizontal, at row r
        ky(r) = ay + by * (0.5 - r)   tiles per px, vertical, around row r
    with r the fraction down the client. A horizontal drag at row r moves
    the camera -kx(r) * dpx in X; a vertical one moves it by the ground
    between its press and release rows in Y.
    """
    W, H = win["width"], win["height"]
    ok = [l for l in legs if l.get("ok")]
    hold = [l for l in ok if l["style"] == "hold"]
    farm = [l for l in ok if l["style"] == "farm"]
    out = {"legs_ok": len(ok), "legs_total": len(legs), "client": [W, H]}

    hl = [l for l in hold if l["kind"] == "h" and abs(l["dpx"]) > 200]
    vl = [l for l in hold if l["kind"] == "v" and abs(l["dpy"]) > 150]
    if len(hl) < 6 or len(vl) < 4:
        print(f"\n\n[FAIL] {len(hl)} horizontal and {len(vl)} vertical usable hold "
              f"legs -- not enough to fit")
        return out

    # Axis leakage: does a horizontal drag move Y at all, and vice versa?
    out["h_leak_dY_median"] = float(np.median([abs(l["dY"]) for l in hl]))
    out["v_leak_dX_median"] = float(np.median([abs(l["dX"]) for l in vl]))

    hr = [(l["press_row"] + l["release_row"]) / 2 for l in hl]
    kx = [l["dX"] / -l["dpx"] for l in hl]
    ax, bx = _line([0.5 - r for r in hr], kx)
    vr = [(l["press_row"] + l["release_row"]) / 2 for l in vl]
    ky = [l["dY"] / l["dpy"] for l in vl]
    ay, by = _line([0.5 - r for r in vr], ky)
    out.update(kx_mid=round(ax, 6), kx_slope=round(bx, 6),
               ky_mid=round(ay, 6), ky_slope=round(by, 6))
    rx = [k - (ax + bx * (0.5 - r)) for k, r in zip(kx, hr)]
    ry = [k - (ay + by * (0.5 - r)) for k, r in zip(ky, vr)]
    print(f"\n== hold legs: {len(hl)} horizontal, {len(vl)} vertical ==")
    print(f"  axis leakage: horizontal drags moved Y by {out['h_leak_dY_median']:.1f} "
          f"(median), vertical drags moved X by {out['v_leak_dX_median']:.1f}")
    print(f"  kx(r) = {100*ax:.3f} + {100*bx:+.3f}*(0.5-r) tiles/100px  "
          f"(resid sd {100*np.std(rx):.3f})")
    print(f"  ky(r) = {100*ay:.3f} + {100*by:+.3f}*(0.5-r) tiles/100px  "
          f"(resid sd {100*np.std(ry):.3f})")
    for row in sorted(set(round(r, 2) for r in hr)):
        v = [k for k, r in zip(kx, hr) if abs(r - row) < 0.05]
        print(f"    horizontal at row {row:.2f}: n={len(v)} "
              f"median {100*np.median(v):.3f} tiles/100px")
    for row in sorted(set(round(r, 2) for r in vr)):
        v = [k for k, r in zip(ky, vr) if abs(r - row) < 0.05]
        print(f"    vertical around row {row:.2f}: n={len(v)} "
              f"median {100*np.median(v):.3f} tiles/100px")

    # One window. The width of the ground under a row is W*kx(r); the ground
    # between two rows is H times the integral of ky between them.
    def ky_int(r1, r2):
        def f(r):
            return ay * r + by * (0.5 * r - r * r / 2)
        return f(r2) - f(r1)
    top_w = W * (ax + bx * 0.5)
    mid_w = W * ax
    bot_w = W * (ax - bx * 0.5)
    depth = H * ky_int(0.0, 1.0)
    upper = H * ky_int(0.0, 0.5)
    lower = H * ky_int(0.5, 1.0)
    out.update(window_top_width=round(top_w, 1), window_mid_width=round(mid_w, 1),
               window_bottom_width=round(bot_w, 1), window_depth=round(depth, 1),
               window_upper_depth=round(upper, 1), window_lower_depth=round(lower, 1),
               window_area=round((top_w + bot_w) / 2 * depth, 0))
    print(f"\n== one window ({W}x{H} client) ==")
    print(f"  width of the ground: {top_w:.1f} tiles at the top edge, "
          f"{mid_w:.1f} across the middle, {bot_w:.1f} at the bottom edge")
    print(f"  depth: {depth:.1f} tiles ({upper:.1f} above the centre, "
          f"{lower:.1f} below)")
    print(f"  about {out['window_area']:.0f} tiles of ground in one frame")

    if farm:
        gains = []
        for l in farm:
            r = (l["press_row"] + l["release_row"]) / 2
            if l["kind"] == "h" and abs(l["dpx"]) > 100:
                pred = -(ax + bx * (0.5 - r)) * l["dpx"]
                gains.append(l["dX"] / pred if pred else float("nan"))
            elif l["kind"] == "v" and abs(l["dpy"]) > 100:
                pred = H * ky_int(l["press_row"], l["release_row"])
                gains.append(l["dY"] / pred if pred else float("nan"))
        g = [x for x in gains if x == x]
        if g:
            out["farm_gain_median"] = round(float(np.median(g)), 3)
            out["farm_gain_all"] = [round(x, 2) for x in g]
            print(f"\n== scan-style drags, {len(farm)} usable ==")
            print(f"  actual / predicted from the pointer: median "
                  f"{out['farm_gain_median']}  all {out['farm_gain_all']}")
            print("  (1.0 = the map stops where the pointer stops; above = it "
                  "carries on after a moving release; below or negative = "
                  "it flicks back)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rounds", type=int, default=2,
                    help="hold rounds; each is 3 horizontal rows + 1 vertical, "
                         "4 legs each")
    ap.add_argument("--farm-rounds", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true",
                    help="read the position a few times, drag nothing")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--no-roundtrip", action="store_true",
                    help="skip the city round-trip check at the end")
    ap.add_argument("--analyse-only", action="store_true",
                    help="re-fit the last saved run, drag nothing")
    ap.add_argument("--keep-game", action="store_true",
                    help="leave the client open at the end (only when the "
                         "farm is started straight after)")
    args = ap.parse_args()

    if args.analyse_only:
        # Re-fit the last saved run without touching the game.
        rec = json.loads(OUT.read_text(encoding="utf-8"))[-1]
        w, h = rec["summary"]["client"]
        print(f"  run of {rec['when']}, {len(rec['legs'])} legs")
        analyse(rec["legs"], {"width": w, "height": h})
        return 0

    from rok_farm import session_control as sc
    if sc.farm_procs():
        print("[FAIL] the farm is running and holds the board -- stop it first")
        return 1

    from rok_farm.runner import GemFarmRunner
    rng = random.Random(args.seed)
    r = GemFarmRunner(port=None, count=0, loop=False, initial_alttab=True,
                      auto_launch=False, allow_restart=False, use_oracle=False)
    if not r._setup():
        print("[FAIL] setup did not complete")
        return 1
    legs = []
    try:
        if not r._ensure_game_focused("pan survey"):
            print("[FAIL] the game would not come to the front")
            return 1
        if not r._step_to_world_map("survey"):
            print("[FAIL] could not reach the world map")
            return 1
        gauge = r.read_zoom_gauge()
        if gauge != "icon":
            # Seen on the second run: the map was entered by a toggle step 1
            # did not recognise as coming from the city, the gauge could not
            # be read, and the zoom was left at the close default. Going
            # through the city is the one path whose zoom-out is known.
            print(f"  zoom gauge reads {gauge!r} -- through the city to reset it")
            r._toggle_view("survey: to the city")
            time.sleep(rng.uniform(2.0, 3.0))
            r._view_is_world = False
            if not r._step_to_world_map("survey"):
                print("[FAIL] could not get back to the world map")
                return 1
            gauge = r.read_zoom_gauge()
        if gauge != "icon":
            print(f"[FAIL] zoom gauge reads {gauge!r}, not 'icon' -- the "
                  f"numbers only mean something at the farm's zoom")
            return 1
        win = dict(r.win)
        pos = read_pos(r)
        print(f"  start {pos}, client {win['width']}x{win['height']}")
        if pos is None:
            print("[FAIL] position unreadable at the start")
            return 1
        if args.dry_run:
            for _ in range(4):
                print("  read:", read_pos(r))
            return 0

        plan = []
        for _ in range(args.rounds):
            groups = [group_legs("h", f, win, win["width"], "hold", rng)
                      for f in H_ROWS]
            groups.append(group_legs("v", 0.5, win, win["height"], "hold", rng))
            groups += [span_legs(win, a, b, "hold", rng) for a, b in V_SPANS]
            rng.shuffle(groups)
            for g in groups:
                plan.extend(g)
        for _ in range(args.farm_rounds):
            plan.extend(farm_legs(win, rng))
        print(f"  {len(plan)} legs planned\n")

        for leg in plan:
            if not r._ensure_game_focused("pan survey"):
                print("[FAIL] lost the foreground -- stopping")
                break
            pos = run_leg(r, leg, pos)
            legs.append(leg)

        summary = analyse(legs, win)
        if not args.no_roundtrip:
            summary["roundtrip"] = roundtrip_check(r, rng)
        record = {"when": datetime.now().isoformat(timespec="seconds"),
                  "summary": summary, "legs": legs}
        runs = []
        if OUT.exists():
            try:
                runs = json.loads(OUT.read_text(encoding="utf-8"))
            except Exception:
                runs = []
        runs.append(record)
        OUT.write_text(json.dumps(runs, indent=1), encoding="utf-8")
        print(f"\n  saved to {OUT}")
        return 0
    finally:
        # Never leave the client open with nothing running it. The first
        # survey day did exactly that: the runs finished at 10:00, the game
        # sat logged in and idle on the world map, and the operator closed it
        # from Discord at 10:50 -- online time is what the account gets
        # reclaimed for. Close it unless asked to keep it for the farm.
        if not args.keep_game and not args.analyse_only:
            try:
                r.game.quit_game(r)
            except Exception as e:
                print(f"[WARN] could not close the game: {e} -- close it by hand")
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
