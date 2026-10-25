# Sheet browser — plan

> A **Sheets** tab beside the main window's **Browser** tab, with two panels
> stacked: the **Scenes** panel on top (the same one as in Properties) and a
> new **sheet explorer** with nested folders below. The sheet composer shows
> the very same two panels, so both windows look alike. Same widgets, same
> data. Branch: `feature/sheet-browser`.

## Where we start

- A sheet is a `Composicion` in `scene.compositions`. That list's order drives
  the sheet tabs, the PDF atlas and `{hoja}` page numbering.
- The composer has one combined panel, «Views and sheets» (`SheetsPanel` in
  `views/outliner.py`): saved scenes plus a flat list of sheets, with new
  sheet, rename, move up/down, duplicate, delete and Export PDF. It has no
  folders and no print flag.
- The Properties tray has a **Scenes** panel (`ScenesPanel` in
  `views/tray.py`): a list of saved scenes, double-click shows one, buttons
  + Scene · Update · −. No drag & drop, no previews.
- Printing: the composer previews/prints one sheet at a time, and exports all
  sheets to one PDF (`export_all_pdf`). There is no "print all".
- The proof of concept on `feature/sheets-tree-view` added `folder_id` /
  `position` to the sheet and folders based on `SceneFolder`. `SceneFolder` is
  not on `main`, and that branch carries 12 unrelated commits, so its ideas are
  reused, not its code.

## 1. Data model

`core/composition.py`, `core/scene.py`

- New `SheetFolder`: `id`, `name`, `parent_id` (`None` = top level),
  `expanded`. Stored in a new list `scene.sheet_folders`. Nesting is unlimited.
- Two new fields on each sheet:
  - `folder_id`: `None` = top level.
  - `print_in_all`: included in Print all / Export all; default `True`.
- **Order:** `scene.compositions` stays the single sheet order. After every
  move it is re-sorted to match the tree from top to bottom, so the sheet tabs,
  the PDF and `{hoja}` numbering always follow what the browser shows.
- **Saving (.igz):** folders and the two fields are written only when they
  differ from the default. Old files open unchanged; files without folders
  save exactly as before. Details in the next section.

### Saving and loading

Every place a document's sheets are written, read or reset has to carry the
folders too:

| Where | Code | What changes |
|---|---|---|
| Save | `formats/igz.py`, `save` payload | a new key `sheet_folders` (list of `{id, name, parent_id, expanded}`), written only when there are folders. Each sheet's `to_dict` adds `folder_id` (only when inside a folder) and `print_in_all` (only when `False`). |
| Open | `formats/igz.py`, load | reads `sheet_folders` (missing → no folders), and `Composicion.from_dict` reads the two fields (missing → top level, printed). |
| New document / reset | `Scene.clear()` and the "is the document empty" check in `core/scene.py` | folders are cleared with the sheets and count as content. |
| Autosave and crash recovery | `core/autosave.py` | goes through the same `.igz` save/load, so nothing extra — covered by a test. |
| Import into an open document | `SnapshotImport` in `core/history.py` | no importer brings another file's sheets today; this command's guard (what it adds is undone, a failed import leaves nothing behind) now covers folders as it covers sheets. |
| Older IngeTrazo opening a newer file | — | it ignores the unknown key and fields: the sheets open, flat and all printed. Nothing is lost on its side, but saving there drops the folders. |

**Repairs on load, so a damaged or hand-edited file still opens:**

- a sheet whose folder does not exist → top level;
- a folder whose parent does not exist, or that sits inside itself (a cycle)
  → top level;
- two folders with the same id → the second gets a new id;
- the sheet order is re-sorted to the tree, so tabs and numbering match what
  the browser shows.

## 2. Undoable commands

`core/history.py` — each is one undo step:

| Command | What it does |
|---|---|
| `AddSheetFolderCommand` | a new folder, inside a folder or at the top |
| `RenameSheetFolderCommand` | renames a folder |
| `DeleteSheetFoldersCommand` | removes folders; their sheets and subfolders move **one level up** |
| `MoveSheetItemsCommand` | sheets and/or folders into a folder, at a position |
| `SetSheetPrintCommand` | the Print flag, for one or several sheets |

New and deleted sheets reuse the existing paths (`AddSheetCommand`, the
composer's `delete_sheet`, which asks first and keeps at least one sheet).

## 3. The sheet explorer: `SheetExplorer`

New file `views/sheet_browser.py`. One widget class, built once per window
over the same data. Either one updates when the other changes something.

**Tree:** folders and sheets only. A sheet's view frames are not listed under
it (a sheet can hold many).

**Columns:**

| Name | 🖨 Print |
|---|---|
| folder or sheet name | checkbox: in Print all / Export all |

**Buttons:** + Sheet · + Folder · Delete · Print all… · Export all (PDF)…

- New sheets and folders go into the selected folder.
- Print all and Export all take only the sheets with Print ticked, in tree
  order.

**Mouse:**

- Double-click a sheet: opens it in the composer.
- Single click: selects.
- Drag & drop: sheets and folders move between folders, or between rows to
  reorder. A folder cannot be dropped into itself or into a folder inside it.
- A scene dragged onto a sheet (from the Scenes panel above it) is placed on
  it, as today.

**Keys:** Delete removes · F2 renames · Space toggles Print · Alt+↑/↓ moves.

**Right-click menu:** Open · Rename · Duplicate · Delete · New folder here ·
Include in / Exclude from Print all · Print… · Export PDF… · Place a scene
here.

## 4. The Scenes panel, shared

The existing `ScenesPanel` (Properties tray) is used as is in every place
scenes appear — Properties, the new Sheets tab, the composer — instead of a
second scene list. It gains what the sheets need:

- **Drag & drop:** a scene can be dragged out of the list, onto a sheet in
  the sheet explorer or onto the composer's page.
- **Double-click in the composer** places the scene on the open sheet (as
  today's composer panel does); everywhere else it shows the scene, as now.
- **All copies stay in sync:** a scene added, renamed or deleted in one copy
  shows in the others at once (today only the one copy is refreshed).

## 5. Where it appears

**Main window:** a new dock tab **Sheets**, beside the **Browser** tab (the
model browser stays as it is). It holds two panels, one above the other,
split by a draggable divider:

```
┌ Browser │ Sheets ┐
│ Scenes            │   ← ScenesPanel, same as in Properties
│  ▸ Plan           │
│  ▸ Front          │
│  [+ Scene] [Update] [−]
├───────────────────┤   ← divider, drag to resize
│ Sheets            │   ← SheetExplorer
│  ▾ 📁 Ground floor │
│     ☑ A101 Plan   │
│  ▸ 📁 Details      │
│  [+ Sheet] [+ Folder] [Delete] [Print all…] [Export all…]
└───────────────────┘
```

**Sheet composer:** the combined «Views and sheets» panel is replaced by the
same two panels, Scenes on top and Sheets below, so the composer looks like
the main window's Sheets tab. The only difference: the sheet open in the
composer is highlighted in the sheet explorer.

The old combined `SheetsPanel` is removed. Each of its features lands in one
of the two panels, and its tests move with them.

**Built for the later layout rework.** You want every panel to become movable
between tabs later, so each user can build their own layout. To keep that
open, this work follows three rules:

- each panel (`ScenesPanel`, `SheetExplorer`) is a self-contained widget that
  needs only the main window, never the tab or dock it sits in;
- panels talk to each other only through the document (the scene model),
  never directly — the drag of a scene onto a sheet travels as drag data;
- the Sheets tab is a thin container that just stacks its panels, so a
  layout system can later take them out and put them elsewhere.

The rework itself (moving panels between tabs, saving each user's layout) is
**not** part of this branch.

## 6. Print all and Export all

`views/composer.py`

- **Print all:** a new `print_sheets(sheets)` shows the printer dialog once,
  then prints each sheet as its own page at that sheet's paper size and
  orientation. Without Qt's print module, the existing message appears and
  offers Export PDF for the same sheets.
- **Export all:** `export_all_pdf` takes the same set — sheets with Print
  ticked, in tree order. The composer's existing «Export all sheets (PDF)»
  menu entry changes with it, so every button and menu agrees.
- Both are reachable from the main window and from the composer.

## 7. Translations

Every new string goes into all 9 catalogs (`i18n/*.json`, `en.json` stays the
identity map). Existing strings are reused wherever they fit: «Delete»,
«Rename…», «Export PDF…», «New sheet».

## 8. Tests

**Model and commands**

- folders, flags and the order sync
- `.igz` round trip: nested folders, sheets in them, Print flags, expanded
  state — all back after save and open
- an old file without folders opens flat, all sheets printed; a document
  without folders saves byte-for-byte as before
- the repairs: missing folder, missing parent, a cycle, duplicate ids
- New document clears the folders
- autosave/recovery brings the folders back
- importing a file with folders into a document that has its own: no id
  clash, undo removes what came in
- undo/redo of every command
- deleting a folder moves its contents one level up

**Shared panel**

- the same tree in the main window and in the composer
- a change in one shows in the other
- drag & drop moves sheets and folders and reorders the sheet tabs
- no folder into itself or its subfolders
- the Print checkbox toggles, with undo
- + Sheet and + Folder land in the selected folder
- double-click opens the sheet
- Delete removes it

**Scenes panel and the Sheets tab**

- the main window has a Sheets tab beside Browser, with Scenes above and
  Sheets below
- the composer shows the same two panels
- a scene dragged from the Scenes panel onto a sheet is placed on it
- double-click in the composer's Scenes panel places the scene on the open
  sheet; in the main window it shows the scene
- a scene added or renamed in one Scenes panel shows in all the others

**Print all / Export all**

- only flagged sheets, in tree order, each at its own paper size — checked
  through a PDF, so no real printer is needed

Then the full fast suite (`python -m pytest -m "not slow"`), commit, push.

## Decided: scene previews

Every Scenes panel shows a small picture of each scene — in the main
window's Sheets tab, in the composer and in Properties alike, since they are
one and the same panel. The pictures are rendered in the background, one at
a time, as today's composer panel already does, and rendered again when a
scene changes.

## Implementation steps

Each step ends with a commit pushed to `feature/sheet-browser`, its tests
passing. You can pull and try the branch after any step.

### Step 1 — Data model, saving, commands (nothing visible yet)

- `SheetFolder`, `scene.sheet_folders`, the two new sheet fields
  (section 1).
- Saving and loading with the repairs (section «Saving and loading»).
- The undoable commands (section 2).
- Tests: model, commands, `.igz` round trip, old files, repairs.

### Step 2 — The UI skeleton ★ checkpoint for you

What you see after this step:

- the **Sheets** tab beside **Browser** in the main window, Scenes above,
  Sheets below, with the divider;
- the same two panels in the composer, replacing «Views and sheets»;
- the sheet explorer tree with folders and sheets, the **Name** and
  **🖨 Print** columns;
- the buttons: **+ Sheet**, **+ Folder**, **Delete** and the Print
  checkbox already work (with undo); **Print all…** and **Export all…** are
  in place but still use today's behaviour (all sheets);
- double-click a sheet opens it.

Not yet: drag & drop, the right-click menu, keys, scene previews.

**Here I stop and wait for your feedback** on the layout, the wording and
how it feels. Changes to the look are cheap at this point; what follows
builds on it.

### Step 3 — Working with the tree

- drag & drop of sheets and folders (into folders, reordering, no folder into
  itself), with the sheet tabs following the new order;
- rename (F2), Delete key, Space for Print, Alt+↑/↓;
- the right-click menu (section 3);
- the main window and the composer stay in sync.

### Step 4 — The shared Scenes panel

- dragging a scene onto a sheet in the explorer, or onto the composer's
  page;
- double-click in the composer places the scene on the open sheet;
- all copies of the panel in sync;
- scene previews in every copy.

### Step 5 — Print all and Export all

- `print_sheets` for the printer, one page per sheet at its own paper size;
- Export all takes the same set: ticked sheets, in tree order;
- both from the main window and from the composer, and the composer's
  existing menu entry follows.

### Step 6 — Clean-up and full check ★ second checkpoint

- the old combined `SheetsPanel` removed, its tests moved;
- all new strings in the 9 catalogs;
- the full fast suite;
- a last look from you before the branch goes to a pull request.

## Later: sheet previews

Not part of this branch, but the design leaves room for it: a small
picture of each sheet's page in the sheet explorer, as the scenes have.

- **How:** the composer already paints a sheet for PDF export
  (`_paint_sheet` in mm space). The preview paints the same thing into a
  small image instead — at low resolution, with view frames as simple
  placeholders first, so it stays fast — rendered in the background, one at
  a time, like the scene previews.
- **When it is redrawn:** when the sheet changes (a fingerprint of its
  items, as the composer panel uses today), not on every refresh.
- **Where it shows:** as the row's icon, or larger as a tooltip when the
  pointer rests on the row — to be decided when we get there.
