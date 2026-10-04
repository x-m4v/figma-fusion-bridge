"""Explicit sRGB graphics boundary for supported Fusion working spaces.

DWG primaries: Blackmagic Wide Gamut Intermediate specification, August 2021.
GamutConvert inputs verified against Resolve Studio 21.0.3 SaveSettings.
This does not invert the project's output DRT, grades or display transform.
"""
from .ascii_writer import Tool, Link, FuID, Vec

PRIMARIES = {
    'DWG_LINEAR': ((.8, .313), (.1682, .9877), (.079, -.1155), (.3127, .329)),
    'SRGB_LINEAR': ((.64, .33), (.3, .6), (.15, .06), (.3127, .329)),
}


def add_color_boundary(result, target):
    if target == 'UNMANAGED':
        result.diagnostics.warn('UNMANAGED_COLOR',
            'sRGB values retained. Unmanaged output gamma and display matching require manual verification.')
        return
    if target not in PRIMARIES:
        result.diagnostics.error('COLOR_CONTEXT_UNKNOWN',
            'The Fusion working color space could not be verified. Receive needs a supported color-management context.')
        return
    if not result.output_tool:
        return
    name = 'FFBridge_sRGB_to_' + target
    suffix = 1
    while name in result.comp:
        suffix += 1
        name = 'FFBridge_sRGB_to_' + target + '_' + str(suffix)
    red, green, blue, white = PRIMARIES[target]
    source = result.comp.get(result.output_tool)
    tool = Tool('GamutConvert', name, {
        'Input': Link(result.output_tool), 'SourceSpace': FuID('sRGB'),
        'RemoveGamma': 1, 'OutputSpace': FuID('Custom'), 'AddGamma': 0,
        'CustomOutputRed': Vec(*red), 'CustomOutputGreen': Vec(*green),
        'CustomOutputBlue': Vec(*blue), 'CustomOutputWhite': Vec(*white),
        'WhiteAdaptation': 1, 'PreDividePostMultiply': 1,
    }, pos=(source.pos[0] + 220, source.pos[1]),
        comments='sRGB graphics to Fusion linear working space. Alpha is preserved. '
                 'Project output transform and Viewer remain active.')
    result.comp.add(tool)
    result.output_tool = name
    result.comp.active_tool = name
    result.diagnostics.warn('OUTPUT_COLOR_REVIEW',
        'sRGB graphics converted to ' + target + '. Output tone mapping, grades and Viewer can still change appearance.')
