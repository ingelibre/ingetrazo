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

## Reference

- [buildingSMART IFC 4.3.2.0 documentation](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/index.htm)
- [IfcRelContainedInSpatialStructure, including WR31](https://standards.buildingsmart.org/IFC/RELEASE/IFC4_3/HTML/lexical/IfcRelContainedInSpatialStructure.htm)
