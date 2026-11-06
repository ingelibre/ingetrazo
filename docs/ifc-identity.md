# Persistent IFC identity

Repeated IFC exports previously assigned a new random `GlobalId` to every
element, spatial container, quantity set and relationship. This made the
same wall appear to downstream revision tools as a different object.

## Behavior

- A document has an IFC UUID namespace, stored as `scene.ifc_namespace` in
  `.igz`. New documents get different namespaces; Save As retains identity.
- Tagged groups use their persistent placement `uid`. Copies and inserted
  documents get new placement IDs; moving, renaming, nesting or making a
  group unique preserves its ID.
- Face objects use their tag's new `uid`, scoped to the owning group when
  grouped. The existing integer `id` still determines which faces form one
  BIM object. Geometry rebuilds inherit the tag as before. A new tag gets
  a new token even when a deleted object's integer ID is reused.
- Editing the complete face object's name/class in the BIM panel preserves
  identity. Tagging a partial selection splits off a new object.
- UUID5 derives 22-character compressed IFC GUIDs from these identities.
  Spatial containers, quantity sets and relationships have their own
  stable semantic keys. Export changes neither tags nor document version.
- Duplicate element identities fail before writing the output file.

## Compatibility and boundaries

No dependency or `.igz` format-version change is required. Added keys are
ignored by older readers. A legacy file without a namespace gets one from
its SHA-256 digest, independent of its path; groups without a `uid` get
deterministic IDs on load. Saving with this version stores the namespace
explicitly. Reopening unchanged legacy bytes is stable, but independently
editing an unmigrated legacy file changes its digest. Older applications
can read the geometry but may drop the namespace when saving, so identity
continuity requires saving with a version that preserves this metadata.

Identity follows the current BIM object boundaries. Moving face tags into
another owning group, exploding a group into faces, deleting/recreating or
removing/reapplying a tag changes those boundaries and may create a new ID.
Loose-face copies still follow the existing shared integer-tag semantics:
copying geometry alone does not split it into a separate BIM object; tag
the copy separately, or copy a group/component. This change does not add
IFC import or map IDs from IFC exports made by older builds.

This is an IFC identity fix, not a claim of Türkiye regulatory compliance.
The exporter remains IFC4; IFC4.3, delivery properties, naming validation
and a multi-storey spatial hierarchy are separate work.

## Validation (2026-11-06)

Base: `e61132a7f8a098ca77fb6b0e7cac488c1bd410cb`.
Windows, Python 3.13.5, PySide6/Qt 6.11.3, IfcOpenShell 0.9.0.post1.

- **81 passed, 1 skipped**: IFC identity/export/independent validation,
  BIM tagging/active drawing/grouped tags/takeoff, insertion and component
  sharing. The skip requires a separate IngePresupuestos checkout.
- **94 passed**: IGZ formats 1/3, curves/textures/large documents,
  group copying/naming, new/open document state, clipboard and history.
- Nineteen new identity scenarios cover repeated exports, `.igz` round
  trips, binary geometry, independent copies, metadata edits, partial
  retagging, legacy migration, insertions, collisions and GUID encoding.
- A 4 × 0.25 × 2.6 m wall kept all **11 IfcRoot GlobalIds** across two
  exports and a save/reload/export. IfcOpenShell read the Turkish name and
  computed **2.6 m³**, matching the quantity set.
- All **16 supported element classes** exported with **0 schema findings**
  under IfcOpenShell validation. The full application suite was not run.

The test modules are `tests/test_ifc_identity.py`, the existing `test_ifc_*`
and `test_bim*` modules, `test_insert_document.py`,
`test_components_shared_on_insert.py`, `test_igz_*`, `test_groups.py`,
`test_group_names_on_load.py`, `test_group_vs_component.py`,
`test_redo_keeps_created_groups.py`, `test_scene_clear_materials.py`,
`test_open_replaces_document.py`, `test_new_document_units.py`,
`test_document_boundary_caches.py`, `test_document_caches_reset.py`,
`test_import_igz_path.py`, `test_clipboard_windows.py`, `test_undo_clean.py`
and `test_transactional_history.py`.
