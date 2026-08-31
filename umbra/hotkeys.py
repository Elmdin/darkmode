"""System-wide hotkeys.

``RegisterHotKey(NULL, ...)`` posts ``WM_HOTKEY`` to the *thread* queue rather
than a window, so the same manager works for both engines -- including
full-screen mode, where there is no window of ours at all.
"""

from __future__ import annotations

import sys
from typing import Callable, Dict, List, Tuple

from . import winapi as w
from .config import describe_hotkey, parse_hotkey


class HotkeyManager:
    """Registers hotkeys and routes ``WM_HOTKEY`` back to named actions."""

    def __init__(self) -> None:
        self._actions: Dict[int, Tuple[str, Callable[[], None]]] = {}
        self._combos: Dict[str, str] = {}
        self._next_id = 1

    def register(self, action: str, combo: str, callback: Callable[[], None]) -> bool:
        """Bind one hotkey. Returns False (with a warning) if it is already taken.

        A clash is not fatal: another app owning Ctrl+Alt+D should cost you that
        one shortcut, not the whole tool.
        """
        try:
            mods, vk = parse_hotkey(combo)
        except ValueError as exc:
            print(f"umbra: {exc}", file=sys.stderr)
            return False

        hotkey_id = self._next_id
        if not w.user32.RegisterHotKey(None, hotkey_id, mods, vk):
            print(
                f"umbra: could not register {describe_hotkey(combo)} for '{action}' "
                "-- another application already owns it. Change it in the config "
                "file and restart.",
                file=sys.stderr,
            )
            return False

        self._next_id += 1
        self._actions[hotkey_id] = (action, callback)
        self._combos[action] = combo
        return True

    def register_all(self, bindings: Dict[str, str],
                     callbacks: Dict[str, Callable[[], None]]) -> List[str]:
        """Register every action that has both a binding and a callback."""
        registered = []
        for action, callback in callbacks.items():
            combo = bindings.get(action)
            if combo and self.register(action, combo, callback):
                registered.append(action)
        return registered

    def dispatch(self, hotkey_id: int) -> bool:
        """Invoke the action bound to ``hotkey_id``. Returns True if handled."""
        entry = self._actions.get(hotkey_id)
        if entry is None:
            return False
        _, callback = entry
        callback()
        return True

    def bindings(self) -> Dict[str, str]:
        return dict(self._combos)

    def unregister_all(self) -> None:
        for hotkey_id in list(self._actions):
            w.user32.UnregisterHotKey(None, hotkey_id)
        self._actions.clear()
        self._combos.clear()
