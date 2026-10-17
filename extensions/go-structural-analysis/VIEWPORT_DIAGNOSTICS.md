# Viewport and Model Check update (v0.2.4)

## Changes

- Batch 2D/3D world-to-screen projection; cache world geometry and reuse pixel objects. Every camera frame projects fresh positions. Batch viewport member picking.
- Merge same-sign filled diagram strips while preserving zeros and force jumps; reduce repeated painter calls.
- A single compatibility canvas paints visible overlays. Poll camera changes at 16 ms; stop idle repaints. Cache unchanged result-summary text and avoid rebuilding unchanged quick-control lists.
- Self-weight uses blue member highlights; ordinary loads retain their arrows. Load analysis and full-precision results are unchanged.
- Model / Stability Check lists duplicate/near nodes, duplicate members and partial overlaps, connectivity/joint warnings, and rigid-body restraint deficiencies. Selecting an issue highlights the corresponding existing node/member. Run Analysis performs the solver's additional active stiffness check in the background.

## Install / update

Close IngeTrazo and run `powershell -ExecutionPolicy Bypass -File install.ps1 -SkipDependencies` in the existing project if the PyNiteFEA 3.2.0 worker is already installed. Restart IngeTrazo, open Extensions → GO Structural Analysis v0.2.4, then Model → Check Model / Stability… . No project migration or solver environment change is required.

Backups: `backups/viewport-diagnostics-before-20261010`. This update changes the user plugin only. The previously built installer has not been rebuilt for this patch.

Tolerance is in metres; 0.001 m = 1 mm. Review crossing/unsplit-joint warnings against the intended physical connections. The checker does not auto-merge or delete geometry. A clean precheck does not prove stiffness stability; run analysis. Linear stiffness checks do not constitute a buckling/capacity/code-compliance calculation.

See `TEST_RESULTS_VIEWPORT.md` and `artifacts/viewport-performance/test-results.json` for actual measurements, executed tests and limitations.
