"""Matrix algebra for GDI+ 5x5 colour matrices (row-vector convention)."""
import math

import pytest

from umbra.colormatrix import IDENTITY, apply, compose, lerp, is_identity, to_flat, from_flat


def test_identity_is_5x5_and_diagonal():
    assert len(IDENTITY) == 5
    assert all(len(row) == 5 for row in IDENTITY)
    for i in range(5):
        for j in range(5):
            assert IDENTITY[i][j] == (1.0 if i == j else 0.0)


@pytest.mark.parametrize("rgb", [(0, 0, 0), (1, 1, 1), (0.5, 0.25, 0.75), (0.2, 0.9, 0.1)])
def test_identity_leaves_colour_untouched(rgb):
    assert apply(IDENTITY, rgb) == pytest.approx(rgb, abs=1e-9)


def test_apply_clamps_into_unit_range():
    # a matrix that doubles every channel and adds 0.5 must still land in [0,1]
    m = [[2, 0, 0, 0, 0], [0, 2, 0, 0, 0], [0, 0, 2, 0, 0], [0, 0, 0, 1, 0], [0.5, 0.5, 0.5, 0, 1]]
    assert apply(m, (0.9, 0.9, 0.9)) == pytest.approx((1.0, 1.0, 1.0))
    m2 = [[1, 0, 0, 0, 0], [0, 1, 0, 0, 0], [0, 0, 1, 0, 0], [0, 0, 0, 1, 0], [-2, -2, -2, 0, 1]]
    assert apply(m2, (0.3, 0.3, 0.3)) == pytest.approx((0.0, 0.0, 0.0))


def test_apply_uses_row_vector_convention():
    # translation lives in row 4; out_r must pick up M[4][0]
    m = [r[:] for r in IDENTITY]
    m[4][0] = 0.25
    assert apply(m, (0.5, 0.5, 0.5)) == pytest.approx((0.75, 0.5, 0.5))
    # channel mixing: M[i][j] sends input channel i into output channel j
    m2 = [r[:] for r in IDENTITY]
    m2[0][1] = 1.0  # red contributes to green
    assert apply(m2, (0.4, 0.1, 0.0)) == pytest.approx((0.4, 0.5, 0.0))


def test_compose_with_identity_is_noop():
    m = [[0.3, 0.1, 0, 0, 0], [0, 0.7, 0.2, 0, 0], [0.1, 0, 0.5, 0, 0],
         [0, 0, 0, 1, 0], [0.2, 0.1, 0.05, 0, 1]]
    for i in range(5):
        assert compose(IDENTITY, m)[i] == pytest.approx(m[i])
        assert compose(m, IDENTITY)[i] == pytest.approx(m[i])


def test_compose_order_is_a_then_b():
    add_a = [r[:] for r in IDENTITY]
    add_a[4][0] = 0.1                      # A: red += 0.1
    scale_b = [r[:] for r in IDENTITY]
    scale_b[0][0] = 2.0                    # B: red *= 2
    # A then B  ->  (r + 0.1) * 2
    assert apply(compose(add_a, scale_b), (0.2, 0, 0))[0] == pytest.approx(0.6)
    # B then A  ->  r * 2 + 0.1
    assert apply(compose(scale_b, add_a), (0.2, 0, 0))[0] == pytest.approx(0.5)


def test_compose_is_associative():
    a = [[0.9, 0.05, 0, 0, 0], [0, 0.8, 0.1, 0, 0], [0.2, 0, 0.7, 0, 0], [0, 0, 0, 1, 0], [0.1, 0, 0, 0, 1]]
    b = [[1.1, 0, 0.1, 0, 0], [0, 1.2, 0, 0, 0], [0, 0.1, 0.9, 0, 0], [0, 0, 0, 1, 0], [0, 0.05, 0, 0, 1]]
    c = [[0.5, 0, 0, 0, 0], [0, 0.5, 0, 0, 0], [0, 0, 0.5, 0, 0], [0, 0, 0, 1, 0], [0.25, 0.25, 0.25, 0, 1]]
    left = compose(compose(a, b), c)
    right = compose(a, compose(b, c))
    for i in range(5):
        assert left[i] == pytest.approx(right[i], abs=1e-12)


def test_compose_preserves_affine_last_column():
    a = [[0.3, 0.1, 0, 0, 0], [0, 0.7, 0.2, 0, 0], [0.1, 0, 0.5, 0, 0], [0, 0, 0, 1, 0], [0.2, 0.1, 0.05, 0, 1]]
    out = compose(a, a)
    assert [row[4] for row in out] == pytest.approx([0, 0, 0, 0, 1])
    assert out[3] == pytest.approx([0, 0, 0, 1, 0])


def test_lerp_endpoints_and_midpoint():
    m = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 1, 0], [1, 1, 1, 0, 1]]
    assert lerp(IDENTITY, m, 0.0) == IDENTITY
    for i in range(5):
        assert lerp(IDENTITY, m, 1.0)[i] == pytest.approx(m[i])
        assert lerp(IDENTITY, m, 0.5)[i] == pytest.approx(
            [(IDENTITY[i][j] + m[i][j]) / 2 for j in range(5)])


def test_is_identity():
    assert is_identity(IDENTITY)
    nearly = [r[:] for r in IDENTITY]
    nearly[0][0] = 1.0 + 1e-12
    assert is_identity(nearly)
    nearly[0][0] = 1.05
    assert not is_identity(nearly)


def test_flat_roundtrip_is_row_major_25_floats():
    m = [[float(i * 5 + j) for j in range(5)] for i in range(5)]
    flat = to_flat(m)
    assert flat == [float(k) for k in range(25)]
    assert from_flat(flat) == m


def test_no_nan_or_inf_escapes_apply():
    m = [r[:] for r in IDENTITY]
    m[0][0] = float("inf")
    out = apply(m, (0.5, 0.5, 0.5))
    assert all(not math.isnan(v) and 0.0 <= v <= 1.0 for v in out)
