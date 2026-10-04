"""Stroke alignment geometry.

Alignment is reproduced by moving the path, not by fudging the thickness, so
these tests check the resulting path against the exact band the design describes.
"""

import math

import pytest

from ffbridge.stroke import (
    dash_warning,
    ellipse_stroke_geometry,
    polygon_stroke_geometry,
    rect_stroke_geometry,
)


def test_centre_stroke_leaves_the_path_alone():
    g = rect_stroke_geometry(200, 100, 10, "CENTER")
    assert (g.width, g.height) == (200, 100)
    assert g.thickness == 10


def test_inside_stroke_shrinks_the_path_by_the_weight():
    """An inside stroke covers the band from the edge inward, which is the same
    band a centred stroke covers on a path inset by half the weight."""
    g = rect_stroke_geometry(200, 100, 10, "INSIDE")
    assert (g.width, g.height) == (190, 90)
    # Outer edge of the drawn band must coincide with the original edge.
    assert g.width + g.thickness == 200


def test_outside_stroke_grows_the_path_by_the_weight():
    g = rect_stroke_geometry(200, 100, 10, "OUTSIDE")
    assert (g.width, g.height) == (210, 110)
    assert g.width - g.thickness == 200


@pytest.mark.parametrize(
    "align,expected", [("INSIDE", 15.0), ("CENTER", 20.0), ("OUTSIDE", 25.0)]
)
def test_corner_radius_follows_the_offset_edge(align, expected):
    g = rect_stroke_geometry(200, 100, 10, align, (20, 20, 20, 20))
    assert g.corner_radii == (expected,) * 4


def test_corner_radius_floors_at_zero_when_the_corner_goes_square():
    g = rect_stroke_geometry(200, 100, 20, "INSIDE", (4, 4, 4, 4))
    assert g.corner_radii == (0.0, 0.0, 0.0, 0.0)


def test_overthick_inside_stroke_warns_instead_of_going_negative():
    g = rect_stroke_geometry(20, 20, 40, "INSIDE")
    assert g.width >= 0 and g.height >= 0
    assert "fills it completely" in g.warning


def test_ellipse_offsets_both_axes():
    g = ellipse_stroke_geometry(100, 50, 8, "OUTSIDE")
    assert g.width == pytest.approx(108)
    assert g.height == pytest.approx(58)


def test_thick_ellipse_stroke_is_flagged_as_approximate():
    """The true offset of an ellipse is not an ellipse; say so when it matters."""
    g = ellipse_stroke_geometry(100, 100, 40, "OUTSIDE")
    assert g.warning


def test_thin_ellipse_stroke_is_not_flagged():
    g = ellipse_stroke_geometry(400, 400, 2, "OUTSIDE")
    assert g.warning == ""


def test_polygon_offset_moves_edges_not_vertices():
    """Scaling the circumradius by the offset would misplace a triangle's edges
    by about 15 percent. The apothem correction is what fixes that."""
    sides, offset = 3, 5.0
    g = polygon_stroke_geometry(100, 100, offset * 2, "OUTSIDE", sides)
    expected = 100 + 2 * (offset / math.cos(math.pi / sides))
    assert g.width == pytest.approx(expected)
    assert g.width > 100 + 2 * offset  # strictly more than the naive answer


def test_polygon_with_many_sides_approaches_the_circle_case():
    g = polygon_stroke_geometry(100, 100, 10, "OUTSIDE", 128)
    assert g.width == pytest.approx(110, abs=0.05)


def test_dashes_are_reported_not_ignored():
    assert dash_warning([4, 4])
    assert dash_warning([]) is None
