# Sheet browser — plan

> The sheet composer's **Sheets** page: the scenes as a plain list on top,
> to drag onto sheets, and a **sheet explorer** with nested folders below.
> Branch: `feature/sheet-browser`.
>
> First built as a tab in the main window as well; after the first review
> the sheets live **only in the composer** (section 5).

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

`core/composition.py`, `core/scene.py`, `core/sheet_folders.py`

- New `SheetFolder`: `id`, `name`, `parent_id` (`None` = top level),
  `expanded`. Stored in a new list `scene.sheet_folders`. Nesting is unlimited.
- Two new fields on each sheet:
  - `folder_id`: `None` = top level (a folder the document does not have
    counts as the top too, so a sheet never drops out of sight).
  - `print_in_all`: included in Print all / Export all; default `True`.
- A folder has its own `print_in_all` too (default `True`): a sheet prints
  when its own switch and every folder around it are on.
- **Order:** `scene.compositions` stays the single sheet order. After every
  move it is re-sorted to match the tree from top to bottom — in each folder
  its subfolders first, then its own sheets — so the sheet tabs, the PDF and
  `{hoja}` numbering always follow what the explorer shows.
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
  the explorer shows.

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

**Undo never adds or removes a sheet.** The composer makes and deletes
sheets outside this undo (the «+» tab, Delete sheet). Undoing a tree change
puts back folders, each sheet's folder, its Print flag and the order — for
the sheets that exist now. (Found in review: undoing a folder brought back
a sheet deleted in the composer and dropped one made there, while the
composer still showed it.)

## 3. The sheet explorer: `SheetExplorer`

`views/sheet_browser.py`.

**Tree:** folders, sheets, and under each sheet the scenes placed on it
(with their scale; a scene the model lost is flagged with a warning).

**Columns:**

| Name | 🖨 |
|---|---|
| folder, sheet or scene | printer: in Print all / Export all. Click to switch. A folder has its own switch, on by default and saved with the document; what is moved in or out never changes it. A folder switched off leaves out everything inside it — the sheets keep their own switches, shown faded meanwhile (as the Browser shows what a hidden group hides), and come back when it is on again |

**Bar:** a filter field (like the Browser's) and small icon buttons with
tips: new sheet · new folder · rename · delete · print all · export all
(PDF).

- New sheets and folders go into the selected folder.
- Print all and Export all take only the marked sheets, in tree order.
- The filter keeps matching rows, their folders open to show them, and all
  of a matching folder or sheet.

**Mouse:**

- Double-click a sheet (or a scene on it): opens it in the composer.
- Drag & drop: sheets and folders move into folders (drop on one), or
  between rows to reorder (drop above/below). A folder never goes into
  itself or a folder inside it. Dropped on a scene row, it means that row's
  sheet; on empty space, the top.
- A scene dragged from the list above: dropped on a sheet (or a scene row),
  it is placed on that sheet in a free spot; on a folder or empty space, it
  goes on a new sheet named after it, in that folder.

**Keys:** Delete removes · F2 renames · Space switches Print · Alt+↑/↓
moves among the neighbours.

**Right-click menu:**

- on a sheet: Open · Rename · Duplicate · Delete · Place a scene here ·
  Include in / Exclude from Print all · Print… · Export PDF… · Move up /
  down · New sheet here · New folder here;
- on a folder: Rename · Delete folder · Include / Exclude all · Print… ·
  Export PDF… · New sheet here · New folder here;
- on empty space: New sheet · New folder · Print all… · Export all (PDF)….

## 4. The scenes list above

The existing `ScenesPanel` in a **compact** form: just the list of scenes,
to drag them onto sheets — no hint, no buttons, no renaming or deleting
(scenes are made and changed in the main window's Scenes panel, which stays
as it is).

- **Drag:** scenes drag out by name, onto a sheet in the explorer or onto
  the composer's page.
- **Double-click** places the scene on the open sheet.
- **Pictures:** each scene shows a small preview (the composer's scene
  render), drawn one at a time while the list is on screen.
- **Room for 7 scenes**; more scroll.
- A scene and the views that show it **mark each other**: select a scene,
  its views on the sheets light up; select a view, its scene does.

## 5. Where it appears

**Only in the sheet composer**, as its «Sheets» page (the old «Views and
sheets» page's place, so a side the user gave it is kept):

```
┌ Sheets ──────────────┐
│ Scenes               │   ← the compact scenes list, room for 7
│  ▸ Plan              │
│  ▸ Front             │
├──────────────────────┤   ← divider, drag to resize
│ Sheets  [filter] ⊕⊕✎🗑🖨⇩ │   ← SheetExplorer
│  ▾ 📁 Ground floor 🖨 │
│     ▾ A101 Plan   🖨 │
│         Plan · 1:100 │
│  ▸ 📁 Details      🖨 │
└──────────────────────┘
```

The old combined `SheetsPanel` is removed; each of its features lives on in
one of the two panels, and its tests moved with them.

**Built for the later layout rework.** You want every panel to become movable
between tabs later, so each user can build their own layout. To keep that
open, this work follows three rules:

- each panel (`ScenesPanel`, `SheetExplorer`) is a self-contained widget that
  needs only the main window, never the tab or dock it sits in;
- panels talk to each other only through the document and drag data — the
  drag of a scene onto a sheet travels as drag data; the Sheets page only
  wires the scene/view marking between its two panels;
- the Sheets page is a thin container that just stacks its panels, so a
  layout system can later take them out and put them elsewhere.

The rework itself (moving panels between tabs, saving each user's layout) is
**not** part of this branch.

## 6. Print all and Export all

`views/composer.py`

- **Print all:** `print_sheets(sheets)` shows the printer dialog once, then
  prints each sheet as its own page at that sheet's paper size and
  orientation. Without Qt's print module, a message points at Export all,
  which gives the same pages.
- **Export all:** the marked sheets, in tree order. The composer's own
  «Export all sheets (PDF)» menu entry takes the same set.
- The PDF export and the printer share one painting loop (`_paint_atlas`),
  so both give the same pages.

## 7. Translations

Every new string is in all 9 catalogs (`i18n/*.json`, `en.json` stays the
identity map); existing strings are reused wherever they fit.

Also on this branch: the texts a **new sheet item** starts with follow the
interface's language — the title block's labels (were fixed Spanish:
PROYECTO, LÁMINA…), the legend title, a label's text, the level mark, the
scale label and the default sheet name («Lámina 1»). What a document was
saved with stays as it is; filling the date, scale and sheet number finds
its row in any of the languages.

## 8. Tests

`tests/test_sheet_folders.py` — model and commands:

- folders, flags and the order sync; undo/redo of every command; deleting a
  folder moves its contents one level up;
- `.igz` round trip, old files, the repairs, New document, autosave;
- an import's guard covers folders.

`tests/test_sheet_browser.py` — the Sheets page:

- the sheets live only in the composer; the scenes are a plain list with
  room for 7;
- the tree: folders, sheets, their scenes, a lost scene flagged; printers,
  a folder's switching all inside it (and «some»); Space; the filter;
- renaming; opening; new sheet / folder in the selected folder; deleting
  folders (contents move up) and sheets;
- undo never brings back or drops a sheet the composer made or deleted;
- drag & drop of sheets and folders (into, above, below, never into itself),
  the sheet tabs following; Alt+↑/↓ with undo;
- scenes: the list drags them by name; dropped on a sheet, on a scene row,
  on a folder or on empty space; double-click places on the open sheet;
  «Place a scene here»; previews that leave the document untouched; a scene
  and its views marking each other; Create plan shows its scene;
- the right-click menus;
- Print all / Export all: only marked sheets, in tree order, each at its own
  paper size — checked through a PDF, so no real printer is needed; the
  composer's own Export all takes the same set.

`tests/test_sheet_item_texts_follow_the_language.py` — the default texts.

## Steps

| Step | What | State |
|---|---|---|
| 1 | Data model, saving, commands | done |
| 2 | The Sheets page (UI skeleton) ★ checkpoint | done, reviewed |
| — | Review: printers on folders, filter, icon bar, right-click menu, scenes under sheets; texts in the interface's language | done |
| — | Review: sheets only in the composer, scenes list compact with room for 7, the undo bug | done |
| 3 | Working with the tree: drag & drop, Alt+↑/↓ | done |
| 4 | The scenes list: drag onto sheets, double-click, previews, marking | done |
| 5 | Print all / Export all, the composer's menu entry | done |
| 6 | Old panel removed, its tests ported, full suite ★ checkpoint | done — your look next |

## Later: sheet previews

Not part of this branch, but the design leaves room for it: a small
picture of each sheet's page in the sheet explorer, as the scenes have.

- **How:** the composer already paints a sheet for PDF export
  (`_paint_sheet` in mm space). The preview paints the same thing into a
  small image instead — at low resolution, with view frames as simple
  placeholders first, so it stays fast — rendered in the background, one at
  a time, like the scene previews.
- **When it is redrawn:** when the sheet changes (a fingerprint of its
  items), not on every refresh.
- **Where it shows:** as the row's icon, or larger as a tooltip when the
  pointer rests on the row — to be decided when we get there.
