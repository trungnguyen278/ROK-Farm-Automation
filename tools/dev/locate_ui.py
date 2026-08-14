r"""Locate a cropped UI element inside a full-window screenshot, and report its
position as a fraction of the game CLIENT area (what ScreenCapture grabs).

The screenshots are full-window grabs (title bar + client). The bot captures
only the client, so we subtract the title bar. From the runtime window info:
client 1533x862, full window height 909, title bar 45px, no side borders --
ratios used below.

Run: .venv\Scripts\python tools/locate_ui.py
"""

import sys

import cv2

TITLE_FRAC = 45.0 / 909.0          # title-bar height / full-window height
CLIENT_FRAC = 862.0 / 909.0        # client height / full-window height

PAIRS = [
    ("new_troop", r"C:\Users\LEGION\Pictures\Screenshots\Screenshot 2026-06-16 120252.png",
     r"C:\Users\LEGION\Pictures\Screenshots\Screenshot 2026-06-16 120306.png"),
    ("queue", r"C:\Users\LEGION\Pictures\Screenshots\Screenshot 2026-06-16 120334.png",
     r"C:\Users\LEGION\Pictures\Screenshots\Screenshot 2026-06-16 120349.png"),
    ("march", r"C:\Users\LEGION\Pictures\Screenshots\Screenshot 2026-06-16 121554.png",
     r"C:\Users\LEGION\Pictures\Screenshots\Screenshot 2026-06-16 121601.png"),
]


def locate(ctx_path, crop_path):
    ctx = cv2.imread(ctx_path)
    crop = cv2.imread(crop_path)
    if ctx is None or crop is None:
        return None
    H, W = ctx.shape[:2]
    ch, cw = crop.shape[:2]
    best = None
    # crop may be at a different scale than the context; sweep a few scales.
    for s in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.25, 1.5, 1.75, 2.0]:
        rc = cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        rh, rw = rc.shape[:2]
        if rw > W or rh > H:
            continue
        res = cv2.matchTemplate(ctx, rc, cv2.TM_CCOEFF_NORMED)
        _, mv, _, ml = cv2.minMaxLoc(res)
        if best is None or mv > best[0]:
            best = (mv, ml, rw, rh)
    if best is None:
        return None
    conf, (x, y), w, h = best
    cx, cy = x + w / 2, y + h / 2
    # full-window fractions
    fx, fy = cx / W, cy / H
    # client fractions (x maps directly; y subtract title bar)
    client_fx = fx
    client_fy = (fy - TITLE_FRAC) / CLIENT_FRAC
    return dict(conf=conf, ctx_wh=(W, H), box=(x, y, w, h),
                win_frac=(fx, fy), client_frac=(client_fx, client_fy),
                client_box_frac=(x / W, (y / H - TITLE_FRAC) / CLIENT_FRAC,
                                 (x + w) / W, ((y + h) / H - TITLE_FRAC) / CLIENT_FRAC))


def main():
    for name, ctx_path, crop_path in PAIRS:
        r = locate(ctx_path, crop_path)
        print(f"\n=== {name} ===")
        if r is None:
            print("  could not load / match")
            continue
        print(f"  match conf={r['conf']:.3f}  ctx={r['ctx_wh']}  box={r['box']}")
        print(f"  CENTER client frac: x={r['client_frac'][0]:.3f} y={r['client_frac'][1]:.3f}")
        bx1, by1, bx2, by2 = r['client_box_frac']
        print(f"  BOX    client frac: x=[{bx1:.3f},{bx2:.3f}] y=[{by1:.3f},{by2:.3f}]")


if __name__ == "__main__":
    main()
