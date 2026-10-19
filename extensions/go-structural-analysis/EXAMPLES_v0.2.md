# GO Structural Analysis v0.2.3 — 3D examples

Use Model → Engineering Examples / Benchmarks. Select one of the **3D** entries,
choose **Load selected example**, then **Run Analysis**. Results offers both base
cases and user combinations. All 21 existing 2D examples remain available.

You can also open the supplied `examples/v0.2/*.igz` documents with IngeTrazo.
They contain editable analytical data with no precomputed result. Run Analysis
after opening. Corresponding `.json` files document the complete schema.

| Example | Independent reference / expected behavior |
|---|---|
| `3d_cantilever` | Lateral bending in Y and Z: PL³/3EI |
| `3d_torsion` | Pure torsion: tip RX = TL/GJ; internal T = −applied tip MX |
| `3d_axial` | PL/EA; tension has negative diagram N |
| `3d_portal` | Space portal, vertical and lateral loads; independent 12-DOF direct-stiffness solver |
| `3d_truss` | Three inclined bars to a free apex; independent axial stiffness and joint equilibrium |
| `3d_multibay` | Two bays in X/Y; independent direct-stiffness solver |
| `3d_rotation` | Unequal Iy/Iz rotated 37°; transformed analytical bending flexibility |
| `3d_release` | Local RZ release at j end; end Mz = 0 |
| `3d_selfweight` | ON/OFF; reaction = weight density × A × L; wL⁴/8EI tip displacement |
| `3d_combo` | User-defined 1.4DL + 1.7LL and reversed combination; linear superposition/envelope |
| `3d_equilibrium` | Inclined/rotated member, partial varying local load; six global equilibrium components |
| `3d_unstable` | Pin-supported cantilever mechanism: analysis **must fail** |

## Directions, units and signs

- Global axes are XYZ, Z up. Forces/moments use uppercase FX/FY/FZ/MX/MY/MZ.
  Positive global rotations and applied/reaction moments use the right-hand rule.
- Local x runs i→j. Local y/z are right-handed; default y has a positive global Z
  component except for vertical members. For upward vertical members, local y = −X
  and local z = −Y. Positive section rotation follows the right-hand rule about x.
- Solver coordinates are a proper rotation `(X,Y,Z)_solver = (X,Z,−Y)_global`.
  There is no mirrored axis transformation. Displayed local axes match PyNite's
  actual transformation matrix, including section rotation.
- Local member loads use Fx/Fy/Fz/Mx/My/Mz. Node loads are global only.
- Diagram N is positive in compression. Vy/Vz/T/My/Mz retain PyNite's internal-cut
  conventions, distinct from nodal end forces. End forces are the element's forces
  acting at its i/j ends in local axes. In a +local-X axial tip-load cantilever,
  diagram N is negative while the j end force N is positive.
- For a positive local MX tip load, internal diagram T is negative, tip RX is
  positive. In each plane dMz/dx = −Vy and dMy/dx = −Vz between load jumps.
- Units: m, kN, kN·m, rad; E/G kN/m²; A m²; Iy/Iz/J m⁴. Spring stiffness is
  kN/m for translations and kN·m/rad for rotations. `rho` is **weight density**
  kN/m³. Optional JSON `mass_density` kg/m³ is converted by ×9.80665/1000;
  specifying both density forms is rejected.

## Self-weight and combinations

3D automatic self-weight belongs to exactly one chosen case, usually DL. It is
distributed on frames and lumped half to each truss end. Combination factors apply
once to that case. Explicit loads marked `source: self_weight` cannot coexist with
automatic self-weight. Unmarked external dead loads are not guessed or removed.
Legacy 2D documents retain their previous self-weight-in-every-case behavior.

Illustrative factors do **not** provide code compliance or member capacity checks.
Result Tables → Member Force Envelope reports min/max, x, side and governing
combination. Inspector → Combination envelope at x/L evaluates each combination
at the selected position. The viewport displays one case/combination at a time.

## Migration and geometry conversion

Existing schema 1 files still open and run in 2D. Selecting 3D opens a copy in the
editor for review before applying migration. The old screen-CCW MY convention is
converted to physical global −MY, and planar restraints are retained. Legacy
self-weight is materialized per original case to preserve its behavior.
Save the migrated model under a new filename to retain the original file.

Select straight edges in the original IngeTrazo document, then use **Preview
selected edges → analytical model**. Shared endpoints are merged; duplicates
are removed. Review support DOFs, materials, sections, releases and connectivity
in the editor before OK. Cancel leaves analytical data unchanged. Group/face/curve
centerlines and intersection splitting are not inferred automatically; create
explicit analytical nodes/member ends at intended joints.

PyNite reference: [member axes, releases, rotation and directions](https://pynite.readthedocs.io/en/latest/member.html).
