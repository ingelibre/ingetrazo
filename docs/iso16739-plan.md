# ISO 16739 (IFC) plan — from "tagged export" to a conforming BIM exchange

*Written 2026-10-27. Starting point: `core/bim.py` (tags + takeoff) and
`formats/ifc.py` (hand-written IFC4 writer, ~230 lines). Trigger: the
export carries no element type (`PredefinedType` / type objects) and no
status (new / existing / demolish), and both matter downstream.*

## 0. What "fully supporting ISO 16739" can honestly mean

ISO 16739-1 *is* the IFC schema: IFC4 ADD2 TC1 (ISO 16739-1:2018) and
IFC4.3 ADD2 (ISO 16739-1:2024). The schema has ~1300 entities. No modeller
implements all of them, and the standard does not ask them to. Conformance
is defined per **Model View Definition (MVD)**: the subset an exchange
promises to fill correctly.

So "full support" here means:

| Goal | Meaning | Proof |
|---|---|---|
| **G1 — Valid** | Every file we write validates against the schema and its WHERE rules / normative rules | `ifcopenshell.validate` + buildingSMART Validation Service, clean |
| **G2 — Reference View conformant** | Everything IFC4 *Reference View* (RV 1.2) requires for the elements we export: spatial structure, typed elements, PredefinedType, psets, quantities, materials, openings, types, georeferencing | RV checks in the validation service; round-trip through BlenderBIM / FreeCAD / BIMcollab Zoom |
| **G3 — Round trip** | IFC import (#129) of what we export, and of RV files from other tools, without losing identity (GlobalId) | import → export → diff test |
| **G4 — IFC4.3** | The 2024 edition: infrastructure (IfcFacility, IfcRoad, IfcAlignment) for the civil users of georef | same validation on `IFC4X3_ADD2` |

Design Transfer View (parametric editing, extrusions with boolean openings) is
**not** a goal. It goes against the freeform-first principle: the geometry
is the user's drawing, not a parametric wall. We would only add extrusions
where they are exact (see M7).

## 1. Gap analysis — what is missing today

### 1.1 Bugs (wrong data today)

1. **Groups export in local coordinates.** `save_ifc` uses
   `obj.get("faces") or list(obj["group"].mesh.faces)`, but group objects
   carry no `"faces"`. A moved group or a component instance ends up at its
   definition's origin, and its quantities are computed on the local mesh.
   `quantities_csv` has the same bug. `collect_objects` already does it
   right (`world_mesh`).
2. **GlobalId changes on every export.** `ifc_guid()` is called fresh, so
   two exports of the same model share no identity. No viewer, clash tool or
   budget update can track changes. ISO 16739 requires GlobalId to stay the
   same for the object's lifetime.
3. **`Tag = 'IngeTrazo'` on every element.** `Tag` is the element's mark
   (e.g. "W-12", "P3"). For `IfcSpace` that slot is `LongName`, so every
   space is called "IngeTrazo".
4. **`IfcQuantityWeight` without a mass unit.** The unit assignment has
   length, area and volume only, so the rebar weight has no defined unit.

### 1.2 Element attributes (the reported gap)

| Attribute | Today | Needed |
|---|---|---|
| `PredefinedType` (e.g. `IfcWall.SOLIDWALL`, `IfcSlab.FLOOR / ROOF / BASESLAB`, `IfcBeam.LINTEL`) | `$` or `.NOTDEFINED.` | Enum per class from the schema; `USERDEFINED` + `ObjectType` text |
| `ObjectType` | `$` | Free text; **required** when PredefinedType = USERDEFINED (WHERE rule `CorrectPredefinedType`) |
| `Description` | `$` | Free text |
| `Tag` | `'IngeTrazo'` | User's mark / the object's id |
| **Status** | — | In IFC4 this is a **property**, `Pset_<Class>Common.Status` (`NEW`, `EXISTING`, `DEMOLISH`, `TEMPORARY`, `OTHER`, `NOTKNOWN`, `UNSET`), not an entity attribute |
| Class-specific (`IfcDoor.OperationType`, `IfcWindow.PartitioningType`, `IfcReinforcingBar.SteelGrade / BarSurface`, `IfcSpace.LongName`, `IfcPile.ConstructionType`…) | partly | From the schema table, editable where meaningful |
| **Type object** (`IfcWallType`, `IfcDoorType`… via `IfcRelDefinesByType`) | — | "This wall is a *Muro de ladrillo KK 15 cm*": shared psets, material and PredefinedType for many instances |

### 1.3 Property sets

- No `IfcPropertySet` is written at all. RV expects the common psets
  (`Pset_WallCommon`: `IsExternal`, `LoadBearing`, `FireRating`,
  `ThermalTransmittance`, `Reference`, `Status`, …).
- Values must be typed (`IfcBoolean`, `IfcLabel`, `IfcLengthMeasure`,
  `IfcThermalTransmittanceMeasure`, enumerations via
  `IfcPropertyEnumeratedValue`). Today there is no typed value system.
- User-defined psets (any name not starting with `Pset_`) for project data,
  e.g. budget partida codes for IngePresupuestos.

### 1.4 Quantities

- The `Qto_*` sets exist for the 16 classes. Missing: the mass unit (above),
  `MethodOfMeasurement`, Qto sets for the new classes, and a way to type in
  a manual value where measuring is impossible (open sheets have no
  volume). Manual values must be marked as such, not mixed silently with
  measured ones.

### 1.5 Spatial structure and placement

- One fixed `Site / Building / Storey` with fixed names, storey elevation 0.
  Needed: project name and units from the document; multiple buildings and
  storeys with elevations; assigning elements to a storey (manually or by
  height); `IfcSpace` aggregated into its storey.
- Every element shares the world-origin placement and writes world
  coordinates. RV wants placements relative to the storey
  (`IfcLocalPlacement` chains) and geometry local to the element.
- **Georeferencing:** `scene.georef` exists but is not exported. Needed:
  `IfcMapConversion` + `IfcProjectedCRS` (EPSG), and
  `IfcSite.RefLatitude / RefLongitude / RefElevation`. Without this, large
  UTM coordinates also hurt precision.

### 1.6 Representation context and geometry

- No sub-contexts. RV requires `IfcGeometricRepresentationSubContext`
  for `Body` (and `Axis`, `Box`, `FootPrint` where used); `TrueNorth` is missing.
- `IfcFacetedBrep` / `IfcShellBasedSurfaceModel` are allowed, but RV prefers
  `IfcTriangulatedFaceSet` / `IfcPolygonalFaceSet` (smaller, faster to read).
- No colours: `IfcStyledItem` + `IfcSurfaceStyle` from the face / group
  material, with textures optional.
- No `Axis` representation for walls, beams and members, which some
  consumers read for length.

### 1.7 Materials, layers, classification

- No `IfcMaterial` / `IfcRelAssociatesMaterial`. Walls and slabs want an
  `IfcMaterialLayerSetUsage` (thickness per layer). Columns and beams want an
  `IfcMaterialProfileSetUsage`, or simply a single `IfcMaterial`.
- Layers ("tags" in the UI) → `IfcPresentationLayerAssignment`.
- No classification. `IfcClassificationReference` (Uniclass, OmniClass,
  Uniformat, or the local budget catalogue) via
  `IfcRelAssociatesClassification` is the clean channel for partida codes.

### 1.8 Relationships and composition

- Nested groups are flattened. A group of tagged groups should be an
  `IfcElementAssembly` (or a type-specific aggregate such as `IfcStair` of
  flights) via `IfcRelAggregates`.
- Components (instances) → `IfcRepresentationMap` + `IfcMappedItem` on
  the type object instead of one copy of the geometry per instance.
- Logical groups → `IfcGroup` / `IfcZone` / `IfcSystem`
  (`IfcRelAssignsToGroup`).
- **Openings:** doors and windows are separate objects today, and the hole
  in the wall face is just a hole. RV expects
  `IfcOpeningElement` + `IfcRelVoidsElement` (wall ← opening) +
  `IfcRelFillsElement` (opening ← door). The hole loops we already have give
  us the opening's outline.

### 1.9 Class coverage

16 curated classes plus a fallback to `IfcBuildingElementProxy`. Missing
building elements in common use: `IfcCurtainWall`, `IfcPlate`,
`IfcChimney`, `IfcShadingDevice`, `IfcBuildingElementPart`,
`IfcFurnishingElement`/`IfcFurniture`, `IfcEarthworksFill/Cut` (4.3),
`IfcFlowSegment` family for MEP, `IfcGeographicElement` (terrain),
`IfcAnnotation` (grids → `IfcGrid`), `IfcCourse` / `IfcPavement` (4.3).
The proxy fallback must carry `ObjectType` so the information is not lost.

### 1.10 File level

- Header: `FILE_DESCRIPTION` must name the view
  (`('ViewDefinition [ReferenceView_V1.2]')`). `FILE_NAME` should carry
  author and organization from preferences, and the application version.
- `IfcOwnerHistory` is optional in IFC4. It is still worth writing once
  (`IfcApplication` with version, `IfcPersonAndOrganization`) because
  many checkers warn without it.
- Only IFC4 can be written; IFC4.3 (`IFC4X3_ADD2`) is the current ISO
  edition, and IFC2x3 is still what many tools import best (optional, low
  priority).

### 1.11 Import

No IFC import at all (#129, on the roadmap as "later").

### 1.12 Verification

`test_ifc_validation.py` runs `ifcopenshell.validate` (schema + WHERE
rules) when ifcopenshell is installed. Missing: the buildingSMART normative
rules (gherkin rules of the Validation Service), RV-specific checks, an IDS
check (ISO 7817 *Information Delivery Specification*, the standard way a
client states "every wall needs Status and FireRating"), and golden-file
tests for stable output.

## 2. Proposed restructuring

### 2.1 The core problem: the tag is a dict copied onto every face

Today, `face.attrs["ifc"] = {"id", "class", "name"}` is duplicated across
every face of an object, and `group.ifc` is a separate copy. Adding type,
status, psets, materials, classification and a stable GUID to *every face*
multiplies memory and makes editing one object a walk over all its faces,
with the risk that the copies drift apart after push/pull or heal.

**Proposal: one BIM registry per document. Geometry only points into it.**

```
scene.bim : BimModel
    project      : ProjectInfo        name, author, org, units, schema/view
    sites/buildings/storeys : SpatialNode (guid, name, elevation, children)
    objects      : dict[guid, BimObject]
    types        : dict[guid, BimType]
    materials    : dict[key, BimMaterial | LayerSet]
    classifications : dict[key, ClassificationRef]
    groups       : dict[guid, BimGroup]           IfcGroup / IfcZone / IfcSystem

BimObject
    guid, ifc_class, predefined_type, object_type
    name, description, tag
    storey      -> SpatialNode guid (None = automatic by height)
    type        -> BimType guid | None
    psets       : dict[pset_name, dict[prop, TypedValue]]   (incl. Status)
    qto_overrides : dict[name, (value, "manual")]
    material    -> key | None
    classification : list[key]

face.attrs["bim"] = guid           # loose faces: just the reference
group.bim       = guid             # group objects: just the reference
```

The rule that geometry stays free and the tag is metadata does not change.
Only the metadata moves to one place.

### 2.2 Packages

```
core/bim/
    __init__.py       re-exports today's public API (tag_faces, collect_objects,
                      class_quantities…) so extensions keep working
    model.py          BimModel, BimObject, BimType, SpatialNode, TypedValue
    registry.py       create / retag / untag / merge / split, GUID reuse
                      rules (copy = new GUID, move = same GUID)
    quantities.py     today's class_quantities + manual overrides
    takeoff.py        collect_objects, quantities_csv
    schema/
        express.py    parses the verbatim EXPRESS file from vendor/ at
                      runtime: per entity the attribute order + types,
                      PredefinedType enums, abstract/concrete, supertypes
        psets.py      parses the verbatim pset XML: Pset_*Common templates
                      (properties, value types, enums), Qto_* templates
        cache.py      caches the parsed tables per schema version
vendor/ifc-schema/    official buildingSMART files, unmodified, own
                      LICENSE (CC BY-ND 4.0) + attribution
formats/ifc/
    step.py           ISO 10303-21 writer: typed values (IfcLabel(...),
                      enums, booleans, reals), header, string encoding
    entities.py       schema-checked builder:
                      b.entity("IfcWall", GlobalId=..., PredefinedType="SOLIDWALL")
                      → right attribute order, padding, required-attribute
                        and enum check against schema/ifc4.py
    export.py         project/spatial tree, placements, georef,
                      geometry, psets, qto, materials, styles, layers,
                      openings, types, aggregation
    views.py          per-MVD switches (RV now, IFC2x3 CV2.0 maybe)
    importer.py       (M8)
```

Why a generated schema table instead of ifcopenshell at runtime: the reason
recorded in `formats/ifc.py` still holds (heavy native wheels lag new Python
versions and ARM). The table removes the main weakness of the
hand-written writer: attribute positions counted by hand (`_ATTR_COUNT`).
ifcopenshell stays a **dev/test dependency** that checks our output.

**Licensing (checked 2026-10-27).** IngeTrazo is GPL-3.0. buildingSMART
publishes the formal IFC releases (EXPRESS schema, pset templates) under
**CC BY-ND 4.0**. The repository notice also says the material may be "used
in software development, or translated into another computer language,
provided full attribution is given", and that changing the specification
needs prior written consent.

- Implementing the standard, i.e. writing and reading IFC files, is not
  restricted. Today's hand-written writer is fine.
- CC BY-ND is **not GPL-compatible**: the ND clause forbids distributing
  adapted material, and the GPL requires that recipients may modify what
  they get. A table generated from the schema and committed *as part of the
  GPL program* would carry content that can't be relicensed under GPL.
- **Chosen approach:** ship the official files **verbatim and unmodified**
  in `vendor/ifc-schema/` (e.g. `IFC4_ADD2_TC1.exp`, `IFC4X3_ADD2.exp`, the
  pset XML) with their own licence file and attribution. They are
  separate data next to the program (aggregation, GPL-3.0 §5), not part of
  it. `formats/ifc/schema` parses them **at runtime** (cached on first use)
  into the attribute and enum tables. No derived table is committed.
- In addition, ask buildingSMART (contact@buildingsmart.org) for written
  consent to ship derived tables. If granted, committing generated tables
  becomes an option for start-up speed.
- Hand-written class lists that only *name* entities and enums for
  interoperability (like today's `IFC_CLASSES`, `QSET_NAMES`) are facts
  needed to interoperate, not copied expression, and stay as they are.

This is an engineering reading, not legal advice.

### 2.3 Persistence and undo

- `.igz` gains a `bim` section (the registry). The format version goes up.
  The loader migrates old `{"id","class","name"}` tags: one BimObject per
  old id or tagged group, with fresh GUIDs that are stable from then on.
  Old IngeTrazo versions reading a new file lose the tags (acceptable,
  document it), or we keep writing the legacy dict for one release.
- Every registry edit is a `History` command (retag, set property, assign
  storey…), like geometry edits. Tags already survive undo; properties must
  too.
- Copy / paste / component instancing: a copied object gets a new GUID and
  copies its properties; the type stays shared.

### 2.4 UI

- **BIM panel** becomes *class + type + PredefinedType + name/tag +
  status* in the top row, with a property editor below that is built from
  the pset template of the class (checkboxes for booleans, combos for
  enums, unit-aware fields for measures), plus "custom property".
- **Project / storeys dialog**: names, elevations, georef link (reuses the
  datum), author and organization.
- **Types library**: create a type from a tagged object, apply it to the
  selection, edit it once for all instances.
- Outliner: optional columns Type, Status, Storey.
- Status gets a viewport colour filter (new = normal, existing = grey,
  demolish = red/dashed): this is what makes the attribute useful while
  drawing, not just in the file.

### 2.5 Extension API

ROADMAP step 1 ("one common BIM API for extensions") lands here: extensions
call `core.bim.registry`, never touch `face.attrs["ifc"]`. The windowizer
example is the first consumer (window + opening + fill in one call).

## 3. Implementation order and milestones

Each step is its own PR with tests. Every milestone ends with an exported
sample house (the "casita" of `test_ifc_bridge.py`) that is clean in the
buildingSMART Validation Service and opens correctly in BlenderBIM and
IngePresupuestos.

### M0 — Correctness fixes (small, no model change) — DONE 2026-10-27
1. Group objects export `world_mesh` geometry and quantities (IFC, CSV and
   the BIM panel's takeoff column), through `core.bim.object_faces`.
   Tests: a moved group and a component whose geometry lives in a nested
   placement land at their world position.
2. Mass and plane-angle units in the unit assignment; `Tag` empty instead of
   `'IngeTrazo'` (which also left `IfcSpace.LongName` empty).
3. Header with `ViewDefinition [ReferenceView_V1.2]` and the application
   version. The file name is escaped like any IFC string (a name with `ñ`
   used to abort the export with `UnicodeEncodeError`).
   `IfcOwnerHistory` + `IfcApplication` **moved to M4**: a valid
   `IfcPerson` needs a name, and IngeTrazo has no author setting yet.
   Inventing one, or writing the OS login into a file that gets shared, is
   worse than the optional attribute left empty.
4. `Body` sub-context.
5. CI installs `ifcopenshell==0.8.5` (test-only), so the validation tests
   run in the gate instead of skipping.

*Gate:* the existing tests and the validation suite pass in CI, not just locally.

### M1 — Foundation: schema tables + entity builder
1. The verbatim IFC4 EXPRESS + pset files in `vendor/ifc-schema/` with
   their licence, and a runtime parser that builds the entity / enum / pset
   tables (cached).
2. `formats/ifc/step.py` + `entities.py`. Port `save_ifc` onto the builder
   **without changing its output** (golden-file test against today's file,
   GUIDs masked).

*Gate:* `_ATTR_COUNT` is gone, and an unknown attribute or invalid enum
raises at export instead of producing a broken file.

### M2 — Data model: the BIM registry (the big refactor)
1. `core/bim/model.py` + `registry.py`. `face.attrs["bim"] = guid`,
   `group.bim = guid`.
2. Push/pull, heal, explode, copy, group/ungroup and undo carry the
   reference (today's `attrs["ifc"]` code paths in `tools/pushpull.py`,
   `core/history.py`, `core/edits.py`, `core/group.py`).
3. `.igz` migration (old → new), with a test on a saved pre-M2 file.
4. Stable GlobalIds in the export.
5. Compatibility re-exports in `core/bim/__init__.py`.

*Gate:* exporting twice yields the same GlobalIds, and all BIM tests pass
unchanged. This milestone has no visible feature on purpose. It is the
riskiest step, so it lands alone.

### M3 — Type and status (the reported gap) ← first user-visible milestone
1. `PredefinedType` / `ObjectType` / `Description` / `Tag` in the registry,
   the panel and the export (with the USERDEFINED rule).
2. `Pset_<Class>Common` with `Status`, `IsExternal`, `LoadBearing`,
   `Reference`, typed values; custom psets.
3. Status colour filter in the viewport.
4. IngePresupuestos bridge test extended: Status reaches the importer, and
   demolition can be billed separately.

*Gate:* the casita validates with filled common psets, and an IDS file
("all walls have Status and IsExternal") passes.

### M4 — Spatial structure and georeferencing
1. Project / site / building / storey editor; storey assignment
   (automatic by height, manual override).
2. Relative placements; geometry local to the element.
3. `IfcMapConversion` + `IfcProjectedCRS` from `scene.georef`;
   `IfcSite` lat/long.
4. `IfcSpace` aggregated into storeys.
5. Author and organization in the project dialog (stored in the document,
   with a default from preferences) → `FILE_NAME` author/organization and
   `IfcOwnerHistory` + `IfcPersonAndOrganization` + `IfcApplication`.

### M5 — Materials, styles, layers, classification
1. `IfcMaterial` from the IngeTrazo material; layer sets for walls/slabs
   (thickness measured, as with `Width` today).
2. `IfcStyledItem` colours.
3. `IfcPresentationLayerAssignment` from layers.
4. `IfcClassificationReference`, starting with the IngePresupuestos partida
   catalogue.

### M6 — Types, components, assemblies
1. `BimType` + `IfcRelDefinesByType`; the types library in the UI.
2. Components → `IfcRepresentationMap` / `IfcMappedItem`.
3. Nested tagged groups → `IfcElementAssembly` / aggregates.
4. `IfcGroup` / `IfcZone` / `IfcSystem`.

### M7 — Openings, geometry, class coverage
1. Door/window in a wall hole → `IfcOpeningElement` + voids + fills
   (detected from the hole loop the door's face sits in, or stated by the
   windowizer API).
2. `IfcPolygonalFaceSet` as default body. `IfcExtrudedAreaSolid` only where
   the face set *is* an exact prism (pushed planar face), and `Axis` for
   walls, beams and members.
3. Class list from the schema table (grouped, searchable) instead of 16
   names; the proxy fallback keeps `ObjectType`.

**Milestone "IFC4 Reference View" (G1 + G2):** after M7. The casita and a
real project (piscina) validate clean in the buildingSMART service and pass
an RV-level IDS. This is the point where we can say "conforms to ISO 16739
(IFC4 RV) for export" and announce it.

### M8 — Import (#129) (G3)
1. A STEP parser (pure Python; a small tokenizer is enough for Part 21) plus
   the schema tables to resolve entities.
2. Geometry: faceted / polygonal / triangulated sets and extrusions natively.
   Advanced BReps and booleans through **optional** ifcopenshell when
   installed, otherwise as proxy mesh with a warning.
3. Map into groups + the registry, keeping GUIDs. Round-trip test:
   export → import → export gives the same file (GUIDs, psets, quantities).

### M9 — IFC4.3 / ISO 16739-1:2024 (G4)
1. Generate the `IFC4X3_ADD2` tables. The writer selects the schema; the
   default stays IFC4 until the consumers (IngePresupuestos) read 4.3.
2. `IfcFacility` family (`IfcRoad`, `IfcBridge`…), `IfcAlignment` from the
   georef traced paths, earthworks and courses from the terrain work.

### M10 — Conformance as a permanent check
- IDS validation in-app ("check model against requirements…"), useful to
  users as well as to us.
- CI runs the buildingSMART normative rules against the golden files.
- Optional later: IFC2x3 Coordination View export for old consumers.

## 4. Open decisions (for the maintainers)

1. **Target schema default:** IFC4 (what IngePresupuestos and most tools read
   today) with 4.3 opt-in, or 4.3 from M9 on?
2. **Schema tables:** proposed is the verbatim schema in `vendor/` plus
   runtime parsing (see 2.2, licensing). Do we also ask buildingSMART for
   consent to commit generated tables?
3. **ifcopenshell:** dev/test only (proposed), optional at runtime for import
   geometry (proposed for M8), or never?
4. **.igz compatibility:** write the legacy `ifc` dict alongside the new
   reference for one release, or not?
5. **Status in the viewport:** is the colour filter wanted in the core, or as
   an extension on top of the new API?
