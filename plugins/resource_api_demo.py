# SPDX-License-Identifier: GPL-3.0-or-later
"""Resource API demo — temporary development plugin."""
from __future__ import annotations

import json
from core.resource_library import LibraryInfo, ResourceInfo, ResourceRef


class DemoProvider:
    def __init__(self, items, dependencies=None):
        self._items = {item["id"]: dict(item) for item in items}
        self._dependencies = dependencies or {}

    def list_libraries(self):
        return [
            LibraryInfo("office", "Office library", scope="user"),
            LibraryInfo("project", "Current project", scope="project"),
        ]

    def list_resources(self):
        return [
            ResourceInfo(
                id=item["id"],
                name=item["name"],
                version=item.get("version"),
                tags=tuple(item.get("tags", ())),
                library_id=item.get("library_id", "office"),
            )
            for item in self._items.values()
        ]

    def get_resource(self, resource_id):
        return dict(self._items[resource_id])

    def get_dependencies(self, resource_id):
        return list(self._dependencies.get(resource_id, ()))

    def export_resource(self, resource_id):
        return json.dumps(
            self._items[resource_id],
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")

    def import_resource(self, payload):
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        item = json.loads(payload)
        self._items[item["id"]] = item
        return ResourceInfo(
            item["id"], item["name"],
            version=item.get("version"),
            tags=tuple(item.get("tags", ())),
            library_id=item.get("library_id", "office"),
        )


def setup(app):
    materials = DemoProvider([{
        "id": "gypsum-board",
        "name": "Gypsum board",
        "version": "1",
        "tags": ("material", "drywall"),
        "library_id": "office",
    }])

    walls = DemoProvider([{
        "id": "drywall-100",
        "name": "Drywall 100 mm",
        "version": "1",
        "tags": ("wall", "drywall"),
        "library_id": "project",
        "thickness": 0.10,
    }], dependencies={
        "drywall-100": [
            ResourceRef("resource_api_demo:material", "gypsum-board", "1")
        ]
    })

    app.register_resource_type("material", materials, label="Materials")
    wall_type = app.register_resource_type(
        "wall_preset", walls, label="Wall presets")

    print(
        "[resource-api-demo]",
        wall_type.key,
        [x.name for x in wall_type.list_resources()],
        [x.name for x in wall_type.libraries()],
        wall_type.supports("export_resource"),
        flush=True,
    )
