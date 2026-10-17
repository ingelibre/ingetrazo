# Install / update GO Structural Analysis v0.2.3

Continue using the same source directory and the existing isolated PyNiteFEA
3.2.0 worker. Do not modify the IngeTrazo core or files in Program Files.

1. Save your IngeTrazo document and structural workspace, then close the host.
2. Back up `go_structural_analysis`, your `.igz` files, and the user plugin at
   `%APPDATA%\ingetrazo\plugins\go_structural_analysis`.
3. From this project directory run:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -SkipDependencies
   ```

   Use `-SkipDependencies` only if the existing isolated solver runtime exists.
   For a new development install, omit this switch; the script installs the pinned
   requirements into `%LOCALAPPDATA%\GO Structural Analysis\solver-v0.1` (the
   existing runtime directory name is retained for compatibility).
4. Start IngeTrazo and open Extensions → GO Structural Analysis v0.2.3.
5. Open an existing 2D document or choose a 3D engineering example. Run Analysis.

Workspace parks the original scene. Return restores it. **Store analysis in current
document** explicitly copies analytical data to the original; it is not used by
installation or QA. Save As creates a new structural `.igz` and does not overwrite
the source document unless you choose the same path.

Light/Dark/System affects the extension's palette. System follows the host's
palette; no Windows theme setting is changed. 3D workspaces allow orbit, pan and
zoom. 2D workspaces keep their existing planar camera behavior.

See [examples and schema conventions](EXAMPLES_v0.2.md) and
[executed QA](TEST_RESULTS_v0.2.md). The offline Setup build scripts are under
`packaging/`; use the matching v0.2.3 package, not the older v0.1.3 installer.
