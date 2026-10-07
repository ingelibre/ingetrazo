# SKP import backend seam

> **2026-09-28.** IngeTrazo no longer runs, downloads or links to any
> proprietary .skp tooling: the former external converter and its automatic
> download are gone, the validation tests built on it are gone, and the `.skp`
> export is off because OpenSKP's writer builds on a blank template document
> that IngeTrazo no longer distributes. `.skp` files are read with OpenSKP
> only. Where the sections below say "the oracle", they mean the reference
> output the reader was validated against at the time.

IngeTrazo aims to open **any** `.skp` (old → recent). This document describes
the single seam that decouples the app from *how* a `.skp` is read.

## Backends

- **OpenSKP** (pure Python, MIT). IngeTrazo installs it from our
  [GWydouw/openskp fork](https://github.com/GWydouw/openskp), based on
  [iamahsanmehmood/openskp](https://github.com/iamahsanmehmood/openskp).
  `requirements.txt` and the Linux/Windows release workflows pin commit
  `291700bc213655a00461838de71e5f206311e619`, which is present in the fork.
  This switches repository ownership while preserving the validated parser
  version. Install with `python -m pip install -r requirements.txt`.
  The backend reports itself unavailable when the package cannot be imported.

## The seam — `formats/skp.py`

**Parse then apply.** A backend *parses* a file into a plain **payload** (world-
space face loops), touching no `Scene`. The heavy parse runs *outside* the undo
history; `apply_payload` then adds the geometry cheaply inside a command — so a
failed or empty parse never leaves a half-applied edit.

Public API:

- `detect_format(path) -> "skp" | "unknown"` — from the first bytes. Real `.skp`
  files (legacy MFC **and** 2021+) begin with the same UTF-16 format
  marker (or a `PK` ZIP wrapper), so the *era* is **not** observable from the
  magic bytes — and doesn't need to be, since OpenSKP handles the range.

## Legacy (pre-2021) MFC container — SUPPORTED (2026-07-22)

Classic `.skp` files (versions ≤2020; validated on real 2016/2017/2018
models) are ONE uncompressed MFC `CArchive` stream with a global 1-based
store map — no ZIP, no `model.dat`. Our fork adds
`openskp/legacy.py`: a full walker (materials + textures, layers,
half-edge kernel, definitions/instances/groups, face-camera flags, UV
matrices, dims/texts/guides/section planes) that emits the same
`full_parse()` dict, so `SkpFile.parse()` and the whole IngeTrazo seam
work unchanged. Validated: exact face/edge/area/bbox parity on five
user models against their VFF (2021+) re-saves; `skp_diff`
fingerprints identical through `apply_payload` (incl. materials and
textures). Key decoding notes (where real files differ from the public
2017 spec) are in the module docstring. Known gaps: files with fewer
than 2 materials can't bootstrap the slot base yet, legacy colorized materials untinted, CImage entities and doc
thumbnail skipped, positioned-texture UV parity unverified visually.
- `can_handle(path) -> bool` — a pure backend is available and recognises it
  (does not guarantee a non-empty parse).
- `parse_skp(path, progress=None) -> payload` — first backend that yields
  geometry; raises `NeedsConverter` on an unrecognised file, a parser error, or
  an empty parse.
- `apply_payload(scene, payload) -> backend_name` — add the payload as reference
  groups.
- `load_skp(scene, path)` — `apply_payload(parse_skp(...))`, for the diff harness.
- `NeedsConverter`, `backends_status()`.

Backends implement `available()`, `supports(fmt)`, `parse(path, progress)`.

### Cascade in the UI

`views/main_window.py::import_skp_path`:

1. If `can_handle(skp)` → `parse_skp` (outside history). Non-empty → apply
   through `SnapshotImport`.
2. Empty or `NeedsConverter` → the file is reported as unreadable, with the
   way around it (export COLLADA or OBJ from the program that made it). There is no
   converter behind it any more.

## The OpenSKP adapter — `formats/skp_openskp.py`

Isolated so `import openskp` is lazy. OpenSKP 0.2.0 model (by introspection):

- `SkpFile.open(path).parse()` → `SkpModel(definitions, materials, layers,
  version)`.
- `Definition(id, name, vertices{id→Vertex(x,y,z)}, edges{id→Edge(v1_id,v2_id)},
  faces{id→Face}, instances[Instance])`.
- `Face(loops, normal, material_id)`; each loop is `[(edge_id, sense), …]`,
  first = outer, rest = holes; `sense` 1 walks `v1→v2`.
- `Instance(matrix[13], ref_idx→def id, children)` — 3×3 row-major + translation.

The .skp format is **inches, Z-up** (same up axis as IngeTrazo) → scale ×0.0254, no
axis swap. The instance tree is flattened to world-space polygons (reference
geometry, one group). Enable/disable via `_OpenSkpBackend` in `formats/skp.py`.

## What works / what's missing (measured with `scripts/skp_diff.py`)

Validated against a reference oracle on real files (e.g. `demuna.skp`, a .skp
of the 2022 version):

- ✅ **Bounding box exact** — units, Z-up and instance transforms correct.
- ✅ **Geometry ~90–95% complete** — faces/vertices/triangles within ~5–9% of
  the oracle.
- ✅ **Materials / colours** — resolved. `Face.material_id` joins through
  `SkpModel.materials_by_id`, added by **our upstream PR**
  ([openskp#3](https://github.com/iamahsanmehmood/openskp/pull/3)).
- ✅ **Textures** — resolved. `Material.texture` (image bytes + tile size in
  inches), added by **our upstream PR**
  ([openskp#4](https://github.com/iamahsanmehmood/openskp/pull/4)). The adapter
  writes the images to the app's own cache —
  `<user data>/IngeTrazo/textures/skp/<stem>-<hash of path+size+mtime>/`,
  overridable with `$INGETRAZO_TEXTURE_CACHE`, emptied from
  *File ▸ Import ▸ Clear imported texture cache…* — so importing never creates
  a folder next to the user's `.skp` (it used to write `<stem>/` there, the
  usual COLLADA-export convention). Saving the document copies those
  images **into** the `.igz` container (`formats/igz.py`), which is what makes
  it portable; the cache is disposable and re-fills on open. It maps them with
  IngeTrazo's planar
  projection at the material's real tile size. Measured: **18/18 materials and
  2/2 textures — exact parity with the oracle**; those rows no longer appear
  in the diff.
  Until the PRs ship on PyPI, install from the integration branch:
  `pip install git+https://github.com/tuxiasumari/openskp@ingetrazo#subdirectory=packages/python`
  (branch `ingetrazo` = upstream `main` + both PR branches merged). With PyPI
  0.2.0 (no joins) faces import uncoloured.
- ✅ **"~5–9% skipped faces" — resolved: it was a measurement artefact, not
  lost geometry.** The raw DAE carries 4516 triangles = exactly what OpenSKP
  parses, and **total surface area matches to 0.00%** (327.268 vs 327.269 m²).
  The count deltas came from comparing a fused path (the DAE import runs
  coplanar fusion + weld + double-face dedupe) against raw .skp polygons.
  Two fixes landed: the harness fingerprint now carries **`area_m2`** (the
  fusion-invariant completeness metric — when areas agree, count deltas are
  labelled as post-processing); and `apply_payload` now runs the **same
  fusion pipeline as the DAE import** (`fuse_coplanar_loops` +
  `soften_smooth_edges`, hole-carrying faces added directly), so a `.skp`
  through the pure backend looks identical to one through the converter.
  After both: triangles Δ1.3%, vertices Δ0.7%, faces 262 vs 389 — the pure
  path fuses *better* (it starts from the file's original polygons, not
  reconstructed triangles). Perf: plaza Yanque (34 MB) parses in ~12 s pure
  Python — 97k faces, 42 273 m², 19 materials + 10 textures.
- ✅ **Grouping — resolved (with shared components).** The
  adapter now mirrors the DAE reference import: the root's loose faces become
  one group named after the file, each top-level instance becomes its own
  group carrying its .skp definition name, and a definition placed ≥2
  times above the DAE sharing thresholds becomes **one prototype** (extracted
  at any depth) with each copy an O(1) `Group.xform` instance. Measured:
  demuna → 3 groups, exact parity with the oracle and with *better* names
  ('Niraj', 'Derrick' vs the reference's 'node'); plaza Yanque → 39 groups of which
  31 are instances sharing 5 prototypes, and import time dropped 12.1 → 7.5 s
  (each prototype fuses once, not per copy). Library definitions never placed
  in the model are not emitted.
- ⚠️ **Instance-tree misplacement (upstream, latent)** — in `demuna.skp` the
  parser hangs Rodeo#2's instance under the *Derrick* definition instead of
  the root, and `CASCO.dwg` (137 verts / 156 edges, a pure-wireframe DWG
  import) is never instanced. Positions still come out right in this file,
  but the hierarchy is wrong — worth an upstream issue with the repro.

These gaps are the concrete contribution targets for OpenSKP (see
`docs/openskp-collaboration.md`). Geometry — the hard part — already works.

## Layer folders in IngeTrazo (2026-10-06)

The Layers panel supports nested folders, sibling order, expansion state,
and inherited visibility/locking. These are stored in `.igz` as
`layer_folders`; each layer records its `folder_id` and `position`.
Saved views also record hidden folder IDs. Layer 0 remains at the root.

Native tag-folder support is implemented in the local OpenSKP feature commit
`61abde1ed6ae1829b926ad3f371bdac619b40057`, based on the currently pinned
commit. The complete source change is preserved in
`patches/openskp-tagfolders.patch`; it has not yet been published, so the
dependency pins remain at the existing public commit until publication is
approved. To test locally, apply the patch to a checkout of that pinned
OpenSKP commit and install its `packages/python` package in your development
environment (or put `packages/python/src` on `PYTHONPATH`).

The local macOS installation at `/Applications/IngeTrazo.app` has been
rebuilt with this patched OpenSKP package. The build is also available in
`dist/tagfolders/IngeTrazo.app`, with the previous installed app preserved in
`dist/tagfolders/previous/IngeTrazo.app`. Restart a running app to load the
updated parser. The installed build uses the initial feature commit
`60775ddeae81b054be361d08eb9d7f0573565e9e`; the later test audit only adds
formatting, type annotations and an internal invariant assertion. This local
installation does not change the public dependency
pin or publish the patch.

The extended Python model exposes `layer_folders`, tag `folder_id`/`position`,
and per-scene `hidden_layer_folder_ids`. Both modern VFF and classic files
carrying native folder records are read. The adapter translates source IDs
to new IngeTrazo folder IDs per import, preserving duplicate names, nesting,
empty folders, individual tag switches and inherited folder visibility.
Saved-view hidden-folder references use that same mapping.

The writer adds `add_layer_folder` and `set_layer_folder`. It extends the
classic container with native `CLayerManager` schema 7 / `CLayerGroup`
version 3 records, including the implicit managers inside definitions; a
complete new VFF geometry writer is not required. Files with folders require
SketchUp 2021+ for tag-folder support. The existing `skp_out` backend forwards
the hierarchy and retains geometry hidden by tags/folders, unused tags and
empty folders. Older writers report unsupported folder export explicitly.
The application still has no SKP export menu and no SDK runtime dependency.
Its existing packaging exclusion of the third-party scaffold is unchanged.

The OpenSKP patch includes regression tests and an optional local C API
oracle: SDK-created classic/VFF folders, native writer geometry and folder
tree verification, new-scene visibility and VFF scene-specific hidden folders.
SDK binaries and SDK-produced fixture files are not included. Classic scene
folder visibility export, locking and expansion state are not implemented as
native SketchUp fields. No folder names are inferred from tag names.

Validation of the final patch on macOS / Python 3.12: the full OpenSKP
suite passed 618 tests with 34 skips. Running the existing create/edit SDK
tests against the local macOS SDK passed the 33 previously skipped SDK
tests too (263 tests in that run); only the optional `ifcopenshell` test
remains skipped. IngeTrazo import/export/history regression coverage passed
165 tests. Ruff 0.15.13 passes for all Python sources/tests; the new parser
and tests pass Black/isort, and the new parser passes standalone strict
mypy. Repository-wide Black/isort/mypy still fail on existing code: 69
formatting files, 45 import-sorting files and 1,307 type errors, versus
69 / 45 / 1,342 in the pinned baseline. No additional mypy diagnostics
remain. Detailed logs and coverage are in `dist/tagfolders/validation/`.
