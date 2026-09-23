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
import math
import random
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from capture.screen_info import get_cursor_pos  # noqa: E402
from rok_farm import pan_model  # noqa: E402
from rok_farm.config import ZOOM_OUT_QUIET_DIFF  # noqa: E402

OUT = ROOT / "data" / "pan_survey.json"

# Never let the pointer work closer than this to the client's border. The
# half-window legs keep a quarter window in hand anyway; this is the check
# that refuses a leg if the geometry ever says otherwise.
EDGE_PX = 60

# Heights (fraction of the client) the horizontal legs run at.
H_ROWS = (0.34, 0.50, 0.66)


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
    elif leg["release_err_px"] > 8:
        leg["ok"] = False
        leg["why"] = f"released {leg['release_err_px']}px from the aim"
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
    return after or before


def analyse(legs, win):
    W, H = win["width"], win["height"]
    hold = [l for l in legs if l.get("ok") and l["style"] == "hold"]
    farm = [l for l in legs if l.get("ok") and l["style"] == "farm"]
    out = {"legs_ok": len(hold) + len(farm), "legs_total": len(legs),
           "client": [W, H]}
    if len(hold) < 6:
        print(f"\n[FAIL] only {len(hold)} usable hold legs -- not fitting")
        return out
    m, resid = pan_model.fit([(l["dpx"], l["dpy"], l["dX"], l["dY"]) for l in hold])
    err = np.hypot(resid[:, 0], resid[:, 1])
    moves = np.array([math.hypot(l["dX"], l["dY"]) for l in hold])
    out["M"] = m.round(6).tolist()
    out["resid_median"] = round(float(np.median(err)), 2)
    out["resid_max"] = round(float(err.max()), 2)
    out["move_median"] = round(float(np.median(moves)), 1)
    print(f"\n== hold fit, {len(hold)} legs ==")
    print(f"  M = [[{m[0,0]:+.5f} {m[0,1]:+.5f}]  (dX per px x, px y)")
    print(f"       [{m[1,0]:+.5f} {m[1,1]:+.5f}]] (dY per px x, px y)")
    print(f"  residual median {out['resid_median']} tiles, max "
          f"{out['resid_max']}, on moves of median {out['move_median']}")

    # Perspective: tiles per horizontal pixel at each height.
    rows = {}
    for l in hold:
        if l["kind"] == "h" and abs(l["dpx"]) > 100:
            rows.setdefault(l["row"], []).append(
                math.hypot(l["dX"], l["dY"]) / abs(l["dpx"]))
    out["h_tiles_per_100px_by_row"] = {
        f"{k:.2f}": round(100 * float(np.median(v)), 3) for k, v in sorted(rows.items())}
    print("  horizontal tiles per 100px by height:",
          out["h_tiles_per_100px_by_row"])

    wv = pan_model.drag_to_tiles(m, W, 0)
    hv = pan_model.drag_to_tiles(m, 0, H)
    out["window_width_tiles"] = [round(wv[0], 1), round(wv[1], 1)]
    out["window_height_tiles"] = [round(hv[0], 1), round(hv[1], 1)]
    out["window_area_tiles"] = round(pan_model.view_area_tiles(m, W, H), 0)
    print(f"\n== one window ({W}x{H} client) ==")
    print(f"  its width  spans {wv[0]:+.1f},{wv[1]:+.1f} tiles "
          f"({math.hypot(*wv):.1f} long)")
    print(f"  its height spans {hv[0]:+.1f},{hv[1]:+.1f} tiles "
          f"({math.hypot(*hv):.1f} long)")
    print(f"  area {out['window_area_tiles']:.0f} tiles")
    corners = pan_model.view_corners(m, W, H)
    out["corners"] = [[round(c[0], 1), round(c[1], 1)] for c in corners]
    print("  corners from the centre (TL, TR, BR, BL):", out["corners"])

    if farm:
        gains = []
        for l in farm:
            px, py = pan_model.drag_to_tiles(m, l["dpx"], l["dpy"])
            pred = math.hypot(px, py)
            if pred >= 3:
                gains.append(math.hypot(l["dX"], l["dY"]) / pred)
        if gains:
            out["farm_gain_median"] = round(float(np.median(gains)), 3)
            out["farm_gain_range"] = [round(min(gains), 3), round(max(gains), 3)]
            print(f"\n== scan-style drags, {len(farm)} legs ==")
            print(f"  actual / hold-predicted: median {out['farm_gain_median']}, "
                  f"range {out['farm_gain_range']}  (1.0 = no carry-on)")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rounds", type=int, default=2,
                    help="hold rounds; each is 3 horizontal rows + 1 vertical, "
                         "4 legs each")
    ap.add_argument("--farm-rounds", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true",
                    help="read the position a few times, drag nothing")
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

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
        try:
            r._teardown()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
