"""Receive compatibility pass: avoid the experimental shape renderer.

The offline builder retains its experimental plans. Receive must call this
pass before writing any settings. Unsupported branches fail closed.
"""
from .ascii_writer import Link, Point


def prepare_receive_graph(result, width, height):
    tools = {t.name: t for t in result.comp.tools}
    for render in result.comp.tools:
        if render.tool_id != 'sRender':
            continue
        link = render.inputs.get('Input')
        shape = tools.get(link.source_op) if isinstance(link, Link) else None
        if (shape is None or shape.tool_id not in ('sRectangle', 'sEllipse')
                or shape.inputs.get('Solid', 1) != 1):
            result.diagnostics.error('SHAPE_RENDER_QUARANTINED',
                'This polygon or stroke needs the experimental shape renderer. '
                'Receive is blocked until that renderer is verified on this Resolve version.')
            continue
        inputs = shape.inputs
        mask = {
            'Center': Point(0.5 + inputs.get('Translate.X', 0) * height / width,
                            0.5 + inputs.get('Translate.Y', 0)),
            'Width': inputs['Width'] * height / width,
            'Height': inputs['Height'], 'Angle': inputs.get('Angle', 0),
            'Solid': 1, 'MaskWidth': width, 'MaskHeight': height,
            'UseFrameFormatSettings': 1,
        }
        if shape.tool_id == 'sRectangle':
            mask['CornerRadius'] = inputs.get('CornerRadius', 0)
        shape.tool_id = 'RectangleMask' if shape.tool_id == 'sRectangle' else 'EllipseMask'
        shape.inputs = mask
        render.tool_id = 'Background'
        render.inputs = {
            'EffectMask': Link(shape.name, 'Mask'),
            'Width': width, 'Height': height, 'UseFrameFormatSettings': 1,
            'TopLeftRed': inputs.get('Red', 1),
            'TopLeftGreen': inputs.get('Green', 1),
            'TopLeftBlue': inputs.get('Blue', 1),
            'TopLeftAlpha': inputs.get('Alpha', 1),
        }
    # Native masks expose Mask, not the image/shape Output port.
    for tool in result.comp.tools:
        for value in tool.inputs.values():
            if isinstance(value, Link):
                source = tools.get(value.source_op)
                if source and source.tool_id in ('RectangleMask', 'EllipseMask', 'PolygonMask', 'BitmapMask'):
                    value.source = 'Mask'
    return result
