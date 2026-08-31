"""Colour pairs from shipped design systems, and a perceptual score against them.

The question this answers: *is this a real dark theme, or just an inversion?*
A designed dark theme is not a function of the light theme -- humans chose each
value. So the only honest test is to compare against what they chose.

Distances are Oklab, where roughly 0.02 is a just-noticeable difference and 0.10
reads as a different colour. Pure Python: no numpy, so it ships with the tool.
"""

from __future__ import annotations

from typing import Dict, List, NamedTuple, Sequence, Tuple

from .colormatrix import Matrix, apply

RGB = Tuple[float, float, float]


class Pair(NamedTuple):
    name: str
    light: str
    dark: str
    source: str


# Hex values marked [verified] were checked against published documentation while
# this table was assembled; the rest are widely published palette steps. Scores
# are reported per pair so a wrong entry shows up as a single outlier rather than
# quietly biasing the total.
PAIRS: List[Pair] = [
    Pair("canvas",        "#ffffff", "#0d1117", "GitHub Primer [verified]"),
    Pair("canvas subtle", "#f6f8fa", "#161b22", "GitHub Primer [verified]"),
    Pair("body text",     "#1f2328", "#e6edf3", "GitHub Primer [verified]"),
    Pair("accent link",   "#0969da", "#2f81f7", "GitHub Primer [verified]"),
    Pair("danger text",   "#cf222e", "#f85149", "GitHub Primer [verified]"),
    Pair("editor bg",     "#ffffff", "#1e1e1e", "VS Code Light+/Dark+"),
    Pair("editor fg",     "#000000", "#d4d4d4", "VS Code Light+/Dark+"),
    Pair("page bg",       "#ffffff", "#111827", "Tailwind white/gray-900 [verified]"),
    Pair("surface",       "#f3f4f6", "#1f2937", "Tailwind gray-100/800 [verified]"),
    Pair("border",        "#e5e7eb", "#374151", "Tailwind gray-200/700"),
    Pair("muted text",    "#6b7280", "#9ca3af", "Tailwind gray-500/400"),
    Pair("strong text",   "#374151", "#d1d5db", "Tailwind gray-700/300"),
    Pair("heading",       "#111827", "#f3f4f6", "Tailwind gray-900/100 [verified]"),
    Pair("blue accent",   "#2563eb", "#60a5fa", "Tailwind blue-600/400 [verified]"),
    Pair("red accent",    "#dc2626", "#f87171", "Tailwind red-600/400 [verified]"),
    Pair("green accent",  "#16a34a", "#4ade80", "Tailwind green-600/400"),
    Pair("amber accent",  "#d97706", "#fbbf24", "Tailwind amber-600/400"),
    Pair("purple accent", "#9333ea", "#c084fc", "Tailwind purple-600/400"),
]


def from_hex(text: str) -> RGB:
    text = text.lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected a 6-digit hex colour, got {text!r}")
    return tuple(int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def to_hex(rgb: Sequence[float]) -> str:
    return "#" + "".join(f"{int(round(max(0.0, min(1.0, c)) * 255)):02x}" for c in rgb[:3])


def _linearise(channel: float) -> float:
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def oklab(rgb: RGB) -> Tuple[float, float, float]:
    """sRGB to Oklab, whose distances track perceived colour difference."""
    r, g, b = (_linearise(c) for c in rgb)
    long_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    med = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    short = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (v ** (1 / 3) if v >= 0 else -((-v) ** (1 / 3)) for v in (long_, med, short))
    return (
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    )


def delta_e(a: RGB, b: RGB) -> float:
    """Perceptual distance. ~0.02 is just noticeable, ~0.10 is a different colour."""
    return sum((x - y) ** 2 for x, y in zip(oklab(a), oklab(b))) ** 0.5


class Score(NamedTuple):
    mean: float
    worst: float
    worst_pair: str
    per_pair: List[Tuple[Pair, RGB, float]]


def score(matrix: Matrix, pairs: Sequence[Pair] = PAIRS) -> Score:
    """How close a transform lands to what real dark themes chose."""
    rows = []
    for pair in pairs:
        got = apply(matrix, from_hex(pair.light))
        rows.append((pair, got, delta_e(got, from_hex(pair.dark))))
    distances = [d for _, _, d in rows]
    worst_index = distances.index(max(distances))
    return Score(sum(distances) / len(distances), max(distances),
                 rows[worst_index][0].name, rows)
