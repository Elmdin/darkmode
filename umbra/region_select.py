"""Drag a rectangle over the screen to choose the region.

Runs as its **own process** (``python -m umbra.region_select``) and prints the
chosen rectangle on stdout. That isolation is deliberate: Tk runs its own event
loop, and the main app runs a raw Win32 message loop. Keeping them in separate
processes means neither can wedge or crash the other, and a cancelled selection
costs nothing.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from .geometry import Rect, parse_region

_OVERLAY_ALPHA = 0.35
_HINT = "Drag to choose the area  ·  Enter for the whole screen  ·  Esc to cancel"


def drag_to_rect(anchor: Tuple[int, int], release: Tuple[int, int],
                 origin: Tuple[int, int]) -> Rect:
    """Convert a drag on the overlay canvas into a screen rectangle.

    Canvas coordinates start at the overlay's top-left corner, which sits at the
    *virtual desktop* origin -- and that origin is negative when a monitor is
    placed above or left of the primary one. Kept separate from the Tk callbacks
    so this arithmetic can be tested without a display.
    """
    ox, oy = origin
    return Rect.from_points(anchor[0] + ox, anchor[1] + oy,
                            release[0] + ox, release[1] + oy)


def _virtual_bounds() -> Tuple[int, int, int, int]:
    """(x, y, width, height) spanning every monitor, in physical pixels."""
    if sys.platform == "win32":
        from . import winapi as w
        w.set_dpi_awareness()
        r = w.virtual_screen()
        return r.left, r.top, r.width, r.height
    import tkinter as tk
    probe = tk.Tk()
    probe.withdraw()
    size = (0, 0, probe.winfo_screenwidth(), probe.winfo_screenheight())
    probe.destroy()
    return size


def select_interactively() -> Optional[Rect]:
    """Show the overlay and block until the user drags, accepts, or cancels."""
    import tkinter as tk

    x0, y0, width, height = _virtual_bounds()
    result: dict = {"rect": None}

    root = tk.Tk()
    root.title("Umbra region")
    root.overrideredirect(True)
    root.geometry("%dx%d+%d+%d" % (width, height, x0, y0))
    root.attributes("-topmost", True)
    try:
        root.attributes("-alpha", _OVERLAY_ALPHA)
    except tk.TclError:  # pragma: no cover - very old Tk
        pass
    root.configure(bg="black")
    root.config(cursor="crosshair")

    canvas = tk.Canvas(root, bg="black", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)
    canvas.create_text(width // 2, 40, text=_HINT, fill="#ffffff",
                       font=("Segoe UI", 16))

    anchor: dict = {"x": 0, "y": 0}
    box = canvas.create_rectangle(0, 0, 0, 0, outline="#ffffff", width=2,
                                  dash=(6, 4), state="hidden")
    label = canvas.create_text(0, 0, text="", fill="#ffffff",
                               font=("Consolas", 12), state="hidden")

    def on_press(event: "tk.Event") -> None:
        anchor.update(x=event.x, y=event.y)
        canvas.itemconfigure(box, state="normal")
        canvas.itemconfigure(label, state="normal")

    def on_drag(event: "tk.Event") -> None:
        canvas.coords(box, anchor["x"], anchor["y"], event.x, event.y)
        w = abs(event.x - anchor["x"])
        h = abs(event.y - anchor["y"])
        canvas.coords(label, (anchor["x"] + event.x) / 2, (anchor["y"] + event.y) / 2)
        canvas.itemconfigure(label, text=f"{w} x {h}")

    def on_release(event: "tk.Event") -> None:
        result["rect"] = drag_to_rect(
            (anchor["x"], anchor["y"]), (event.x, event.y), (x0, y0)
        )
        root.destroy()

    def accept_whole_screen(_event: "tk.Event") -> None:
        result["rect"] = Rect(x0, y0, width, height)
        root.destroy()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda _e: root.destroy())
    root.bind("<Return>", accept_whole_screen)
    root.focus_force()
    root.mainloop()
    return result["rect"]


def select_in_subprocess(timeout: float = 300.0) -> Optional[Rect]:
    """Run the selector in a child process and parse the rectangle it prints.

    Returns ``None`` if the user cancelled or the selector failed; callers should
    simply keep their current region in that case.
    """
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "umbra.region_select"],
            capture_output=True, text=True, timeout=timeout,
            # Run from the package's parent so 'umbra' is importable regardless
            # of where the launcher left the working directory.
            cwd=str(Path(__file__).resolve().parent.parent),
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        print(f"umbra: region selector failed: {exc}", file=sys.stderr)
        return None

    output = (completed.stdout or "").strip()
    if completed.returncode != 0 or not output:
        if completed.stderr.strip():
            print(completed.stderr.strip(), file=sys.stderr)
        return None
    try:
        return parse_region(output)
    except ValueError as exc:
        print(f"umbra: region selector returned {output!r} ({exc})", file=sys.stderr)
        return None


def main() -> int:
    rect = select_interactively()
    if rect is None:
        return 1
    print(rect)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
