"""Presentation-only layout: layer lanes and dependency-ordered columns.

No renaming, rewiring, parameter changes or collapsing animation controls.
"""
from collections import OrderedDict, deque
from .ascii_writer import Link


def positions(records):
    """records: name -> (stable layer owner, upstream names). Reject cycles."""
    ranks = dict.fromkeys(records, 0)
    pending = {}
    consumers = {name: [] for name in records}
    for name, (_, upstream) in records.items():
        parents = set(upstream) & records.keys()
        pending[name] = len(parents)
        for parent in parents:
            consumers[parent].append(name)
    queue = deque(name for name in records if not pending[name])
    visited = 0
    while queue:
        name = queue.popleft()
        visited += 1
        for child in consumers[name]:
            ranks[child] = max(ranks[child], ranks[name] + 1)
            pending[child] -= 1
            if not pending[child]:
                queue.append(child)
    if visited != len(records):
        raise ValueError('Cannot organize a cyclic graph')
    lanes = OrderedDict()
    for name, (owner, _) in records.items():
        lanes.setdefault(owner, []).append(name)
    result = {}
    y = 0
    for names in lanes.values():
        occupied = {}
        for name in names:
            rank = ranks[name]
            slot = occupied.get(rank, 0)
            occupied[rank] = slot + 1
            result[name] = (rank * 160.0, y + slot * 100.0)
        y += max(occupied.values()) * 100.0 + 100.0
    return result


def organize_result(result):
    records = OrderedDict()
    for tool in result.comp.tools:
        owner = tool.data.get('nodeId') or '__assembly__'
        if tool.tool_id == 'GamutConvert':
            owner = '__output__'
        records[tool.name] = (owner, [v.source_op for v in tool.inputs.values()
                                    if isinstance(v, Link)])
    layout = positions(records)
    for tool in result.comp.tools:
        tool.pos = layout[tool.name]
        label = tool.data.get('layerName') or 'Assembly / Output'
        note = 'Figma layer: ' + label + ' | ' + tool.data.get('part', tool.tool_id)
        if note not in tool.comments:
            tool.comments = (tool.comments + '\n' + note).strip()
