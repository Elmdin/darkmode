"""Command line for umbra."""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .config import Config, default_path, load
from .geometry import Rect, parse_region
from .transforms import LUMA_WEIGHTS, PRESETS, DarkParams, list_presets

_PARAM_FLAGS = {
    "strength": ("--strength", "0 leaves the screen alone, 1 is the full effect"),
    "saturation": ("--saturation", "-1 plain negative, 0 greyscale, 1 hue-preserving, >1 vivid"),
    "black_point": ("--black-point", "what white becomes (the dark background level)"),
    "white_point": ("--white-point", "what black becomes (the light text level)"),
    "contrast": ("--contrast", "multiplier about mid-grey"),
    "warmth": ("--warmth", "0 neutral, 1 full amber night shift"),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="umbra",
        description="Real-time dark mode over your whole screen or any region of it.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  umbra                        whole screen, default look\n"
            "  umbra --select               drag a rectangle first\n"
            "  umbra --region 0,0,1280,800  a specific rectangle\n"
            "  umbra --preset warm          amber night mode\n"
            "  umbra preview                see what each preset does, in this terminal\n"
            "  umbra compare                score the presets against real dark themes\n"
            "  umbra reset                  clear a stuck effect after a hard kill\n"
        ),
    )
    parser.add_argument("--version", action="version", version=f"umbra {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="start the overlay (default)")
    _add_run_arguments(run)
    _add_run_arguments(parser)   # allow the flags with no subcommand too

    prev = sub.add_parser("preview", help="show colour swatches in this terminal")
    prev.add_argument("preset", nargs="?", help="a single preset; default shows all")
    prev.add_argument("--no-colour", action="store_true", help="hex values only")
    _add_param_arguments(prev)

    comp = sub.add_parser(
        "compare", help="score the presets against real dark-theme colours")
    comp.add_argument("presets", nargs="*",
                      help="presets to compare; default theme, dark, negative")
    comp.add_argument("--no-colour", action="store_true", help="hex values only")

    sub.add_parser("presets", help="list the presets")
    sub.add_parser("doctor", help="check this machine can run umbra")
    sub.add_parser("reset", help="clear a stuck screen colour effect")
    sub.add_parser("select", help="drag a region and print it")
    return parser


def _add_param_arguments(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("colour")
    for field, (flag, help_text) in _PARAM_FLAGS.items():
        group.add_argument(flag, dest=field, type=float, default=None, help=help_text)
    group.add_argument("--luma", choices=sorted(LUMA_WEIGHTS), default=None,
                       help="weights used to split lightness from colour")


def _add_run_arguments(parser: argparse.ArgumentParser) -> None:
    where = parser.add_argument_group("what to cover")
    where.add_argument("--region", metavar="X,Y,W,H", default=None,
                       help="a rectangle, e.g. 0,0,1280,800 or 1280x800+0+0")
    where.add_argument("--select", action="store_true",
                       help="drag the rectangle out with the mouse first")
    where.add_argument("--fullscreen", action="store_true",
                       help="cover every monitor (the default)")

    look = parser.add_argument_group("look")
    look.add_argument("--preset", choices=list_presets(), default=None)
    _add_param_arguments(parser)

    other = parser.add_argument_group("other")
    other.add_argument("--fps", type=int, default=None,
                       help="region refresh rate (default 60)")
    other.add_argument("--no-cursor", action="store_true",
                       help="leave the mouse pointer untransformed in region mode")
    other.add_argument("--config", type=Path, default=None, help="config file to use")
    other.add_argument("--no-save", action="store_true",
                       help="do not write settings back to the config file")
    other.add_argument("--duration", type=float, default=None, metavar="SECONDS",
                       help="quit automatically after this long (for testing)")


# --------------------------------------------------------------------------- helpers

def _params_from_args(base: DarkParams, args: argparse.Namespace) -> DarkParams:
    """Apply only the colour flags the user actually passed."""
    changes = {
        field: getattr(args, field)
        for field in list(_PARAM_FLAGS) + ["luma"]
        if getattr(args, field, None) is not None
    }
    return base.replace(**changes) if changes else base


def _config_from_args(args: argparse.Namespace) -> Config:
    config = load(args.config)

    if args.preset:
        config = config.replace(preset=args.preset, params=PRESETS[args.preset])

    region: Optional[Rect] = config.region
    mode = config.mode

    if args.select:
        from .region_select import select_in_subprocess
        chosen = select_in_subprocess()
        if chosen is None:
            raise SystemExit("umbra: region selection cancelled")
        region, mode = chosen, "region"
    elif args.region:
        region, mode = parse_region(args.region), "region"
    elif args.fullscreen:
        mode = "fullscreen"

    changes = {"mode": mode, "region": region,
               "params": _params_from_args(config.params, args)}
    if args.fps is not None:
        changes["fps"] = args.fps
    if args.no_cursor:
        changes["show_cursor"] = False
    return config.replace(**changes)


# --------------------------------------------------------------------------- commands

def cmd_run(args: argparse.Namespace) -> int:
    try:
        config = _config_from_args(args)
    except ValueError as exc:
        print(f"umbra: {exc}", file=sys.stderr)
        return 2

    from .app import UmbraApp
    from .winapi import NotWindows

    try:
        return UmbraApp(config, persist=not args.no_save,
                        duration=args.duration).run()
    except NotWindows as exc:
        print(f"umbra: {exc}", file=sys.stderr)
        print("       Try 'umbra preview' -- the colour preview works anywhere.",
              file=sys.stderr)
        return 2


def cmd_preview(args: argparse.Namespace) -> int:
    from .preview import render, render_presets, render_ramp

    colour = False if args.no_colour else None
    if args.preset:
        if args.preset not in PRESETS:
            print(f"umbra: unknown preset {args.preset!r}; "
                  f"try: {', '.join(PRESETS)}", file=sys.stderr)
            return 2
        params = _params_from_args(PRESETS[args.preset], args)
        print(render(params, title=args.preset, colour=colour))
        print(render_ramp(params, colour=colour))
    else:
        print(render_presets(colour=colour))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    from .preview import render_comparison

    unknown = [n for n in args.presets if n not in PRESETS]
    if unknown:
        print(f"umbra: unknown preset(s) {', '.join(unknown)}; "
              f"try: {', '.join(PRESETS)}", file=sys.stderr)
        return 2
    print(render_comparison(args.presets or None,
                            colour=False if args.no_colour else None))
    return 0


def cmd_presets(_args: argparse.Namespace) -> int:
    from .preview import summarise
    from .reference import score
    from .transforms import build, endpoints

    width = max(len(n) for n in PRESETS)
    print(f"  {'preset':<{width}}  {'white ->':>8} {'black ->':>9} {'dE':>7}   description")
    for name, params in PRESETS.items():
        white, black = endpoints(params)
        distance = score(build(params)).mean
        print(f"  {name:<{width}}  {white:8.3f} {black:9.3f} {distance:7.4f}   "
              f"{summarise(params)}")
    print("\n  dE = mean Oklab distance from real dark-theme colours "
          "(lower is closer). See 'umbra compare'.")
    return 0


def cmd_reset(_args: argparse.Namespace) -> int:
    from .engines import reset_fullscreen_effect
    from .winapi import NotWindows

    try:
        reset_fullscreen_effect()
    except NotWindows as exc:
        print(f"umbra: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"umbra: {exc}", file=sys.stderr)
        return 1
    print("umbra: screen colours restored.")
    return 0


def cmd_select(_args: argparse.Namespace) -> int:
    from .region_select import select_in_subprocess

    rect = select_in_subprocess()
    if rect is None:
        print("umbra: cancelled", file=sys.stderr)
        return 1
    print(rect)
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    """Report anything that would stop the overlay working."""
    import platform

    ok = True
    print(f"  umbra {__version__}")
    print(f"  python           {platform.python_version()} "
          f"({struct.calcsize('P') * 8}-bit)")
    print(f"  platform         {platform.system()} {platform.release()}")
    print(f"  config           {default_path()}")

    if sys.platform != "win32":
        print("  status           not Windows -- only 'preview' and 'presets' will work")
        return 1
    if struct.calcsize("P") * 8 != 64:
        print("  status           FAIL: 32-bit Python cannot use the Magnification API")
        return 1

    from . import winapi as w

    print(f"  dpi awareness    {w.set_dpi_awareness()}")
    try:
        v = w.virtual_screen()
        print(f"  virtual desktop  {v.width}x{v.height} at ({v.left}, {v.top})")
    except OSError as exc:
        print(f"  virtual desktop  FAIL: {exc}")
        ok = False

    try:
        w.check(w.magnification.MagInitialize(), "MagInitialize")
        w.magnification.MagUninitialize()
        print("  magnification    available")
    except OSError as exc:
        print(f"  magnification    FAIL: {exc}")
        ok = False

    if _colour_filters_active():
        print("  colour filters   ON -- Windows' own filter will fight umbra.")
        print("                   Turn it off in Settings > Accessibility > Colour filters.")
        ok = False
    else:
        print("  colour filters   off")

    print(f"  status           {'ready' if ok else 'see the failures above'}")
    return 0 if ok else 1


def _colour_filters_active() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\ColorFiltering") as key:
            return bool(winreg.QueryValueEx(key, "Active")[0])
    except (ImportError, OSError, FileNotFoundError):
        return False


COMMANDS = {
    "run": cmd_run, "preview": cmd_preview, "presets": cmd_presets,
    "compare": cmd_compare,
    "doctor": cmd_doctor, "reset": cmd_reset, "select": cmd_select,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command or "run"](args)
