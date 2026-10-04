import pytest
from ffbridge.organize import positions, organize_result
from ffbridge.builder import build_graph
from fixtures import base_doc, node, solid


def test_parallel_sources_never_overlap_and_edges_flow_right():
    records = {'a': ('layer', []), 'b': ('layer', []),
               'merge': ('layer', ['a', 'b']), 'out': ('output', ['merge'])}
    p = positions(records)
    assert len(set(p.values())) == len(records)
    for name, (_, parents) in records.items():
        for parent in parents:
            assert p[parent][0] < p[name][0]
    assert positions(records) == p


def test_cycle_is_rejected_without_partial_layout():
    with pytest.raises(ValueError):
        positions({'a': ('x', ['b']), 'b': ('x', ['a'])})


def test_layout_keeps_graph_inputs_and_identity_and_is_idempotent():
    r = build_graph(base_doc([node('1', 'RECTANGLE', 0, 0, 100, 100,
                                  fills=[solid(.5, .2, .1)])]))
    before = [(t.name, dict(t.inputs), dict(t.data)) for t in r.comp.tools]
    organize_result(r)
    assert before == [(t.name, t.inputs, t.data) for t in r.comp.tools]
    first = [(t.pos, t.comments) for t in r.comp.tools]
    organize_result(r)
    assert first == [(t.pos, t.comments) for t in r.comp.tools]
