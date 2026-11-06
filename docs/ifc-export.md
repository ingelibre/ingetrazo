# IFC4 and IFC4.3 ADD2 export

File > Export > IFC offers **IFC4** (the unchanged default) and
**IFC4.3 ADD2** in the save dialog's file-type list. Both write `.ifc`
STEP files. The existing translated IFC4/All files filters are retained;
the new technical schema label is the same in every language.

The Python API remains backward compatible:

```python
from formats.ifc import save_ifc

save_ifc(scene, "model.ifc")                       # IFC4, as before
save_ifc(scene, "model-43.ifc", schema="IFC4X3_ADD2")
```

Only `IFC4` and `IFC4X3_ADD2` are accepted. The latter is the canonical
schema identifier for IFC4.3 ADD2 / IFC 4.3.2.0. Unsupported identifiers
raise `ValueError` before writing the file. IfcOpenShell is a development
validator, not a runtime dependency of the writer.

## Preserved data and corrected spatial relationship

The existing 16 curated BIM classes have compatible serialized attribute
layouts in these two schemas. The geometry, SI units, canonical class
names, quantity sets, door/window dimensions and reinforcing-bar values
are preserved. Switching schema does not replace a model's GlobalIds;
the [persistent identity rules](ifc-identity.md) apply to both formats.

Strict EXPRESS validation exposed an existing relationship error for
`IfcSpace`: spatial structure cannot be placed in `RelatedElements` of
`IfcRelContainedInSpatialStructure` (WR31). Spaces now decompose the
storey through `IfcRelAggregates`; ordinary elements retain their storey
containment. This correction applies to **both** schema choices. The
new spatial relationship has its own stable GlobalId; an existing space
keeps its element GlobalId. A spaces-only export also works.

## Scope

This adds an export schema choice for the existing supported object
types. It does not add IFC import, infrastructure modelling, new tagging
classes, an MVD/certification claim, multiple editable storeys, delivery
property sets or Türkiye naming-rule enforcement. Unknown tag classes
continue to export as `IfcBuildingElementProxy`, as before.

IFC4.3 output alone does not establish regulatory compliance. Export
requirements, naming, property sets and delivery validation need their
own checks. Compatibility with specific external BIM applications must
also be tested separately.

## Validation (2026-11-06)

Windows, Python 3.13.5, PySide6/Qt 6.11.3, IfcOpenShell 0.9.0.post1.
Implementation base: `b15899a` (the persistent identity contribution).

- **139 passed, 1 skipped** in focused IFC/BIM/insertion/file-dialog tests,
  including **52 new scenarios** in `tests/test_ifc43_export.py`. The skip
  requires the separate IngePresupuestos checkout.
- All 16 supported classes in both schemas: independent type/schema and
  **EXPRESS rule validation with zero findings**, plus real-kernel geometry
  tessellation. Each synthetic box retained its 2.6 m³ geometric volume.
- Door/window field positions and the existing realistic reinforcing-bar
  fixture were checked in both schemas. Quantity sets, SI units, open
  surfaces, Turkish names, unsupported schemas, spatial aggregation and
  save-dialog selection/cancellation were also checked.
- A 4 × 0.25 × 2.6 m wall retained all **11 IfcRoot GlobalIds** when switching
  between IFC4 and IFC4.3 ADD2, including after `.igz` save/reopen. Independent
  volume remained **2.6 m³**.
- **38 passed** in a temporary merge with the Turkish contribution
  (`5eea8af`): identity/workspace tests, export-dialog tests and two additional
  tests with the Turkish catalog active. Merge was conflict-free; the
  3,312-key Turkish catalog validator reported no errors. These checks
  overlap the focused suite and are not 38 additional unique cases.

The full application suite, Linux CI and external desktop BIM viewers were
not verified in this step. Schema/rule validation is not an MVD or delivery
requirements certification.

## Reference

- [buildingSMART IFC 4.3.2.0 documentation](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/index.html)
- [IfcRelContainedInSpatialStructure, including WR31](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcRelContainedInSpatialStructure.htm)
