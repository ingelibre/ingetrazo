# Thailand 2566 — Code Pack 1.0.0

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
