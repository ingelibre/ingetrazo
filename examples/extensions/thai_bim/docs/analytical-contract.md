# Thai BIM analytical geometry contract v1

`schema: "thai-bim-analytical/1"`. Generated geometry snapshot, not a structural-analysis input deck.
Stored as a separate `scene.plugin_data["thai_bim_analytical"]` record in IGZ and exported as UTF-8 JSON.
The current validator reconstructs and compares the graph; hand-edited snapshots are rejected.

| Field | Meaning |
| --- | --- |
| id, revision | Model UUID and saved-source generation revision. Retained ID across regeneration. |
| units | length m, force kN, mass tonne, stress kN/m2. UI inspection tolerance is mm. |
| source_digest | SHA256 of sorted canonical source records. A name/pose/identity/geometry/parameter change invalidates the snapshot. |
| sources | BIM business ID, native group UID, name/kind, box parameters in metres, rigid row-major 4x4 pose and local geometry hash. |
| nodes | Deterministic coordinate-derived ID and xyz_m in global coordinates, rounded to 1e-9 m. Moving nodes changes their IDs. |
| members | Source-linked stable member ID, physical centroid endpoints, right-handed local x/y/z axes and rectangular section. |
| elements | Frame element ID, owning member ID, node_i/node_j and fractional range along the original member axis. One BIM member may map to multiple elements. |
| components, issues | Connectivity groups and diagnostics. A free endpoint may be a legitimate support/free end, not necessarily a defect. |
| state, solver_ready | review_required and false; no solver readiness is inferred from a connected graph. |

Section width/depth are dimensions along local y/z respectively. A is m2; Iy/Iz are m4.
Beam centroid local x runs along stored box width; local y is stored box Y.
Column local x runs along stored box height; local y is stored box X.
Local z is x cross y. Axes are rotated through the validated rigid BIM pose.
Torsion, material_id, releases and offsets are null; no engineering values are inferred.
Materials, supports, load_cases and load_combinations are reserved empty arrays in v1.

Exact endpoint-to-axis contacts use a numerical 1e-8 m coincidence allowance and split
the target analytical member. The user inspection tolerance only reports near contacts;
it never welds nodes or introduces rigid offsets. Interior-to-interior crossings remain
unconnected and are reported. Parallel overlaps/duplicate axes remain separate elements.
All these assumptions require engineering review before a future solver run.

## Boundary for a separate analysis plugin

The analysis plugin consumes a versioned geometry snapshot, validates the supported schema,
and supplies its own explicit analysis-input record referencing snapshot id/revision/source_digest.
Do not modify Thai BIM physical meshes or assume the empty reserved arrays are complete inputs.
Future editable analytical inputs require a new compatible contract/API version with explicit validation.
Store results against the exact immutable geometry and input hashes used by the solver; a source
change makes those results stale. Loads/supports must be remapped/reviewed when node IDs or topology change.
No solver, code-based design, slab shell mesh, foundation springs or automated axis adjustment is implemented.
The module has no Qt dependency, but uses the existing pure engine/placement helpers; JSON consumers
do not need to import the Thai BIM UI or read the physical meshes.

Source limit is 1000 frame members for the initial pairwise diagnostic implementation.
No whole-Family10 or large-frame performance benchmark is claimed.
