# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Generic resource/library registry for extensions."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


class ResourceError(RuntimeError):
    pass


class UnsupportedCapability(ResourceError):
    pass


class ResourceDependencyError(ResourceError):
    pass


def _text(value, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    value = value.strip()
    if not value:
        raise ValueError(f"{field} cannot be empty")
    return value


@dataclass(frozen=True, slots=True)
class LibraryInfo:
    id: str
    name: str
    description: str = ""
    scope: str = "user"
    enabled: bool = True
    version: str | None = None

    @classmethod
    def from_value(cls, value):
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("libraries must be LibraryInfo or mappings")
        return cls(
            id=_text(str(value["id"]), "library id"),
            name=_text(str(value["name"]), "library name"),
            description=str(value.get("description", "") or ""),
            scope=str(value.get("scope", "user") or "user"),
            enabled=bool(value.get("enabled", True)),
            version=None if value.get("version") is None else str(value["version"]),
        )


@dataclass(frozen=True, slots=True)
class ResourceInfo:
    id: str
    name: str
    description: str = ""
    version: str | None = None
    tags: tuple[str, ...] = ()
    library_id: str | None = None

    @classmethod
    def from_value(cls, value):
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("list_resources() items must be ResourceInfo or mappings")
        raw_tags = value.get("tags", ()) or ()
        if isinstance(raw_tags, str):
            raw_tags = (raw_tags,)
        return cls(
            id=_text(str(value["id"]), "resource id"),
            name=_text(str(value["name"]), "resource name"),
            description=str(value.get("description", "") or ""),
            version=None if value.get("version") is None else str(value["version"]),
            tags=tuple(str(tag) for tag in raw_tags),
            library_id=None if value.get("library_id") is None
            else str(value["library_id"]),
        )


@dataclass(frozen=True, slots=True)
class ResourceRef:
    type_key: str
    resource_id: str
    version: str | None = None

    @classmethod
    def from_value(cls, value):
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("resource references must be ResourceRef or mappings")
        type_key = value.get("type_key", value.get("type"))
        resource_id = value.get("resource_id", value.get("id"))
        if type_key is None or resource_id is None:
            raise ValueError("resource reference requires type_key and resource_id")
        return cls(
            _text(str(type_key), "type_key"),
            _text(str(resource_id), "resource_id"),
            None if value.get("version") is None else str(value["version"]),
        )


@dataclass(frozen=True, slots=True)
class ResourceDependency:
    ref: ResourceRef
    optional: bool = False

    @classmethod
    def from_value(cls, value):
        if isinstance(value, cls):
            return value
        if isinstance(value, ResourceRef):
            return cls(value)
        if not isinstance(value, Mapping):
            raise TypeError("invalid resource dependency")
        return cls(
            ResourceRef.from_value(value.get("ref", value)),
            bool(value.get("optional", False)),
        )


@dataclass(frozen=True, slots=True)
class ResourceHit:
    type_key: str
    type_label: str
    info: ResourceInfo


@dataclass(frozen=True, slots=True)
class ResourceType:
    key: str
    owner: str
    name: str
    label: str
    provider: Any

    def list_resources(self):
        return tuple(ResourceInfo.from_value(x)
                     for x in self.provider.list_resources())

    def get_resource(self, resource_id: str):
        return self.provider.get_resource(resource_id)

    def libraries(self):
        fn = getattr(self.provider, "list_libraries", None)
        if not callable(fn):
            return (LibraryInfo("default", self.label, scope="extension"),)
        return tuple(LibraryInfo.from_value(x) for x in fn())

    def dependencies(self, resource_id: str):
        fn = getattr(self.provider, "get_dependencies", None)
        if not callable(fn):
            return ()
        return tuple(ResourceDependency.from_value(x)
                     for x in fn(resource_id))

    def supports(self, capability: str) -> bool:
        return callable(getattr(self.provider, capability, None))

    def export_resource(self, resource_id: str):
        fn = getattr(self.provider, "export_resource", None)
        if not callable(fn):
            raise UnsupportedCapability(
                f"{self.key} does not support export_resource")
        return fn(resource_id)

    def import_resource(self, payload):
        fn = getattr(self.provider, "import_resource", None)
        if not callable(fn):
            raise UnsupportedCapability(
                f"{self.key} does not support import_resource")
        return fn(payload)


class ResourceRegistry:
    _REQUIRED_PROVIDER_METHODS = ("list_resources", "get_resource")

    def __init__(self):
        self._types: dict[str, ResourceType] = {}

    @staticmethod
    def _clean_part(value: str, field: str) -> str:
        value = _text(value, field)
        if ":" in value:
            raise ValueError(f"{field} cannot contain ':'")
        return value

    @classmethod
    def _validate_provider(cls, provider):
        missing = [
            m for m in cls._REQUIRED_PROVIDER_METHODS
            if not callable(getattr(provider, m, None))
        ]
        if missing:
            raise TypeError(
                "provider is missing required method(s): " + ", ".join(missing))

    def register(self, owner: str, name: str, provider, *, label=None):
        owner = self._clean_part(owner, "owner")
        name = self._clean_part(name, "name")
        self._validate_provider(provider)
        key = f"{owner}:{name}"
        if key in self._types:
            raise ValueError(f"resource type already registered: {key}")
        label = name if label is None else str(label).strip() or name
        item = ResourceType(key, owner, name, label, provider)
        self._types[key] = item
        return item

    def get(self, key: str):
        return self._types.get(key)

    def require(self, key: str):
        item = self.get(key)
        if item is None:
            raise KeyError(f"resource type is not registered: {key}")
        return item

    def all(self):
        return tuple(self._types.values())

    def for_owner(self, owner: str):
        owner = self._clean_part(owner, "owner")
        return tuple(x for x in self._types.values() if x.owner == owner)

    def resolve(self, ref):
        ref = ResourceRef.from_value(ref)
        return self.require(ref.type_key).get_resource(ref.resource_id)

    def dependency_closure(self, ref):
        root = ResourceRef.from_value(ref)
        ordered = []
        visited = set()
        visiting = set()

        def visit(current, optional=False):
            ident = (current.type_key, current.resource_id)
            if ident in visited:
                return
            if ident in visiting:
                raise ResourceDependencyError(
                    f"cyclic resource dependency at "
                    f"{current.type_key}:{current.resource_id}")
            resource_type = self.get(current.type_key)
            if resource_type is None:
                if optional:
                    return
                raise ResourceDependencyError(
                    f"missing required resource type: {current.type_key}")
            visiting.add(ident)
            for dep in resource_type.dependencies(current.resource_id):
                visit(dep.ref, dep.optional)
            visiting.remove(ident)
            visited.add(ident)
            if ident != (root.type_key, root.resource_id):
                ordered.append(current)

        visit(root)
        return tuple(ordered)

    def search(self, text="", *, owner=None, type_key=None,
               library_id=None, tags=()):
        needle = text.strip().casefold()
        wanted_tags = {str(tag).casefold() for tag in tags}
        hits = []
        for resource_type in self._types.values():
            if owner is not None and resource_type.owner != owner:
                continue
            if type_key is not None and resource_type.key != type_key:
                continue
            for info in resource_type.list_resources():
                if library_id is not None and info.library_id != library_id:
                    continue
                item_tags = {tag.casefold() for tag in info.tags}
                if wanted_tags and not wanted_tags.issubset(item_tags):
                    continue
                haystack = " ".join(
                    (info.name, info.description, " ".join(info.tags))
                ).casefold()
                if needle and needle not in haystack:
                    continue
                hits.append(ResourceHit(
                    resource_type.key, resource_type.label, info))
        return tuple(hits)

    def unregister(self, key: str):
        return self._types.pop(key, None) is not None

    def unregister_owner(self, owner: str):
        owner = self._clean_part(owner, "owner")
        keys = [k for k, x in self._types.items() if x.owner == owner]
        for key in keys:
            del self._types[key]
        return len(keys)

    def __len__(self):
        return len(self._types)
