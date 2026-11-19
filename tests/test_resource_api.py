# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import pytest
from core.resource_library import (
    LibraryInfo,
    ResourceDependencyError,
    ResourceInfo,
    ResourceRef,
    ResourceRegistry,
    UnsupportedCapability,
)
from views.extension_api import API_VERSION, ExtensionApp


class FakeProvider:
    def __init__(self, deps=None):
        self.payloads = {
            "a": {"id": "a", "name": "Alpha", "value": 10},
            "b": {"id": "b", "name": "Beta", "value": 20},
        }
        self.deps = deps or {}

    def list_resources(self):
        return [
            ResourceInfo("a", "Alpha", tags=("demo",), library_id="user"),
            {"id": "b", "name": "Beta", "version": "2",
             "tags": ["demo", "beta"], "library_id": "project"},
        ]

    def get_resource(self, resource_id):
        return dict(self.payloads[resource_id])

    def get_dependencies(self, resource_id):
        return self.deps.get(resource_id, ())


class FakeWindow:
    def __init__(self):
        self.resource_registry = ResourceRegistry()


def test_api_version_is_4_or_newer():
    assert API_VERSION >= 4
    assert ExtensionApp.api_version >= 4


def test_namespaces_and_duplicate_rejection():
    r = ResourceRegistry()
    a = r.register("first", "preset", FakeProvider())
    b = r.register("second", "preset", FakeProvider())
    assert a.key == "first:preset"
    assert b.key == "second:preset"
    with pytest.raises(ValueError):
        r.register("first", "preset", FakeProvider())


def test_provider_contract_is_checked():
    class Incomplete:
        def list_resources(self):
            return []
    with pytest.raises(TypeError, match="get_resource"):
        ResourceRegistry().register("demo", "broken", Incomplete())


def test_metadata_and_payload_are_separate():
    t = ResourceRegistry().register("demo", "preset", FakeProvider())
    items = t.list_resources()
    assert items[0].name == "Alpha"
    assert items[1].version == "2"
    assert t.get_resource("a")["value"] == 10


def test_libraries_have_default_and_custom_forms():
    r = ResourceRegistry()
    t = r.register("demo", "preset", FakeProvider())
    assert t.libraries() == (
        LibraryInfo("default", "preset", scope="extension"),
    )

    class WithLibraries(FakeProvider):
        def list_libraries(self):
            return [{"id": "office", "name": "Office", "scope": "user"}]

    t2 = r.register("demo", "other", WithLibraries())
    assert t2.libraries()[0].id == "office"


def test_import_export_are_optional_capabilities():
    t = ResourceRegistry().register("demo", "preset", FakeProvider())
    with pytest.raises(UnsupportedCapability):
        t.export_resource("a")

    class Exporting(FakeProvider):
        def export_resource(self, resource_id):
            return b"payload"
        def import_resource(self, payload):
            return ResourceInfo("c", "Gamma")

    t2 = ResourceRegistry().register("demo", "preset", Exporting())
    assert t2.export_resource("a") == b"payload"
    assert t2.import_resource(b"x").name == "Gamma"


def test_dependency_closure_orders_dependencies_first():
    r = ResourceRegistry()
    r.register("demo", "material", FakeProvider())
    r.register("demo", "profile", FakeProvider({
        "a": [ResourceRef("demo:material", "a")]
    }))
    r.register("demo", "wall", FakeProvider({
        "a": [ResourceRef("demo:profile", "a")]
    }))
    assert r.dependency_closure(ResourceRef("demo:wall", "a")) == (
        ResourceRef("demo:material", "a"),
        ResourceRef("demo:profile", "a"),
    )


def test_missing_and_cyclic_dependencies_are_safe():
    r = ResourceRegistry()
    r.register("demo", "wall", FakeProvider({
        "a": [ResourceRef("missing:type", "x")]
    }))
    with pytest.raises(ResourceDependencyError, match="missing required"):
        r.dependency_closure(ResourceRef("demo:wall", "a"))

    r = ResourceRegistry()
    r.register("demo", "preset", FakeProvider({
        "a": [ResourceRef("demo:preset", "b")],
        "b": [ResourceRef("demo:preset", "a")],
    }))
    with pytest.raises(ResourceDependencyError, match="cyclic"):
        r.dependency_closure(ResourceRef("demo:preset", "a"))


def test_optional_missing_dependency_is_skipped():
    r = ResourceRegistry()
    r.register("demo", "wall", FakeProvider({
        "a": [{
            "type_key": "missing:type",
            "resource_id": "x",
            "optional": True,
        }]
    }))
    assert r.dependency_closure(ResourceRef("demo:wall", "a")) == ()


def test_search_never_loads_payload():
    class NoPayload(FakeProvider):
        def get_resource(self, resource_id):
            raise AssertionError("payload loaded during search")
    r = ResourceRegistry()
    r.register("demo", "preset", NoPayload(), label="Presets")
    hits = r.search("beta", tags=("demo",), library_id="project")
    assert len(hits) == 1
    assert hits[0].info.id == "b"


def test_extension_app_registers_with_its_namespace():
    app = ExtensionApp(FakeWindow(), "parametric_architecture")
    t = app.register_resource_type(
        "wall_preset", FakeProvider(), label="Wall presets")
    assert t.key == "parametric_architecture:wall_preset"
    assert app.resource_types() == (t,)
