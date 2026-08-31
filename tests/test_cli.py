"""Command-line parsing and the commands that work off Windows."""
import subprocess

import pytest

from umbra import cli, region_select
from umbra.geometry import Rect
from umbra.transforms import PRESETS


def parse(*argv, config=None):
    args = list(argv)
    if config is not None:
        args += ["--config", str(config)]
    return cli.build_parser().parse_args(args)


# ---------------------------------------------------------------- run arguments

def test_bare_invocation_defaults_to_run(tmp_path):
    args = parse(config=tmp_path / "c.json")
    assert args.command is None
    assert cli.COMMANDS[args.command or "run"] is cli.cmd_run


def test_region_flag_selects_region_mode(tmp_path):
    config = cli._config_from_args(parse("--region", "10,20,300,400", config=tmp_path / "c.json"))
    assert config.mode == "region" and config.region == Rect(10, 20, 300, 400)


def test_fullscreen_flag_overrides_a_saved_region(tmp_path):
    from umbra.config import Config, save
    path = tmp_path / "c.json"
    save(Config(mode="region", region=Rect(0, 0, 10, 10)), path)
    assert cli._config_from_args(parse("--fullscreen", config=path)).mode == "fullscreen"


def test_preset_flag_replaces_the_params(tmp_path):
    config = cli._config_from_args(parse("--preset", "warm", config=tmp_path / "c.json"))
    assert config.preset == "warm" and config.params == PRESETS["warm"]


def test_colour_flags_layer_on_top_of_the_preset(tmp_path):
    config = cli._config_from_args(
        parse("--preset", "warm", "--strength", "0.4", "--contrast", "1.2",
              config=tmp_path / "c.json"))
    assert config.params.strength == 0.4
    assert config.params.contrast == 1.2
    assert config.params.warmth == PRESETS["warm"].warmth, "untouched fields must survive"


def test_flags_not_passed_leave_the_saved_params_alone(tmp_path):
    from umbra.config import Config, save
    from umbra.transforms import DarkParams
    path = tmp_path / "c.json"
    save(Config(params=DarkParams(strength=0.6, warmth=0.2)), path)
    params = cli._config_from_args(parse(config=path)).params
    assert params.strength == 0.6 and params.warmth == 0.2


def test_out_of_range_colour_flag_is_reported_not_raised(tmp_path, capsys):
    assert cli.cmd_run(parse("--strength", "5", config=tmp_path / "c.json")) == 2
    assert "strength" in capsys.readouterr().err


def test_malformed_region_is_reported_not_raised(tmp_path, capsys):
    assert cli.cmd_run(parse("--region", "nope", config=tmp_path / "c.json")) == 2
    assert "region" in capsys.readouterr().err


def test_select_flag_uses_the_selector(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "_config_from_args", cli._config_from_args)
    monkeypatch.setattr(region_select, "select_in_subprocess",
                        lambda *a, **k: Rect(1, 2, 30, 40))
    config = cli._config_from_args(parse("--select", config=tmp_path / "c.json"))
    assert config.mode == "region" and config.region == Rect(1, 2, 30, 40)


def test_cancelling_select_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.setattr(region_select, "select_in_subprocess", lambda *a, **k: None)
    with pytest.raises(SystemExit):
        cli._config_from_args(parse("--select", config=tmp_path / "c.json"))


def test_fps_and_cursor_flags(tmp_path):
    config = cli._config_from_args(parse("--fps", "30", "--no-cursor", config=tmp_path / "c.json"))
    assert config.fps == 30 and config.show_cursor is False


# ---------------------------------------------------------------- other commands

def test_presets_command_lists_every_preset(capsys):
    assert cli.main(["presets"]) == 0
    out = capsys.readouterr().out
    assert all(name in out for name in PRESETS)


def test_preview_command_renders_all_presets(capsys):
    assert cli.main(["preview", "--no-colour"]) == 0
    out = capsys.readouterr().out
    assert "#ffffff" in out and "dark" in out


def test_preview_command_accepts_one_preset_with_overrides(capsys):
    assert cli.main(["preview", "mono", "--no-colour", "--contrast", "1.2"]) == 0
    assert "mono" in capsys.readouterr().out


def test_preview_rejects_an_unknown_preset(capsys):
    assert cli.main(["preview", "nope"]) == 2
    assert "unknown preset" in capsys.readouterr().err


def test_doctor_reports_non_windows_without_crashing(capsys):
    assert cli.main(["doctor"]) == 1
    assert "not Windows" in capsys.readouterr().out


def test_run_off_windows_explains_itself(tmp_path, capsys):
    assert cli.cmd_run(parse(config=tmp_path / "c.json")) == 2
    err = capsys.readouterr().err
    assert "only runs on Windows" in err and "preview" in err


def test_reset_off_windows_explains_itself(capsys):
    assert cli.main(["reset"]) == 2
    assert "only runs on Windows" in capsys.readouterr().err


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "umbra" in capsys.readouterr().out


# ---------------------------------------------------------------- region selector

def test_selector_parses_the_child_processes_output(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout="10,20,300,400\n", stderr=""))
    assert region_select.select_in_subprocess() == Rect(10, 20, 300, 400)


def test_selector_returns_none_when_cancelled(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 1, stdout="", stderr=""))
    assert region_select.select_in_subprocess() is None


def test_selector_survives_garbage_output(monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a[0], 0, stdout="not a rectangle", stderr=""))
    assert region_select.select_in_subprocess() is None
    assert "not a rectangle" in capsys.readouterr().err


def test_selector_survives_a_hung_child(monkeypatch, capsys):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired(a[0], 1)
    monkeypatch.setattr(subprocess, "run", boom)
    assert region_select.select_in_subprocess() is None
    assert "failed" in capsys.readouterr().err


# ---------------------------------------------------------------- drag maths

@pytest.mark.parametrize("anchor,release,origin,expected", [
    ((10, 10), (110, 60), (0, 0), Rect(10, 10, 100, 50)),
    ((110, 60), (10, 10), (0, 0), Rect(10, 10, 100, 50)),      # dragged up-left
    ((10, 10), (110, 60), (-1920, 0), Rect(-1910, 10, 100, 50)),  # monitor on the left
    ((0, 0), (50, 50), (1920, -200), Rect(1920, -200, 50, 50)),   # monitor above right
])
def test_drag_maps_canvas_coordinates_onto_the_virtual_desktop(
        anchor, release, origin, expected):
    assert region_select.drag_to_rect(anchor, release, origin) == expected


def test_a_stray_click_still_yields_a_usable_region():
    rect = region_select.drag_to_rect((100, 100), (101, 100), (0, 0))
    assert rect.width >= 8 and rect.height >= 8
