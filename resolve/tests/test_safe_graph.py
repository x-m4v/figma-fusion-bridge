import pytest
from ffbridge.builder import BuildOptions, build_graph
from ffbridge.safe_graph import prepare_receive_graph
from ffbridge.ascii_writer import Link
from fixtures import base_doc, node, solid


@pytest.mark.parametrize('width,height', [(1920,1080),(1080,1920),(3840,2160)])
def test_receive_uses_editable_masks_without_shape_renderer(width, height):
    result = build_graph(base_doc([node('1', 'RECTANGLE', 0, 0, 200, 100,
        fills=[solid(1,0,0,opacity=0.4)], geometry={'cornerRadii':[20]*4})]),
        BuildOptions(comp_width=width, comp_height=height))
    prepare_receive_graph(result, width, height)
    assert not result.diagnostics.has_errors
    assert not any(t.tool_id == 'sRender' for t in result.comp.tools)
    mask = next(t for t in result.comp.tools if t.tool_id == 'RectangleMask')
    bg = next(t for t in result.comp.tools if t.tool_id == 'Background')
    assert mask.inputs['Width'] * width == pytest.approx(200)
    assert mask.inputs['Height'] * height == pytest.approx(100)
    assert mask.inputs['CornerRadius'] == pytest.approx(0.4)
    assert bg.inputs['EffectMask'] == Link(mask.name, 'Mask')
    assert bg.inputs['TopLeftAlpha'] == pytest.approx(0.4)


def test_unverified_renderer_blocks_receive_instead_of_silent_loss():
    result = build_graph(base_doc([node('1', 'POLYGON', 0,0,100,100,
        fills=[solid(1,0,0)], geometry={'pointCount':5})]))
    prepare_receive_graph(result, 1920,1080)
    assert result.diagnostics.has_errors
    assert any(d.code == 'SHAPE_RENDER_QUARANTINED' for d in result.diagnostics.items)
