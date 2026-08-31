"""The dark-mode colour pipeline.

The whole tool rests on one idea. Naive inversion, ``out = 1 - rgb``, flips hue:
blue turns orange, red turns cyan. What you actually want from a dark mode is to
invert **lightness** and leave **hue** alone.

Split a colour into luma and chroma, ``L = w . rgb`` and ``chroma = rgb - L``,
invert only the luma, and keep the chroma::

    out = (1 - L) + s * (rgb - L)
        = s*rgb - (1 + s)*L + 1

That is affine, so it folds into the single 5x5 matrix the Magnification API
takes. One knob, ``s``, spans every mode worth having:

===== =======================================================
``s``  behaviour
===== =======================================================
-1     classic negative (hue flips; what Windows Magnifier does)
 0     inverted greyscale
 1     hue-preserving dark mode -- the default
>1     vivid: chroma boosted to offset perceived washout
===== =======================================================

At ``s = 1`` the transform reduces to *adding a per-pixel constant to all three
channels*. Channel differences are untouched, so hue and chroma are preserved
exactly, not approximately -- for any colour that does not clip (see
:func:`clipping_headroom`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace as _dc_replace
from typing import Dict, List, Tuple

from .colormatrix import (
    IDENTITY, Matrix, RGB, affine, apply, compose_all, identity, lerp,
)

# Luma weights. Rec.709 matches how bright the eye actually finds each primary;
# "equal" reproduces the classic NegativeScreen "smart invert" exactly.
LUMA_WEIGHTS: Dict[str, Tuple[float, float, float]] = {
    "rec709": (0.2126, 0.7152, 0.0722),
    "rec601": (0.299, 0.587, 0.114),
    "equal": (1 / 3, 1 / 3, 1 / 3),
}

# How far `warmth` pushes each channel at full strength. Blue drops hardest,
# red lifts slightly: the same direction as a night-light filter.
_WARMTH_GAIN = (0.12, -0.05, -0.40)

PARAM_LIMITS = {
    "strength": (0.0, 1.0),
    "saturation": (-1.0, 3.0),
    "black_point": (0.0, 1.0),
    "white_point": (0.0, 1.0),
    "contrast": (0.1, 3.0),
    "warmth": (0.0, 1.0),
}


@dataclass(frozen=True)
class DarkParams:
    """Immutable description of one dark-mode look.

    Args:
        strength: Outermost blend against "no change". 0.0 restores the screen
            bit-exactly; 1.0 is the full effect.
        saturation: Chroma retention ``s`` from the module docstring.
        black_point: The dark background level -- what pure white becomes when
            ``contrast`` is 1.0. Contrast is applied before this mapping, so at
            other contrasts the true endpoint moves; :func:`endpoints` reports
            where it actually lands.
        white_point: The light foreground level -- what pure black becomes, with
            the same caveat. Keeping these off 0.0/1.0 is what separates a real
            dark theme from a raw negative, and it buys back gamut headroom.
        contrast: Multiplier pivoting about mid-grey.
        warmth: Shifts the result amber for night use.
        luma: Which weights to split luma and chroma with.
    """

    strength: float = 1.0
    saturation: float = 1.0
    black_point: float = 0.05
    white_point: float = 0.92
    contrast: float = 1.0
    warmth: float = 0.0
    luma: str = "rec709"

    def __post_init__(self) -> None:
        for name, (low, high) in PARAM_LIMITS.items():
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"{name} must be a number, got {value!r}")
            if not low <= float(value) <= high:
                raise ValueError(f"{name} must be within [{low}, {high}], got {value}")
        if self.black_point >= self.white_point:
            raise ValueError(
                f"black_point ({self.black_point}) must be below white_point "
                f"({self.white_point}); they name what white and black become, "
                "so the range is inverted relative to the input"
            )
        if self.luma not in LUMA_WEIGHTS:
            raise ValueError(
                f"unknown luma weighting {self.luma!r}; "
                f"choose one of {sorted(LUMA_WEIGHTS)}"
            )

    def replace(self, **changes: object) -> "DarkParams":
        """A new params object with ``changes`` applied; validated like any other."""
        return _dc_replace(self, **changes)


def _core_matrix(saturation: float, luma: str) -> Matrix:
    """``out = s*rgb - (1 + s)*L + 1`` -- invert the luma, keep the chroma."""
    w = LUMA_WEIGHTS[luma]
    s = float(saturation)
    m = identity()
    for i in range(3):          # input channel
        for j in range(3):      # output channel
            m[i][j] = (s if i == j else 0.0) - (1.0 + s) * w[i]
        m[i][3] = 0.0
    m[4][0] = m[4][1] = m[4][2] = 1.0
    return m


def _contrast_matrix(contrast: float) -> Matrix:
    c = float(contrast)
    offset = 0.5 * (1.0 - c)
    return affine((c, c, c), (offset, offset, offset))


def _range_matrix(black_point: float, white_point: float) -> Matrix:
    """Squeeze the inverted result into ``[black_point, white_point]``."""
    span = float(white_point) - float(black_point)
    return affine((span, span, span), (black_point,) * 3)


def _warmth_matrix(warmth: float) -> Matrix:
    gains = tuple(1.0 + g * float(warmth) for g in _WARMTH_GAIN)
    return affine(gains, (0.0, 0.0, 0.0))


def build(params: DarkParams | None = None, **overrides: object) -> Matrix:
    """Fold a :class:`DarkParams` into the single 5x5 matrix the screen gets.

    ``build(strength=0)`` returns the exact identity, because the strength blend
    is applied last -- dialing the effect to zero must restore the screen
    perfectly, not merely nearly.
    """
    if params is None:
        params = DarkParams(**overrides)  # type: ignore[arg-type]
    elif overrides:
        params = params.replace(**overrides)

    dark = compose_all(
        _core_matrix(params.saturation, params.luma),
        _contrast_matrix(params.contrast),
        _range_matrix(params.black_point, params.white_point),
        _warmth_matrix(params.warmth),
    )
    return lerp(IDENTITY, dark, params.strength)


# --------------------------------------------------------------------------- presets

PRESETS: Dict[str, DarkParams] = {
    # Off is a real preset so cycling modes can land on "no effect".
    "off": DarkParams(strength=0.0),
    # The default. Tuned against colour pairs from shipped design systems
    # (see umbra.reference and `umbra compare`): 16% closer to what real dark
    # themes chose than plain inversion, by leave-one-out cross-validation.
    # Boosted chroma and Rec.601 weights are what the data asked for.
    "theme": DarkParams(saturation=1.4, black_point=0.12, white_point=0.94,
                        contrast=1.0, luma="rec601"),
    # Pure hue-preserving lightness inversion, untuned.
    "dark": DarkParams(),
    # Lower contrast between background and text; easier for long reading.
    "soft": DarkParams(black_point=0.10, white_point=0.85, contrast=0.95),
    # OLED-friendly: deeper background, dimmer foreground.
    "midnight": DarkParams(black_point=0.02, white_point=0.80, contrast=1.10),
    # Inverted colours look washed out; give the chroma back.
    "vivid": DarkParams(saturation=1.30, black_point=0.04, white_point=0.95),
    # Dark plus a night-light amber shift.
    "warm": DarkParams(warmth=0.45),
    # Inverted greyscale: no colour at all.
    "mono": DarkParams(saturation=0.0),
    # What Windows Magnifier does, for comparison. Hue flips.
    "negative": DarkParams(saturation=-1.0, black_point=0.0, white_point=1.0),
}

DEFAULT_PRESET = "theme"


def list_presets() -> List[str]:
    """Preset names in a sensible cycling order."""
    return list(PRESETS)


def preset(name: str) -> Matrix:
    """Build the matrix for a named preset."""
    try:
        params = PRESETS[name]
    except KeyError:
        raise KeyError(
            f"unknown preset {name!r}; choose one of {', '.join(PRESETS)}"
        ) from None
    return build(params)


def next_preset(name: str, step: int = 1) -> str:
    """The next preset when cycling with a hotkey; wraps around."""
    names = list_presets()
    try:
        index = names.index(name)
    except ValueError:
        return DEFAULT_PRESET
    return names[(index + step) % len(names)]


# --------------------------------------------------------------------------- analysis

def clipping_headroom(params: DarkParams) -> Tuple[float, float]:
    """Worst-case output before clamping, over the whole input cube.

    Hue-preserving inversion at ``s >= 1`` *must* overshoot ``[0, 1]`` on fully
    saturated primaries -- the extremes of the transform lie outside the sRGB
    cube, and no choice of black/white point fixes that without collapsing
    contrast. Returns ``(minimum, maximum)`` so callers can report how far.
    """
    m = build(params)
    lows: List[float] = []
    highs: List[float] = []
    for j in range(3):
        # Each output channel is monotone in each input, so the extremes of the
        # unit cube are found by picking each input channel independently.
        base = m[3][j] + m[4][j]
        lows.append(base + sum(min(m[i][j], 0.0) for i in range(3)))
        highs.append(base + sum(max(m[i][j], 0.0) for i in range(3)))
    return min(lows), max(highs)


def sample_map(params: DarkParams, colours: List[RGB]) -> List[Tuple[RGB, RGB]]:
    """Pair each input colour with what it becomes. Used by ``umbra preview``."""
    m = build(params)
    return [(c, apply(m, c)) for c in colours]


def endpoints(params: DarkParams) -> Tuple[float, float]:
    """What pure white and pure black actually become, after every stage.

    ``black_point``/``white_point`` name the intent, but contrast is applied
    before the range mapping and can push past them, so this reports the truth.
    """
    from .colormatrix import apply as _apply

    matrix = build(params)
    return _apply(matrix, (1.0, 1.0, 1.0))[0], _apply(matrix, (0.0, 0.0, 0.0))[0]


def clamp_param(field: str, value: float) -> float:
    """Clamp one parameter into its valid range, for interactive nudging."""
    low, high = PARAM_LIMITS[field]
    return round(min(high, max(low, value)), 3)
