# Türkiye project and verified delivery workflow

Open **BIM → Türkiye delivery information → Project and delivery workflow**.
This optional workflow extends the [object field editor](turkiye-delivery.md).
It preserves canonical IFC names, existing documents and the default IFC4 exporter.

## Prepare a project

1. Enter the authority's project identifier and naming reference, project type,
   description, application year and cadastral/application information.
2. Record the actual scope/transition decision and its supporting reference,
   building use, area, population and exemption facts. These are project inputs;
   a checkbox does not create an authority decision.
3. Enter the responsible person's registration, name, organization, roles and
   address. The exporter creates real `IfcPerson`, `IfcOrganization`,
   `IfcPersonAndOrganization`, `IfcActor` and `IfcOwnerHistory` records.
4. Enter the TUREF 3-degree EPSG system/central meridian, geodetic and vertical
   datum, origin east/north/height, local X unit vector, scale and precision.
   No measurement is guessed. `IfcProjectedCRS` and `IfcMapConversion` preserve
   the model's local geometry. An optional measured survey point exports as
   `IfcAnnotation` (`SURVEY` in IFC4.3).
5. Add the site, buildings and storeys. Enter names, addresses, cadastral and
   planning properties, quantities and elevations. Conditional fields accept
   a documented exception. IDs persist in IGZ; reordering does not recreate them.
6. Apply the project and assign each tagged object to its storey in the object
   editor. Spaces use an EK-3 room number, e.g. `K00_KNT_001`. Other objects may
   be assigned to an existing space on the same floor. Assigning a floor does
   not translate the model. Delete/reparent operations expose dangling
   references as errors rather than silently assigning another floor.
7. For coverings, enter ordered material/thickness layers, axis, direction
   and offset. The declared layer interval is compared with the exported
   geometry along that axis; a mismatch blocks the checked package.
8. Enter the nine EK-2 filename fields and the authority's actual size limit.
   The model uses document kind `MD`; sheets use `PL` with successive two-digit
   sequence values. Do not substitute a guessed authority code.

All Apply operations use the existing undo history. Closing an untouched
dialog changes nothing. Project, spatial and object metadata survive IGZ saves.

## Review and generate

The quality tab contains the 21 architectural or 16 other-discipline EK-9
rows. Record an answer and evidence for each row, the reviewer and ISO date,
then explicitly **Confirm review for current model**. Changing model content,
sheet content, CRS or applicability invalidates the recorded model fingerprint.
Changing answers/reviewer/date requires confirmation again. Answers are never
automatically filled with “yes”.

Automated checks cover required typed fields, enums and references, naming,
duplicate geometry, closed rooms, actual solid intersections between rooms,
storey assignment, floor/space area totals and material-layer intervals.
Room contact without positive intersection volume is allowed. Room numbers
are unique per building. Engineering interpretation, LOD suitability, planning
calculations and PDF/model design correspondence also require the identified
reviewer's recorded evidence; software does not manufacture those decisions.

Prepare model-linked sheets with **parallel vector** frames referencing standard
or saved model views in the composer. Save a live camera view before using it
for delivery so the review binds to persistent view settings.
Install `requirements-delivery.txt`, install Java and the official
[veraPDF CLI](https://verapdf.org/software/), and select its CLI JAR in the
delivery tab. Ordinary modeling/export does not require these optional tools.

**Build verified delivery package** freshly renders the sheets and exports
`IFC4X3_ADD2`. It runs IfcOpenShell schema **and EXPRESS** validation, validates
each sheet and the quality form as **PDF/A-1b** with veraPDF, checks file sizes,
and checks the model fingerprint again. Qt's invalid XMP `pdf:Trapped`
duplicate is normalized without rasterizing the sheet before validation.

Only a passing result atomically replaces the chosen ZIP. On failure the
existing ZIP survives. A failed/pending quality gate saves a `.checks.json`
diagnostic next to the chosen destination.

The ZIP includes IFC, source IGZ, PDF/A sheets, PDF/A/HTML/JSON quality forms,
veraPDF XML reports, IfcOpenShell evidence and a SHA-256 manifest. These reports
describe the checked model revision and the recorded review; they do not
forge an electronic signature or submit a permit application.

## Source and reproducibility

The rules record [RG 05.08.2026/33331](https://www.resmigazete.gov.tr/eskiler/2026/08/20260805-2.htm)
and the provided 241-page annex PDF's SHA-256 in
`resources/bim/turkiye_delivery.json`. The additional field/form definitions,
source page numbers and EK-9 rows are in `resources/bim/turkiye_workflow.json`.
Official annex download timed out; the provided bytes have not been matched
against a fresh official download. This provenance is carried into the manifest.

Run `pytest tests/test_delivery_workflow.py tests/test_delivery_package.py`.
Set `INGETRAZO_TEST_VERAPDF` to the actual CLI JAR to run the external PDF/A
and full package integration tests; without it those two tests explicitly skip.
`INGETRAZO_TEST_ARTIFACTS` optionally saves the fictitious test delivery ZIP.
Test reviewers, measurements, registrations and authority references are
clearly fictitious; they are not a real project's sign-off.

The legacy field-only `TR_EK5_2026` report retains its original API. Version-2
projects use per-row `pass`/`fail`/`pending`, a revision fingerprint and
`release_ready`, rather than a constant overall regulatory status.
