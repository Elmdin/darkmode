import pytest

from umbra.config import DEFAULT_HOTKEYS
from umbra.hotkeys import HotkeyManager


@pytest.fixture
def manager(win):
    return HotkeyManager()


def test_registering_binds_and_dispatches(manager, win):
    fired = []
    assert manager.register("toggle", "ctrl+alt+d", lambda: fired.append(1))
    assert win.count("RegisterHotKey") == 1
    hotkey_id = [args[1] for name, args in win.calls if name == "RegisterHotKey"][0]
    assert manager.dispatch(hotkey_id) is True
    assert fired == [1]


def test_dispatching_an_unknown_id_is_ignored(manager):
    assert manager.dispatch(999) is False


def test_a_malformed_combo_is_reported_not_raised(manager, capsys):
    assert manager.register("toggle", "not a hotkey", lambda: None) is False
    assert "needs at least one modifier" in capsys.readouterr().err
    assert manager.register("toggle", "ctrl+alt+notakey", lambda: None) is False
    assert "unknown key" in capsys.readouterr().err


def test_a_taken_hotkey_is_reported_and_skipped(monkeypatch, win, capsys):
    from umbra import hotkeys as module
    fake = type(win)(fail_on={"RegisterHotKey"})
    monkeypatch.setattr(module, "w", fake)
    assert HotkeyManager().register("toggle", "ctrl+alt+d", lambda: None) is False
    assert "already owns it" in capsys.readouterr().err


def test_register_all_binds_every_default(manager, win):
    callbacks = {action: (lambda: None) for action in DEFAULT_HOTKEYS}
    assert sorted(manager.register_all(DEFAULT_HOTKEYS, callbacks)) == sorted(DEFAULT_HOTKEYS)
    assert manager.bindings() == DEFAULT_HOTKEYS


def test_register_all_skips_actions_with_no_binding(manager):
    registered = manager.register_all({"toggle": "ctrl+alt+d"},
                                      {"toggle": lambda: None, "quit": lambda: None})
    assert registered == ["toggle"]


def test_ids_are_unique_across_registrations(manager, win):
    for action, combo in list(DEFAULT_HOTKEYS.items())[:4]:
        manager.register(action, combo, lambda: None)
    ids = [args[1] for name, args in win.calls if name == "RegisterHotKey"]
    assert len(set(ids)) == len(ids)


def test_unregister_all_releases_every_hotkey(manager, win):
    for action, combo in list(DEFAULT_HOTKEYS.items())[:3]:
        manager.register(action, combo, lambda: None)
    manager.unregister_all()
    assert win.count("UnregisterHotKey") == 3
    assert manager.bindings() == {}
    assert manager.dispatch(1) is False
