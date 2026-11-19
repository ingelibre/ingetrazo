# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Portable bundles for extension-owned resources."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from core.resource_library import (
    ResourceDependency,
    ResourceRef,
    ResourceRegistry,
    UnsupportedCapability,
)

FORMAT_ID = "ingetrazo-resource-bundle"
FORMAT_VERSION = 1
MANIFEST_NAME = "manifest.json"


class ResourceBundleError(RuntimeError):
    pass


class ResourceConflictError(ResourceBundleError):
    pass


@dataclass(frozen=True, slots=True)
class BundleImportResult:
    imported: tuple[ResourceRef, ...]
    skipped: tuple[ResourceRef, ...]
    root: ResourceRef


def _payload_bytes(value) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError("export_resource() must return bytes, bytearray or str")


def _ref_dict(ref: ResourceRef) -> dict:
    out = {"type_key": ref.type_key, "resource_id": ref.resource_id}
    if ref.version is not None:
        out["version"] = ref.version
    return out


def _dep_dict(dep: ResourceDependency) -> dict:
    out = _ref_dict(dep.ref)
    if dep.optional:
        out["optional"] = True
    return out


def _current_info(registry: ResourceRegistry, ref: ResourceRef):
    resource_type = registry.get(ref.type_key)
    if resource_type is None:
        return None
    for info in resource_type.list_resources():
        if info.id == ref.resource_id:
            return info
    return None


def export_bundle(
    registry: ResourceRegistry,
    ref,
    path,
    *,
    include_dependencies: bool = True,
) -> Path:
    root = ResourceRef.from_value(ref)
    registry.require(root.type_key)

    ordered = list(registry.dependency_closure(root)) if include_dependencies else []
    ordered.append(root)

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    entries = []

    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for index, current in enumerate(ordered):
            resource_type = registry.require(current.type_key)
            if not resource_type.supports("export_resource"):
                raise UnsupportedCapability(
                    f"{current.type_key} does not support export_resource"
                )

            info = _current_info(registry, current)
            version = current.version
            if version is None and info is not None:
                version = info.version
            normalized = ResourceRef(
                current.type_key,
                current.resource_id,
                version,
            )

            payload_path = f"resources/{index:04d}.bin"
            payload = _payload_bytes(
                resource_type.export_resource(current.resource_id)
            )
            archive.writestr(payload_path, payload)

            entries.append({
                "ref": _ref_dict(normalized),
                "payload": payload_path,
                "dependencies": [
                    _dep_dict(dep)
                    for dep in resource_type.dependencies(current.resource_id)
                ],
            })

        manifest = {
            "format": FORMAT_ID,
            "format_version": FORMAT_VERSION,
            "root": _ref_dict(root),
            "entries": entries,
        }
        archive.writestr(
            MANIFEST_NAME,
            json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8"),
        )

    return destination


def read_manifest(path) -> dict:
    try:
        with ZipFile(Path(path), "r") as archive:
            try:
                raw = archive.read(MANIFEST_NAME)
            except KeyError as exc:
                raise ResourceBundleError("bundle has no manifest.json") from exc
    except BadZipFile as exc:
        raise ResourceBundleError("not a valid resource bundle") from exc

    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResourceBundleError("invalid bundle manifest") from exc

    if manifest.get("format") != FORMAT_ID:
        raise ResourceBundleError("unsupported bundle format")
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ResourceBundleError(
            f"unsupported bundle version: {manifest.get('format_version')}"
        )
    if not isinstance(manifest.get("entries"), list):
        raise ResourceBundleError("bundle manifest has no entries")

    ResourceRef.from_value(manifest.get("root", {}))
    return manifest


def import_bundle(
    registry: ResourceRegistry,
    path,
    *,
    conflict: str = "error",
) -> BundleImportResult:
    if conflict not in {"error", "skip", "replace"}:
        raise ValueError("conflict must be 'error', 'skip' or 'replace'")

    manifest = read_manifest(path)
    root = ResourceRef.from_value(manifest["root"])
    imported = []
    skipped = []

    try:
        archive = ZipFile(Path(path), "r")
    except BadZipFile as exc:
        raise ResourceBundleError("not a valid resource bundle") from exc

    with archive:
        for raw_entry in manifest["entries"]:
            if not isinstance(raw_entry, dict):
                raise ResourceBundleError("invalid bundle entry")

            ref = ResourceRef.from_value(raw_entry.get("ref", {}))
            resource_type = registry.get(ref.type_key)
            if resource_type is None:
                raise ResourceBundleError(
                    f"required resource type is not registered: {ref.type_key}"
                )
            if not resource_type.supports("import_resource"):
                raise UnsupportedCapability(
                    f"{ref.type_key} does not support import_resource"
                )

            existing = _current_info(registry, ref)
            if existing is not None:
                same_version = (
                    ref.version is not None
                    and existing.version == ref.version
                )
                if same_version or conflict == "skip":
                    skipped.append(ref)
                    continue
                if conflict == "error":
                    raise ResourceConflictError(
                        f"resource already exists with another version: "
                        f"{ref.type_key}:{ref.resource_id} "
                        f"(local={existing.version!r}, bundle={ref.version!r})"
                    )

            payload_path = raw_entry.get("payload")
            if not isinstance(payload_path, str) or not payload_path:
                raise ResourceBundleError("bundle entry has no payload")
            try:
                payload = archive.read(payload_path)
            except KeyError as exc:
                raise ResourceBundleError(
                    f"bundle payload is missing: {payload_path}"
                ) from exc

            resource_type.import_resource(payload)
            imported.append(ref)

    return BundleImportResult(
        imported=tuple(imported),
        skipped=tuple(skipped),
        root=root,
    )
