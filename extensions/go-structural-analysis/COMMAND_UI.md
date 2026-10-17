# Command search and analytical context menus

## How to use

- Press **Ctrl+K** while working in the IngeTrazo window, or use **ค้นหา** in the
  Ribbon header. Search by English/Thai title, command group or keywords such as
  `node coordinate`, `combination`, `ตรวจ`, `CSV`. Enter/double-click executes the
  selected command. Unavailable commands remain visible with an explanation.
- Use the **Model Tree search** to filter nodes/members by ID, coordinates, member
  type or connectivity text. Multiple terms must all match. Clear to show all;
  the filter is retained during model refresh and never changes engineering inputs.
- Right-click a Model Tree item or analytical Node/Member in the viewport.
  Properties opens the existing editor at the selected object. Member menus open
  its Result Inspector; node menus do not offer member-only results.
- Delete requires a confirmation preview listing affected members, orphan nodes
  and loads. It delegates to the existing deletion/history workflow. Cancel keeps
  inputs intact. A menu action retains the object originally clicked and rejects
  an object removed while the menu was open.

## Shared command rules

`command_ui.py` supplies a single registry for Ribbon, search and context menus.
Unavailable model/selection commands explain the required input. Editing, delete,
save and analysis commands are blocked while the worker is running or finishing.
Current CSV/report exports require Current results and recheck at execution.
Display/panel controls remain available during analysis. Search/menu availability
updates when model, selection, result or worker state changes.

Schema, solver equations, kN–m units and full precision are unchanged. The registry
delegates to existing forms and worker. It does not introduce an independent model
store. The new forms/menu/search use the extension palette.

## Install / remaining work

Save work and restart IngeTrazo after running `./install.ps1 -SkipDependencies`.
This is a v0.2.4 source patch; the packaged Setup executable has not been rebuilt.
See [actual evidence](TEST_RESULTS_COMMAND_UI.md).

Configurable shortcuts/quick access, a full Project menu, standalone property
forms with units/previews, storeys/grids and named views remain separate roadmap
increments. Physical right-click/orbit behavior and shortcut conflicts need live
mouse/keyboard review after a cold restart.
