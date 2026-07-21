# SKP import backend seam

IngeTrazo aims to open **any** `.skp` (old → recent). This document describes
the single seam that decouples the app from *how* a `.skp` is read, so the
parser can evolve independently.

## Why a seam

There are two eras of the SketchUp format:

- **Legacy MFC binary** — SketchUp v8–v20 (~2010–2020).
- **VFF / ZIP container** — v2021+ (a ZIP whose entries start with `PK\x03\x04`).

No single free parser covers the whole range yet. The Blender importer covers
everything only because it uses Trimble's proprietary `SketchUpAPI.dll`. Our
strategy is to migrate to a **pure-Python parser** (offline, Linux-native, no
Wine, no proprietary DLL) while keeping the DLL path as a full-coverage
fallback for versions the pure parser can't read yet.

## The seam — `formats/skp.py`

A small registry of **backends**, tried in order. Each backend implements:

- `available() -> bool` — is its parser importable/wired?
- `supports(fmt) -> bool` — can it read this container format?
- `load(scene, path, progress=None)` — parse into the `Scene`.

Public API:

- `detect_format(path) -> "vff" | "legacy" | "unknown"` — from the first bytes,
  no parser required.
- `can_handle(path) -> bool` — a pure backend can read it directly.
- `load_skp(scene, path, progress=None) -> str` — loads with the first
  supporting backend and returns its name, or raises `NeedsConverter`.
- `NeedsConverter` — signal that no pure backend can read this file; the caller
  runs the external skp2dae converter.
- `backends_status() -> list[(name, available)]` — diagnostics.

### Cascade in the UI

`views/main_window.py::import_skp_path` checks `can_handle(skp)` first:

1. **Pure backend** → import through history (`SnapshotImport`), no Wine.
2. Else → **skp2dae** converter (Trimble `SketchUpAPI.dll` via Wine, a separate
   process — the DLL never enters GPL IngeTrazo). Its dialog/subprocess flow
   stays in `main_window`, not in this module.

Today no pure backend is wired, so every file cascades to the converter —
behaviour identical to before the seam existed.

## Wiring OpenSKP (or a fork)

Preferred pure backend: **OpenSKP** (https://github.com/iamahsanmehmood/openskp,
MIT) or a maintained downstream fork. Because it is MIT, IngeTrazo's ability to
ship it never depends on upstream merging our contributions — we vendor a
pinned fork behind this seam and stay decoupled (see
`docs/openskp-collaboration.md`).

To activate the backend:

1. Vendor the parser (git submodule / vendored copy / pinned PyPI dependency),
   keeping its MIT license notice.
2. Implement `_OpenSkpBackend.load()` — adapt an OpenSKP model to the `Scene`:
   meshes → `Group`s (reference geometry), materials → `Face.attrs`
   (`color` / `texture`), component instances → shared prototypes
   (`Group.xform`). Mirror `formats/dae.py`'s reference-import path.
3. Widen `_OpenSkpBackend.supports()` as version coverage grows
   (`"vff"` today; add `"legacy"` when the MFC decoder lands).
4. Flip `_OpenSkpBackend._WIRED = True`.

Keep skp2dae as the fallback until the pure backend matches its coverage.
