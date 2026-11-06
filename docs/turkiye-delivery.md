# Türkiye delivery fields: naming and properties

This opt-in editor implements a **bounded field matrix**, not approval of a
complete regulatory delivery. Existing IFC4 and IFC4.3 exports remain
available; selecting the Türkiye profile additionally checks the entered
fields described below. No engineering values or authority IDs are inferred.

## Use

1. Open **Türkiye delivery information** in the BIM panel.
2. Enter the project identifier supplied by the authority, project type and
   optional description. The application does not issue or authenticate a
   project code. The initial object selection edits project information only.
3. Choose a tagged BIM object. Select a discipline and enter description
   tokens to preview `discipline-category-description`, for example
   `MM-DVR-Aks_A`. The category comes from the verified class mapping.
4. Enter the predefined type, identifier, required material name/strength
   and the listed properties. Empty Boolean fields remain unknown; **False
   is a supplied value**, not missing data. Thicknesses and offsets use metres.
5. **Apply entered data** saves one undoable edit. A valid generated name
   replaces the object's IFC name; an incomplete name leaves the original
   name intact and appears in the saved-data check. Closing without Apply
   changes nothing. **Check saved data** evaluates the applied model state.
6. Choose **Türkiye IFC4.3 profile** in the IFC save dialog to enforce this
   field matrix. Missing or invalid fields prevent overwriting output. The
   ordinary IFC choices allow partial, correctly typed information.

The Python equivalent is:

```python
from core.turkiye_delivery import PROFILE, check_scene
from formats.ifc import save_ifc

report = check_scene(scene)
# report['checked_fields_complete'] is NOT regulatory compliance.
save_ifc(scene, path, schema="IFC4X3_ADD2", delivery_profile=PROFILE)
```

## Verified matrix

The shipped `resources/bim/turkiye_delivery.json` records the source pages,
category codes, required fields, canonical property names and supported
predefined-type choices. It also contains the profile's localized labels
(English/Spanish/Turkish); other locales fall back to English without
changing the main catalogs or the separate Turkish localization contribution.
The asset is included in the PyInstaller data manifest.

The current 15 mapped classes are Beam, Column, Covering, Door, Footing,
Member, Pile, Railing, Ramp, Roof, Slab, Space, Stair, Wall and Window, always
using their canonical `Ifc*` names. Categories include `KRS`, `KLN`, `KPL`,
`KAP`, `TML`, `ELM`, `KZK`, `KRK`, `RMP`, `CAT`, `DSM`, `MHL`, `MRD`, `DVR`
and `PNC`. `IfcReinforcingBar` has no category in the supplied tables: the
profile reports it instead of inventing one. Ordinary IFC export still
supports that class.

- Attributes: `Name`, `PredefinedType`, `ObjectType` for `USERDEFINED`, and
  `Tag` where applicable. `IfcSpace` has no `Tag` and does not receive a
  direct material association.
- Materials: entered names produce `IfcMaterial` and
  `IfcRelAssociatesMaterial`. Required name/strength tokens follow the
  table footnote, e.g. `Beton_C25` or `Çelik_S355`.
- Coverings: an explicitly entered thickness, layer axis, direction sense
  and offset produce one `IfcMaterialLayer` / `IfcMaterialLayerSet` /
  `IfcMaterialLayerSetUsage`. No orientation or thickness is guessed. This
  does not generate geometry or model a multi-layer assembly.
- Properties: the applicable `Pset_*Common` fields include `FireRating`,
  `IsExternal`, `LoadBearing` and `FireExit`, according to each class table.
  The six `Pset_SpaceCoveringRequirements` fields use `IfcLabel` or
  `IfcPositiveLengthMeasure`. Boolean properties use `IfcBoolean`.
- Project: `IfcProject.Name`, `Description` and
  `Pset_ProjectCommon.ProjectType` implement the fields in Table 7.1.

Property sets and their relationships have stable GUIDs derived from the
owner and set name. Editing values preserves element and relationship
identity. Quantity sets and geometry remain separate. Tagged groups now
provide their placed faces to consumers, correcting an existing export
error that lost group scaling, translation and nested placements; exported
geometry and class-specific quantities use the same world-space faces. Data travel in
`Scene.ifc_project` and each BIM tag's `delivery` dictionary through `.igz`
(including binary geometry), copying and undo/redo. No format-version bump
or runtime IfcOpenShell dependency is introduced. Older builds may discard
new metadata on edit/resave; continuity requires a build that preserves it.

## Source and interpretation limits

Reference: [publication of 5 August 2026 / 33331](https://www.resmigazete.gov.tr/eskiler/2026/08/20260805-2.htm),
Articles 11–13, and the **user-supplied 241-page annex PDF**. Its hash is
recorded in the JSON asset. The official HTML was retrieved; the official
annex download timed out, so byte equality with the official server was
not established. Table contents were visually checked in the supplied PDF,
not accepted from OCR alone. PDF page numbers are one-based:

- Disciplines: p. 3, Table 2.2. Naming/category rules: pp. 29–34, Tables
  5.1 and 5.3. Object fields: pp. 38, 53–54, 58–59, 64, 73, 79, 83,
  87–88, 91, 96, 98–99, 102, 107–108. Project fields: p. 222, Table 7.1.
- **Separator discrepancy:** Article 11(2) describes hyphens within the
  description; annex 5.5.3 describes underscores and excludes hyphens there.
  The editor exposes both interpretations. The initial annex-based choice
  is explicit and stored with the object; it does not resolve the legal
  interpretation for the user. The outer separators remain hyphens.
- IFC enumeration choices are checked against the supported schema. The
  additional IFC4.3 `BERTH` space type is not included in this field profile
  because it is not in the supplied annex's space table.

Every check report sets **`regulatory_compliance: "not_assessed"`** and lists
unchecked scope. This includes authority-code validity, EK-2 delivery
filenames, spatial-container names/properties and a full storey hierarchy,
other EK-7 actor/organization/CRS information, multi-layer and geometry/material
alignment checks, EK-8 development level, EK-9 forms, amendments and legal
applicability. This editor is not an MVD certification or a delivery approval.
