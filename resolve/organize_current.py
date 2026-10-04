"""Reposition the bridge-only MediaOut1 graph; never modify image inputs.

Run with Resolve's scripting Modules and this resolve folder on PYTHONPATH.
Refuse mixed graphs rather than rearranging unrelated user work.
"""
import builtins
import collections
import os
import sys

builtins.OrderedDict = collections.OrderedDict
import DaVinciResolveScript as d
from ffbridge.organize import positions


def main():
    c = d.scriptapp('Resolve').Fusion().GetCurrentComp()
    tools = {t.GetAttrs()['TOOLS_Name']: t for t in c.GetToolList(False).values()}
    records = collections.OrderedDict()
    for name, tool in tools.items():
        identity = tool.GetData('FFBridge') or {}
        if not isinstance(identity, dict):
            identity = {}
        owner = identity.get('nodeId')
        if not owner:
            if name in ('Root_Merge', 'BG_Merge'):
                owner = '__assembly__'
            elif name == 'MediaOut1' or name.startswith('FFBridge_sRGB_to_'):
                owner = '__output__'
            else:
                raise RuntimeError('Unowned node; refusing automatic layout: ' + name)
        parents = []
        for inp in tool.GetInputList().values():
            output = inp.GetConnectedOutput()
            if output is not None:
                parents.append(output.GetTool().GetAttrs()['TOOLS_Name'])
        records[name] = (owner, parents)
    layout = positions(records)
    flow = c.CurrentFrame.FlowView
    previous = {name: flow.GetPosTable(tool) for name, tool in tools.items()}
    c.StartUndo('Figma Bridge: organize layer lanes')
    try:
        for name, (x, y) in layout.items():
            # .setting uses pixel positions; FlowView uses 110x33 grid units.
            flow.SetPos(tools[name], x / 110.0, y / 33.0)
        for name, (x, y) in layout.items():
            actual = flow.GetPosTable(tools[name])
            assert abs(actual[1] - x / 110.0) < .02
            assert abs(actual[2] - y / 33.0) < .02
    except Exception:
        for name, p in previous.items():
            flow.SetPos(tools[name], p[1], p[2])
        raise
    finally:
        c.EndUndo(True)
    print('Verified positions for', len(layout), 'nodes. Connections and parameters unchanged.')


if __name__ == '__main__':
    main()
    sys.stdout.flush()
    # Resolve 21 binding can crash during Python proxy teardown.
    os._exit(0)
