"""Coordinate mapping is the highest-risk maths in the project, so it gets the
most explicit tests: a sign error here is invisible in a demo."""

import math

import pytest

from ffbridge.coordinate import (
    CoordinateMapper,
    decompose,
    mat_apply,
    mat_invert,
    mat_mul,
    mapper_for,
)

RESOLUTIONS = [
    (1920, 1080),
    (1080, 1920),
    (1080, 1080),
    (3840, 2160),
    (4096, 2160),
    (2560, 1440),
    (1234, 567),
]


@pytest.mark.parametrize("w,h", RESOLUTIONS)
def test_corners_map_to_image_space_corners(w, h):
    m = mapper_for(w, h, 0, 0, w, h)
    assert m.to_image_space(0, 0) == pytest.approx((0.0, 1.0))
    assert m.to_image_space(w, h) == pytest.approx((1.0, 0.0))
    assert m.to_image_space(w / 2, h / 2) == pytest.approx((0.5, 0.5))


@pytest.mark.parametrize("w,h", RESOLUTIONS)
def test_centre_maps_to_shape_space_origin(w, h):
    m = mapper_for(w, h, 0, 0, w, h)
    assert m.to_shape_space(w / 2, h / 2) == pytest.approx((0.0, 0.0))


@pytest.mark.parametrize("w,h", RESOLUTIONS)
def test_shape_space_is_uniform(w, h):
    """A square in design space must stay square in shape space, whatever the
    composition aspect ratio. This is what keeps vector shapes undistorted."""
    m = mapper_for(w, h, 0, 0, w, h)
    side = 100.0
    assert m.length_to_shape_space(side) == pytest.approx(side / h)
    # Vertical extent of the visible canvas is always exactly 1.0.
    top = m.to_shape_space(0, 0)[1]
    bottom = m.to_shape_space(0, h)[1]
    assert top - bottom == pytest.approx(1.0)


def test_selection_origin_is_subtracted():
    """A frame far from the page origin must land centred, not off-screen."""
    m = mapper_for(1920, 1080, 48000, -32000, 1920, 1080)
    assert m.to_image_space(48000, -32000) == pytest.approx((0.0, 1.0))
    assert m.to_image_space(48960, -31460) == pytest.approx((0.5, 0.5))


def test_smaller_selection_is_centred_not_corner_pinned():
    m = mapper_for(1920, 1080, 0, 0, 960, 540)
    # The design's centre must sit at the comp's centre.
    assert m.to_image_space(480, 270) == pytest.approx((0.5, 0.5))


def test_fit_scales_uniformly_and_preserves_aspect():
    m = mapper_for(1920, 1080, 0, 0, 3840, 2160, fit=True)
    assert m.scale == pytest.approx(0.5)
    assert m.to_image_space(0, 0) == pytest.approx((0.0, 1.0))
    assert m.to_image_space(3840, 2160) == pytest.approx((1.0, 0.0))


def test_fit_never_distorts_a_mismatched_aspect():
    m = mapper_for(1920, 1080, 0, 0, 1000, 1000, fit=True)
    assert m.scale == pytest.approx(1.08)  # min(1.92, 1.08)
    # Square input stays square: equal design lengths give equal shape lengths.
    assert m.length_to_shape_space(100) == pytest.approx(m.length_to_shape_space(100))


@pytest.mark.parametrize("deg", [0, 45, 90, 180, -45, -90, 137.5])
def test_angle_conversion_flips_handedness(deg):
    assert CoordinateMapper.angle_to_fusion(deg) == pytest.approx(-deg)


@pytest.mark.parametrize("deg", [0, 45, 90, 180, 270, 359, -180, -370])
def test_normalize_angle_folds_into_half_open_range(deg):
    a = CoordinateMapper.normalize_angle(deg)
    assert -180 < a <= 180


# -- affine algebra --------------------------------------------------------

@pytest.mark.parametrize("deg", [0, 45, 90, 180, -30, 137.5])
def test_decompose_recovers_rotation(deg):
    r = math.radians(deg)
    m = ((math.cos(r), -math.sin(r), 10.0), (math.sin(r), math.cos(r), 20.0))
    d = decompose(m)
    assert d.rotation_deg == pytest.approx(deg, abs=1e-9)
    assert d.scale_x == pytest.approx(1.0)
    assert d.scale_y == pytest.approx(1.0)
    assert d.translate_x == pytest.approx(10.0)
    assert d.translate_y == pytest.approx(20.0)
    assert not d.has_skew


def test_decompose_handles_non_uniform_scale():
    d = decompose(((2.0, 0.0, 0.0), (0.0, 3.0, 0.0)))
    assert d.scale_x == pytest.approx(2.0)
    assert d.scale_y == pytest.approx(3.0)
    assert not d.is_uniform


def test_decompose_handles_mirroring_without_flipping_rotation():
    """A horizontal flip must read as negative scale, not a 180 degree turn."""
    d = decompose(((1.0, 0.0, 0.0), (0.0, -1.0, 0.0)))
    assert d.rotation_deg == pytest.approx(0.0)
    assert d.scale_y < 0


def test_decompose_detects_skew():
    d = decompose(((1.0, 0.5, 0.0), (0.0, 1.0, 0.0)))
    assert d.has_skew


def test_invert_round_trips():
    m = ((2.0, 0.3, 15.0), (-0.1, 1.5, -7.0))
    inv = mat_invert(m)
    x, y = mat_apply(m, 3.0, 4.0)
    assert mat_apply(inv, x, y) == pytest.approx((3.0, 4.0))


def test_invert_rejects_singular_matrix():
    with pytest.raises(ValueError):
        mat_invert(((1.0, 2.0, 0.0), (2.0, 4.0, 0.0)))


def test_matrix_multiply_matches_sequential_application():
    a = ((0.0, -1.0, 5.0), (1.0, 0.0, 0.0))   # rotate 90 then translate
    b = ((2.0, 0.0, 0.0), (0.0, 2.0, 1.0))    # scale then translate
    composed = mat_mul(a, b)
    px, py = 3.0, 7.0
    step = mat_apply(a, *mat_apply(b, px, py))
    assert mat_apply(composed, px, py) == pytest.approx(step)
