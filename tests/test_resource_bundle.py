# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import pytest

from core.resource_bundle import (
    ResourceBundleError,
    ResourceConflictError,
    export_bundle,
    import_bundle,
    read_manifest,
)
from core.resource_library import ResourceInfo, ResourceRef, ResourceRegistry


class MemoryProvider:
    def __init__(self, items, deps=None):
        self.items = {item["id"]: dict(item) for item in items}
        self.deps = deps or {}

    def list_resources(self):
        return [
            ResourceInfo(item["id"], item["name"], version=item.get("version"))
            for item in self.items.values()
        ]

    def get_resource(self, resource_id):
        return dict(self.items[resource_id])

    def get_dependencies(self, resource_id):
        return self.deps.get(resource_id, ())

    def export_resource(self, resource_id):
        return json.dumps(
            self.items[resource_id],
            sort_keys=True,
        ).encode("utf-8")

    def import_resource(self, payload):
        item = json.loads(payload.decode("utf-8"))
        self.items[item["id"]] = item
        return ResourceInfo(
            item["id"],
            item["name"],
            version=item.get("version"),
        )


def _source_registry():
    r = ResourceRegistry()
    r.register("demo", "material", MemoryProvider([{
        "id": "mat-a", "name": "Material A", "version": "1"
    }]))
    r.register("demo", "profile", MemoryProvider([{
        "id": "profile-a", "name": "Profile A", "version": "2"
    }], {
        "profile-a": [ResourceRef("demo:material", "mat-a", "1")]
    }))
    r.register("demo", "wall", MemoryProvider([{
        "id": "wall-a", "name": "Wall A", "version": "3"
    }], {
        "wall-a": [ResourceRef("demo:profile", "profile-a", "2")]
    }))
    return r


def _empty_target_registry():
    r = ResourceRegistry()
    r.register("demo", "material", MemoryProvider([]))
    r.register("demo", "profile", MemoryProvider([]))
    r.register("demo", "wall", MemoryProvider([]))
    return r


def test_export_contains_root_and_dependencies(tmp_path):
    bundle = export_bundle(
        _source_registry(),
        ResourceRef("demo:wall", "wall-a", "3"),
        tmp_path / "wall.iglib",
    )
    manifest = read_manifest(bundle)
    assert [x["ref"]["type_key"] for x in manifest["entries"]] == [
        "demo:material",
        "demo:profile",
        "demo:wall",
    ]


def test_round_trip_import(tmp_path):
    bundle = export_bundle(
        _source_registry(),
        ResourceRef("demo:wall", "wall-a", "3"),
        tmp_path / "wall.iglib",
    )
    target = _empty_target_registry()
    result = import_bundle(target, bundle)

    assert result.imported == (
        ResourceRef("demo:material", "mat-a", "1"),
        ResourceRef("demo:profile", "profile-a", "2"),
        ResourceRef("demo:wall", "wall-a", "3"),
    )
    assert target.require("demo:wall").get_resource("wall-a")["version"] == "3"


def test_second_import_skips_same_versions(tmp_path):
    bundle = export_bundle(
        _source_registry(),
        ResourceRef("demo:wall", "wall-a", "3"),
        tmp_path / "wall.iglib",
    )
    target = _empty_target_registry()
    import_bundle(target, bundle)
    again = import_bundle(target, bundle)
    assert again.imported == ()
    assert len(again.skipped) == 3


def test_conflict_modes(tmp_path):
    bundle = export_bundle(
        _source_registry(),
        ResourceRef("demo:wall", "wall-a", "3"),
        tmp_path / "wall.iglib",
        include_dependencies=False,
    )

    def old_target():
        r = ResourceRegistry()
        r.register("demo", "wall", MemoryProvider([{
            "id": "wall-a", "name": "Old Wall", "version": "1"
        }]))
        return r

    with pytest.raises(ResourceConflictError):
        import_bundle(old_target(), bundle, conflict="error")

    skipped = import_bundle(old_target(), bundle, conflict="skip")
    assert skipped.imported == ()

    target = old_target()
    import_bundle(target, bundle, conflict="replace")
    assert target.require("demo:wall").get_resource("wall-a")["version"] == "3"


def test_missing_type_is_reported(tmp_path):
    bundle = export_bundle(
        _source_registry(),
        ResourceRef("demo:wall", "wall-a", "3"),
        tmp_path / "wall.iglib",
    )
    target = ResourceRegistry()
    target.register("demo", "wall", MemoryProvider([]))
    with pytest.raises(ResourceBundleError, match="not registered"):
        import_bundle(target, bundle)


def test_invalid_file_is_rejected(tmp_path):
    path = tmp_path / "bad.iglib"
    path.write_text("not a zip", encoding="utf-8")
    with pytest.raises(ResourceBundleError):
        read_manifest(path)
