"""Engine lifecycle, exercised off-Windows with a stubbed Win32 layer.

These cover the bugs that are invisible until you switch modes twice on a real
machine: a window procedure bound to a dead engine, and an unbalanced
MagInitialize/MagUninitialize pair.
"""
import ctypes

import pytest

from tests.conftest import FakeWin

from umbra import engines
from umbra.colormatrix import IDENTITY, is_identity
from umbra.geometry import Rect
from umbra.transforms import preset


# ---------------------------------------------------------------- fullscreen

def test_fullscreen_applies_and_restores(win):
    engine = engines.FullscreenEngine()
    engine.start()
    engine.set_effect(preset("dark"))
    assert win.count("MagInitialize") == 1
    engine.stop()
    assert win.count("MagUninitialize") == 1
    # the last effect pushed must be the identity, or the desktop stays inverted
    final = win.effects[-1]._obj if hasattr(win.effects[-1], "_obj") else win.effects[-1]
    assert is_identity([[final.transform[i][j] for j in range(5)] for i in range(5)])


def test_fullscreen_stop_is_idempotent(win):
    engine = engines.FullscreenEngine()
    engine.start()
    engine.stop()
    engine.stop()
    assert win.count("MagUninitialize") == 1


def test_fullscreen_cannot_be_started_twice(win):
    engine = engines.FullscreenEngine()
    engine.start()
    with pytest.raises(RuntimeError):
        engine.start()


def test_set_effect_before_start_is_refused(win):
    with pytest.raises(RuntimeError):
        engines.FullscreenEngine().set_effect(IDENTITY)


def test_refused_fullscreen_effect_explains_the_likely_cause(monkeypatch):
    fake = FakeWin(fail_on={"MagSetFullscreenColorEffect"})
    monkeypatch.setattr(engines, "w", fake)
    monkeypatch.setattr(engines._MagnificationRuntime, "_depth", 0)
    engine = engines.FullscreenEngine()
    engine.start()
    with pytest.raises(OSError) as exc:
        engine.set_effect(preset("dark"))
    assert "Colour filters" in str(exc.value) or "Magnifier" in str(exc.value)


# ---------------------------------------------------------------- region

def test_region_engine_creates_host_and_magnifier(win):
    engine = engines.RegionEngine(Rect(10, 20, 300, 200))
    engine.start()
    assert win.count("CreateWindowExW") == 2
    assert win.count("MagSetWindowTransform") == 1
    assert win.count("MagSetWindowFilterList") == 1   # must exclude its own windows
    assert win.count("SetTimer") == 1
    engine.stop()
    assert win.count("KillTimer") == 1
    assert win.count("DestroyWindow") == 1


def test_region_stop_is_idempotent(win):
    engine = engines.RegionEngine(Rect(0, 0, 100, 100))
    engine.start()
    engine.stop()
    engine.stop()
    assert win.count("MagUninitialize") == 1, "runtime released twice"


def test_failed_start_leaves_the_runtime_balanced(monkeypatch):
    """start() cleans up after itself, and the caller's stop() must not double-release."""
    fake = FakeWin(fail_on={"CreateWindowExW"})
    monkeypatch.setattr(engines, "w", fake)
    monkeypatch.setattr(engines, "_class_registered", False)
    monkeypatch.setattr(engines, "_engines_by_host", {})
    monkeypatch.setattr(engines._MagnificationRuntime, "_depth", 0)

    engine = engines.RegionEngine(Rect(0, 0, 100, 100))
    with pytest.raises(OSError):
        engine.start()
    engine.stop()
    assert fake.count("MagUninitialize") == 1
    assert engines._MagnificationRuntime._depth == 0


def test_runtime_is_shared_while_engines_overlap(win):
    a, b = engines.FullscreenEngine(), engines.RegionEngine(Rect(0, 0, 50, 50))
    a.start()
    b.start()
    assert win.count("MagInitialize") == 1
    a.stop()
    assert win.count("MagUninitialize") == 0, "torn down while still in use"
    b.stop()
    assert win.count("MagUninitialize") == 1


def test_set_region_moves_both_windows(win):
    engine = engines.RegionEngine(Rect(0, 0, 100, 100))
    engine.start()
    before = win.count("SetWindowPos")
    engine.set_region(Rect(400, 300, 640, 480))
    assert engine.region == Rect(400, 300, 640, 480)
    assert win.count("SetWindowPos") == before + 1
    assert win.count("MoveWindow") >= 1


def test_refresh_reads_the_current_region(win):
    engine = engines.RegionEngine(Rect(5, 6, 70, 80))
    engine.start()
    engine.refresh()
    rects = [args[1] for name, args in win.calls if name == "MagSetWindowSource"]
    assert rects, "the magnifier must be told which rectangle to read"
    last = rects[-1]
    assert (last.left, last.top, last.right, last.bottom) == (5, 6, 75, 86)


# ---------------------------------------------------------------- window procedure

def test_timer_reaches_the_engine_that_owns_the_window(win):
    """The regression: a second RegionEngine must still receive its timer ticks.

    The window class is registered once per process, so a procedure that closed
    over the first engine would leave every later overlay frozen.
    """
    first = engines.RegionEngine(Rect(0, 0, 100, 100))
    first.start()
    first.stop()

    second = engines.RegionEngine(Rect(200, 200, 300, 300))
    second.start()
    win.calls.clear()

    engines._host_wndproc(second._host, engines.w.WM_TIMER, 0, 0)
    assert win.count("MagSetWindowSource") == 1, "timer did not reach the live engine"


def test_timer_for_an_unknown_window_is_ignored(win):
    engines._host_wndproc(0xDEAD, engines.w.WM_TIMER, 0, 0)
    assert win.count("MagSetWindowSource") == 0


def test_destroy_forgets_the_engine(win):
    engine = engines.RegionEngine(Rect(0, 0, 100, 100))
    engine.start()
    host = engine._host
    engines._host_wndproc(host, engines.w.WM_DESTROY, 0, 0)
    assert host not in engines._engines_by_host


@pytest.mark.parametrize("handle,expected", [(None, 0), (0, 0), (0x1234, 0x1234)])
def test_handle_key_normalises(handle, expected):
    assert engines._handle_key(handle) == expected


def test_handle_key_accepts_a_ctypes_pointer():
    assert engines._handle_key(ctypes.c_void_p(0x5678)) == 0x5678
