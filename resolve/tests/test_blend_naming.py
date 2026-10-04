"""Blend mapping and Fusion node naming."""

import pytest

from ffbridge.blend import map_blend_mode
from ffbridge.naming import NameAllocator, sanitize


@pytest.mark.parametrize("mode,expected", [
    ("MULTIPLY", "Multiply"), ("SCREEN", "Screen"), ("OVERLAY", "Overlay"),
    ("COLOR_BURN", "Color Burn"), ("COLOR_DODGE", "Color Dodge"),
    ("HARD_LIGHT", "Hard Light"), ("SOFT_LIGHT", "Soft Light"),
    ("LINEAR_BURN", "LinearBurn"), ("DIFFERENCE", "Difference"), ("LIGHTEN", "Lighten"),
])
def test_exact_modes_use_fusions_own_spelling(mode, expected):
    """Fusion's naming is inconsistent — "Color Burn" has a space, "LinearBurn"
    does not — and an unrecognised FuID silently keeps the default."""
    m = map_blend_mode(mode)
    assert m.apply_mode == expected
    assert m.exact


@pytest.mark.parametrize("mode", ["NORMAL", "PASS_THROUGH"])
def test_normal_leaves_apply_mode_unset(mode):
    m = map_blend_mode(mode)
    assert m.apply_mode is None and m.exact


@pytest.mark.parametrize("mode", ["DARKEN", "LINEAR_DODGE", "EXCLUSION"])
def test_approximated_modes_explain_themselves(mode):
    m = map_blend_mode(mode)
    assert not m.exact and m.note


@pytest.mark.parametrize("mode", ["HUE", "SATURATION", "COLOR", "LUMINOSITY"])
def test_non_separable_modes_are_reported_not_faked(mode):
    m = map_blend_mode(mode)
    assert m.apply_mode is None
    assert not m.exact and m.note


def test_unknown_mode_degrades_safely_with_a_message():
    m = map_blend_mode("SOMETHING_NEW")
    assert m.apply_mode is None and "SOMETHING_NEW" in m.note


# -- naming ----------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("CTA Button", "CTA_Button"),
    ("Card / Header", "Card_Header"),
    ("  spaced  out  ", "spaced_out"),
    ("hyphen-name", "hyphen_name"),
    ("dots.in.name", "dots_in_name"),
])
def test_sanitize_produces_legal_identifiers(raw, expected):
    assert sanitize(raw) == expected


def test_leading_digit_is_prefixed_because_identifiers_cannot_start_with_one():
    assert sanitize("123 Start") == "N123_Start"


def test_cyrillic_is_transliterated_not_discarded():
    """Dropping non-Latin names would turn a whole document into Layer_1..N."""
    assert sanitize("Заголовок") == "Zagolovok"
    assert sanitize("Кнопка Купить") == "Knopka_Kupit"


def test_accents_fold_to_ascii():
    assert sanitize("Título") == "Titulo"
    assert sanitize("Über") == "Uber"


def test_emoji_only_names_fall_back_rather_than_producing_nothing():
    assert sanitize("🔥🔥🔥") == "Layer"
    assert sanitize("") == "Layer"


def test_reserved_words_are_escaped():
    assert sanitize("Comp") == "Comp_"


def test_allocator_keeps_the_first_name_clean_then_suffixes():
    a = NameAllocator()
    assert a.allocate("Card", "Shape") == "Card_Shape"
    assert a.allocate("Card", "Shape") == "Card_Shape_2"
    assert a.allocate("Card", "Shape") == "Card_Shape_3"


def test_allocator_is_deterministic_across_runs():
    seq = ["A", "B", "A", "C", "A"]
    first = [NameAllocator().allocate(n, "Shape") for n in seq]
    a, b = NameAllocator(), NameAllocator()
    assert [a.allocate(n, "Shape") for n in seq] == [b.allocate(n, "Shape") for n in seq]


def test_reserved_names_are_not_reused():
    a = NameAllocator()
    a.reserve("Card_Shape")
    assert a.allocate("Card", "Shape") == "Card_Shape_2"
