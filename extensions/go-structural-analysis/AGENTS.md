# GO Structural Analysis — continuation instructions

Work in the existing project. Do not replace it with a new project or modify
IngeTrazo Core in Program Files. Preserve 2D/3D behavior, kN–m, full precision,
PyNiteFEA 3.2.0 worker and result-safety rules. Back up source/model before changes.

For UI/workflow tasks using Prota as reference:
1. Read `docs/PROTA_REFERENCE.md` and the requested task in `docs/UI_BACKLOG.md`.
2. Read its file under `docs/tasks/` if present. Inspect the stated PDF pages before
   implementing; do not assume all chapters have already been reviewed.
3. Use Prota as workflow reference; implement GO's own UI and existing commands.
   Use the current Thai Code Pack for statutory combinations. The training guide
   is not authority for Thai factors, design compliance or solver validation.
4. Scope a continuation to one topic/task ID. Preserve other uncommitted work.
5. Add meaningful tests, run relevant Qt/primary regression and use IngeTrazo MCP
   for live checks. Record Passed, Failed, Not Tested separately. A temporary live
   component test is not a cold plugin-load test.
6. Update task/backlog evidence and changed files. Never mark the whole reference
   chapter complete merely because part of its UI is implemented.

Source PDF: `docs/reference/prota2022/protastructure-2022-basic-training-guide.pdf`.
Metadata and download URL: `docs/reference/prota2022/source.json`. The PDF is local
reference material, ignored by Git and excluded from the installer. If absent,
download the URL and verify SHA-256 against metadata before using it.

Validation: `.venv/Scripts/python.exe -m pytest tests -q` for primary checks.
Use `.qa-venv/Scripts/python.exe -m pytest tests/test_qt_*.py -q` with explicit
file expansion appropriate to the shell; host adapter source is
`../ingetrazo-api-reference`. Install using `./install.ps1 -SkipDependencies` when
the worker already exists. Restart for final source loading; never claim restart
QA when only hot-loaded components were checked.

Primary source: `C:/Users/g_np2/Projects/go-structural-analysis` (not a Git checkout).
Git checkout: `C:/Users/g_np2/Projects/ingetrazo`; extension mirror:
`C:/Users/g_np2/Projects/ingetrazo/extensions/go-structural-analysis`.
Check the active directory before Git operations. Back up and check before copying
changes; do not overwrite independent mirror edits. Commit/push only when requested.
