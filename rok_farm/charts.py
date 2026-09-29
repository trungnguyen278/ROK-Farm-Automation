"""Charts for the Discord bot, drawn with Pillow in one visual language.

Discord shows an embed's picture about 520 px wide on a desktop and 350 on a
phone, on its own dark surface. So the picture is laid out at 1000 px and
scaled down by Discord: text sizes here are about twice what the reader sees.

Colour: the surface and the ink are Discord's own dark-theme tokens, so a
chart sits in the embed instead of on it. Marks take the dark steps of the
dataviz reference palette -- blue for one series, orange for the second --
validated on #2B2D31 (adjacent CVD dE 26.8, normal vision 31.8, both >= 3:1
contrast). Text never wears a series colour; a swatch beside it does.

Pillow draws shapes without anti-aliasing, so everything is drawn at SS
times the size and scaled down with a Lanczos filter.
"""

from __future__ import annotations

import io
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SURFACE = (43, 45, 49)          # #2B2D31, Discord's embed background
INK = (242, 243, 245)           # #F2F3F5, primary text
INK_2 = (181, 186, 193)         # #B5BAC1, secondary text
MUTED = (148, 155, 164)         # #949BA4, axis text
GRID = (63, 65, 71)             # #3F4147, hairline grid
BASELINE = (78, 80, 88)         # #4E5058
SERIES = ((57, 135, 229), (217, 89, 38))     # #3987E5 blue, #D95926 orange
WARNING = (250, 178, 25)        # #FAB219, status "warning": the march cap

SS = 2                          # supersampling factor
WASH = 0.38                     # an unfinished bar: its hue this much over the surface

_FONT_FILES = {"regular": ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"),
               "semibold": ("seguisb.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"),
               "bold": ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")}
_FONT_DIRS = (Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"),
              Path("/usr/share/fonts/truetype"))
_font_cache: dict = {}


def font(size: int, weight: str = "regular"):
    """Segoe UI at `size` logical px (drawn at SS times that)."""
    key = (size, weight)
    if key not in _font_cache:
        f = None
        for name in _FONT_FILES[weight]:
            for folder in _FONT_DIRS:
                try:
                    f = ImageFont.truetype(str(folder / name), size * SS)
                    break
                except OSError:
                    continue
            if f is not None:
                break
        _font_cache[key] = f or ImageFont.load_default()
    return _font_cache[key]


def mix(colour, over=SURFACE, alpha=WASH):
    """`colour` laid over `over` at `alpha` -- a wash, as an opaque RGB."""
    return tuple(round(c * alpha + o * (1 - alpha)) for c, o in zip(colour, over))


# --------------------------------------------------------------------------
# numbers

def fmt_int(v) -> str:
    return "-" if v is None else f"{v:,.0f}"


def fmt_1(v) -> str:
    return "-" if v is None else f"{v:,.1f}"


def fmt_pct(v) -> str:
    return "-" if v is None else f"{v:.0f}%"


def fmt_tick(v: float) -> str:
    """Axis ticks: 0 / 500 / 1,000 / 12.5K."""
    if v >= 10000:
        return f"{v / 1000:.0f}K" if v % 1000 == 0 else f"{v / 1000:.1f}K"
    if v == int(v):
        return f"{v:,.0f}"
    return f"{v:.1f}"


def nice_ticks(top: float, target: int = 4) -> list[float]:
    """0 to at least `top` in about `target` steps of 1, 2, 2.5 or 5 x 10^k."""
    if top <= 0:
        return [0.0, 1.0]
    raw = top / target
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    n = math.ceil(top / step - 1e-9)
    return [round(k * step, 6) for k in range(n + 1)]


# --------------------------------------------------------------------------
# the canvas

class Canvas:
    """Draw in logical px; saved at logical size, drawn at SS times it."""

    def __init__(self, width: int, height: int):
        self.w, self.h = width, height
        self.img = Image.new("RGB", (width * SS, height * SS), SURFACE)
        self.d = ImageDraw.Draw(self.img)

    def text(self, xy, s, size=20, weight="regular", fill=INK, anchor="la"):
        self.d.text((xy[0] * SS, xy[1] * SS), s, font=font(size, weight),
                    fill=fill, anchor=anchor)

    def text_w(self, s, size=20, weight="regular") -> float:
        return self.d.textlength(s, font=font(size, weight)) / SS

    def line(self, x0, y0, x1, y1, fill=GRID, width=1):
        self.d.line([(x0 * SS, y0 * SS), (x1 * SS, y1 * SS)], fill=fill,
                    width=max(1, round(width * SS)))

    def rect(self, x0, y0, x1, y1, fill, radius=0, top_only=True):
        box = [x0 * SS, y0 * SS, x1 * SS, y1 * SS]
        w, h = box[2] - box[0], box[3] - box[1]
        if h < 1 or w < 1:
            return
        # Pillow needs the corners to fit inside the box with a pixel to
        # spare, or it raises on a bar only a few pixels tall.
        r = min(radius * SS, (w - 1) / 2, (h - 1) if top_only else (h - 1) / 2)
        if r >= 1:
            corners = (True, True, False, False) if top_only else None
            self.d.rounded_rectangle(box, radius=r, fill=fill, corners=corners)
        else:
            self.d.rectangle(box, fill=fill)

    def png(self) -> bytes:
        out = self.img.resize((self.w, self.h), Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, "PNG", optimize=True)
        return buf.getvalue()


def legend(c: Canvas, right: float, y: float, items) -> None:
    """Keys right-aligned on one row at `y` (the text middle).

    items: [(name, colour, kind)] -- kind "box" for a series swatch, "line"
    for a reference line. The name is ink; only the key wears the colour.
    """
    x = right
    for name, colour, kind in reversed(list(items)):
        x -= c.text_w(name, 19)
        c.text((x, y), name, 19, fill=INK_2, anchor="lm")
        if kind == "line":
            x -= 30
            c.line(x, y, x + 20, y, colour, 2)
        else:
            x -= 22
            c.rect(x, y - 7, x + 14, y + 7, colour, radius=3, top_only=False)
        x -= 22


# --------------------------------------------------------------------------
# the one chart: columns over a category axis (days, hours)

def column_chart(labels, series, *, title="", subtitle="", fmt=fmt_int,
                 names=None, partial=(), label_at=(), label_text=None,
                 partial_note=" so far", ref=None, groups=None,
                 width=1000, height=440) -> bytes:
    """PNG of columns, one per label, stacked when `series` has two rows.

    series      [[v, ...]] -- one list per stacked series, bottom first; None
                where there is no value (drawn as an empty slot, never a zero)
    partial     indices still in progress or thin on data: drawn as a wash
    label_at    indices that get a value on the cap -- selective, never
                every bar; the embed's table carries the rest
    label_text  i -> the text for a labelled bar (default: fmt of its total)
    partial_note  added to a partial bar's label; None = no label on them
    ref         (value, text, colour): one solid reference line, keyed in
                the header -- never labelled on the plot, where it collides
    groups      [(first, last, name)]: a bracket under the x labels
    names       series names; a legend is drawn only for two or more
    """
    c = Canvas(width, height)
    n = len(labels)
    totals = [None if all(s[i] is None for s in series)
              else sum(s[i] or 0 for s in series) for i in range(n)]
    top = max([t for t in totals if t is not None] + [0.0])
    if ref is not None:
        top = max(top, ref[0])
    # Headroom for the value on the tallest cap.
    ticks = nice_ticks(top * 1.12 if top else 1.0)
    vmax = ticks[-1]

    head = 64 if title or subtitle else 20
    foot = 40 + (40 if groups else 0)
    tick_w = max(c.text_w(fmt_tick(t), 18) for t in ticks)
    left, right = 24 + tick_w + 12, 24
    base_y = height - foot
    plot_w, plot_h = width - left - right, base_y - head - 10

    if title:
        c.text((24, 20), title, 24, "semibold", INK)
    if subtitle:
        c.text((24 + (c.text_w(title, 24, "semibold") + 14 if title else 0), 24),
               subtitle, 19, fill=MUTED)
    keys = []
    if names and len(names) >= 2:
        keys += [(name, SERIES[k % len(SERIES)], "box") for k, name in enumerate(names)]
    if ref is not None:
        keys.append((ref[1], ref[2], "line"))
    if keys:
        legend(c, width - right, 34, keys)

    def y_of(v):
        return base_y - plot_h * (v / vmax)

    for t in ticks:
        y = y_of(t)
        c.line(left, y, width - right, y, GRID if t else BASELINE, 1)
        c.text((left - 12, y), fmt_tick(t), 18, fill=MUTED, anchor="rm")

    if ref is not None:                         # under the bars, over the grid
        c.line(left, y_of(ref[0]), width - right, y_of(ref[0]), ref[2], 2)

    slot = plot_w / max(n, 1)
    bar_w = min(slot * 0.62, 44.0)
    gap = 3.0                                   # surface gap between stacked fills
    label_w = max((c.text_w(s, 18) for s in labels), default=0)
    every = max(1, math.ceil((label_w + 10) / slot))

    for i in range(n):
        cx = left + slot * (i + 0.5)
        x0, x1 = cx - bar_w / 2, cx + bar_w / 2
        if totals[i] is None:
            c.text((cx, base_y - 12), "-", 18, fill=MUTED, anchor="ms")
        else:
            y = base_y
            parts = [(s[i] or 0, SERIES[k % len(SERIES)])
                     for k, s in enumerate(series)]
            drawn = [p for p in parts if p[0] > 0]
            for j, (v, colour) in enumerate(drawn):
                h = plot_h * (v / vmax)
                last = j == len(drawn) - 1
                fill = mix(colour) if i in partial else colour
                y_top = y - h
                c.rect(x0, y_top, x1, y - (gap if j else 0), fill,
                       radius=5 if last else 0)
                y = y_top
            thin = i in partial
            if i in label_at or (thin and partial_note is not None):
                txt = label_text(i) if label_text else fmt(totals[i])
                room = slot * 1.6
                if thin and partial_note and \
                        c.text_w(txt + partial_note, 19) <= room:
                    txt += partial_note
                tw = c.text_w(txt, 19, "regular" if thin else "semibold")
                if thin and tw > room:
                    # A short wash beside a tall neighbour: the label would
                    # sit on the neighbour's bar. The embed says it anyway.
                    txt = ""
                # Kept inside the picture: the last bar's label hangs off the
                # right edge otherwise.
                lx = min(max(cx, 8 + tw / 2), width - 8 - tw / 2)
                c.text((lx, y_of(totals[i]) - 8), txt, 19,
                       "regular" if thin else "semibold",
                       INK_2 if thin else INK, anchor="ms")
        if i % every == 0 or i == n - 1:
            if i == n - 1 or (n - 1 - i) >= every:
                c.text((cx, base_y + 10), labels[i], 18, fill=MUTED, anchor="ma")

    if groups:
        gy = base_y + 42
        for first, last, name in groups:
            gx0 = left + slot * first + 6
            gx1 = left + slot * (last + 1) - 6
            c.line(gx0, gy, gx1, gy, BASELINE, 1)
            c.text(((gx0 + gx1) / 2, gy + 6), name, 17, fill=MUTED, anchor="ma")
    return c.png()
