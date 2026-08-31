"""Two ways to put a colour transform on the screen, behind one interface.

Both use the Magnification API, which applies a 5x5 colour matrix inside the
desktop compositor. Nothing is captured, copied or re-drawn by us, so the effect
is genuinely real-time and costs no frame latency.

``FullscreenEngine``
    One call, whole desktop, every monitor, cursor included. Windows 8+.

``RegionEngine``
    A ``WC_MAGNIFIER`` control at 1.0x magnification inside a click-through
    layered window pinned over the chosen rectangle. The control re-reads that
    rectangle each tick and paints it back transformed.
"""

from __future__ import annotations

import ctypes
import sys
from typing import Dict, Optional

from . import winapi as w
from .colormatrix import IDENTITY, Matrix
from .geometry import Rect

_HOST_CLASS = "UmbraHostWindow"
_REFRESH_TIMER = 1

# The window class is registered once per process, so its window procedure must
# not close over any one engine instance -- switching modes twice would leave the
# class pointing at a dead engine and the overlay would silently stop refreshing.
# Instead the procedure looks the live engine up by window handle.
_class_registered = False
_wndproc_ref = None  # module-level so the callback is never garbage collected
_engines_by_host: Dict[int, "RegionEngine"] = {}


def _handle_key(handle: object) -> int:
    """Normalise an HWND from ctypes (int, c_void_p, or None) to a dict key."""
    if not handle:
        return 0
    if isinstance(handle, int):
        return handle
    return ctypes.cast(handle, ctypes.c_void_p).value or 0


def _host_wndproc(hwnd, msg, wparam, lparam):
    if msg == w.WM_TIMER:
        engine = _engines_by_host.get(_handle_key(hwnd))
        if engine is not None:
            engine.refresh()
        return 0
    if msg == w.WM_DESTROY:
        _engines_by_host.pop(_handle_key(hwnd), None)
        return 0
    return w.user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _register_host_class() -> None:
    global _class_registered, _wndproc_ref
    if _class_registered:
        return
    _wndproc_ref = w.WNDPROC(_host_wndproc)
    cls = w.WNDCLASSEXW()
    cls.cbSize = ctypes.sizeof(w.WNDCLASSEXW)
    cls.lpfnWndProc = _wndproc_ref
    cls.hInstance = w.kernel32.GetModuleHandleW(None)
    cls.hCursor = None       # the host is click-through; its cursor is never shown
    cls.hbrBackground = w.gdi32.GetStockObject(w.BLACK_BRUSH)
    cls.lpszClassName = _HOST_CLASS
    w.check(w.user32.RegisterClassExW(ctypes.byref(cls)), "RegisterClassExW")
    _class_registered = True


class Engine:
    """Strategy interface. ``start`` -> ``set_effect``/``set_region`` -> ``stop``."""

    name = "engine"

    def start(self) -> None:
        raise NotImplementedError

    def set_effect(self, matrix: Matrix) -> None:
        raise NotImplementedError

    def set_region(self, region: Rect) -> None:
        """No-op for engines that always cover everything."""

    def stop(self) -> None:
        raise NotImplementedError

    @property
    def region(self) -> Optional[Rect]:
        return None


class _MagnificationRuntime:
    """Reference-counted MagInitialize/MagUninitialize.

    Both engines need the runtime, and switching modes must not tear it down
    while the other engine still holds it.
    """

    _depth = 0

    @classmethod
    def acquire(cls) -> None:
        if cls._depth == 0:
            w.check(w.magnification.MagInitialize(), "MagInitialize")
        cls._depth += 1

    @classmethod
    def release(cls) -> None:
        if cls._depth == 0:
            return
        cls._depth -= 1
        if cls._depth == 0:
            w.magnification.MagUninitialize()


class FullscreenEngine(Engine):
    """Colour-transform the entire desktop via ``MagSetFullscreenColorEffect``."""

    name = "fullscreen"

    def __init__(self) -> None:
        self._running = False

    def start(self) -> None:
        w.require_windows()
        if self._running:
            raise RuntimeError("engine already started")
        _MagnificationRuntime.acquire()
        self._running = True

    def set_effect(self, matrix: Matrix) -> None:
        if not self._running:
            raise RuntimeError("engine not started")
        effect = w.MAGCOLOREFFECT.from_matrix(matrix)
        ok = w.magnification.MagSetFullscreenColorEffect(ctypes.byref(effect))
        if not ok:
            raise OSError(
                "MagSetFullscreenColorEffect was refused. Usually this means "
                "something else owns the full-screen magnifier: close Windows "
                "Magnifier, and turn off Settings > Accessibility > Colour filters."
            )

    def stop(self) -> None:
        if not self._running:
            return
        try:
            self.set_effect(IDENTITY)
        except OSError:
            pass
        finally:
            self._running = False
            _MagnificationRuntime.release()


class RegionEngine(Engine):
    """Colour-transform one rectangle, leaving the rest of the screen alone."""

    name = "region"

    def __init__(self, region: Rect, fps: int = 60, show_cursor: bool = True) -> None:
        self._region = region
        self._interval_ms = max(1, round(1000 / max(1, min(fps, 240))))
        self._show_cursor = show_cursor
        self._matrix: Matrix = IDENTITY
        self._host = None
        self._mag = None
        self._holds_runtime = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        w.require_windows()
        if self._holds_runtime:
            raise RuntimeError("engine already started")
        _MagnificationRuntime.acquire()
        self._holds_runtime = True
        try:
            self._create_windows()
            self._apply_filter_list()
            transform = w.MAGTRANSFORM.scale(1.0)
            w.check(
                w.magnification.MagSetWindowTransform(self._mag, ctypes.byref(transform)),
                "MagSetWindowTransform",
            )
            self.set_effect(self._matrix)
            self.set_region(self._region)
            w.user32.ShowWindow(self._host, w.SW_SHOWNA)
            w.user32.SetTimer(self._host, _REFRESH_TIMER, self._interval_ms, None)
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        """Idempotent: ``start`` calls this on failure and the caller calls it
        again afterwards, so a second call must not release the runtime twice."""
        if self._host:
            w.user32.KillTimer(self._host, _REFRESH_TIMER)
            _engines_by_host.pop(_handle_key(self._host), None)
            w.user32.DestroyWindow(self._host)
        self._host = self._mag = None
        if self._holds_runtime:
            self._holds_runtime = False
            _MagnificationRuntime.release()

    # -- window plumbing ---------------------------------------------------

    def _create_windows(self) -> None:
        instance = w.kernel32.GetModuleHandleW(None)
        _register_host_class()

        # Click-through (WS_EX_TRANSPARENT) so the overlay never eats input, and
        # NOACTIVATE/TOOLWINDOW so it stays out of Alt+Tab and the taskbar.
        self._host = w.user32.CreateWindowExW(
            w.WS_EX_TOPMOST | w.WS_EX_LAYERED | w.WS_EX_TRANSPARENT
            | w.WS_EX_TOOLWINDOW | w.WS_EX_NOACTIVATE,
            _HOST_CLASS, "Umbra", w.WS_POPUP | w.WS_CLIPCHILDREN,
            self._region.x, self._region.y, self._region.width, self._region.height,
            None, None, instance, None,
        )
        w.check(self._host, "CreateWindowExW (host)")
        _engines_by_host[_handle_key(self._host)] = self
        # Fully opaque: the magnifier's output must not blend with what is behind it.
        w.check(w.user32.SetLayeredWindowAttributes(self._host, 0, 255, w.LWA_ALPHA),
                "SetLayeredWindowAttributes")

        style = w.WS_CHILD | w.WS_VISIBLE
        if self._show_cursor:
            style |= w.MS_SHOWMAGNIFIEDCURSOR
        self._mag = w.user32.CreateWindowExW(
            0, w.WC_MAGNIFIER, "UmbraMagnifier", style,
            0, 0, self._region.width, self._region.height,
            self._host, None, instance, None,
        )
        w.check(self._mag, "CreateWindowExW (magnifier)")

    def _apply_filter_list(self) -> None:
        """Exclude our own windows from what the magnifier reads.

        Without this the overlay reads its own output and feeds back into itself
        -- the transform would be applied again every frame.
        """
        handles = [h for h in (self._host, self._mag) if h]
        array = w.hwnd_array(handles)
        if not w.magnification.MagSetWindowFilterList(
            self._mag, w.MW_FILTERMODE_EXCLUDE, len(handles), array
        ):
            print(
                "umbra: warning -- could not exclude the overlay from its own "
                "capture. If the region flickers or darkens progressively, use "
                "full-screen mode instead.",
                file=sys.stderr,
            )

    # -- per-frame ---------------------------------------------------------

    def refresh(self) -> None:
        if not self._mag:
            return
        rect = w.RECT.from_bounds(
            self._region.x, self._region.y, self._region.width, self._region.height
        )
        w.magnification.MagSetWindowSource(self._mag, rect)
        w.user32.InvalidateRect(self._mag, None, True)

    # -- interface ---------------------------------------------------------

    def set_effect(self, matrix: Matrix) -> None:
        self._matrix = matrix
        if self._mag:
            effect = w.MAGCOLOREFFECT.from_matrix(matrix)
            w.check(w.magnification.MagSetColorEffect(self._mag, ctypes.byref(effect)),
                    "MagSetColorEffect")

    def set_region(self, region: Rect) -> None:
        self._region = region
        if self._host:
            w.user32.SetWindowPos(
                self._host, w.HWND_TOPMOST, region.x, region.y,
                region.width, region.height, w.SWP_NOACTIVATE | w.SWP_SHOWWINDOW,
            )
            w.user32.MoveWindow(self._mag, 0, 0, region.width, region.height, True)
            self.refresh()

    @property
    def region(self) -> Optional[Rect]:
        return self._region


def reset_fullscreen_effect() -> None:
    """Clear a stuck desktop colour effect, e.g. after a hard kill.

    Safe to call when nothing is applied.
    """
    w.require_windows()
    w.check(w.magnification.MagInitialize(), "MagInitialize")
    try:
        effect = w.MAGCOLOREFFECT.from_matrix(IDENTITY)
        w.magnification.MagSetFullscreenColorEffect(ctypes.byref(effect))
    finally:
        w.magnification.MagUninitialize()
