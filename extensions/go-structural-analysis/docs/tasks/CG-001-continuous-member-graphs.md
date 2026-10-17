# CG-001 — Continuous collinear beam plots

User-requested follow-up to LC-002, 11 October 2026. Source/model backed up in
`backups/continuous-graphs-before-20261011/`. Existing single-member view retained.

## Implemented

- One horizontal graph for a connected collinear beam, cumulative station s,
  common ordinate scale, member/Node boundary labels and total length.
- Common frame from the original context-selected member's local i→j basis.
  Reverse cut direction and section rotation are accounted for. 3D moment vector
  transformation accounts for adapter storage `(T, -My, Mz)` before projection.
- Displacements project without the section-cut sign reversal; D is invariant.
- Extrema from derivative roots of the projected polynomials (D from squared
  displacement magnitude), including both sides of each segment boundary.
- Physical jumps retained; no artificial smoothing across point loads, nodal
  moments or member boundaries. One consistent positive/negative fill palette.
- Click station to select member/x/L. Joint left/right selection uses cumulative
  direction, reversing local-side inspection for reversed members.
- Horizontal scroll for long groups. No changes to model, solver values or units.
- Overlapping/branched sequences rejected with a Check Model message.
- Current/Stale gates, single-member diagrams, case selection retained.

## Verification

8 primary tests: unsplit vs split 2D/3D results, reversed member, section rotation
37°, all force/deflection components and exact extrema, point-load shear jump
and bending continuity, overlap rejection. Comparison rel 1e-7 / abs 1e-9.
3 Qt tests: one plot, total length, QTest station click, joint sides, reversed
selection, all components, stale invalidation and horizontal scroll with 6 spans.
Real MCP: original M2/M10 4+4 m beam, total 8 m, station 6 m → M10 x=2 m,
joint left/right, single-member mode and all seven 3D plots. Original preserved.

See TEST_RESULTS_CONTINUOUS_GRAPHS.md, artifacts/continuous-graphs/pytest.xml
and test-results-continuous-graphs.json for final counts and real PNG captures.
Cold Restart, physical mouse and clean VM remain Not Tested; hot reloaded
installed components are not a full plugin restart test. No Setup rebuilt.
