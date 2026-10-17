from pathlib import Path
import json
import sys
sys.path.insert(0,str(Path(__file__).parents[2]))
from go_structural_analysis.thai_code import PACK,ACTIONS,presets
root=Path('.')
(root/'code_packs/thailand-2566-v1.0.0.json').write_text(json.dumps(dict(metadata=PACK,actions=ACTIONS,presets=presets()),ensure_ascii=False,indent=2),encoding='utf-8')
(root/'THAI_CODE_PACK_v0.2.4.md').write_text('''# Thailand 2566 — Code Pack 1.0.0

Source: [Gazette, 6 September 2566, volume 140 part 54 ก](https://ratchakitcha.soc.go.th/documents/140A054N0000000000400.pdf).
Printed pages 7–8 (PDF pages 4–5), clauses 6 and 7. The downloaded source SHA256 is
`488f6315e12d1ca1913f72960f76a9ef9422619ceaf784df4564351ba70704c9`.

`code_packs/thailand-2566-v1.0.0.json` contains all 7 ASD and 11 LRFD original
formulas, expanded factors, design methods and citations. `thai_code.py` is the
runtime pack, requiring no external file or Qt. Original factors are read-only;
Clone creates Custom factors with origin metadata. Select one statutory method at
a time. Custom combinations remain explicitly labelled and have their own envelope group.

D includes configured self-weight; L includes impact where applicable. W is wind;
E is a separately verified earthquake action; H is lateral earth/water pressure;
F is liquid pressure; T is temperature/shrinkage/creep/settlement action.

Map actual load-case names in the manager. WX+, WX−, WY+, WY− (or ASCII minus)
and EX+, EX−, EY+, EY− are alternative directional cases, not automatic simultaneous
actions. Each generated row records its direction and governing original formula.
Directional derivatives are identified separately from statutory formulas.
Missing mappings/references produce Missing Input and disable the related presets.

E requires an independently reviewed action and reference. H/F/T require a
reviewed equivalent-force model and reference; this solver does not generate
pressure, temperature, creep or prescribed-settlement actions automatically.
The checkboxes record user review, not a certification of the upstream action model.

For both 2D and 3D code-managed combinations, self-weight belongs to one selected
D case. A load tagged self_weight cannot coexist with automatic self-weight.
Untouched legacy 2D files retain their original per-case self-weight convention
until the user reviews the Code Pack and selects its single D case.

This pack supplies load combination factors only. Capacity, full code compliance,
seismic action generation, and complete serviceability checks are Not Available.
''',encoding='utf-8')
(root/'UPDATE_v0.2.4.md').write_text('''# Update to GO Structural Analysis v0.2.4

1. Save the model/workspace and close IngeTrazo. Back up source, `.igz` files and
   `%APPDATA%\\ingetrazo\\plugins\\go_structural_analysis`.
2. Use the matching v0.2.4 Windows Setup for an offline bundled runtime, or run
   `powershell -ExecutionPolicy Bypass -File .\\install.ps1 -SkipDependencies`
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
''',encoding='utf-8')
(root/'CHANGELOG_v0.2.4.md').write_text('''# v0.2.4

- Thailand 2566 versioned/cited pack: 7 ASD + 11 LRFD formulas, reviewed action
  bindings, directional derivatives, missing inputs, self-weight once in D.
- Read-only statutory factors; editable/disableable Custom factor tables, Clone
  provenance and separate method envelope groups.
- 2D combinations and envelopes added without changing legacy 2D case behavior.
- Current/Stale/Running/Failed/Not Analyzed safety state; full input fingerprints,
  snapshots, finite/equilibrium guards, scene-geometry checks and failure invalidation.
- Stale watermark independent of Legend. Optional archived snapshot visualization;
  gated current CSV/JSON report and explicitly labelled archived CSV exports.
- Selected-member axes by default, All/Selected/None, label collision placement and
  density, consistent signed fills, visible diagram planes, display tolerance and mm.
- Analytical model tree, collapsible sections, width bounds, viewport quick controls,
  themes, status text and background progress.
- Added independent golden factor/closed-form solver tests, safety tests and Qt/live QA.

Limits: linear elastic analysis; no automatic seismic/pressure/thermal action
construction, no section capacity or complete serviceability/design checks.
''',encoding='utf-8')
