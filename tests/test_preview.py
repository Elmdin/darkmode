from umbra.preview import (
    SWATCHES, render, render_presets, render_ramp, summarise, supports_colour,
)
from umbra.transforms import PRESETS, DarkParams


def test_plain_render_shows_every_swatch_as_hex():
    out = render(PRESETS["dark"], colour=False)
    assert out.count("->") == len(SWATCHES)
    assert "#ffffff" in out and "#0d0d0d" in out


def test_render_includes_the_title_when_given():
    assert "midnight" in render(PRESETS["midnight"], title="midnight", colour=False)


def test_render_warns_when_colours_will_clip():
    assert "clipped" in render(PRESETS["dark"], colour=False)


def test_render_does_not_warn_for_a_transform_that_cannot_clip():
    assert "clipped" not in render(PRESETS["off"], colour=False)


def test_colour_render_emits_ansi_and_plain_does_not():
    assert "\x1b[48;2;" in render(PRESETS["dark"], colour=True)
    assert "\x1b[" not in render(PRESETS["dark"], colour=False)


def test_render_presets_covers_them_all():
    out = render_presets(colour=False)
    assert all(name in out for name in PRESETS)


def test_ramp_is_empty_without_colour():
    assert render_ramp(PRESETS["dark"], colour=False) == ""


def test_ramp_shows_both_a_grey_and_a_hue_sweep():
    out = render_ramp(PRESETS["dark"], colour=True)
    assert "grey ramp" in out and "hue sweep" in out


def test_summarise_describes_the_interesting_fields():
    assert summarise(PRESETS["off"]) == "no effect"
    text = summarise(DarkParams(warmth=0.4, contrast=1.2, strength=0.5))
    assert "warmth" in text and "contrast" in text and "strength" in text


def test_no_colour_env_disables_colour(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert supports_colour() is False
