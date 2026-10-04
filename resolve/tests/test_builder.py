"""End-to-end builder tests.

These run the real converter over real documents and assert on the Fusion ASCII
it produces. No Resolve is involved, which is the point: every conversion rule
in the product is verifiable in a plain test run.
"""

import pytest

from ffbridge.builder import BuildOptions, build_graph
from ffbridge.fonts import FontResolver
from fixtures import base_doc, node, solid


def build(nodes, **kw):
    opts = BuildOptions(**kw)
    return build_graph(base_doc(nodes), opts, FontResolver({"inter": ["Regular", "Bold"]}))


# -- shapes ----------------------------------------------------------------

def test_rectangle_becomes_a_native_shape_not_an_image():
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100, fills=[solid(1, 0, 0)])])
    text = r.comp.render()
    assert "sRectangle" in text
    assert "Loader" not in text
    assert r.output_tool is not None


def test_rectangle_keeps_a_numeric_editable_corner_radius():
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100,
                    fills=[solid(1, 0, 0)],
                    geometry={"cornerRadii": [20, 20, 20, 20], "cornerSmoothing": 0})])
    shape = next(t for t in r.comp.tools if t.tool_id == "sRectangle")
    # Fusion normalises against half the shorter side: 20 / (100/2) = 0.4
    assert shape.inputs["CornerRadius"] == pytest.approx(0.4)


def test_full_corner_radius_reads_as_a_pill():
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100,
                    fills=[solid(1, 0, 0)],
                    geometry={"cornerRadii": [50, 50, 50, 50]})])
    shape = next(t for t in r.comp.tools if t.tool_id == "sRectangle")
    assert shape.inputs["CornerRadius"] == pytest.approx(1.0)


def test_mixed_corner_radii_warn_rather_than_average():
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100,
                    fills=[solid(1, 0, 0)],
                    geometry={"cornerRadii": [0, 20, 0, 20]})])
    assert any(d.code == "MIXED_CORNER_RADIUS" for d in r.diagnostics.items)


def test_ellipse_and_polygon_use_their_own_tools():
    r = build([
        node("1", "ELLIPSE", 0, 0, 100, 100, fills=[solid(0, 1, 0)]),
        node("2", "POLYGON", 200, 0, 100, 100, index=1, fills=[solid(0, 0, 1)],
             geometry={"pointCount": 6}),
    ])
    ids = {t.tool_id for t in r.comp.tools}
    assert "sEllipse" in ids and "sNGon" in ids
    ngon = next(t for t in r.comp.tools if t.tool_id == "sNGon")
    assert ngon.inputs["Sides"] == 6


def test_polygon_side_count_stays_editable():
    r = build([node("1", "POLYGON", 0, 0, 100, 100, fills=[solid(1, 1, 1)],
                    geometry={"pointCount": 7})])
    ngon = next(t for t in r.comp.tools if t.tool_id == "sNGon")
    assert ngon.inputs["Sides"] == 7


# -- opacity ---------------------------------------------------------------

def test_fill_opacity_and_layer_opacity_stay_independent():
    """The single most important fidelity rule: 40% fill inside a 70% layer is
    not a 28% anything. They must land on different Fusion controls."""
    n1 = node("1", "RECTANGLE", 0, 0, 100, 100, fills=[solid(1, 0, 0)])
    n2 = node("2", "RECTANGLE", 50, 50, 100, 100, index=1,
              opacity=0.7, fills=[solid(0, 0, 1, opacity=0.4)])
    r = build([n1, n2])

    shape = next(t for t in r.comp.tools
                 if t.tool_id == "sRectangle" and t.inputs.get("Blue") == 1.0)
    assert shape.inputs["Alpha"] == pytest.approx(0.4)   # fill opacity

    merge = next(t for t in r.comp.tools if t.tool_id == "Merge" and "Blend" in t.inputs)
    assert merge.inputs["Blend"] == pytest.approx(0.7)   # layer opacity

    # And crucially, neither is the product of the two.
    assert shape.inputs["Alpha"] != pytest.approx(0.28)
    assert merge.inputs["Blend"] != pytest.approx(0.28)


# -- gradients -------------------------------------------------------------

def gradient_paint(kind="GRADIENT_LINEAR", opacity=1.0):
    return {
        "type": kind, "visible": True, "opacity": opacity, "blendMode": "NORMAL",
        "stops": [
            {"position": 0.0, "color": {"r": 1, "g": 0, "b": 0, "a": 1}},
            {"position": 0.5, "color": {"r": 0, "g": 1, "b": 0, "a": 0.5}},
            {"position": 1.0, "color": {"r": 0, "g": 0, "b": 1, "a": 1}},
        ],
        "transform": [[1, 0, 0], [0, 1, 0]],
    }


def test_gradient_becomes_a_native_background_with_all_stops():
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100, fills=[gradient_paint()])])
    bg = next(t for t in r.comp.tools if t.tool_id == "Background")
    grad = bg.inputs["Gradient"]
    assert len(grad.stops) == 3
    assert bg.inputs["Type"].value == "Gradient"
    assert bg.inputs["GradientType"].value == "Linear"
    # And it is a real gradient, not a picture of one.
    assert "Loader" not in r.comp.render()


def test_gradient_stop_alpha_survives():
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100, fills=[gradient_paint()])])
    bg = next(t for t in r.comp.tools if t.tool_id == "Background")
    alphas = [rgba[3] for _, rgba in bg.inputs["Gradient"].stops]
    assert pytest.approx(0.5) in alphas


def test_radial_gradient_maps_to_radial():
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100,
                    fills=[gradient_paint("GRADIENT_RADIAL")])])
    bg = next(t for t in r.comp.tools if t.tool_id == "Background")
    assert bg.inputs["GradientType"].value == "Radial"


def test_angular_gradient_is_flagged_as_approximate():
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100,
                    fills=[gradient_paint("GRADIENT_ANGULAR")])])
    assert any(d.code == "GRADIENT_APPROXIMATED" for d in r.diagnostics.items)


# -- strokes ---------------------------------------------------------------

def stroke(weight=10, align="CENTER", paint=None):
    return {
        "paints": [paint or solid(0, 0, 0)],
        "weight": weight, "align": align,
        "cap": "NONE", "join": "MITER", "miterLimit": 4, "dashPattern": [],
    }


def test_stroke_is_a_separate_branch_from_the_fill():
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100,
                    fills=[solid(1, 0, 0)], stroke=stroke())])
    shapes = [t for t in r.comp.tools if t.tool_id == "sRectangle"]
    assert len(shapes) == 2
    solids = sorted(s.inputs["Solid"] for s in shapes)
    assert solids == [0, 1]  # one filled, one outlined


@pytest.mark.parametrize("align,expected_px", [("INSIDE", 190), ("CENTER", 200), ("OUTSIDE", 210)])
def test_stroke_alignment_changes_the_geometry(align, expected_px):
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100,
                    fills=[solid(1, 0, 0)], stroke=stroke(10, align))],
              comp_width=1920, comp_height=1080)
    outline = next(t for t in r.comp.tools
                   if t.tool_id == "sRectangle" and t.inputs.get("Solid") == 0)
    assert outline.inputs["Width"] == pytest.approx(expected_px / 1080.0)


def test_gradient_stroke_is_not_rasterised():
    r = build([node("1", "RECTANGLE", 0, 0, 200, 100,
                    fills=[solid(1, 0, 0)],
                    stroke=stroke(paint=gradient_paint()))])
    text = r.comp.render()
    assert "Background" in text and "Loader" not in text


# -- text ------------------------------------------------------------------

def text_payload(chars="Hello", family="Inter", style="Regular", size=48):
    return {
        "characters": chars,
        "font": {"family": family, "style": style, "italic": False},
        "fontSize": size,
        "letterSpacing": {"unit": "PERCENT", "value": 0},
        "lineHeight": {"unit": "AUTO"},
        "paragraphSpacing": 0, "paragraphIndent": 0,
        "alignHorizontal": "LEFT", "alignVertical": "TOP",
        "autoResize": "NONE", "hasMixedStyles": False, "segments": [],
    }


def test_text_becomes_editable_textplus_never_a_raster():
    r = build([node("1", "TEXT", 0, 0, 400, 60, fills=[solid(1, 1, 1)],
                    text=text_payload("Headline"))])
    tp = next(t for t in r.comp.tools if t.tool_id == "TextPlus")
    assert tp.inputs["StyledText"] == "Headline"
    assert "Loader" not in r.comp.render()


def test_multiline_text_keeps_its_line_breaks():
    r = build([node("1", "TEXT", 0, 0, 400, 120, fills=[solid(1, 1, 1)],
                    text=text_payload("One\nTwo"))])
    tp = next(t for t in r.comp.tools if t.tool_id == "TextPlus")
    assert tp.inputs["StyledText"] == "One\nTwo"
    assert "\\n" in r.comp.render()  # escaped, so the tool block stays intact


def test_text_size_is_relative_to_composition_height():
    r = build([node("1", "TEXT", 0, 0, 400, 60, fills=[solid(1, 1, 1)],
                    text=text_payload(size=108))], comp_width=1920, comp_height=1080)
    tp = next(t for t in r.comp.tools if t.tool_id == "TextPlus")
    assert tp.inputs["Size"] == pytest.approx(0.1)


def test_alignment_uses_the_modern_justification_inputs():
    """Resolve 21 writes HorizontalJustificationNew; the un-suffixed input is
    the legacy one and setting it alone does nothing."""
    payload = text_payload()
    payload["alignHorizontal"] = "CENTER"
    payload["alignVertical"] = "BOTTOM"
    r = build([node("1", "TEXT", 0, 0, 400, 60, fills=[solid(1, 1, 1)], text=payload)])
    tp = next(t for t in r.comp.tools if t.tool_id == "TextPlus")
    assert tp.inputs["HorizontalJustificationNew"] == 1
    assert tp.inputs["VerticalJustificationNew"] == 2


def test_missing_font_warns_and_keeps_the_original_name():
    r = build([node("1", "TEXT", 0, 0, 400, 60, fills=[solid(1, 1, 1)],
                    text=text_payload(family="Neue Haas Grotesk Display Pro", style="Medium"))])
    assert any(d.code == "FONT_MISSING" for d in r.diagnostics.items)
    tp = next(t for t in r.comp.tools if t.tool_id == "TextPlus")
    assert tp.inputs["Font"] == "Neue Haas Grotesk Display Pro"


# -- hierarchy and z-order -------------------------------------------------

def test_hierarchy_is_preserved_not_flattened():
    nodes = [
        node("g", "GROUP", 0, 0, 300, 300),
        node("a", "RECTANGLE", 0, 0, 100, 100, parent="g", index=0, fills=[solid(1, 0, 0)]),
        node("b", "RECTANGLE", 50, 50, 100, 100, parent="g", index=1, fills=[solid(0, 1, 0)]),
    ]
    r = build(nodes)
    assert r.manifest.tool_for("g", "Container")
    assert r.manifest.tool_for("a", "Shape")
    assert r.manifest.tool_for("b", "Shape")


def test_z_order_matches_paint_order():
    nodes = [
        node("bottom", "RECTANGLE", 0, 0, 100, 100, index=0, fills=[solid(1, 0, 0)]),
        node("top", "RECTANGLE", 0, 0, 100, 100, index=1, fills=[solid(0, 0, 1)]),
    ]
    r = build(nodes)
    merge = next(t for t in r.comp.tools if t.tool_id == "Merge")
    bg_name = merge.inputs["Background"].source_op
    fg_name = merge.inputs["Foreground"].source_op
    # The first-painted layer must be the Background of the Merge.
    assert r.manifest.tool_for("bottom", "Anim") == bg_name
    assert r.manifest.tool_for("top", "Anim") == fg_name


def test_hidden_layers_are_skipped_by_default():
    nodes = [
        node("1", "RECTANGLE", 0, 0, 100, 100, fills=[solid(1, 0, 0)]),
        node("2", "RECTANGLE", 0, 0, 100, 100, index=1, visible=False, fills=[solid(0, 1, 0)]),
    ]
    r = build(nodes)
    assert len([t for t in r.comp.tools if t.tool_id == "sRectangle"]) == 1


def test_hidden_layers_are_included_on_request():
    nodes = [
        node("1", "RECTANGLE", 0, 0, 100, 100, fills=[solid(1, 0, 0)]),
        node("2", "RECTANGLE", 0, 0, 100, 100, index=1, visible=False, fills=[solid(0, 1, 0)]),
    ]
    r = build(nodes, include_hidden=True)
    assert len([t for t in r.comp.tools if t.tool_id == "sRectangle"]) == 2


# -- animation preservation ------------------------------------------------

def test_every_layer_gets_a_user_animation_slot():
    """The Transform that sync never writes to. Without it, a re-sync would
    have nowhere safe to leave the user's keyframes."""
    r = build([node("1", "RECTANGLE", 0, 0, 100, 100, fills=[solid(1, 0, 0)])])
    anim_name = r.manifest.tool_for("1", "Anim")
    assert anim_name
    anim = r.comp.get(anim_name)
    assert anim.tool_id == "Transform"
    assert anim.data["role"] == "USER"
    assert "never overwrites" in anim.comments


def test_every_node_carries_its_source_identity():
    r = build([node("1", "RECTANGLE", 0, 0, 100, 100, name="CTA", fills=[solid(1, 0, 0)])])
    shape = next(t for t in r.comp.tools if t.tool_id == "sRectangle")
    assert shape.data["nodeId"] == "1"
    assert shape.data["documentId"] == "doc-1"
    assert shape.data["transferId"] == "t-test"


# -- naming ----------------------------------------------------------------

def test_node_names_come_from_layer_names():
    r = build([node("1", "RECTANGLE", 0, 0, 100, 100, name="CTA Button", fills=[solid(1, 0, 0)])])
    assert any(t.name.startswith("CTA_Button") for t in r.comp.tools)


def test_duplicate_layer_names_get_stable_suffixes():
    nodes = [
        node("1", "RECTANGLE", 0, 0, 100, 100, name="Card", fills=[solid(1, 0, 0)]),
        node("2", "RECTANGLE", 0, 0, 100, 100, index=1, name="Card", fills=[solid(0, 1, 0)]),
    ]
    r = build(nodes)
    names = [t.name for t in r.comp.tools if t.tool_id == "sRectangle"]
    assert len(set(names)) == 2


# -- effects ---------------------------------------------------------------

def test_drop_shadow_creates_a_shadow_node():
    eff = {"type": "DROP_SHADOW", "visible": True,
           "color": {"r": 0, "g": 0, "b": 0, "a": 0.25},
           "offset": {"x": 0, "y": 4}, "radius": 8, "spread": 0,
           "blendMode": "NORMAL", "showShadowBehindNode": True}
    r = build([node("1", "RECTANGLE", 0, 0, 100, 100, fills=[solid(1, 0, 0)], effects=[eff])])
    assert any(t.tool_id == "Shadow" for t in r.comp.tools)


def test_layer_blur_creates_a_blur_node():
    eff = {"type": "LAYER_BLUR", "visible": True, "radius": 12}
    r = build([node("1", "RECTANGLE", 0, 0, 100, 100, fills=[solid(1, 0, 0)], effects=[eff])])
    assert any(t.tool_id == "Blur" for t in r.comp.tools)


def test_inner_shadow_is_built_from_real_nodes_not_skipped():
    eff = {"type": "INNER_SHADOW", "visible": True,
           "color": {"r": 0, "g": 0, "b": 0, "a": 0.5},
           "offset": {"x": 0, "y": 2}, "radius": 4, "spread": 0,
           "blendMode": "NORMAL", "showShadowBehindNode": True}
    r = build([node("1", "RECTANGLE", 0, 0, 100, 100, fills=[solid(1, 0, 0)], effects=[eff])])
    ids = [t.tool_id for t in r.comp.tools]
    assert "ChannelBoolean" in ids and "Blur" in ids
    assert any(d.code == "INNER_SHADOW_BUILT" for d in r.diagnostics.items)


def test_background_blur_is_reported_never_silently_dropped():
    eff = {"type": "BACKGROUND_BLUR", "visible": True, "radius": 20}
    r = build([node("1", "RECTANGLE", 0, 0, 100, 100, fills=[solid(1, 0, 0)], effects=[eff])])
    assert any(d.code == "BACKGROUND_BLUR_EXPERIMENTAL" for d in r.diagnostics.items)


# -- clipping --------------------------------------------------------------

def test_clipping_frame_creates_a_mask():
    nodes = [
        node("f", "FRAME", 0, 0, 200, 200, clipsContent=True, fills=[solid(1, 1, 1)]),
        node("c", "RECTANGLE", 150, 150, 200, 200, parent="f", fills=[solid(1, 0, 0)]),
    ]
    r = build(nodes)
    assert any(t.tool_id == "RectangleMask" for t in r.comp.tools)


def test_clip_frames_off_skips_the_mask():
    nodes = [
        node("f", "FRAME", 0, 0, 200, 200, clipsContent=True, fills=[solid(1, 1, 1)]),
        node("c", "RECTANGLE", 150, 150, 200, 200, parent="f", fills=[solid(1, 0, 0)]),
    ]
    r = build(nodes, clip_frames="OFF")
    assert not any(t.tool_id == "RectangleMask" for t in r.comp.tools)


# -- structural ------------------------------------------------------------

def test_output_is_syntactically_balanced():
    nodes = [
        node("f", "FRAME", 0, 0, 400, 400, fills=[solid(1, 1, 1)], clipsContent=True),
        node("t", "TEXT", 20, 20, 200, 40, parent="f", fills=[solid(0, 0, 0)], text=text_payload()),
        node("r", "RECTANGLE", 20, 80, 200, 60, parent="f", index=1,
             fills=[gradient_paint()], stroke=stroke(4, "INSIDE"),
             geometry={"cornerRadii": [8, 8, 8, 8]}),
    ]
    r = build(nodes)
    text = r.comp.render()
    assert text.count("{") == text.count("}")
    assert text.startswith("{") and text.rstrip().endswith("}")
    assert "Tools = ordered()" in text


def test_empty_selection_is_an_error_not_a_crash():
    r = build([])
    assert r.diagnostics.has_errors
    assert any(d.code == "EMPTY_TRANSFER" for d in r.diagnostics.items)


def test_every_link_points_at_a_tool_that_exists():
    """A dangling SourceOp loads as a broken node in Fusion with no error."""
    from ffbridge.ascii_writer import Link

    nodes = [
        node("f", "FRAME", 0, 0, 400, 400, fills=[solid(1, 1, 1)], clipsContent=True),
        node("t", "TEXT", 20, 20, 200, 40, parent="f", fills=[solid(0, 0, 0)], text=text_payload()),
        node("r", "RECTANGLE", 20, 80, 200, 60, parent="f", index=1,
             fills=[gradient_paint()], stroke=stroke(4, "OUTSIDE")),
    ]
    r = build(nodes)
    names = {t.name for t in r.comp.tools}
    for tool in r.comp.tools:
        for key, val in tool.inputs.items():
            if isinstance(val, Link):
                assert val.source_op in names, f"{tool.name}.{key} -> {val.source_op}"


# -- rotation --------------------------------------------------------------

def test_rotated_layer_is_centred_about_its_real_centre():
    """Design tools rotate about the top-left corner, so the visual centre is
    the local midpoint pushed through absoluteTransform — not x + w/2. Adding
    half the width is right only for unrotated layers and drifts further off
    the more a layer is turned."""
    import math

    w, h, deg = 200.0, 100.0, 90.0
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    n = node("1", "RECTANGLE", 0, 0, w, h, fills=[solid(1, 0, 0)])
    n["absoluteTransform"] = [[c, -s, 960.0], [s, c, 540.0]]
    n["rotation"] = deg

    r_out = build([n], comp_width=1920, comp_height=1080)
    shape = next(t for t in r_out.comp.tools if t.tool_id == "sRectangle")

    # Rotating (100, 50) by 90 degrees gives (-50, 100), so the centre lands at
    # (910, 640) in design space, not at (1060, 590).
    expected = ((910.0 - 960.0) / 1080.0, (540.0 - 640.0) / 1080.0)
    assert shape.inputs["Translate.X"] == pytest.approx(expected[0])
    assert shape.inputs["Translate.Y"] == pytest.approx(expected[1])
    # And the naive answer must be measurably different, or the test proves nothing.
    assert shape.inputs["Translate.X"] != pytest.approx((1060.0 - 960.0) / 1080.0)


def test_unrotated_layer_still_centres_the_obvious_way():
    n = node("1", "RECTANGLE", 100, 200, 200, 100, fills=[solid(1, 0, 0)])
    r_out = build([n], comp_width=1920, comp_height=1080)
    shape = next(t for t in r_out.comp.tools if t.tool_id == "sRectangle")
    assert shape.inputs["Translate.X"] == pytest.approx((200.0 - 960.0) / 1080.0)


def test_rotation_sign_is_flipped_for_fusion():
    """+Y is down in design space and up in Fusion, so a clockwise turn in the
    design tool must become counter-clockwise in Fusion or every rotated layer
    mirrors."""
    import math

    deg = 30.0
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    n = node("1", "RECTANGLE", 0, 0, 100, 100, fills=[solid(1, 0, 0)])
    n["absoluteTransform"] = [[c, -s, 0.0], [s, c, 0.0]]
    r_out = build([n])
    shape = next(t for t in r_out.comp.tools if t.tool_id == "sRectangle")
    assert shape.inputs["Angle"] == pytest.approx(-deg)


def test_rotated_text_is_placed_about_its_real_centre():
    import math

    deg = 45.0
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    n = node("1", "TEXT", 0, 0, 400, 100, fills=[solid(1, 1, 1)], text=text_payload())
    n["absoluteTransform"] = [[c, -s, 500.0], [s, c, 300.0]]
    r_out = build([n], comp_width=1920, comp_height=1080)
    place = next(t for t in r_out.comp.tools if t.inputs.get("Center") is not None
                 and t.tool_id == "Transform")
    cx, cy = mat_apply_local(c, s, 500.0, 300.0, 200.0, 50.0)
    assert place.inputs["Center"].x == pytest.approx(cx / 1920.0)
    assert place.inputs["Center"].y == pytest.approx(1.0 - cy / 1080.0)


def mat_apply_local(c, s, tx, ty, x, y):
    return (c * x - s * y + tx, s * x + c * y + ty)
