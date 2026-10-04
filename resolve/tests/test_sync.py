"""Re-sync planning.

The contract: identity comes from the design tool's stable id and nothing else,
and a layer that already exists is updated rather than duplicated.
"""

from ffbridge.identity import (
    DELETED_KEEP, TransferManifest, plan_sync,
)


def manifest_with(ids, anim=True):
    m = TransferManifest("t1", "doc", "1.0.0", "now", 1920, 1080)
    for i in ids:
        m.record(i, "Shape", f"{i}_Shape")
        if anim:
            m.record(i, "Anim", f"{i}_Anim")
    return m


def test_first_transfer_creates_everything():
    plan = plan_sync(None, ["a", "b", "c"])
    assert plan.created == ["a", "b", "c"]
    assert not plan.updated and not plan.removed


def test_resend_updates_rather_than_duplicating():
    """The headline requirement: sending the same frame twice must not produce
    two copies of every layer."""
    plan = plan_sync(manifest_with(["a", "b"]), ["a", "b"])
    assert plan.updated == ["a", "b"]
    assert not plan.created


def test_new_layers_are_created_and_existing_ones_updated():
    plan = plan_sync(manifest_with(["a", "b"]), ["a", "b", "c"])
    assert plan.updated == ["a", "b"]
    assert plan.created == ["c"]


def test_deleted_layers_are_listed_not_acted_on_automatically():
    plan = plan_sync(manifest_with(["a", "b", "c"]), ["a", "c"])
    assert plan.removed == ["b"]


def test_layers_with_animation_are_flagged_for_preservation():
    plan = plan_sync(manifest_with(["a", "b"]), ["a", "b"])
    assert set(plan.preserved_animation) == {"a", "b"}


def test_layers_without_an_animation_slot_are_not_flagged():
    plan = plan_sync(manifest_with(["a"], anim=False), ["a"])
    assert plan.preserved_animation == []


def test_identity_survives_a_rename():
    """Renaming a layer in the design tool must not orphan its Fusion nodes."""
    previous = manifest_with(["node-42"])
    plan = plan_sync(previous, ["node-42"])
    assert plan.updated == ["node-42"] and not plan.created


def test_reordering_does_not_look_like_deletion():
    plan = plan_sync(manifest_with(["a", "b", "c"]), ["c", "a", "b"])
    assert not plan.removed and not plan.created
    assert sorted(plan.updated) == ["a", "b", "c"]


def test_duplicate_incoming_ids_are_collapsed():
    plan = plan_sync(None, ["a", "a", "b"])
    assert plan.created == ["a", "b"]


def test_manifest_round_trips_through_json():
    m = manifest_with(["a", "b"])
    m.assets["asset1"] = "/tmp/x.png"
    restored = TransferManifest.from_dict(m.to_dict())
    assert restored.nodes == m.nodes
    assert restored.assets == m.assets
    assert restored.comp_width == 1920


def test_empty_plan_is_detectable():
    assert plan_sync(manifest_with([]), []).is_empty
