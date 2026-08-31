"""Algebra for GDI+ 5x5 colour matrices.

Windows' Magnification API takes a ``MAGCOLOREFFECT``: a 5x5 row-major matrix of
floats applied to the colour treated as a **row vector** ``[r, g, b, a, 1]``::

    out[j] = sum_i  v[i] * M[i][j]

So ``M[i][j]`` routes input channel *i* into output channel *j*, and row 4 is the
translation. Everything here is pure Python on plain lists: no numpy, no Windows,
so it runs and is testable anywhere.
"""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

Matrix = List[List[float]]
RGB = Tuple[float, float, float]

SIZE = 5

IDENTITY: Matrix = [
    [1.0, 0.0, 0.0, 0.0, 0.0],
    [0.0, 1.0, 0.0, 0.0, 0.0],
    [0.0, 0.0, 1.0, 0.0, 0.0],
    [0.0, 0.0, 0.0, 1.0, 0.0],
    [0.0, 0.0, 0.0, 0.0, 1.0],
]

_IDENTITY_TOLERANCE = 1e-6


def identity() -> Matrix:
    """A fresh, mutable identity matrix."""
    return [row[:] for row in IDENTITY]


def affine(diagonal: Sequence[float], translation: Sequence[float]) -> Matrix:
    """Build the matrix ``out_c = diagonal[c] * in_c + translation[c]`` for r, g, b."""
    m = identity()
    for c in range(3):
        m[c][c] = float(diagonal[c])
        m[4][c] = float(translation[c])
    return m


def compose(first: Matrix, second: Matrix) -> Matrix:
    """Matrix applying ``first`` and then ``second``.

    With the row-vector convention this is simply ``first @ second``: for a colour
    ``v``, ``(v @ A) @ B == v @ (A @ B)``.
    """
    return [
        [sum(first[i][k] * second[k][j] for k in range(SIZE)) for j in range(SIZE)]
        for i in range(SIZE)
    ]


def compose_all(*matrices: Matrix) -> Matrix:
    """Compose matrices left to right; ``compose_all()`` is the identity."""
    result = identity()
    for m in matrices:
        result = compose(result, m)
    return result


def lerp(a: Matrix, b: Matrix, t: float) -> Matrix:
    """Blend two matrices. ``t=0`` returns ``a`` exactly, ``t=1`` returns ``b``."""
    s = 1.0 - t
    return [[s * a[i][j] + t * b[i][j] for j in range(SIZE)] for i in range(SIZE)]


def _clamp01(x: float) -> float:
    # NaN can only arise from inf*0 in a malformed matrix; treat it as black
    # rather than letting it reach the compositor.
    if math.isnan(x):
        return 0.0
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def apply(m: Matrix, rgb: RGB, alpha: float = 1.0) -> RGB:
    """Transform one sRGB colour, clamped into ``[0, 1]``.

    Clamping mirrors what the compositor does to out-of-gamut results, so callers
    previewing a matrix see exactly what the screen will show.
    """
    v = (rgb[0], rgb[1], rgb[2], alpha, 1.0)
    return tuple(  # type: ignore[return-value]
        _clamp01(sum(v[i] * m[i][j] for i in range(SIZE))) for j in range(3)
    )


def is_identity(m: Matrix, tolerance: float = _IDENTITY_TOLERANCE) -> bool:
    """True if ``m`` leaves colours unchanged to within ``tolerance``."""
    return all(
        abs(m[i][j] - IDENTITY[i][j]) <= tolerance
        for i in range(SIZE)
        for j in range(SIZE)
    )


def to_flat(m: Matrix) -> List[float]:
    """Row-major 25 floats, the memory layout ``MAGCOLOREFFECT`` expects."""
    return [float(x) for row in m for x in row]


def from_flat(values: Sequence[float]) -> Matrix:
    if len(values) != SIZE * SIZE:
        raise ValueError(f"expected {SIZE * SIZE} values, got {len(values)}")
    return [[float(values[i * SIZE + j]) for j in range(SIZE)] for i in range(SIZE)]


def describe(m: Matrix) -> str:
    """Human-readable dump, handy for debugging a custom matrix."""
    return "\n".join("  ".join(f"{x:+.5f}" for x in row) for row in m)
