"""Node identity and re-sync bookkeeping.

The rule that makes Live Sync safe: a Fusion node's link back to a design layer
is stored *in the node*, using Fusion's ``SetData``, and is never inferred from
the node's name, its position in the graph, or its order. All three of those are
things a motion designer legitimately changes, and a bridge that reads identity
from them will destroy work the first time someone renames a node.

Each design layer maps to a small, fixed set of Fusion nodes with distinct
roles. Only ``SOURCE`` roles are rebuilt on re-sync. The ``ANIM`` role is created
once and then belongs to the user:

    design layer
      ├─ *_Shape   SOURCE   geometry, rebuilt from the design every sync
      ├─ *_Stroke  SOURCE   rebuilt
      ├─ *_Shadow  SOURCE   rebuilt
      ├─ *_Anim    USER     created once, never touched again
      └─ *_Merge   SPINE    reconnected, its Blend/ApplyMode refreshed

That split is the whole animation-preservation strategy. Keyframes live on
``*_Anim``, and the sync never writes to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

#: Key under which the bridge stores its data on a Fusion node.
DATA_NAMESPACE = "FFBridge"

ROLE_SOURCE = "SOURCE"
ROLE_USER = "USER"
ROLE_SPINE = "SPINE"
ROLE_CONTAINER = "CONTAINER"

#: Roles a re-sync is allowed to delete and rebuild.
REBUILDABLE_ROLES = frozenset({ROLE_SOURCE, ROLE_SPINE, ROLE_CONTAINER})


@dataclass
class NodeIdentity:
    """What gets written into a Fusion node's persistent data."""

    source: str                 # "figma"
    document_id: str
    node_id: str                # the design tool's stable layer id
    transfer_id: str
    schema_version: str
    role: str
    #: Which part of the layer this node represents, e.g. "Shape", "Stroke".
    part: str = ""
    node_name: str = ""

    def to_data(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "documentId": self.document_id,
            "nodeId": self.node_id,
            "transferId": self.transfer_id,
            "schemaVersion": self.schema_version,
            "role": self.role,
            "part": self.part,
            "layerName": self.node_name,
        }

    @property
    def is_rebuildable(self) -> bool:
        return self.role in REBUILDABLE_ROLES


@dataclass
class TransferManifest:
    """The index written alongside a transfer.

    Redundant with the per-node data on purpose. Per-node data is authoritative
    because it cannot drift from the node it describes; the manifest exists so
    the bridge can answer "what did this transfer create?" without opening
    Resolve, which is what makes the history list and diagnostics reports work
    when Resolve is closed.
    """

    transfer_id: str
    document_id: str
    schema_version: str
    created_at: str
    comp_width: int
    comp_height: int
    #: design node id -> {part -> fusion tool name}
    nodes: Dict[str, Dict[str, str]] = field(default_factory=dict)
    #: design asset id -> absolute cache path
    assets: Dict[str, str] = field(default_factory=dict)
    diagnostics: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, node_id: str, part: str, tool_name: str) -> None:
        self.nodes.setdefault(node_id, {})[part] = tool_name

    def tool_for(self, node_id: str, part: str) -> Optional[str]:
        return self.nodes.get(node_id, {}).get(part)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transferId": self.transfer_id,
            "documentId": self.document_id,
            "schemaVersion": self.schema_version,
            "createdAt": self.created_at,
            "comp": {"width": self.comp_width, "height": self.comp_height},
            "nodes": self.nodes,
            "assets": self.assets,
            "diagnostics": self.diagnostics,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "TransferManifest":
        comp = d.get("comp", {}) or {}
        m = cls(
            transfer_id=d.get("transferId", ""),
            document_id=d.get("documentId", ""),
            schema_version=d.get("schemaVersion", ""),
            created_at=d.get("createdAt", ""),
            comp_width=int(comp.get("width", 1920)),
            comp_height=int(comp.get("height", 1080)),
        )
        m.nodes = dict(d.get("nodes", {}) or {})
        m.assets = dict(d.get("assets", {}) or {})
        m.diagnostics = list(d.get("diagnostics", []) or [])
        return m


#: What to do with a Fusion node whose design layer no longer exists.
DELETED_KEEP = "KEEP"
DELETED_DISABLE = "DISABLE"
DELETED_REMOVE = "REMOVE"


@dataclass
class SyncPlan:
    """The diff between a previous transfer and a new one."""

    created: List[str] = field(default_factory=list)
    updated: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    #: Nodes that exist in both but whose user Transform must be preserved.
    preserved_animation: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.created or self.updated or self.removed)


def plan_sync(previous: Optional[TransferManifest], incoming_node_ids: List[str]) -> SyncPlan:
    """Diff a previous transfer against the incoming one, by stable id only."""
    plan = SyncPlan()
    incoming = list(dict.fromkeys(incoming_node_ids))  # de-dup, keep order

    if previous is None:
        plan.created = incoming
        return plan

    known = set(previous.nodes.keys())
    for nid in incoming:
        if nid in known:
            plan.updated.append(nid)
            if previous.tool_for(nid, "Anim"):
                plan.preserved_animation.append(nid)
        else:
            plan.created.append(nid)

    incoming_set = set(incoming)
    plan.removed = [nid for nid in previous.nodes if nid not in incoming_set]
    return plan
