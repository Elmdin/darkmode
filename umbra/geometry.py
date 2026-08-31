"""Immutable screen rectangles.

Kept free of any Windows dependency so region maths is testable anywhere.
Coordinates are physical pixels on the virtual desktop, so ``x`` and ``y`` may
legitimately be negative when a monitor sits above or left of the primary one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple

MIN_SIDE = 8


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", int(self.x))
        object.__setattr__(self, "y", int(self.y))
        object.__setattr__(self, "width", int(self.width))
        object.__setattr__(self, "height", int(self.height))
        if self.width <= 0 or self.height <= 0:
            raise ValueError(
                f"region must have positive size, got {self.width}x{self.height}"
            )

    # -- derived -----------------------------------------------------------

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return self.width * self.height

    @property
    def center(self) -> Tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    # -- construction ------------------------------------------------------

    @classmethod
    def from_points(cls, x1: int, y1: int, x2: int, y2: int,
                    minimum: int = MIN_SIDE) -> "Rect":
        """Build from two drag corners, in any order.

        A drag can end up-left of where it started, and a stray click would
        otherwise produce a zero-size region, so both are normalised here.
        """
        left, right = sorted((int(x1), int(x2)))
        top, bottom = sorted((int(y1), int(y2)))
        return cls(left, top, max(right - left, minimum), max(bottom - top, minimum))

    @classmethod
    def from_edges(cls, left: int, top: int, right: int, bottom: int) -> "Rect":
        return cls(left, top, right - left, bottom - top)

    # -- transformation (always returns a new Rect) ------------------------

    def moved(self, x: int, y: int) -> "Rect":
        return Rect(x, y, self.width, self.height)

    def resized(self, width: int, height: int) -> "Rect":
        return Rect(self.x, self.y, width, height)

    def clamped_to(self, bounds: "Rect") -> "Rect":
        """Trim to the part that actually lies inside ``bounds``."""
        left = max(self.x, bounds.x)
        top = max(self.y, bounds.y)
        right = min(self.right, bounds.right)
        bottom = min(self.bottom, bounds.bottom)
        if right - left < 1 or bottom - top < 1:
            raise ValueError(f"region {self} lies entirely outside {bounds}")
        return Rect.from_edges(left, top, right, bottom)

    # -- text --------------------------------------------------------------

    def __str__(self) -> str:
        return f"{self.x},{self.y},{self.width},{self.height}"

    def describe(self) -> str:
        return f"{self.width}x{self.height} at ({self.x}, {self.y})"


_GEOMETRY = re.compile(r"^\s*(\d+)\s*x\s*(\d+)\s*([+-]\d+)\s*([+-]\d+)\s*$")


def parse_region(text: str) -> Rect:
    """Parse ``x,y,w,h`` or X-style ``WxH+X+Y``.

    Raises ValueError with a usable message, since this is a CLI boundary.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("region is empty; expected 'x,y,width,height'")

    match = _GEOMETRY.match(text)
    if match:
        width, height, x, y = (int(g) for g in match.groups())
        return Rect(x, y, width, height)

    parts = [p.strip() for p in text.split(",")]
    if len(parts) != 4:
        raise ValueError(
            f"could not read region {text!r}; expected 'x,y,width,height' "
            "(e.g. 0,0,1280,800) or 'WxH+X+Y' (e.g. 1280x800+0+0)"
        )
    try:
        x, y, width, height = (int(p) for p in parts)
    except ValueError:
        raise ValueError(f"region {text!r} must be four whole numbers") from None
    return Rect(x, y, width, height)
