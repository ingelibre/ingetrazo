# v0.1 → v0.1.3: changed files

## Windows trial installer

- Added: `packaging/build_installer.py`, `packaging/setup.iss`, `packaging/install-helper.ps1`
- Added: `packaging/healthcheck.py`, `packaging/test_installer.ps1`, `packaging/test_installer_worker.py`
- Added: `packaging/START-HERE.txt`, `packaging/README.md`, `INSTALLER_TEST_RESULTS.md`
- Added: `artifacts/installer/test-results.json` and actual installer test logs
- Modified: `README.md` with the Setup installation workflow

## Extension

- Modified: `go_structural_analysis/__init__.py`
- Modified: `go_structural_analysis/client.py`
- Added: `go_structural_analysis/diagram_geometry.py`
- Added: `go_structural_analysis/examples.py`
- Added: `go_structural_analysis/inspector.py`
- Added: `go_structural_analysis/materials.py`
- Modified: `go_structural_analysis/model.py`
- Added: `go_structural_analysis/results.py`
- Added: `go_structural_analysis/solver_results.py`
- Modified: `go_structural_analysis/ui.py`
- Added: `go_structural_analysis/visualization.py`
- Modified: `go_structural_analysis/worker.py`
- Added: `tests/build_examples_gallery.py`
- Added: `tests/build_report_v013.py`
- Added: `tests/build_visual_fixtures.py`
- Added: `tests/live_audit_v013.py`
- Added: `tests/live_examples.py`
- Added: `tests/live_materials.py`
- Added: `tests/live_visuals.py`
- Added: `tests/package_v013.py`
- Added: `tests/reference_frame.py`
- Added: `tests/test_client_errors_v013.py`
- Added: `tests/test_diagram_geometry.py`
- Added: `tests/test_engineering_v013.py`
- Added: `tests/test_examples.py`
- Added: `tests/test_materials.py`
- Modified: `install.ps1`
- Modified: `README.md`
- Added: `TEST_RESULTS_v0.1.3.md`
- Added: `ROADMAP.md`
- Added: `EXAMPLES.md`

Generated evidence: `artifacts/v0.1.3/` (pytest XML, JSON, CSV, IGZ and PNG).
Original `tests/test_solver.py`, `requirements.txt`, icons, theme and `TEST_RESULTS.md` were retained.
