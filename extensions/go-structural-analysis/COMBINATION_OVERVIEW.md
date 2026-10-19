# Combination table and Loading Generator

Loads → Load Combinations now opens the overview table first.
Rows are combinations; columns are actual load cases. Double-click a Custom factor
to edit its number. Tab/Enter commits the edit; zero excludes a case, negative
reverses it. Formula and selected-row details update immediately. Search narrows
the visible rows. Custom checkboxes enable/disable combinations. Add by name,
press Enter, or duplicate the selected row. The detail form is collapsible.

ASD/LRFD rows are protected originals. Duplicate creates a Custom clone with its
provenance; rename/delete/edit controls are disabled when an original is selected.
Full-precision factors are retained when an editor is opened/closed unchanged.
Non-finite edits are rejected, and empty enabled factors prevent Save.

**Loading Generator** uses the existing Thailand 2566 pack:
1. Select ASD or LRFD and map existing Dead/Live cases.
2. Select existing wind cases as alternatives. Review actual formulas, clause
   references and missing inputs; unavailable formulas cannot be selected.
3. Apply selected presets to the dialog draft. Existing Custom combinations stay.
   Save commits through the original panel workflow; Cancel preserves the model.

The generator replaces the active statutory preset selection with the reviewed
selection; it does not append another design method silently. It creates neither
load cases nor physical wind/seismic actions. Add missing cases through Load Cases
and define their forces first. Concrete/steel capacity checks, cracked stiffness
and P-Delta controls shown in Prota are not supplied by this feature.

The training guide pages 30–31 informed the workflow. Legal factors remain those
of GO's cited Thai pack. Full guide/reference/task records are under
[docs/PROTA_REFERENCE.md](docs/PROTA_REFERENCE.md).

The final package was copied by the development installer; restart IngeTrazo to
load all final source. Setup was not rebuilt. Read
[actual evidence](TEST_RESULTS_COMBINATION_OVERVIEW.md) before release.
