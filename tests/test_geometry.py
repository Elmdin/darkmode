import pytest

from umbra.geometry import Rect, parse_region


def test_rect_is_immutable():
    r = Rect(0, 0, 10, 10)
    with pytest.raises(Exception):
        r.x = 5


def test_rect_derived_edges():
    r = Rect(10, 20, 100, 50)
    assert (r.right, r.bottom) == (110, 70)
    assert r.area == 5000
    assert r.center == (60, 45)


def test_rect_rejects_non_positive_size():
    with pytest.raises(ValueError):
        Rect(0, 0, 0, 10)
    with pytest.raises(ValueError):
        Rect(0, 0, 10, -1)


def test_from_points_normalises_any_drag_direction():
    expected = Rect(10, 20, 90, 80)
    assert Rect.from_points(10, 20, 100, 100) == expected
    assert Rect.from_points(100, 100, 10, 20) == expected   # dragged up-left
    assert Rect.from_points(100, 20, 10, 100) == expected   # dragged down-left


def test_from_points_enforces_a_minimum_size():
    r = Rect.from_points(50, 50, 51, 51, minimum=8)
    assert r.width >= 8 and r.height >= 8


def test_clamped_to_keeps_the_rect_inside_bounds():
    screen = Rect(0, 0, 1920, 1080)
    assert Rect(1900, 1060, 200, 200).clamped_to(screen) == Rect(1900, 1060, 20, 20)
    assert Rect(-50, -50, 100, 100).clamped_to(screen) == Rect(0, 0, 50, 50)
    inside = Rect(100, 100, 200, 200)
    assert inside.clamped_to(screen) == inside


def test_clamped_to_handles_negative_origin_screens():
    """A monitor left of the primary has negative virtual-desktop coordinates."""
    virtual = Rect(-1920, 0, 3840, 1080)
    assert Rect(-2000, 10, 500, 100).clamped_to(virtual) == Rect(-1920, 10, 420, 100)


def test_clamped_to_raises_when_there_is_no_overlap():
    with pytest.raises(ValueError):
        Rect(5000, 5000, 100, 100).clamped_to(Rect(0, 0, 1920, 1080))


def test_moved_and_resized_return_new_objects():
    r = Rect(0, 0, 10, 10)
    assert r.moved(5, 5) == Rect(5, 5, 10, 10)
    assert r.resized(20, 30) == Rect(0, 0, 20, 30)
    assert r == Rect(0, 0, 10, 10)


@pytest.mark.parametrize("text,expected", [
    ("0,0,800,600", Rect(0, 0, 800, 600)),
    (" 10 , 20 , 30 , 40 ", Rect(10, 20, 30, 40)),
    ("10x20+30+40", Rect(30, 40, 10, 20)),
    ("-1920,0,1920,1080", Rect(-1920, 0, 1920, 1080)),
])
def test_parse_region_accepts_both_notations(text, expected):
    assert parse_region(text) == expected


@pytest.mark.parametrize("text", ["", "1,2,3", "a,b,c,d", "1,2,3,4,5", "10x20", "1,2,0,5"])
def test_parse_region_rejects_junk(text):
    with pytest.raises(ValueError):
        parse_region(text)


def test_str_roundtrips_through_parse():
    r = Rect(-100, 25, 640, 480)
    assert parse_region(str(r)) == r
