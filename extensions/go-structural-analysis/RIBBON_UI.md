# Engineering workspace ribbon

## Reference and scope

Reference: [ProtaStructure 2022 Basic Training Guide, pages 6–9](https://d2dpssj7o46s6b.cloudfront.net/documents/protastructure-2022-basic-training-guide.pdf).
Those pages illustrate task-ordered ribbon groups, quick access, structure-tree
search, view organization and display controls. GO uses that workflow principle
with its existing analysis commands; no Prota graphical assets or implementation
are copied. This patch adds a compact ribbon inside the extension viewport without
changing IngeTrazo Core or the solver.

## Implemented first increment

| Tab | Groups / commands |
|---|---|
| Model | Geometry: Nodes, Members; Properties: Materials, Sections, Supports; Selection: edit selected, preview existing geometry |
| Loads | Load Cases, Combinations; Point/Moment and Distributed Load forms |
| Analysis | Check Model / Stability and Run Analysis |
| Results | Inspector, result tables, current CSV and engineering report |
| Display | Diagram/label settings, restore defaults, show/hide panel, return to parked model |

Save and Run remain in the quick-access header, with textual analysis status.
Collapse hides the command row while keeping tabs and quick actions available.
Wide command groups scroll horizontally in narrow viewports. Ribbon tab changes
follow the retained Model / Loads / Results side panel. Display settings and the
inspector open the relevant expanded panel section. Existing viewport controls
remain available for diagram/case/scale. Current exports follow the original
Current/Stale safety rules; analysis continues in the existing background worker.

The ribbon is a Qt child of the viewport, so it also works when the side panel is
hidden. Geometry projection is unchanged. Legends are placed below the ribbon,
and label bounds reserve that area; canvas repainting keeps controls above the
overlay. Light/Dark/System use the extension palette.

## Further UI work

Command search, shared Ribbon routing, Model Tree filtering and analytical
context menus are now implemented; see [usage](COMMAND_UI.md) and
[actual QA](TEST_RESULTS_COMMAND_UI.md).

1. Extend the command registry with configurable shortcuts and quick-access
   commands. Routing, search and Ribbon/context enable-state rules are implemented.
2. Add an integrated Project menu for validated Open/Save As/example workflows,
   retaining the host's parked model and unsaved-change protections.
3. Expand implemented Model Tree search and Node/Member context menus with
   bulk-edit previews and additional geometry actions.
4. Improve Node/Member/Support/Load forms with labelled fields, unit indicators,
   pick-in-viewport tools and previews; keep tables for bulk entry.
5. Introduce storey/grid management and named plan/elevation/3D views as separate
   model/view features, with schema/migration and selection tests.
6. Add a dedicated Review workflow for connectivity, releases, duplicate objects
   and stability messages; route warnings to affected geometry.
7. Result-specific controls for components, case/envelope, governing combination,
   inspector and report filtering. Persist workspace display preferences separately
   from engineering input fingerprints.

These are planned work, not implemented claims. A Design ribbon requires a real
capacity/serviceability module first; current code-compliance status remains Not
Available. Full ribbon customization, multi-view docking and physical building
objects are outside this first increment.

## Installation and evidence

Run the existing development installer with `-SkipDependencies`, then restart
IngeTrazo to load the new user-plugin source. The distributed Setup executable has
not been rebuilt. Read [ribbon QA](TEST_RESULTS_RIBBON.md) before release.
