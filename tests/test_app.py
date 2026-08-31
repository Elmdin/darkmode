"""The app's state machine: what it does when you press the hotkeys."""
import pytest

from umbra import app as app_module
from umbra import engines
from umbra.colormatrix import apply, is_identity
from umbra.config import Config
from umbra.geometry import Rect
from umbra.transforms import PRESETS, build


@pytest.fixture
def make_app(win, monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "w", win)
    monkeypatch.setattr(app_module, "save_config", lambda *a, **k: None)

    def factory(**config_kwargs):
        return app_module.UmbraApp(Config(**config_kwargs), persist=False)
    return factory


def _select(monkeypatch, rect):
    monkeypatch.setattr(app_module, "select_in_subprocess", lambda *a, **k: rect)


# ---------------------------------------------------------------- reconcile

def test_starting_enabled_applies_the_effect(make_app, win):
    app = make_app()
    app._reconcile()
    assert isinstance(app._engine, engines.FullscreenEngine)
    assert apply(win.last_matrix(), (1, 1, 1))[0] < 0.2, "white should be dark now"


def test_starting_disabled_touches_nothing(make_app, win):
    app = make_app(start_enabled=False)
    app._reconcile()
    assert app._engine is None
    assert win.count("MagInitialize") == 0


def test_toggle_off_restores_the_screen(make_app, win):
    app = make_app()
    app._reconcile()
    app.toggle()
    assert app.enabled is False
    assert is_identity(win.last_matrix()), "screen left transformed after toggling off"


def test_toggle_round_trip_reapplies(make_app, win):
    app = make_app()
    app._reconcile()
    app.toggle()
    app.toggle()
    assert app.enabled is True
    assert not is_identity(win.last_matrix())


def test_region_mode_without_a_region_falls_back_to_fullscreen(make_app):
    app = make_app()
    app.mode = "region"          # e.g. a stale config
    app.region = None
    app._reconcile()
    assert app.mode == "fullscreen"
    assert isinstance(app._engine, engines.FullscreenEngine)


def test_switching_modes_swaps_the_engine_and_balances_the_runtime(make_app, win):
    app = make_app(mode="region", region=Rect(0, 0, 200, 200))
    app._reconcile()
    assert isinstance(app._engine, engines.RegionEngine)
    app.use_fullscreen()
    assert isinstance(app._engine, engines.FullscreenEngine)
    assert engines._MagnificationRuntime._depth == 1, "runtime leaked on mode switch"


def test_reconcile_reports_failures_instead_of_crashing(make_app, monkeypatch, capsys):
    app = make_app()
    monkeypatch.setattr(app, "_reconcile",
                        lambda: (_ for _ in ()).throw(OSError("magnifier busy")))
    app._reconcile_safely()
    assert "magnifier busy" in capsys.readouterr().err


# ---------------------------------------------------------------- region choice

def test_choosing_a_region_switches_mode_and_clamps_to_the_desktop(make_app, monkeypatch):
    app = make_app()
    _select(monkeypatch, Rect(1800, 1000, 400, 400))   # runs off the 1920x1080 edge
    app.choose_region()
    assert app.mode == "region"
    assert app.region == Rect(1800, 1000, 120, 80)
    assert app.enabled is True


def test_cancelling_the_selector_leaves_everything_alone(make_app, monkeypatch):
    app = make_app(mode="region", region=Rect(10, 10, 100, 100))
    app._reconcile()
    _select(monkeypatch, None)
    app.choose_region()
    assert app.region == Rect(10, 10, 100, 100)
    assert app.enabled is True


def test_a_region_entirely_off_screen_is_refused(make_app, monkeypatch, capsys):
    app = make_app()
    _select(monkeypatch, Rect(9000, 9000, 100, 100))
    app.choose_region()
    assert app.mode == "fullscreen"
    assert "outside" in capsys.readouterr().err


def test_effect_is_dropped_while_the_selector_is_open(make_app, win, monkeypatch):
    """Dragging a rectangle through an inverted screen is disorienting."""
    app = make_app()
    app._reconcile()
    seen = {}

    def selector(*_a, **_k):
        seen["engine_running"] = app._engine is not None
        return Rect(0, 0, 100, 100)

    monkeypatch.setattr(app_module, "select_in_subprocess", selector)
    app.choose_region()
    assert seen["engine_running"] is False


# ---------------------------------------------------------------- look

def test_cycling_presets_wraps_and_applies(make_app, win):
    app = make_app()
    app._reconcile()
    first = app.preset
    for _ in range(len(PRESETS)):
        app.cycle_preset(1)
    assert app.preset == first
    assert app.params == PRESETS[first]


def test_cycling_onto_off_disables_the_effect(make_app, win):
    app = make_app(preset="negative")
    app._reconcile()
    while app.preset != "off":
        app.cycle_preset(1)
    assert app.enabled is False
    assert is_identity(win.last_matrix())


def test_nudging_strength_is_clamped_at_both_ends(make_app, win):
    app = make_app()
    app._reconcile()
    for _ in range(30):
        app.nudge("strength", 0.1)
    assert app.params.strength == 1.0
    for _ in range(30):
        app.nudge("strength", -0.1)
    assert app.params.strength == 0.0
    assert app.enabled is False, "zero strength means the effect is off"
    assert is_identity(win.last_matrix())


def test_nudging_contrast_changes_the_applied_matrix(make_app, win):
    app = make_app()
    app._reconcile()
    before = win.last_matrix()
    app.nudge("contrast", 0.05)
    assert win.last_matrix() != before
    assert app.params.contrast == pytest.approx(1.05)


def test_warmth_cycles_through_its_stops_and_wraps(make_app, win):
    app = make_app()
    app._reconcile()
    seen = []
    for _ in range(len(app_module._WARMTH_CYCLE) + 1):
        app.cycle_warmth()
        seen.append(app.params.warmth)
    assert seen[:len(app_module._WARMTH_CYCLE) - 1] == list(app_module._WARMTH_CYCLE[1:])
    assert seen[-1] in app_module._WARMTH_CYCLE


def test_the_applied_matrix_matches_the_current_params(make_app, win):
    app = make_app(preset="vivid")
    app._reconcile()
    expected = build(app.params)
    for row, want in zip(win.last_matrix(), expected):
        assert row == pytest.approx(want, abs=1e-6)


# ---------------------------------------------------------------- run / shutdown

def test_run_applies_then_restores_on_quit(make_app, win):
    app = make_app()
    win.messages = [0]           # GetMessageW returns 0 -> WM_QUIT immediately
    assert app.run() == 0
    assert is_identity(win.last_matrix()), "screen not restored on exit"
    assert win.count("MagUninitialize") == 1
    assert win.count("UnregisterHotKey") >= 1


def test_run_restores_even_when_the_loop_raises(make_app, win, monkeypatch):
    app = make_app()
    monkeypatch.setattr(app, "_message_loop",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert app.run() == 1
    assert is_identity(win.last_matrix())
    assert win.count("MagUninitialize") == 1


def test_console_close_handler_restores_the_screen(make_app, win):
    app = make_app()
    app._reconcile()
    app._console_handler = win.install_console_handler(app._emergency_reset)
    win.console_callback()
    assert is_identity(win.last_matrix())


def test_emergency_reset_never_raises(make_app, win, monkeypatch):
    app = make_app()
    app._reconcile()
    monkeypatch.setattr(app._engine, "set_effect",
                        lambda _m: (_ for _ in ()).throw(OSError("gone")))
    app._emergency_reset()       # must swallow everything


def test_quit_posts_a_quit_message(make_app, win):
    app = make_app()
    app.quit()
    assert win.count("PostQuitMessage") == 1


def test_current_config_captures_live_state(make_app, monkeypatch):
    app = make_app()
    _select(monkeypatch, Rect(5, 5, 300, 200))
    app.choose_region()
    app.cycle_preset(1)
    saved = app._current_config()
    assert saved.mode == "region" and saved.region == Rect(5, 5, 300, 200)
    assert saved.preset == app.preset and saved.params == app.params


def test_banner_survives_a_config_missing_hotkeys(make_app, capsys):
    app = make_app(hotkeys={"toggle": "ctrl+alt+d"})
    app._print_banner()
    out = capsys.readouterr().out
    assert "Ctrl+Alt+D" in out and "?" in out


# ---------------------------------------------------------------- auto-quit

def test_duration_posts_a_quit_to_the_loop_thread(make_app, win):
    """PostQuitMessage only works on the loop's own thread, so the deadline
    timer must post WM_QUIT to that thread by id instead."""
    app = make_app()
    app.duration = 0.01
    win.messages = []
    assert app.run() == 0
    posted = [args for name, args in win.calls if name == "PostThreadMessageW"]
    assert posted and posted[0][1] == win.WM_QUIT


def test_no_duration_arms_no_timer(make_app, win):
    app = make_app()
    win.messages = [0]
    app.run()
    assert app._deadline is None
    assert win.count("PostThreadMessageW") == 0


def test_deadline_is_cancelled_on_shutdown(make_app, win):
    app = make_app()
    app.duration = 60
    win.messages = [0]
    app.run()
    # Timer.cancel() sets the finished event; the thread may take a moment
    # longer to actually exit, so assert on the event rather than is_alive().
    assert app._deadline is not None
    assert app._deadline.finished.is_set()
