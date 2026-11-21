# Sheets combined — working plan

> Temporary note for the draft PR; folded into the final PR description and
> removed before the PR is marked ready.

One branch that brings together four open sheet / AI-bridge PRs, rebased on
current `main`, plus **Sheet sets** (#1519) on top.

| Part | From | What |
|---|---|---|
| Sheet browser | #932 | sheet explorer in the composer: folders, Print flag, drag & drop of scenes |
| Sheet index | #1501 (#1409) | a table of contents element listing the document's sheets |
| Headless mode | #1494 | IngeTrazo without a window for AI automation, MCP save/shutdown, plain-JSON `.igz` |
| Sheets over MCP | #1506 (#1505) | headless sheets API and MCP tools, render/export without the composer window |
| Sheet sets | #1519 | named, ordered subsets of sheets; print/export a set; `{page}`, `{total}`, the index count within the set; `{set}` field |

## Steps

- **M0** branch from `main`, draft PR
- **M1** #932 rebased onto `main`
- **M2** #1501 and #1494 added
- **M3** #1506 added + integration (index "by folder" reads the real folders, sheets API knows folders / Print flag, sheet tools headless)
- **M4** sheet sets: model, `.igz`, undo
- **M5** sheet sets: set-relative fields and index, export PDF / PNG / SVG, API and MCP
- **M6** UI design review (previews before any GUI code)
- **M7** sheet sets GUI, translations
- **M8** screenshots, final description

## Decisions

- A sheet set prints its members whose Print flag (and folders) are on;
  "All sheets" is what Print all prints today.
- Sets reference sheets by a new sheet `uid`, so renames and reordering
  keep them. Deleting a sheet removes it from every set; deleting a set
  never deletes sheets.
- No separate sets dialog: sets are created and assigned in the sheet's
  properties (details after the UI review).
- Export formats for a set: PDF (one file), PNG and SVG (one file per
  sheet). Whole-sheet DXF is a follow-up.
