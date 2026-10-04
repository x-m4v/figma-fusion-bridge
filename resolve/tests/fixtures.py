"""Fixture documents used across the test suite."""

from typing import Any, Dict


def rgba(r, g, b, a=1.0):
    return {"r": r, "g": g, "b": b, "a": a}


def solid(r, g, b, a=1.0, opacity=1.0):
    return {"type": "SOLID", "visible": True, "opacity": opacity, "blendMode": "NORMAL", "color": rgba(r, g, b, a)}


def base_doc(nodes, canvas=(0, 0, 1920, 1080)) -> Dict[str, Any]:
    x, y, w, h = canvas
    return {
        "schemaVersion": "1.0.0",
        "transferId": "t-test",
        "createdAt": "2026-09-08T00:00:00Z",
        "source": {"app": "figma", "producerVersion": "0.1.0", "documentId": "doc-1", "documentName": "Test"},
        "canvas": {"frame": {"x": x, "y": y, "width": w, "height": h}, "rootFrameId": None},
        "selection": [n["id"] for n in nodes if n.get("parentId") is None],
        "nodes": nodes,
        "assets": [],
        "fonts": [],
        "options": {},
        "diagnostics": [],
    }


def node(
    id, kind, x, y, w, h, *, parent=None, index=0, name=None, **kw
) -> Dict[str, Any]:
    n = {
        "id": id,
        "parentId": parent,
        "childIndex": index,
        "kind": kind,
        "name": name or id,
        "visible": True,
        "locked": False,
        "opacity": 1.0,
        "blendMode": "PASS_THROUGH",
        "bounds": {"x": x, "y": y, "width": w, "height": h},
        "absoluteTransform": [[1, 0, x], [0, 1, y]],
        "relativeTransform": [[1, 0, x], [0, 1, y]],
        "rotation": 0.0,
        "clipsContent": False,
        "isMask": False,
        "fills": [],
        "effects": [],
        "extra": {},
    }
    n.update(kw)
    return n
