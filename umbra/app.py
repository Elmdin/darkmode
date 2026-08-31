"""Orchestration: state, engine selection, hotkeys, and the message loop.

The app owns the *desired* state (on/off, mode, region, colour params) and
reconciles the engine to it. Engines are swapped, never mutated into a different
kind, so full-screen and region modes stay independent of each other.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import traceback
from typing import Callable, Dict, Optional

from . import winapi as w
from .colormatrix import IDENTITY
from .config import Config, describe_hotkey, save as save_config
from .engines import (
    Engine, FullscreenEngine, RegionEngine, reset_fullscreen_effect,
)
from .geometry import Rect
from .hotkeys import HotkeyManager
from .region_select import select_in_subprocess
from .transforms import PRESETS, build, clamp_param, next_preset

_STEP_STRENGTH = 0.1
_STEP_CONTRAST = 0.05
_WARMTH_CYCLE = (0.0, 0.25, 0.5, 0.8)


class UmbraApp:
    """Runs until the quit hotkey, then restores the screen."""

    def __init__(self, config: Config, persist: bool = True,
                 duration: Optional[float] = None) -> None:
        self.config = config
        self.persist = persist
        self.duration = duration
        self.enabled = config.start_enabled
        self.mode = config.mode
        self.region: Optional[Rect] = config.region
        self.preset = config.preset
        self.params = config.params
        self._engine: Optional[Engine] = None
        self._hotkeys = HotkeyManager()
        self._console_handler = None
        self._quitting = False
        self._deadline: Optional[threading.Timer] = None

    # -- lifecycle ---------------------------------------------------------

    def run(self) -> int:
        w.require_windows()
        w.set_dpi_awareness()
        # Registered before anything is applied: if the console is closed with
        # the X button, this is the only thing standing between the user and a
        # permanently inverted desktop.
        self._console_handler = w.install_console_handler(self._emergency_reset)
        try:
            self._reconcile()
            self._bind_hotkeys()
            self._print_banner()
            self._arm_deadline()
            return self._message_loop()
        except Exception:
            traceback.print_exc()
            return 1
        finally:
            self._shutdown()

    def _arm_deadline(self) -> None:
        """Quit on our own after ``duration`` seconds, for unattended testing.

        The timer fires on a worker thread, and PostQuitMessage only works on the
        thread that owns the message loop -- so post WM_QUIT to that thread by id
        instead.
        """
        if not self.duration:
            return
        thread_id = w.kernel32.GetCurrentThreadId()
        print(f"  quitting automatically in {self.duration:g}s", flush=True)

        def expire() -> None:
            w.user32.PostThreadMessageW(thread_id, w.WM_QUIT, 0, 0)

        self._deadline = threading.Timer(self.duration, expire)
        self._deadline.daemon = True
        self._deadline.start()

    def _shutdown(self) -> None:
        if self._deadline:
            self._deadline.cancel()
        self._hotkeys.unregister_all()
        self._stop_engine()
        if self.persist:
            try:
                save_config(self._current_config())
            except OSError as exc:
                print(f"umbra: could not save config: {exc}", file=sys.stderr)

    def _emergency_reset(self) -> None:
        """Last-ditch restore when the process is being torn down.

        This runs on the console-control thread, not the main one, so it also
        falls back to a self-contained reset that does its own MagInitialize --
        leaving the desktop inverted after a window close would look like a
        broken monitor.
        """
        for attempt in (lambda: self._engine and self._engine.set_effect(IDENTITY),
                        self._stop_engine,
                        reset_fullscreen_effect):
            try:
                attempt()
            except Exception:
                pass

    def _current_config(self) -> Config:
        return self.config.replace(
            mode=self.mode, region=self.region, preset=self.preset,
            params=self.params, start_enabled=self.enabled,
        )

    # -- engine reconciliation --------------------------------------------

    def _stop_engine(self) -> None:
        if self._engine:
            try:
                self._engine.stop()
            finally:
                self._engine = None

    def _reconcile(self) -> None:
        """Make the running engine match the desired state."""
        if not self.enabled:
            self._stop_engine()
            return

        wanted = self.mode
        if wanted == "region" and self.region is None:
            print("umbra: no region chosen yet; staying full screen", file=sys.stderr)
            wanted = self.mode = "fullscreen"

        current = self._engine.name if self._engine else None
        if current != wanted:
            self._stop_engine()
            if wanted == "fullscreen":
                self._engine = FullscreenEngine()
            else:
                assert self.region is not None
                self._engine = RegionEngine(
                    self.region, fps=self.config.fps,
                    show_cursor=self.config.show_cursor,
                )
            self._engine.start()

        assert self._engine is not None
        if wanted == "region" and self.region is not None:
            self._engine.set_region(self.region)
        self._engine.set_effect(build(self.params))

    def _reconcile_safely(self) -> None:
        """Reconcile, reporting failures instead of killing the message loop."""
        try:
            self._reconcile()
        except OSError as exc:
            print(f"umbra: {exc}", file=sys.stderr)

    # -- actions -----------------------------------------------------------

    def toggle(self) -> None:
        self.enabled = not self.enabled
        self._reconcile_safely()
        self._status("on" if self.enabled else "off")

    def use_fullscreen(self) -> None:
        self.mode = "fullscreen"
        self.enabled = True
        self._reconcile_safely()
        self._status("full screen")

    def choose_region(self) -> None:
        # Drop the effect first: selecting a region through an inverted screen
        # is disorienting, and the selector's own window would be transformed.
        was_enabled = self.enabled
        self.enabled = False
        self._reconcile_safely()

        rect = select_in_subprocess()
        if rect is None:
            self.enabled = was_enabled
            self._reconcile_safely()
            self._status("region unchanged")
            return

        try:
            rect = rect.clamped_to(_virtual_rect())
        except ValueError as exc:
            print(f"umbra: {exc}", file=sys.stderr)
            self.enabled = was_enabled
            self._reconcile_safely()
            return

        self.region = rect
        self.mode = "region"
        self.enabled = True
        self._reconcile_safely()
        self._status(f"region {rect.describe()}")

    def cycle_preset(self, step: int = 1) -> None:
        self.preset = next_preset(self.preset, step)
        self.params = PRESETS[self.preset]
        self.enabled = self.params.strength > 0
        self._reconcile_safely()
        self._status(f"preset {self.preset}")

    def nudge(self, field: str, delta: float) -> None:
        """Adjust one colour parameter, clamped to its valid range."""
        value = clamp_param(field, getattr(self.params, field) + delta)
        self.params = self.params.replace(**{field: value})
        self.enabled = self.params.strength > 0
        self._reconcile_safely()
        self._status(f"{field.replace('_', ' ')} {value:g}")

    def cycle_warmth(self) -> None:
        current = self.params.warmth
        nxt = next((v for v in _WARMTH_CYCLE if v > current + 1e-6), _WARMTH_CYCLE[0])
        self.params = self.params.replace(warmth=nxt)
        self._reconcile_safely()
        self._status(f"warmth {nxt:g}")

    def quit(self) -> None:
        self._quitting = True
        w.user32.PostQuitMessage(0)

    # -- hotkeys and loop --------------------------------------------------

    def _callbacks(self) -> Dict[str, Callable[[], None]]:
        return {
            "toggle": self.toggle,
            "fullscreen": self.use_fullscreen,
            "select_region": self.choose_region,
            "next_preset": lambda: self.cycle_preset(1),
            "prev_preset": lambda: self.cycle_preset(-1),
            "strength_up": lambda: self.nudge("strength", _STEP_STRENGTH),
            "strength_down": lambda: self.nudge("strength", -_STEP_STRENGTH),
            "contrast_up": lambda: self.nudge("contrast", _STEP_CONTRAST),
            "contrast_down": lambda: self.nudge("contrast", -_STEP_CONTRAST),
            "warmth": self.cycle_warmth,
            "quit": self.quit,
        }

    def _bind_hotkeys(self) -> None:
        registered = self._hotkeys.register_all(self.config.hotkeys, self._callbacks())
        if "quit" not in registered:
            print("umbra: the quit hotkey is unavailable -- close this window to exit "
                  "(the screen will be restored).", file=sys.stderr)

    def _message_loop(self) -> int:
        msg = w.MSG()
        while True:
            got = w.user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if got == 0:            # WM_QUIT
                return 0
            if got == -1:           # error
                raise OSError("GetMessageW failed")
            if msg.message == w.WM_HOTKEY:
                try:
                    self._hotkeys.dispatch(msg.wParam)
                except Exception:
                    traceback.print_exc()
                continue
            w.user32.TranslateMessage(ctypes.byref(msg))
            w.user32.DispatchMessageW(ctypes.byref(msg))

    # -- console output ----------------------------------------------------

    def _status(self, message: str) -> None:
        where = self.region.describe() if self.mode == "region" and self.region else "whole screen"
        state = "on" if self.enabled else "off"
        print(f"  {message:<28} [{state}, {self.preset}, {where}]", flush=True)

    def _print_banner(self) -> None:
        keys = self.config.hotkeys
        rows = [
            ("toggle on/off", "toggle"),
            ("whole screen", "fullscreen"),
            ("pick a region", "select_region"),
            ("previous / next preset", None),
            ("stronger / weaker", None),
            ("less / more contrast", None),
            ("cycle warmth", "warmth"),
            ("quit and restore", "quit"),
        ]
        print()
        print(f"  umbra  |  {self.preset}  |  "
              f"{'region ' + self.region.describe() if self.region and self.mode == 'region' else 'whole screen'}")
        print("  " + "-" * 52)
        for label, action in rows:
            if action:
                combo = describe_hotkey(keys.get(action) or "?")
            elif label.startswith("previous"):
                combo = _pair(keys, 'prev_preset', 'next_preset')
            elif label.startswith("stronger"):
                combo = _pair(keys, 'strength_up', 'strength_down')
            else:
                combo = _pair(keys, 'contrast_down', 'contrast_up')
            print(f"  {label:<24} {combo}")
        print("  " + "-" * 52)
        print("  Leave this window open. Closing it restores your screen.")
        print()


def _pair(keys: Dict[str, str], first: str, second: str) -> str:
    return (f"{describe_hotkey(keys.get(first) or '?')} / "
            f"{describe_hotkey(keys.get(second) or '?')}")


def _virtual_rect() -> Rect:
    r = w.virtual_screen()
    return Rect(r.left, r.top, r.width, r.height)
