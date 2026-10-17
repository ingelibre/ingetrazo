# Windows trial installer

Builds a per-user offline Setup.exe for Windows 10/11 x64. IngeTrazo Plugin API v2
must be installed separately. No admin, host-file changes, system Python or PATH changes.

The payload contains the tested standalone CPython 3.12.14 distribution, exact
installed versions of PyNiteFEA 3.2.0 dependencies, plugin source, GPL licence,
corresponding source/build scripts, trial guide and evidence/example gallery.
Dependency distribution licences remain inside their `.dist-info` directories.
Each build uses a new staging directory and records payload SHA256 and versions.

Build from this existing project, using an installed Inno Setup 6 compiler:

```powershell
python packaging/build_installer.py --runtime "PATH-TO-STANDALONE-PYTHON-3.12" --site-packages "PATH-TO-TESTED-SOLVER-ENV/Lib/site-packages"
powershell -NoProfile -ExecutionPolicy Bypass -File packaging/test_installer.ps1
```

`--iscc` optionally selects the compiler. The builder does not modify either
input environment. It vendors installed dependencies rather than downloading at install time.
Output: `dist/GO-Structural-Analysis-v0.2.4-Windows-x64-Setup.exe` plus SHA256/manifest.
The payload keeps all 21 2D examples and adds 12 3D examples. Solver healthcheck
executes both schemas. See `TEST_RESULTS_v0.2.md` for current extension QA;
`INSTALLER_TEST_RESULTS.md` records the original v0.1.3 installer checks.

Default install: `%LOCALAPPDATA%/GO Structural Analysis/installed`.
Plugin: `%APPDATA%/ingetrazo/plugins/go_structural_analysis`.
Backup: `%LOCALAPPDATA%/GO Structural Analysis/plugin-backups/<timestamp>`.
The helper checks the actual bundled worker before copying files to the plugin folder.
Uninstall removes only its manifest-listed plugin files if worker_config still
points at this installation. Files saved by users and backups stay in place.

Automated tests use `/DIR` and `/PluginDir` to install under a separate test folder.
They verify 21 examples through the installed worker, backup, reinstall, blocked
installation while the real host is running, uninstall and original-plugin hashes.
This is not a substitute for a clean-machine/interactive-wizard test. See
`INSTALLER_TEST_RESULTS.md` for actual results and remaining checks.
