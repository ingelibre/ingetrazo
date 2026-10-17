# Installer QA — GO Structural Analysis v0.2.3

Executed on Windows on 2026-10-09T15:58:40.5754875+07:00. This report applies to
`GO-Structural-Analysis-v0.2.3-Windows-x64-Setup.exe` with SHA256 `d51dcf3b6f1e307e158c7f1f105dd4cb3e45d19d9b30bcd63c6b7de63f5787e6`.

| Executed check group | Passed | Failed |
|---|---:|---:|
| Real Setup install/reinstall/backup/uninstall lifecycle | 14 | 0 |
| Bundled isolated runtime: 21 legacy + 12 3D examples | 33 | 0 |

Setup was executed silently in isolated directories, including a Thai-language
runtime path. The worker's expected unstable-structure cases were rejected.
Reinstall made a plugin backup; uninstall preserved the test model and unrelated
file. Default installation was blocked while IngeTrazo was running. The installed
live user plugin remained unchanged. All 18 packaged Python sources match the
final development source.

The earlier Unicode stderr-reader error was corrected and did not occur in this
final run. Lifecycle evidence is in `artifacts/v0.2/installer-test-results.json`;
raw Setup logs remain in `artifacts\installer\test-20261009-155518`.

Not Tested: clean Windows VM without Python, interactive wizard clicks, cold host
restart after installing with Setup (source installation cold restarts were tested
separately), Windows code signing/SmartScreen reputation. This executable is unsigned.

Save the document and close IngeTrazo before installing. Setup includes the offline
Python/PyNite runtime; IngeTrazo with Extension API v2 must be installed separately.
