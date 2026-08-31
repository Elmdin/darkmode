"""Scoring against real dark themes.

These lock in the answer to the question that motivated the tuning: a designed
dark theme is not a function of the light theme, so the only honest check is
distance from what humans actually chose.
"""
import pytest

from umbra.preview import render_comparison
from umbra.reference import (
    PAIRS, delta_e, from_hex, oklab, score, to_hex,
)
from umbra.transforms import PRESETS, DarkParams, build, endpoints


# ---------------------------------------------------------------- colour space

def test_identical_colours_have_zero_distance():
    for _, light, _, _ in PAIRS:
        assert delta_e(from_hex(light), from_hex(light)) == pytest.approx(0.0, abs=1e-12)


def test_black_and_white_are_far_apart():
    assert delta_e((0, 0, 0), (1, 1, 1)) > 0.9


def test_distance_is_symmetric_and_triangular():
    a, b, c = (1, 0, 0), (0, 1, 0), (0, 0, 1)
    assert delta_e(a, b) == pytest.approx(delta_e(b, a))
    assert delta_e(a, c) <= delta_e(a, b) + delta_e(b, c) + 1e-9


def test_a_just_noticeable_difference_is_small():
    """#808080 vs #828282 should score well under the 0.02 JND we document."""
    assert delta_e(from_hex("#808080"), from_hex("#828282")) < 0.02


def test_oklab_lightness_tracks_brightness():
    assert oklab((0, 0, 0))[0] < oklab((0.5, 0.5, 0.5))[0] < oklab((1, 1, 1))[0]


@pytest.mark.parametrize("text", ["#ffffff", "#000000", "#1e1e1e", "#60a5fa"])
def test_hex_roundtrips(text):
    assert to_hex(from_hex(text)) == text


def test_from_hex_rejects_junk():
    with pytest.raises(ValueError):
        from_hex("#fff")


def test_to_hex_clamps_out_of_range_channels():
    assert to_hex((1.4, -0.3, 0.5)) == "#ff0080"


# ---------------------------------------------------------------- the pairs

def test_every_pair_actually_changes():
    for pair in PAIRS:
        assert pair.light.lower() != pair.dark.lower(), pair.name


def test_the_extremes_flip_but_the_midtones_do_not_all_flip():
    """Direct evidence that a real dark theme is not an inversion.

    Near-white and near-black always cross the lightness midpoint. Mid-lightness
    colours do not: '#6b7280' muted text becomes *lighter* '#9ca3af', because on
    a dark background muted text has to rise to stay legible. No inversion --
    lightness, HSL, or otherwise -- reproduces that, because it is a decision
    about contrast against the new background, not a function of the old colour.
    """
    crossed, held = [], []
    for pair in PAIRS:
        light_l = oklab(from_hex(pair.light))[0]
        dark_l = oklab(from_hex(pair.dark))[0]
        (crossed if (light_l > 0.5) != (dark_l > 0.5) else held).append(pair.name)

    extremes = [p for p in PAIRS if oklab(from_hex(p.light))[0] > 0.9
                or oklab(from_hex(p.light))[0] < 0.25]
    for pair in extremes:
        assert pair.name in crossed, f"{pair.name} should have flipped"
    assert held, "expected at least one pair a pure inversion cannot explain"
    assert "muted text" in held


def test_every_pair_names_its_source():
    for pair in PAIRS:
        assert pair.source, pair.name


# ---------------------------------------------------------------- scoring

def test_score_covers_every_pair():
    result = score(build(PRESETS["theme"]))
    assert len(result.per_pair) == len(PAIRS)
    assert result.mean == pytest.approx(
        sum(d for _, _, d in result.per_pair) / len(PAIRS))
    assert result.worst == max(d for _, _, d in result.per_pair)


def test_the_tuned_preset_beats_plain_inversion():
    """The whole point of the tuning. Locks in the measured improvement."""
    tuned = score(build(PRESETS["theme"])).mean
    plain = score(build(PRESETS["dark"])).mean
    assert tuned < plain
    assert tuned < 0.07, "regression: the tuned preset drifted away from real themes"
    assert (plain - tuned) / plain > 0.15, "the improvement should be at least 15%"


def test_naive_inversion_is_by_far_the_worst():
    negative = score(build(PRESETS["negative"])).mean
    assert negative > 2 * score(build(PRESETS["theme"])).mean


def test_doing_nothing_scores_worst_of_all():
    assert score(build(PRESETS["off"])).mean > score(build(PRESETS["negative"])).mean


def test_the_tuned_preset_nails_the_editor_background():
    """#ffffff should land essentially on VS Code's #1e1e1e."""
    rows = {p.name: (got, d) for p, got, d in score(build(PRESETS["theme"])).per_pair}
    assert rows["editor bg"][1] < 0.02
    assert rows["blue accent"][1] < 0.02


def test_bright_saturated_accents_remain_the_known_weakness():
    """Documents the affine ceiling: amber cannot be followed by a matrix.

    A designed theme keeps a bright accent bright so it carries contrast on a
    dark background; inverting lightness necessarily darkens it.
    """
    rows = {p.name: d for p, _, d in score(build(PRESETS["theme"])).per_pair}
    assert rows["amber accent"] > 0.15
    assert rows["green accent"] < rows["amber accent"]


# ---------------------------------------------------------------- endpoints

def test_endpoints_report_what_white_and_black_become():
    white, black = endpoints(PRESETS["theme"])
    assert white == pytest.approx(0.12, abs=0.005)
    assert black == pytest.approx(0.94, abs=0.005)


def test_endpoints_expose_contrast_overshooting_the_nominal_range():
    """The reason endpoints() exists: contrast is applied before the range map."""
    params = DarkParams(black_point=0.1, white_point=0.9, contrast=1.4)
    white, black = endpoints(params)
    assert white < 0.1 and black > 0.9


def test_endpoints_are_exact_when_contrast_is_neutral():
    params = DarkParams(black_point=0.1, white_point=0.9, contrast=1.0, warmth=0.0)
    assert endpoints(params) == pytest.approx((0.1, 0.9), abs=1e-6)


def test_off_leaves_the_endpoints_alone():
    assert endpoints(PRESETS["off"]) == pytest.approx((1.0, 0.0), abs=1e-9)


# ---------------------------------------------------------------- comparison view

def test_comparison_lists_every_pair_and_preset():
    out = render_comparison(["theme", "dark"], colour=False)
    for pair in PAIRS:
        assert pair.name in out
    assert "theme" in out and "dark" in out
    assert "mean" in out


def test_comparison_flags_the_cases_a_matrix_cannot_follow():
    assert "!" in render_comparison(["dark"], colour=False)


def test_comparison_defaults_to_three_presets():
    out = render_comparison(colour=False)
    assert "negative" in out
