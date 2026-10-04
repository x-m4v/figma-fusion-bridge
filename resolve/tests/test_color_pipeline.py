from ffbridge.builder import build_graph
from ffbridge.color_pipeline import add_color_boundary
from ffbridge.ascii_writer import FuID
from fixtures import base_doc, node, solid


def design():
    return build_graph(base_doc([node('1','RECTANGLE',0,0,100,100,fills=[solid(.5,.2,.1)])]))


def test_dwg_boundary_preserves_source_values_and_handles_alpha():
    result = design()
    old_output = result.output_tool
    shape = next(t for t in result.comp.tools if t.tool_id == 'sRectangle')
    add_color_boundary(result, 'DWG_LINEAR')
    boundary = result.comp.get(result.output_tool)
    assert boundary.inputs['Input'].source_op == old_output
    assert shape.inputs['Red'] == .5
    assert boundary.inputs['SourceSpace'] == FuID('sRGB')
    assert boundary.inputs['AddGamma'] == 0
    assert boundary.inputs['PreDividePostMultiply'] == 1
    assert boundary.inputs['CustomOutputBlue'].values == (.079,-.1155)
    assert result.comp.active_tool == result.output_tool


def test_unknown_context_cannot_silently_produce_wrong_colors():
    result = design()
    add_color_boundary(result, 'ACES')
    assert result.diagnostics.has_errors


def test_unmanaged_is_not_automatically_linearized():
    result = design()
    output = result.output_tool
    add_color_boundary(result, 'UNMANAGED')
    assert result.output_tool == output
    assert not result.diagnostics.has_errors
