# Update to GO Structural Analysis v0.2.4

Latest source adds [Combination overview and reviewed Generator](COMBINATION_OVERVIEW.md).
Prota reference/task files are under `docs/`; the local source PDF is excluded
from the installer. Restart after the development install; the existing Setup
executable does not contain this latest patch.

The latest source includes [simplified load forms](LOAD_FORMS.md). The existing
Setup executable predates this patch; use the development installer for these
forms. [Patch evidence](TEST_RESULTS_LOAD_FORMS.md) records incomplete live QA.

1. Save the model/workspace and close IngeTrazo. Back up source, `.igz` files and
   `%APPDATA%\ingetrazo\plugins\go_structural_analysis`.
2. Use the matching v0.2.4 Windows Setup for an offline bundled runtime, or run
   `powershell -ExecutionPolicy Bypass -File .\install.ps1 -SkipDependencies`
   from the existing source directory when the existing PyNite 3.2.0 runtime is present.
3. Restart IngeTrazo; open Extensions → GO Structural Analysis v0.2.4.
4. Existing 2D/3D models remain supported. Older result snapshots are Stale until
   rerun with the new safety/provenance layer. No source model is overwritten by update.
5. Loads → Load Combinations → Thailand 2566 / Custom. Select ASD/LRFD, map cases,
   review missing inputs and E/H/F/T applicability, enable presets, then Apply.
   Clone to edit factors. Inputs, statutory presets and Custom factors have separate pages.
6. Run Analysis. Results show Current/Stale/Running/Failed/Not Analyzed. Current CSV
   and engineering JSON report are disabled for unavailable results. Archived/Stale
   CSV carries an explicit status and original input fingerprint in every row.

Analysis uses kN–m and full precision. Display tolerance, mm displacement, scales,
labels, planes and local axes affect presentation only. Restore Display Defaults
returns to selected-member axes and normal label density. Quick Controls remain in
the viewport when the panel is hidden. Collapsible sections retain active controls.

The original document is parked by Workspace; Return restores it. Save As creates
an independent analytical `.igz`. Store analysis in current document is explicit.
No IngeTrazo Core files in Program Files are modified.

This release provides analysis and load combinations. Capacity, full code compliance
and complete serviceability checks remain Not Available.


## Member workflows - 2026-10-11

ASD/LRFD presets can coexist with Custom combinations, with separate method
metadata/envelope groups. Distributed-load rows show analytical length and an
explicit full-member action. Member context menus open modeless single/connected
collinear result plots, preserving local signs and stale-result protection.
See MEMBER_WORKFLOWS.md and TEST_RESULTS_MEMBER_WORKFLOWS.md for usage, actual
validation and remaining restart/installer/physical-interaction limitations.


## CG-001 - Continuous beam diagrams / 2026-10-11

Connected collinear beam graphs now share one cumulative station axis and scale,
with node/member labels and horizontal scroll. Reversed/rotated member forces
project to the context-selected common frame; exact polynomial extrema and
real jumps retained. Click a station to inspect member/x/L. See
MEMBER_WORKFLOWS.md and TEST_RESULTS_CONTINUOUS_GRAPHS.md for actual QA evidence.
