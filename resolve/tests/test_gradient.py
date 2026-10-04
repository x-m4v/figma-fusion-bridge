"""Gradient transform decomposition.

The angles below are the ones a designer actually reaches for, plus a couple of
awkward ones. Each case builds the gradient transform the way a design tool
would and checks that inverting it recovers the handles.
"""

import math

import pytest

from ffbridge.coordinate import CoordinateMapper, mat_invert
from ffbridge.gradient import (
    build_stops,
    geometry_from_handles,
    geometry_from_transform,
    map_gradient_type,
)


def rotation_transform(deg):
    """The gradient transform a design tool writes for a rotated linear gradient.

    It maps object space to gradient space, so it is the *inverse* of the
    rotation that visually turns the gradient.
    """
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    forward = ((c, -s, 0.5 - 0.5 * c + 0.5 * s), (s, c, 0.5 - 0.5 * s - 0.5 * c))
    return mat_invert(forward)


@pytest.mark.parametrize("deg", [0, 45, 90, 180, 270, -45, 137.5])
def test_angle_round_trips_through_the_transform(deg):
    geom = geometry_from_transform(rotation_transform(deg))
    # Compare as directions, not raw numbers: atan2 reports the negative-x axis
    # as +180 while the caller may have asked for -180, and those are the same
    # gradient. normalize_angle folds both onto the same representative.
    got = CoordinateMapper.normalize_angle(geom.angle_degrees)
    want = CoordinateMapper.normalize_angle(deg)
    assert got == pytest.approx(want, abs=1e-6)


def test_zero_degrees_runs_left_to_right():
    geom = geometry_from_transform(((1, 0, 0), (0, 1, 0)))
    assert geom.start == pytest.approx((0.0, 0.5))
    assert geom.end == pytest.approx((1.0, 0.5))


def test_ninety_degrees_runs_top_to_bottom():
    """+Y is down in design space, so 90 degrees must point downwards."""
    geom = geometry_from_transform(rotation_transform(90))
    assert geom.end[1] > geom.start[1]
    assert geom.end[0] == pytest.approx(geom.start[0], abs=1e-6)


def test_one_eighty_degrees_reverses_direction():
    geom = geometry_from_transform(rotation_transform(180))
    assert geom.end[0] < geom.start[0]


def test_non_uniform_transform_is_not_reduced_to_an_angle():
    """A stretched gradient must keep its length, not just its direction.

    The transform maps object space to gradient space, so scaling x by 2 there
    compresses the gradient to half the object's width.
    """
    geom = geometry_from_transform(((2.0, 0.0, 0.0), (0.0, 1.0, 0.0)))
    assert geom.length == pytest.approx(0.5)
    assert geom.end == pytest.approx((0.5, 0.5))


def test_sheared_transform_survives():
    geom = geometry_from_transform(((1.0, 0.5, 0.0), (0.0, 1.0, 0.0)))
    assert geom.start != geom.end
    # Shear moves the start off the mid-line; an angle-only model would lose this.
    assert geom.start[1] == pytest.approx(0.5)
    assert geom.start[0] != pytest.approx(0.0)


def test_singular_transform_is_rejected_not_silently_fixed():
    with pytest.raises(ValueError):
        geometry_from_transform(((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))


def test_handles_take_priority_when_supplied():
    geom = geometry_from_handles((0.1, 0.2), (0.9, 0.8))
    assert geom.start == (0.1, 0.2)
    assert geom.end == (0.9, 0.8)


# -- stops -----------------------------------------------------------------

def test_all_stops_survive_with_their_alpha():
    stops = [
        {"position": 0.0, "color": {"r": 1, "g": 0, "b": 0, "a": 1.0}},
        {"position": 0.35, "color": {"r": 0, "g": 1, "b": 0, "a": 0.5}},
        {"position": 1.0, "color": {"r": 0, "g": 0, "b": 1, "a": 0.0}},
    ]
    out = build_stops(stops)
    assert len(out) == 3
    assert [p for p, _ in out] == [0.0, 0.35, 1.0]
    assert out[1][1][3] == pytest.approx(0.5)
    assert out[2][1][3] == pytest.approx(0.0)


def test_stops_are_sorted_even_if_supplied_out_of_order():
    stops = [
        {"position": 1.0, "color": {"r": 0, "g": 0, "b": 1, "a": 1}},
        {"position": 0.0, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
    ]
    out = build_stops(stops)
    assert [p for p, _ in out] == [0.0, 1.0]


def test_duplicate_positions_are_separated_not_collapsed():
    """Fusion keys stops by position, so two stops at the same spot would merge
    and silently lose a hard colour break."""
    stops = [
        {"position": 0.5, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
        {"position": 0.5, "color": {"r": 0, "g": 0, "b": 1, "a": 1}},
    ]
    out = build_stops(stops)
    assert len(out) == 2
    assert out[0][0] != out[1][0]


def test_paint_opacity_folds_into_stop_alpha():
    stops = [{"position": 0.0, "color": {"r": 1, "g": 1, "b": 1, "a": 1.0}}]
    out = build_stops(stops, paint_opacity=0.4)
    assert out[0][1][3] == pytest.approx(0.4)


def test_single_stop_is_expanded_so_fusion_can_render_it():
    out = build_stops([{"position": 0.0, "color": {"r": 1, "g": 0, "b": 0, "a": 1}}])
    assert len(out) == 2
    assert out[0][1] == out[1][1]


def test_empty_stops_do_not_crash_the_build():
    assert len(build_stops([])) == 2


# -- type mapping ----------------------------------------------------------

def test_linear_and_radial_are_exact():
    assert map_gradient_type("GRADIENT_LINEAR").exact
    assert map_gradient_type("GRADIENT_RADIAL").exact


@pytest.mark.parametrize("t", ["GRADIENT_ANGULAR", "GRADIENT_DIAMOND"])
def test_approximated_types_always_carry_an_explanation(t):
    m = map_gradient_type(t)
    assert not m.exact
    assert m.note
