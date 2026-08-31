"""Thin ctypes bindings for the Win32 and Magnification APIs.

Deliberately dependency-free: the whole tool runs on a stock Windows Python with
nothing installed. Importing this module on a non-Windows host raises
:class:`NotWindows` rather than failing at import time on ``ctypes.WinDLL``, so
the colour pipeline stays testable everywhere.
"""

from __future__ import annotations

import ctypes
import platform
import struct
import sys
from ctypes import POINTER, Structure, c_float, c_int, c_uint, c_void_p
from typing import Callable, Optional, Sequence


class NotWindows(RuntimeError):
    """Raised when the Windows-only layer is used off Windows."""


IS_WINDOWS = sys.platform == "win32"
IS_64BIT = struct.calcsize("P") * 8 == 64

if IS_WINDOWS:
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    magnification = ctypes.WinDLL("magnification", use_last_error=True)
else:  # pragma: no cover - exercised only on Windows
    wintypes = None  # type: ignore[assignment]
    user32 = kernel32 = gdi32 = magnification = None  # type: ignore[assignment]


def require_windows() -> None:
    if not IS_WINDOWS:
        raise NotWindows(
            "Umbra drives the Windows Magnification API and only runs on Windows. "
            f"This interpreter is {platform.system() or sys.platform}."
        )
    if not IS_64BIT:
        raise NotWindows(
            "The Magnification API is not supported under WOW64 -- a 32-bit "
            "process cannot magnify on 64-bit Windows. Re-run with 64-bit Python."
        )


# --------------------------------------------------------------------------- constants

WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_CHILD = 0x40000000
WS_CLIPCHILDREN = 0x02000000

WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000

MS_SHOWMAGNIFIEDCURSOR = 0x0001
MS_INVERTCOLORS = 0x0004

WC_MAGNIFIER = "Magnifier"
MW_FILTERMODE_EXCLUDE = 0
MW_FILTERMODE_INCLUDE = 1

LWA_ALPHA = 0x00000002

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_QUIT = 0x0012
WM_TIMER = 0x0113
WM_HOTKEY = 0x0312

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

BLACK_BRUSH = 4
SW_SHOWNA = 8
SW_HIDE = 0

HWND_TOPMOST = -1
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002

SM_CXSCREEN, SM_CYSCREEN = 0, 1
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)

CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT = 0, 1, 2
CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT = 5, 6

# Virtual key codes used by the default hotkeys.
VK = {
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "[": 0xDB, "]": 0xDD, "esc": 0x1B, "space": 0x20,
    **{chr(c): c for c in range(0x30, 0x3A)},   # 0-9
    **{chr(c).lower(): c for c in range(0x41, 0x5B)},  # a-z
}


# --------------------------------------------------------------------------- structs

class RECT(Structure):
    _fields_ = [("left", c_int), ("top", c_int), ("right", c_int), ("bottom", c_int)]

    @classmethod
    def from_bounds(cls, x: int, y: int, width: int, height: int) -> "RECT":
        return cls(int(x), int(y), int(x) + int(width), int(y) + int(height))

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


class MAGCOLOREFFECT(Structure):
    """The 5x5 row-major colour matrix the magnifier applies."""
    _fields_ = [("transform", c_float * 5 * 5)]

    @classmethod
    def from_matrix(cls, matrix: Sequence[Sequence[float]]) -> "MAGCOLOREFFECT":
        effect = cls()
        for i in range(5):
            for j in range(5):
                effect.transform[i][j] = c_float(float(matrix[i][j]))
        return effect


class MAGTRANSFORM(Structure):
    """3x3 scale transform; identity means 1.0x, which is what we always want."""
    _fields_ = [("transform", c_float * 3 * 3)]

    @classmethod
    def scale(cls, factor: float = 1.0) -> "MAGTRANSFORM":
        t = cls()
        t.transform[0][0] = c_float(factor)
        t.transform[1][1] = c_float(factor)
        t.transform[2][2] = c_float(1.0)
        return t


if IS_WINDOWS:
    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, wintypes.HWND, c_uint, ctypes.c_size_t, ctypes.c_ssize_t
    )
    HANDLER_ROUTINE = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.DWORD)
    MSG = wintypes.MSG

    class WNDCLASSEXW(Structure):
        _fields_ = [
            ("cbSize", c_uint), ("style", c_uint), ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", c_int), ("cbWndExtra", c_int),
            ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    def _bind() -> None:
        u, m, k = user32, magnification, kernel32
        u.RegisterClassExW.argtypes = [POINTER(WNDCLASSEXW)]
        u.RegisterClassExW.restype = wintypes.ATOM
        u.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            c_int, c_int, c_int, c_int, wintypes.HWND, wintypes.HMENU,
            wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        u.CreateWindowExW.restype = wintypes.HWND
        u.DefWindowProcW.argtypes = [wintypes.HWND, c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        u.DestroyWindow.argtypes = [wintypes.HWND]
        u.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
        u.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, c_int, c_int, c_int, c_int, c_uint]
        u.MoveWindow.argtypes = [wintypes.HWND, c_int, c_int, c_int, c_int, wintypes.BOOL]
        u.InvalidateRect.argtypes = [wintypes.HWND, POINTER(RECT), wintypes.BOOL]
        u.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, c_uint, wintypes.LPVOID]
        u.SetTimer.restype = ctypes.c_size_t
        u.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
        u.RegisterHotKey.argtypes = [wintypes.HWND, c_int, c_uint, c_uint]
        u.UnregisterHotKey.argtypes = [wintypes.HWND, c_int]
        u.GetMessageW.argtypes = [POINTER(wintypes.MSG), wintypes.HWND, c_uint, c_uint]
        u.GetMessageW.restype = c_int
        u.PeekMessageW.argtypes = [POINTER(wintypes.MSG), wintypes.HWND, c_uint, c_uint, c_uint]
        u.TranslateMessage.argtypes = [POINTER(wintypes.MSG)]
        u.DispatchMessageW.argtypes = [POINTER(wintypes.MSG)]
        u.DispatchMessageW.restype = ctypes.c_ssize_t
        u.GetSystemMetrics.argtypes = [c_int]
        u.GetSystemMetrics.restype = c_int
        u.LoadCursorW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR]
        u.LoadCursorW.restype = wintypes.HANDLE
        u.ShowWindow.argtypes = [wintypes.HWND, c_int]
        u.UpdateWindow.argtypes = [wintypes.HWND]
        u.PostQuitMessage.argtypes = [c_int]
        u.PostThreadMessageW.argtypes = [
            wintypes.DWORD, c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
        u.GetParent.argtypes = [wintypes.HWND]
        u.GetParent.restype = wintypes.HWND
        gdi32.GetStockObject.argtypes = [c_int]
        gdi32.GetStockObject.restype = wintypes.HGDIOBJ

        m.MagInitialize.restype = wintypes.BOOL
        m.MagUninitialize.restype = wintypes.BOOL
        m.MagSetFullscreenColorEffect.argtypes = [POINTER(MAGCOLOREFFECT)]
        m.MagSetFullscreenColorEffect.restype = wintypes.BOOL
        m.MagGetFullscreenColorEffect.argtypes = [POINTER(MAGCOLOREFFECT)]
        m.MagGetFullscreenColorEffect.restype = wintypes.BOOL
        m.MagSetColorEffect.argtypes = [wintypes.HWND, POINTER(MAGCOLOREFFECT)]
        m.MagSetColorEffect.restype = wintypes.BOOL
        m.MagSetWindowSource.argtypes = [wintypes.HWND, RECT]
        m.MagSetWindowSource.restype = wintypes.BOOL
        m.MagSetWindowTransform.argtypes = [wintypes.HWND, POINTER(MAGTRANSFORM)]
        m.MagSetWindowTransform.restype = wintypes.BOOL
        m.MagSetWindowFilterList.argtypes = [
            wintypes.HWND, wintypes.DWORD, c_int, POINTER(wintypes.HWND)]
        m.MagSetWindowFilterList.restype = wintypes.BOOL

        k.GetCurrentThreadId.restype = wintypes.DWORD
        k.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        k.GetModuleHandleW.restype = wintypes.HMODULE
        k.SetConsoleCtrlHandler.argtypes = [HANDLER_ROUTINE, wintypes.BOOL]

    _bind()
else:  # pragma: no cover
    WNDPROC = HANDLER_ROUTINE = MSG = None  # type: ignore[assignment]
    WNDCLASSEXW = None  # type: ignore[assignment]


# --------------------------------------------------------------------------- helpers

def check(ok: object, what: str) -> None:
    """Raise a readable OSError when a Win32 call reports failure."""
    if not ok:
        err = ctypes.get_last_error()
        detail = ctypes.WinError(err).strerror if err else "no error code reported"
        raise OSError(f"{what} failed: {detail} (code {err})")


def set_dpi_awareness() -> str:
    """Opt into physical pixels so region coordinates mean what they say.

    Returns the mechanism that worked, for ``umbra doctor``.
    """
    try:
        user32.SetProcessDpiAwarenessContext.argtypes = [c_void_p]
        if user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    try:  # Windows 8.1
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        if shcore.SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:
        user32.SetProcessDPIAware()
        return "system"
    except (AttributeError, OSError):
        return "none"


def virtual_screen() -> RECT:
    """Bounding box of every monitor, in physical pixels."""
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return RECT.from_bounds(x, y, w, h)


def primary_screen() -> RECT:
    return RECT.from_bounds(
        0, 0, user32.GetSystemMetrics(SM_CXSCREEN), user32.GetSystemMetrics(SM_CYSCREEN)
    )


def hwnd_array(handles: Sequence[int]):
    """A ``HWND[]`` for MagSetWindowFilterList."""
    array_type = wintypes.HWND * len(handles)
    return array_type(*[wintypes.HWND(h) for h in handles])


def install_console_handler(callback: Callable[[], None]) -> Optional[object]:
    """Run ``callback`` when the console is closed or Ctrl+C'd.

    Without this, killing the window leaves the desktop colour effect applied,
    which looks like a broken monitor. The returned object must be kept alive.
    """
    def handler(event: int) -> int:
        if event in (CTRL_C_EVENT, CTRL_BREAK_EVENT, CTRL_CLOSE_EVENT,
                     CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT):
            try:
                callback()
            except Exception:
                pass
        return 0  # let default processing continue to terminate us

    routine = HANDLER_ROUTINE(handler)
    try:
        kernel32.SetConsoleCtrlHandler(routine, True)
    except OSError:
        return None
    return routine
