import json

import pytest

from umbra.config import Config, DEFAULT_HOTKEYS, load, parse_hotkey, save
from umbra.geometry import Rect
from umbra.transforms import DEFAULT_PRESET, DarkParams


def test_defaults_are_usable():
    c = Config()
    assert c.mode == "fullscreen"
    assert c.preset == DEFAULT_PRESET
    assert isinstance(c.params, DarkParams)
    assert 1 <= c.fps <= 240
    assert c.region is None


def test_config_is_immutable_and_replace_returns_a_copy():
    c = Config()
    with pytest.raises(Exception):
        c.mode = "region"
    d = c.replace(mode="region", region=Rect(0, 0, 100, 100))
    assert c.mode == "fullscreen" and d.mode == "region" and d is not c


def test_region_mode_requires_a_region():
    with pytest.raises(ValueError):
        Config(mode="region", region=None)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        Config(mode="sideways")


def test_fps_is_bounded():
    with pytest.raises(ValueError):
        Config(fps=0)
    with pytest.raises(ValueError):
        Config(fps=1000)


def test_roundtrip_through_json(tmp_path):
    path = tmp_path / "config.json"
    original = Config(mode="region", region=Rect(-100, 50, 640, 480), preset="warm",
                      params=DarkParams(strength=0.7, warmth=0.3), fps=30)
    save(original, path)
    assert load(path) == original


def test_load_returns_defaults_when_the_file_is_missing(tmp_path):
    assert load(tmp_path / "nope.json") == Config()


def test_load_survives_corrupt_json(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json at all")
    assert load(path) == Config()


def test_load_survives_a_bad_value_without_losing_the_good_ones(tmp_path):
    """A hand-edited config must not brick the tool."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"preset": "warm", "fps": 99999, "mode": "nonsense"}))
    loaded = load(path)
    assert loaded.preset == "warm"          # the valid field survived
    assert loaded.fps == Config().fps       # the invalid ones fell back
    assert loaded.mode == Config().mode


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"preset": "soft", "colour_of_the_bikeshed": "green"}))
    assert load(path).preset == "soft"


def test_save_creates_missing_directories(tmp_path):
    path = tmp_path / "a" / "b" / "config.json"
    save(Config(), path)
    assert path.exists()


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    path = tmp_path / "config.json"
    save(Config(), path)
    save(Config(preset="mono"), path)
    assert load(path).preset == "mono"
    assert [p.name for p in tmp_path.iterdir()] == ["config.json"]


# ---------------------------------------------------------------- hotkeys

def test_default_hotkeys_all_parse():
    for action, combo in DEFAULT_HOTKEYS.items():
        mods, vk = parse_hotkey(combo)
        assert mods > 0 and vk > 0, action


def test_parse_hotkey_is_case_and_space_insensitive():
    assert parse_hotkey("ctrl+alt+D") == parse_hotkey("  CTRL + ALT + d  ")


def test_parse_hotkey_supports_named_keys():
    assert parse_hotkey("ctrl+alt+up")[1] == 0x26
    assert parse_hotkey("ctrl+shift+]")[1] == 0xDD


def test_parse_hotkey_sets_norepeat():
    mods, _ = parse_hotkey("ctrl+alt+d")
    assert mods & 0x4000, "MOD_NOREPEAT keeps a held key from firing repeatedly"


@pytest.mark.parametrize("combo", ["", "d", "ctrl+", "ctrl+alt", "ctrl+alt+notakey"])
def test_parse_hotkey_rejects_junk(combo):
    with pytest.raises(ValueError):
        parse_hotkey(combo)


def test_load_rejects_a_json_array(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text("[1, 2, 3]")
    assert load(path) == Config()
    assert "not a JSON object" in capsys.readouterr().err


def test_load_repairs_region_mode_saved_without_a_region(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"mode": "region", "region": None}))
    assert load(path).mode == "fullscreen"


def test_load_drops_an_out_of_range_param_but_keeps_the_rest(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"preset": "soft", "params": {"strength": 9}}))
    loaded = load(path)
    assert loaded.preset == "soft"
    assert loaded.params == Config().params


def test_load_ignores_an_unknown_or_broken_hotkey(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkeys": {"toggle": "ctrl+alt+k",
                                            "fly_to_the_moon": "ctrl+alt+m",
                                            "quit": "nonsense"}}))
    loaded = load(path)
    assert loaded.hotkeys["toggle"] == "ctrl+alt+k"      # the good one is kept
    assert loaded.hotkeys["quit"] == DEFAULT_HOTKEYS["quit"]
    assert "fly_to_the_moon" not in loaded.hotkeys
    err = capsys.readouterr().err
    assert "fly_to_the_moon" in err and "quit" in err


def test_load_ignores_hotkeys_that_are_not_an_object(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"hotkeys": "ctrl+alt+d"}))
    assert load(path).hotkeys == DEFAULT_HOTKEYS


def test_to_dict_is_json_serialisable_and_complete():
    data = Config(region=Rect(1, 2, 3, 4), mode="region").to_dict()
    json.dumps(data)
    assert data["region"] == "1,2,3,4"
    assert set(data["params"]) == set(DarkParams.__dataclass_fields__)


def test_default_path_is_under_appdata_on_windows(monkeypatch, tmp_path):
    import umbra.config as module
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    assert module.default_path() == tmp_path / "umbra" / "config.json"
