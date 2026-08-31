"""Persisted settings and hotkey parsing.

A config file is a boundary: it can be hand-edited, half-written, or left over
from an older version. Loading therefore never raises — every field is validated
independently and a bad one falls back to its default with a warning, so one
stray value cannot stop the tool from starting.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field, replace as _dc_replace
from pathlib import Path
from typing import Dict, Optional, Tuple

from .geometry import Rect, parse_region
from .transforms import DEFAULT_PRESET, PRESETS, DarkParams

MODES = ("fullscreen", "region")
FPS_LIMITS = (1, 240)

# --------------------------------------------------------------------------- hotkeys

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000

_MODIFIERS: Dict[str, int] = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT, "shift": MOD_SHIFT,
    "win": MOD_WIN, "super": MOD_WIN, "cmd": MOD_WIN,
}

_NAMED_KEYS: Dict[str, int] = {
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    "esc": 0x1B, "escape": 0x1B, "space": 0x20, "tab": 0x09,
    "pgup": 0x21, "pgdn": 0x22, "home": 0x24, "end": 0x23,
    "ins": 0x2D, "del": 0x2E, "backspace": 0x08, "enter": 0x0D,
    "[": 0xDB, "]": 0xDD, "\\": 0xDC, ";": 0xBA, "'": 0xDE,
    ",": 0xBC, ".": 0xBE, "/": 0xBF, "-": 0xBD, "=": 0xBB, "`": 0xC0,
    **{f"f{n}": 0x6F + n for n in range(1, 25)},
}

DEFAULT_HOTKEYS: Dict[str, str] = {
    "toggle": "ctrl+alt+d",
    "fullscreen": "ctrl+alt+f",
    "select_region": "ctrl+alt+r",
    "prev_preset": "ctrl+alt+[",
    "next_preset": "ctrl+alt+]",
    "strength_up": "ctrl+alt+up",
    "strength_down": "ctrl+alt+down",
    "contrast_down": "ctrl+alt+left",
    "contrast_up": "ctrl+alt+right",
    "warmth": "ctrl+alt+w",
    "quit": "ctrl+alt+q",
}


def parse_hotkey(combo: str) -> Tuple[int, int]:
    """``"ctrl+alt+d"`` -> ``(modifier flags, virtual key code)``.

    At least one modifier is required: an unmodified global hotkey would steal
    the key from every other application on the system.
    """
    if not isinstance(combo, str) or not combo.strip():
        raise ValueError("hotkey is empty")

    parts = [p.strip().lower() for p in combo.split("+")]
    if any(not p for p in parts):
        raise ValueError(f"malformed hotkey {combo!r}: empty component")

    *modifier_names, key = parts
    if not modifier_names:
        raise ValueError(
            f"hotkey {combo!r} needs at least one modifier (ctrl, alt, shift, win)"
        )

    mods = MOD_NOREPEAT
    for name in modifier_names:
        if name not in _MODIFIERS:
            raise ValueError(f"unknown modifier {name!r} in {combo!r}")
        mods |= _MODIFIERS[name]

    if key in _NAMED_KEYS:
        return mods, _NAMED_KEYS[key]
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return mods, ord(key.upper())
    raise ValueError(f"unknown key {key!r} in {combo!r}")


def describe_hotkey(combo: str) -> str:
    """Pretty form for the console banner."""
    return "+".join(p.strip().capitalize() for p in combo.split("+"))


# --------------------------------------------------------------------------- config

@dataclass(frozen=True)
class Config:
    mode: str = "fullscreen"
    region: Optional[Rect] = None
    preset: str = DEFAULT_PRESET
    params: DarkParams = field(default_factory=DarkParams)
    fps: int = 60
    show_cursor: bool = True
    start_enabled: bool = True
    hotkeys: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_HOTKEYS))

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")
        if self.mode == "region" and self.region is None:
            raise ValueError("mode 'region' needs a region; select one or pass --region")
        low, high = FPS_LIMITS
        if not isinstance(self.fps, int) or isinstance(self.fps, bool) or not low <= self.fps <= high:
            raise ValueError(f"fps must be an integer within [{low}, {high}], got {self.fps!r}")
        if self.preset not in PRESETS:
            raise ValueError(f"unknown preset {self.preset!r}; try: {', '.join(PRESETS)}")

    def replace(self, **changes: object) -> "Config":
        return _dc_replace(self, **changes)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "region": str(self.region) if self.region else None,
            "preset": self.preset,
            "params": {
                "strength": self.params.strength,
                "saturation": self.params.saturation,
                "black_point": self.params.black_point,
                "white_point": self.params.white_point,
                "contrast": self.params.contrast,
                "warmth": self.params.warmth,
                "luma": self.params.luma,
            },
            "fps": self.fps,
            "show_cursor": self.show_cursor,
            "start_enabled": self.start_enabled,
            "hotkeys": dict(self.hotkeys),
        }


def default_path() -> Path:
    """Per-user config location: ``%APPDATA%\\umbra`` on Windows."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        return Path(base) / "umbra" / "config.json"
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "umbra" / "config.json"


def _warn(message: str) -> None:
    print(f"umbra: config: {message}", file=sys.stderr)


def load(path: Optional[Path] = None) -> Config:
    """Read the config, degrading field by field. Never raises."""
    path = Path(path) if path else default_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Config()
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        _warn(f"could not read {path} ({exc}); using defaults")
        return Config()
    if not isinstance(raw, dict):
        _warn(f"{path} is not a JSON object; using defaults")
        return Config()

    defaults = Config()
    values: Dict[str, object] = {}

    def take(key: str, parse) -> None:
        if key not in raw:
            return
        try:
            values[key] = parse(raw[key])
        except (ValueError, TypeError, KeyError) as exc:
            _warn(f"ignoring {key}={raw[key]!r} ({exc})")

    take("mode", lambda v: v if v in MODES else _raise(f"unknown mode {v!r}"))
    take("region", lambda v: parse_region(v) if v else None)
    take("preset", lambda v: v if v in PRESETS else _raise(f"unknown preset {v!r}"))
    take("params", _params_from)
    take("fps", lambda v: int(v) if FPS_LIMITS[0] <= int(v) <= FPS_LIMITS[1]
         else _raise(f"fps {v} out of range"))
    take("show_cursor", bool)
    take("start_enabled", bool)
    take("hotkeys", _hotkeys_from)

    try:
        return defaults.replace(**values)  # type: ignore[arg-type]
    except ValueError as exc:
        # e.g. mode=region saved without a usable region
        _warn(f"{exc}; using defaults")
        return defaults


def _raise(message: str):
    raise ValueError(message)


def _params_from(value: object) -> DarkParams:
    if not isinstance(value, dict):
        raise TypeError("params must be an object")
    known = {f: value[f] for f in DarkParams.__dataclass_fields__ if f in value}
    return DarkParams(**known)


def _hotkeys_from(value: object) -> Dict[str, str]:
    if not isinstance(value, dict):
        raise TypeError("hotkeys must be an object")
    merged = dict(DEFAULT_HOTKEYS)
    for action, combo in value.items():
        if action not in DEFAULT_HOTKEYS:
            _warn(f"ignoring unknown hotkey action {action!r}")
            continue
        try:
            parse_hotkey(combo)
        except ValueError as exc:
            _warn(f"ignoring hotkey {action}={combo!r} ({exc})")
            continue
        merged[action] = combo
    return merged


def save(config: Config, path: Optional[Path] = None) -> Path:
    """Write the config atomically, so a crash mid-write cannot corrupt it."""
    path = Path(path) if path else default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return path
