import ctypes
import threading

import pytest

from umbra import engines, hotkeys


class RecordingLib:
    """A ctypes-DLL stand-in that records calls and returns plausible handles."""

    def __init__(self, owner, fail_on):
        self._owner = owner
        self._fail_on = fail_on

    def __getattr__(self, name):
        def call(*args):
            self._owner.calls.append((name, args))
            if name in self._fail_on:
                return 0
            if name == "CreateWindowExW":
                self._owner.handle += 0x10
                return self._owner.handle
            if name == "GetMessageW":
                if self._owner.messages:
                    return self._owner.messages.pop(0)
                # block until the deadline timer posts WM_QUIT, like the real loop
                self._owner.quit_posted.wait(2.0)
                return 0
            if name == "PostThreadMessageW":
                self._owner.quit_posted.set()
            if name == "GetCurrentThreadId":
                return 4242
            if name == "GetModuleHandleW":
                return 0x400000
            if name == "GetStockObject":
                return 0x99
            if name in ("MagSetColorEffect", "MagSetFullscreenColorEffect"):
                self._owner.effects.append(args[-1])
            return 1
        return call


class FakeWin:
    """Enough of :mod:`umbra.winapi` to drive the engines and the app off Windows."""

    WM_TIMER, WM_DESTROY, WM_HOTKEY, WM_QUIT = 0x0113, 0x0002, 0x0312, 0x0012
    MW_FILTERMODE_EXCLUDE, BLACK_BRUSH = 0, 4
    WC_MAGNIFIER, SW_SHOWNA, HWND_TOPMOST = "Magnifier", 8, -1
    for _n in ("WS_POPUP", "WS_VISIBLE", "WS_CHILD", "WS_CLIPCHILDREN", "WS_EX_TOPMOST",
               "WS_EX_TRANSPARENT", "WS_EX_TOOLWINDOW", "WS_EX_LAYERED",
               "WS_EX_NOACTIVATE", "MS_SHOWMAGNIFIEDCURSOR", "LWA_ALPHA",
               "SWP_NOACTIVATE", "SWP_SHOWWINDOW"):
        locals()[_n] = 1
    del _n

    MSG = type("MSG", (ctypes.Structure,), {
        "_fields_": [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                     ("wParam", ctypes.c_size_t), ("lParam", ctypes.c_ssize_t)]})

    RECT = engines.w.RECT
    MAGCOLOREFFECT = engines.w.MAGCOLOREFFECT
    MAGTRANSFORM = engines.w.MAGTRANSFORM

    def __init__(self, fail_on=None):
        self.calls = []
        self.effects = []
        self.messages = []
        self.quit_posted = threading.Event()
        self.handle = 0x1000
        fail_on = fail_on or set()
        self.user32 = RecordingLib(self, fail_on)
        self.gdi32 = RecordingLib(self, fail_on)
        self.kernel32 = RecordingLib(self, fail_on)
        self.magnification = RecordingLib(self, fail_on)
        self.WNDPROC = ctypes.CFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
            ctypes.c_size_t, ctypes.c_ssize_t)
        self.WNDCLASSEXW = type("WNDCLASSEXW", (ctypes.Structure,), {
            "_fields_": [("cbSize", ctypes.c_uint), ("lpfnWndProc", self.WNDPROC),
                         ("hInstance", ctypes.c_void_p), ("hCursor", ctypes.c_void_p),
                         ("hbrBackground", ctypes.c_void_p),
                         ("lpszClassName", ctypes.c_wchar_p)]})

    # -- module-level functions -------------------------------------------
    def require_windows(self):
        pass

    def set_dpi_awareness(self):
        return "per-monitor-v2"

    def install_console_handler(self, callback):
        self.console_callback = callback
        return object()

    def virtual_screen(self):
        return self.RECT.from_bounds(0, 0, 1920, 1080)

    def check(self, ok, what):
        if not ok:
            raise OSError(f"{what} failed")

    def hwnd_array(self, handles):
        return (ctypes.c_void_p * len(handles))(*handles)

    # -- assertions --------------------------------------------------------
    def names(self):
        return [name for name, _ in self.calls]

    def count(self, name):
        return self.names().count(name)

    def last_matrix(self):
        """The most recent colour matrix pushed to the screen."""
        if not self.effects:
            return None
        effect = self.effects[-1]
        effect = effect._obj if hasattr(effect, "_obj") else effect
        return [[effect.transform[i][j] for j in range(5)] for i in range(5)]


@pytest.fixture
def win(monkeypatch):
    """A stubbed Win32 layer wired into both the engines and the app."""
    fake = FakeWin()
    monkeypatch.setattr(engines, "w", fake)
    monkeypatch.setattr(hotkeys, "w", fake)
    monkeypatch.setattr(engines, "_class_registered", False)
    monkeypatch.setattr(engines, "_engines_by_host", {})
    monkeypatch.setattr(engines._MagnificationRuntime, "_depth", 0)
    return fake
