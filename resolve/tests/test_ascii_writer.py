"""The Fusion ASCII serialiser.

Expected output was checked against composition files shipped by Blackmagic
Design, so these tests pin compatibility with what Fusion writes itself.
"""

import pytest

from ffbridge.ascii_writer import (
    CompDocument, Expression, FuID, Gradient, Link, Point, Tool, Vec, render_value,
)


def test_enums_render_as_fuid_not_as_strings():
    """A quoted string in an enum input is silently ignored by Fusion."""
    assert render_value(FuID("Gradient")) == 'FuID { "Gradient" }'


def test_numbers_lose_trailing_zeroes_like_fusion_writes_them():
    assert render_value(1920.0) == "1920"
    assert render_value(0.250000) == "0.25"


def test_booleans_render_as_one_and_zero():
    assert render_value(True) == "1"
    assert render_value(False) == "0"


def test_nan_and_infinity_degrade_to_zero_rather_than_corrupting_the_file():
    assert render_value(float("nan")) == "0"
    assert render_value(float("inf")) == "0"


def test_newlines_are_escaped_so_the_tool_block_survives():
    """A raw newline inside StyledText would truncate the tool definition."""
    assert render_value("a\nb") == '"a\\nb"'


def test_quotes_and_backslashes_are_escaped():
    assert render_value('say "hi"\\') == '"say \\"hi\\"\\\\"'


def test_unicode_passes_through_unescaped():
    assert render_value("Заголовок") == '"Заголовок"'


def test_point_and_vec_are_different_forms():
    assert Point(0.5, 0.25).render() == "Point { X = 0.5, Y = 0.25 }"
    assert Vec(0.5, 0.25).render() == "{ 0.5, 0.25 }"


def test_gradient_stops_render_sorted_by_position():
    g = Gradient([(1.0, (0, 0, 1, 1)), (0.0, (1, 0, 0, 1))])
    out = g.render()
    assert out.index("[0]") < out.index("[1]")


def test_dotted_input_names_are_bracketed():
    """Shipped content writes ["Translate.X"]; an unbracketed dot is a syntax error."""
    t = Tool("sRectangle", "R1", {"Translate.X": 0.5})
    assert '["Translate.X"]' in t.render("")


def test_links_render_as_sourceop_pairs():
    t = Tool("Merge", "M1", {"Background": Link("BG1")})
    out = t.render("")
    assert 'SourceOp = "BG1"' in out and 'Source = "Output"' in out


def test_expressions_carry_both_value_and_expression():
    t = Tool("sRectangle", "R1", {"Height": Expression(0.05, "Width")})
    out = t.render("")
    assert 'Expression = "Width"' in out and "Value = 0.05" in out


def test_custom_data_is_namespaced():
    t = Tool("Transform", "T1", {}, data={"nodeId": "1:23"})
    out = t.render("")
    assert "CustomData" in out and "FFBridge" in out and '"1:23"' in out


def test_duplicate_tool_names_are_refused():
    d = CompDocument()
    d.add(Tool("Transform", "T1"))
    with pytest.raises(ValueError):
        d.add(Tool("Transform", "T1"))


def test_document_braces_balance():
    d = CompDocument()
    d.add(Tool("Background", "BG", {"Gradient": Gradient([(0.0, (1, 0, 0, 1))])}))
    d.add(Tool("Merge", "M", {"Background": Link("BG"), "ApplyMode": FuID("Multiply")}))
    d.active_tool = "M"
    out = d.render()
    assert out.count("{") == out.count("}")
    assert "Tools = ordered()" in out and 'ActiveTool = "M"' in out


def test_unserialisable_values_raise_rather_than_writing_garbage():
    with pytest.raises(TypeError):
        render_value(object())
