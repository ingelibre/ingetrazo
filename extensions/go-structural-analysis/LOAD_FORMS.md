# Load Cases and Load Combinations — forms update

The latest [Combination matrix and Generator](COMBINATION_OVERVIEW.md) extends
these named forms. The guide reference and continuation backlog are in `docs/`.

This v0.2.4 source patch replaces visible JSON/semicolon input with named forms.
The stored model format and PyNiteFEA 3.2.0 worker remain compatible.

## Load Cases

Loads → Load Cases opens a table. Use +DL, +LL, +WX+/−, +WY+/− or add a custom
case. Edit the name directly. The usage column counts loads/combinations and
identifies self-weight and action bindings. Save updates all references, including
protected combination metadata. A referenced case cannot be deleted; remove its
loads/bindings first. Cancel leaves the model unchanged. Empty/duplicate names and
names colliding with combinations are rejected.

Load Case selectors in point/distributed-load tables use the existing names.
Renaming or changing combinations makes existing analysis results Stale.

## Load Combinations

Loads → Load Combinations opens Custom factors by default for models without a
saved design-method configuration. Choose a combination or type a new name and
press + เพิ่ม Combination. Enter numeric factors alongside each Load Case:
DL = 1.4 and LL = 1.7 produces `1.4 × DL + 1.7 × LL`.
Zero excludes a case; a negative factor reverses its action. The formula updates
while editing. Rename, delete and Enable/Disable are available. Save applies the
changes; Cancel discards them. The form also opens from the full model editor.

For Thailand 2566 choose ASD or LRFD, then Inputs/action review. Select actual
cases from checkbox menus instead of typing comma-separated strings. Review
missing inputs, self-weight mapping and action applicability. Statutory factors
remain read-only: use Clone selected as Custom to alter them. Custom formulas
are user-defined and do not establish design-code compliance.

## Update and verification

Save and close IngeTrazo, then run `./install.ps1 -SkipDependencies` from the
existing project when the installed PyNite 3.2.0 runtime is present. Restart the
extension to load the copied source. This patch has not rebuilt the distributed
Setup executable. See [actual test evidence](TEST_RESULTS_LOAD_FORMS.md).
