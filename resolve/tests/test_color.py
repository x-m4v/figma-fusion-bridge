"""Colour policy. Design RGB is not unconditionally Fusion RGB."""

import pytest

from ffbridge.color import (
    ADVANCED, MATCH_SRGB, PROJECT_MANAGED,
    convert_rgba, linear_to_srgb, multiply_alpha,
    premultiply, srgb_to_linear, to_hex, unpremultiply,
)


@pytest.mark.parametrize("v", [0.0, 0.02, 0.04045, 0.5, 0.75, 1.0])
def test_srgb_transfer_round_trips(v):
    # 1e-7 rather than machine epsilon on purpose. The sRGB standard publishes
    # rounded constants (0.04045, 12.92, 0.055, 2.4) whose two segments do not
    # meet perfectly; the true continuity point is 0.0404482362. The resulting
    # kink is about 3e-8, five orders of magnitude below one 8-bit code value.
    # Using "exact" constants instead would round-trip perfectly here and
    # disagree with every other tool in the pipeline, which is the worse trade.
    assert linear_to_srgb(srgb_to_linear(v)) == pytest.approx(v, abs=1e-7)


def test_srgb_uses_the_exact_curve_not_gamma_22():
    """The 2.2 approximation is off by enough to shift dark UI surfaces."""
    exact = srgb_to_linear(0.2)
    approx = 0.2 ** 2.2
    assert exact != pytest.approx(approx, abs=1e-4)
    assert exact == pytest.approx(0.033104766, abs=1e-8)


def test_transfer_is_monotonic_across_the_hinge():
    assert srgb_to_linear(0.04) < srgb_to_linear(0.04045) < srgb_to_linear(0.05)


def test_negative_values_stay_monotonic():
    """Out-of-range colours occur in wide-gamut work; they must not fold back."""
    assert srgb_to_linear(-0.5) < srgb_to_linear(-0.1) < srgb_to_linear(0.0)


def test_match_srgb_passes_values_through_untouched():
    assert convert_rgba((0.2, 0.4, 0.6, 0.8), MATCH_SRGB) == (0.2, 0.4, 0.6, 0.8)


def test_project_managed_linearises_colour_but_not_alpha():
    r, g, b, a = convert_rgba((0.5, 0.5, 0.5, 0.42), PROJECT_MANAGED)
    assert r == pytest.approx(srgb_to_linear(0.5))
    assert a == pytest.approx(0.42)  # alpha is not a colour


def test_unknown_policy_is_rejected_rather_than_guessed():
    with pytest.raises(ValueError):
        convert_rgba((0, 0, 0, 1), "SOMETHING_ELSE")


def test_multiply_alpha_touches_only_alpha():
    assert multiply_alpha((0.2, 0.4, 0.6, 1.0), 0.5) == (0.2, 0.4, 0.6, 0.5)


def test_premultiply_round_trips():
    c = (0.8, 0.4, 0.2, 0.5)
    assert unpremultiply(premultiply(c)) == pytest.approx(c)


def test_unpremultiply_survives_fully_transparent_pixels():
    assert unpremultiply((0.0, 0.0, 0.0, 0.0)) == (0.0, 0.0, 0.0, 0.0)


def test_hex_clamps_instead_of_raising():
    assert to_hex((2.0, -1.0, 0.5, 1.0)) == "#FF0080FF"
