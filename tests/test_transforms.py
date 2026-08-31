"""The dark-mode colour pipeline. These tests are the real contract."""
import colorsys

import pytest

from umbra.colormatrix import IDENTITY, apply, is_identity
from umbra.transforms import (
    PRESETS, DarkParams, LUMA_WEIGHTS, build, clipping_headroom, list_presets,
    next_preset, preset,
)

SAMPLES = [
    (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.5, 0.5, 0.5),
    (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0),
    (0.2, 0.4, 0.9), (0.95, 0.93, 0.88), (0.13, 0.13, 0.15),
    (0.8, 0.35, 0.1), (0.45, 0.6, 0.2), (0.99, 0.99, 1.0),
]

# A "pure" transform: no range compression, no contrast, no warmth.
def pure(s, luma="rec709"):
    return build(DarkParams(saturation=s, black_point=0.0, white_point=1.0,
                            contrast=1.0, warmth=0.0, luma=luma))


# ---------------------------------------------------------------- strength

def test_strength_zero_is_exactly_identity():
    m = build(DarkParams(strength=0.0, saturation=1.0, black_point=0.2,
                         white_point=0.8, contrast=1.4, warmth=0.5))
    assert is_identity(m)
    for rgb in SAMPLES:
        assert apply(m, rgb) == pytest.approx(rgb, abs=1e-9)


def test_strength_interpolates_monotonically_toward_dark():
    """Half strength must sit between untouched and fully dark."""
    full = build(DarkParams(strength=1.0))
    half = build(DarkParams(strength=0.5))
    white = (1.0, 1.0, 1.0)
    assert apply(half, white)[0] == pytest.approx(
        (apply(IDENTITY, white)[0] + apply(full, white)[0]) / 2, abs=1e-9)


# ---------------------------------------------------------------- core inversion

def test_lightness_inverts_white_and_black():
    m = pure(1.0)
    assert apply(m, (1, 1, 1)) == pytest.approx((0, 0, 0), abs=1e-6)
    assert apply(m, (0, 0, 0)) == pytest.approx((1, 1, 1), abs=1e-6)


@pytest.mark.parametrize("g", [0.0, 0.25, 0.5, 0.5, 0.75, 1.0])
def test_greys_map_to_their_complement(g):
    """The 'colours in between' requirement, for the achromatic axis."""
    assert apply(pure(1.0), (g, g, g)) == pytest.approx((1 - g, 1 - g, 1 - g), abs=1e-6)


@pytest.mark.parametrize("rgb", [c for c in SAMPLES if len(set(c)) > 1])
def test_hue_is_preserved_at_saturation_one(rgb):
    """Blue must stay blue, not turn orange. Hue angle survives the transform."""
    out = apply(pure(1.0), rgb)
    h_in = colorsys.rgb_to_hsv(*rgb)[0]
    h_out = colorsys.rgb_to_hsv(*out)[0]
    delta = min(abs(h_in - h_out), 1 - abs(h_in - h_out))  # circular distance
    assert delta < 0.02, f"hue drifted {delta:.3f} for {rgb} -> {out}"


@pytest.mark.parametrize("rgb", SAMPLES)
def test_channel_ordering_is_preserved_at_saturation_one(rgb):
    """Stronger channel stays stronger: the structural form of hue preservation."""
    out = apply(pure(1.0), rgb)
    for i in range(3):
        for j in range(3):
            if rgb[i] > rgb[j] + 1e-6:
                assert out[i] >= out[j] - 1e-6


def test_saturation_minus_one_is_exactly_classic_negative():
    m = pure(-1.0)
    for rgb in SAMPLES:
        assert apply(m, rgb) == pytest.approx(tuple(1 - c for c in rgb), abs=1e-6)


def test_saturation_zero_is_achromatic():
    m = pure(0.0)
    for rgb in SAMPLES:
        r, g, b = apply(m, rgb)
        assert r == pytest.approx(g, abs=1e-6) and g == pytest.approx(b, abs=1e-6)


def test_saturation_zero_inverts_luma():
    w = LUMA_WEIGHTS["rec709"]
    for rgb in SAMPLES:
        expected = 1 - sum(wi * c for wi, c in zip(w, rgb))
        assert apply(pure(0.0), rgb)[0] == pytest.approx(max(0.0, min(1.0, expected)), abs=1e-6)


def test_higher_saturation_increases_chroma():
    rgb = (0.2, 0.4, 0.9)
    def chroma(c):
        return max(c) - min(c)
    assert chroma(apply(pure(1.4), rgb)) > chroma(apply(pure(1.0), rgb)) > chroma(apply(pure(0.4), rgb))


def test_naive_inversion_flips_hue_but_ours_does_not():
    """Guards the entire premise of the tool."""
    blue = (0.1, 0.2, 0.9)
    naive = apply(pure(-1.0), blue)
    smart = apply(pure(1.0), blue)
    assert naive[0] > naive[2]   # naive: red channel now dominates -> orange/yellow
    assert smart[2] > smart[0]   # ours: still blue-dominant


# ---------------------------------------------------------------- range compression

def test_black_and_white_points_bound_the_output():
    m = build(DarkParams(black_point=0.06, white_point=0.9, contrast=1.0, warmth=0.0))
    assert apply(m, (1, 1, 1)) == pytest.approx((0.06,) * 3, abs=1e-6)
    assert apply(m, (0, 0, 0)) == pytest.approx((0.9,) * 3, abs=1e-6)


def test_default_preset_never_produces_pure_black_or_white_on_neutrals():
    """The readability requirement: a white page must not become #000, and black
    text must not become #fff. Only neutrals are promised this -- see
    test_saturated_primaries_clip_one_channel_by_design."""
    m = preset("dark")
    neutrals = [(g, g, g) for g in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0)]
    for rgb in neutrals + [(0.95, 0.93, 0.88), (0.13, 0.13, 0.15), (0.99, 0.99, 1.0)]:
        out = apply(m, rgb)
        assert max(out) < 1.0 and min(out) > 0.0, f"{rgb} -> {out}"


def test_saturated_primaries_clip_one_channel_by_design():
    """Hue-preserving inversion has to overshoot the sRGB cube on full primaries.

    The transform is affine, so it cannot clamp mid-pipeline; pure red's red
    channel lands above 1.0 and is clipped. What matters is that clipping is
    *monotone*, so the colour stays red -- it does not become white or shift hue.
    """
    out = apply(preset("dark"), (1.0, 0.0, 0.0))
    assert out[0] == 1.0                      # clipped
    assert out[1] < 0.7 and out[1] == out[2]  # still unmistakably red
    lo, hi = clipping_headroom(PRESETS["dark"])
    assert hi > 1.0 and lo < 0.0              # headroom report is honest about it


def test_clipping_headroom_is_zero_for_off():
    lo, hi = clipping_headroom(PRESETS["off"])
    assert lo == pytest.approx(0.0) and hi == pytest.approx(1.0)


def test_range_compression_reduces_clipping():
    """Pulling the white point down buys back gamut headroom."""
    wide = clipping_headroom(DarkParams(black_point=0.0, white_point=1.0))[1]
    narrow = clipping_headroom(DarkParams(black_point=0.10, white_point=0.85))[1]
    assert narrow < wide


# ---------------------------------------------------------------- contrast & warmth

def test_contrast_pivots_about_mid_grey():
    m = build(DarkParams(contrast=2.0, black_point=0.0, white_point=1.0, warmth=0.0))
    assert apply(m, (0.5, 0.5, 0.5)) == pytest.approx((0.5, 0.5, 0.5), abs=1e-6)


def test_contrast_widens_the_spread():
    lo = build(DarkParams(contrast=1.0, black_point=0.0, white_point=1.0, warmth=0.0))
    hi = build(DarkParams(contrast=1.6, black_point=0.0, white_point=1.0, warmth=0.0))
    a, b = apply(lo, (0.7, 0.7, 0.7))[0], apply(hi, (0.7, 0.7, 0.7))[0]
    assert abs(b - 0.5) > abs(a - 0.5)


def test_warmth_suppresses_blue_relative_to_red():
    neutral = apply(build(DarkParams(warmth=0.0)), (0.5, 0.5, 0.5))
    warm = apply(build(DarkParams(warmth=0.6)), (0.5, 0.5, 0.5))
    assert warm[2] < neutral[2]
    assert warm[0] / max(warm[2], 1e-6) > neutral[0] / max(neutral[2], 1e-6)


# ---------------------------------------------------------------- luma weights

def test_luma_weights_are_normalised():
    for name, w in LUMA_WEIGHTS.items():
        assert sum(w) == pytest.approx(1.0), name
        assert len(w) == 3


def test_rec709_differs_from_equal_weighting_on_saturated_colour():
    a = apply(pure(1.0, "rec709"), (0.0, 0.0, 1.0))
    b = apply(pure(1.0, "equal"), (0.0, 0.0, 1.0))
    assert a != pytest.approx(b, abs=1e-3)


# ---------------------------------------------------------------- presets & validation

def test_every_preset_builds_a_sane_matrix():
    assert "dark" in PRESETS and len(PRESETS) >= 5
    for name in list_presets():
        m = preset(name)
        assert len(m) == 5 and all(len(r) == 5 for r in m)
        assert [row[4] for row in m] == pytest.approx([0, 0, 0, 0, 1])
        for rgb in SAMPLES:
            out = apply(m, rgb)
            assert all(0.0 <= v <= 1.0 for v in out), f"{name} escaped range on {rgb}"


def test_off_preset_is_identity():
    assert is_identity(preset("off"))


def test_every_preset_except_off_actually_darkens_white():
    for name in list_presets():
        if name == "off":
            continue
        assert apply(preset(name), (1, 1, 1))[0] < 0.35, name


def test_every_preset_except_off_lightens_black():
    for name in list_presets():
        if name == "off":
            continue
        assert apply(preset(name), (0, 0, 0))[0] > 0.6, name


def test_unknown_preset_raises_with_helpful_message():
    with pytest.raises(KeyError) as e:
        preset("nope")
    assert "nope" in str(e.value)


@pytest.mark.parametrize("kwargs", [
    {"strength": 1.5}, {"strength": -0.1},
    {"black_point": -0.2}, {"white_point": 1.4},
    {"black_point": 0.9, "white_point": 0.2},   # inverted range
    {"contrast": 0.0}, {"contrast": -1.0},
    {"warmth": 1.5}, {"warmth": -0.1},
    {"saturation": -2.0}, {"saturation": 4.0},
    {"luma": "bogus"},
])
def test_invalid_params_are_rejected(kwargs):
    with pytest.raises(ValueError):
        DarkParams(**kwargs)


def test_valid_boundary_params_are_accepted():
    DarkParams(strength=0.0, saturation=-1.0, black_point=0.0,
               white_point=1.0, contrast=0.1, warmth=0.0, luma="equal")
    DarkParams(strength=1.0, saturation=3.0, black_point=0.49,
               white_point=1.0, contrast=3.0, warmth=1.0, luma="rec601")


def test_params_are_immutable():
    p = DarkParams()
    with pytest.raises(Exception):
        p.strength = 0.5


def test_replace_returns_a_new_params_object():
    p = DarkParams(strength=1.0)
    q = p.replace(strength=0.4)
    assert p.strength == 1.0 and q.strength == 0.4 and q is not p


# ---------------------------------------------------------------- cycling

def test_next_preset_wraps_around():
    names = list_presets()
    assert next_preset(names[-1]) == names[0]
    assert next_preset(names[0], -1) == names[-1]
    for name in names:
        assert next_preset(name) in PRESETS


def test_next_preset_recovers_from_an_unknown_name():
    assert next_preset("garbage") in PRESETS


# ---------------------------------------------------------------- build() overrides

def test_build_accepts_kwargs_or_params_or_both():
    from umbra.colormatrix import is_identity as _is_id
    assert _is_id(build(strength=0.0))
    assert _is_id(build(DarkParams(), strength=0.0))
    assert build(DarkParams(warmth=0.0), warmth=0.5) == build(DarkParams(warmth=0.5))


def test_build_overrides_are_validated():
    with pytest.raises(ValueError):
        build(DarkParams(), contrast=99.0)
