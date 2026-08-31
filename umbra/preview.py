"""Terminal preview of what a colour transform will do.

Renders before/after swatches with 24-bit ANSI colour. This is how you check a
preset without putting it on your whole screen -- and it runs anywhere, since it
touches none of the Windows layer.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional, Sequence, Tuple

from .colormatrix import apply
from .transforms import DarkParams, PRESETS, build, clipping_headroom, list_presets

RGB = Tuple[float, float, float]

# Colours chosen to expose the failure modes: neutrals near the ends (where a
# naive invert slams to pure black/white), saturated primaries (where naive
# inversion flips hue), and real UI colours people actually stare at.
SWATCHES: List[Tuple[str, RGB]] = [
    ("page white", (1.00, 1.00, 1.00)),
    ("off white", (0.96, 0.96, 0.94)),
    ("light grey", (0.85, 0.85, 0.85)),
    ("mid grey", (0.50, 0.50, 0.50)),
    ("dark grey", (0.20, 0.20, 0.20)),
    ("near black", (0.07, 0.07, 0.08)),
    ("black text", (0.00, 0.00, 0.00)),
    ("link blue", (0.10, 0.35, 0.85)),
    ("error red", (0.80, 0.15, 0.15)),
    ("ok green", (0.15, 0.65, 0.30)),
    ("warn amber", (0.95, 0.70, 0.10)),
    ("violet", (0.55, 0.30, 0.80)),
    ("teal", (0.10, 0.60, 0.60)),
    ("skin tone", (0.90, 0.72, 0.60)),
    ("sky photo", (0.45, 0.70, 0.95)),
    ("pure red", (1.00, 0.00, 0.00)),
    ("pure green", (0.00, 1.00, 0.00)),
    ("pure blue", (0.00, 0.00, 1.00)),
]

_RESET = "\x1b[0m"


def supports_colour(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    return bool(getattr(stream, "isatty", lambda: False)())


def _block(rgb: RGB, width: int = 10) -> str:
    r, g, b = (int(round(c * 255)) for c in rgb)
    return f"\x1b[48;2;{r};{g};{b}m{' ' * width}{_RESET}"


def _hex(rgb: RGB) -> str:
    return "#" + "".join(f"{int(round(c * 255)):02x}" for c in rgb)


def render(params: DarkParams, title: str = "", colour: Optional[bool] = None,
           swatches: Sequence[Tuple[str, RGB]] = SWATCHES) -> str:
    """One before/after table for a single set of parameters."""
    use_colour = supports_colour() if colour is None else colour
    matrix = build(params)
    lines: List[str] = []

    if title:
        lines.append("")
        lines.append(f"  \x1b[1m{title}\x1b[0m" if use_colour else f"  {title}")
        lines.append("  " + "-" * 58)

    header = f"  {'':<12} {'before':<12} {'':<10}  {'after':<12}"
    lines.append(header if use_colour else f"  {'':<12} {'before':<12}  {'after':<12}")

    for name, rgb in swatches:
        out = apply(matrix, rgb)
        if use_colour:
            lines.append(
                f"  {name:<12} {_block(rgb)} {_hex(rgb):<8} "
                f"-> {_block(out)} {_hex(out):<8}"
            )
        else:
            lines.append(f"  {name:<12} {_hex(rgb):<8}  ->  {_hex(out):<8}")

    low, high = clipping_headroom(params)
    if low < -0.001 or high > 1.001:
        lines.append(
            f"  note: saturated colours overshoot to [{low:.2f}, {high:.2f}] and are "
            "clipped;\n        hue survives clipping, brightness does not."
        )
    return "\n".join(lines)


def render_presets(names: Optional[Sequence[str]] = None,
                   colour: Optional[bool] = None) -> str:
    """Every preset, one table each, for side-by-side comparison."""
    names = list(names) if names else list_presets()
    return "\n".join(
        render(PRESETS[n], title=f"{n}  ({summarise(PRESETS[n])})", colour=colour)
        for n in names
    )


def summarise(p: DarkParams) -> str:
    if p.strength == 0:
        return "no effect"
    bits = [f"sat {p.saturation:g}", f"range {p.black_point:g}-{p.white_point:g}"]
    if p.contrast != 1.0:
        bits.append(f"contrast {p.contrast:g}")
    if p.warmth:
        bits.append(f"warmth {p.warmth:g}")
    if p.strength != 1.0:
        bits.append(f"strength {p.strength:g}")
    return ", ".join(bits)


def render_ramp(params: DarkParams, steps: int = 24,
                colour: Optional[bool] = None) -> str:
    """A grey ramp and a hue sweep, before and after.

    The ramp is the direct answer to 'does it handle the colours in between':
    every step should map smoothly to its complement rather than banding.
    """
    import colorsys

    use_colour = supports_colour() if colour is None else colour
    if not use_colour:
        return ""
    matrix = build(params)
    greys = [(i / (steps - 1),) * 3 for i in range(steps)]
    hues = [colorsys.hsv_to_rgb(i / steps, 0.75, 0.85) for i in range(steps)]

    def strip(colours: List[RGB], transform: bool) -> str:
        return "".join(
            _block(apply(matrix, c) if transform else c, width=2) for c in colours
        )

    return "\n".join([
        "",
        "  grey ramp    " + strip(greys, False),
        "  transformed  " + strip(greys, True),
        "",
        "  hue sweep    " + strip(hues, False),
        "  transformed  " + strip(hues, True),
    ])


def render_comparison(names: Optional[Sequence[str]] = None,
                      colour: Optional[bool] = None) -> str:
    """Each preset against colours real dark themes actually ship.

    This is the answer to "is it a true dark theme or just an inversion?" --
    it puts the transform's output next to what humans chose, with a perceptual
    distance beside it, and lets you judge.
    """
    from .reference import PAIRS, from_hex, score, to_hex

    names = list(names) if names else ["theme", "dark", "negative"]
    use_colour = supports_colour() if colour is None else colour
    scores = {n: score(build(PRESETS[n])) for n in names}
    lines: List[str] = [""]

    def cell(rgb, text):
        return f"{_block(rgb, 4)} {text}" if use_colour else text

    header = f"  {'':<14} {'light':>9} {'real dark':>10}   " + "  ".join(
        f"{n:>16}" for n in names)
    lines.append(header)
    lines.append("  " + "-" * (37 + 18 * len(names)))

    for index, pair in enumerate(PAIRS):
        light, dark = from_hex(pair.light), from_hex(pair.dark)
        row = f"  {pair.name:<14} {cell(light, pair.light):>9} {cell(dark, pair.dark):>10}   "
        for n in names:
            _, got, distance = scores[n].per_pair[index]
            mark = "!" if distance > 0.15 else " "
            row += f"{cell(got, to_hex(got))} {distance:.3f}{mark} "
        lines.append(row)

    lines.append("  " + "-" * (37 + 18 * len(names)))
    for n in names:
        s = scores[n]
        lines.append(f"  {n:<14} mean {s.mean:.4f}   worst {s.worst:.4f} ({s.worst_pair})")
    lines.append("")
    lines.append("  Oklab distance: ~0.02 is just noticeable, ~0.10 reads as a different colour.")
    lines.append("  '!' marks where an affine transform cannot follow a designed theme:")
    lines.append("  bright saturated accents (amber, green) get darkened by inverting")
    lines.append("  lightness, where a real theme keeps them bright to carry contrast.")
    return "\n".join(lines)
