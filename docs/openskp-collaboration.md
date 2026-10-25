# OpenSKP collaboration

> **2026-09-28.** IngeTrazo no longer runs, downloads or links to any
> proprietary .skp tooling: the former external converter and its automatic
> download are gone, the validation tests built on it are gone, and the `.skp`
> export is off because OpenSKP's writer builds on a blank template document
> that IngeTrazo no longer distributes. `.skp` files are read with OpenSKP
> only. Where the sections below say "the oracle", they mean the reference
> output the reader was validated against at the time.

**Status:** introduction issue **posted** upstream
([iamahsanmehmood/openskp#2](https://github.com/iamahsanmehmood/openskp/issues/2),
2026-07-21). This doc keeps the rationale for how IngeTrazo supports
[OpenSKP](https://github.com/iamahsanmehmood/openskp) without becoming dependent
on it, plus a pointer to the introduction issue.

## Strategy: upstream-first, not upstream-dependent

We want to help OpenSKP become a pure-Python parser that opens **any** `.skp`
(old → recent), and use it in IngeTrazo as its only `.skp` reader.

Because OpenSKP is **MIT**, our ability to ship it never depends on upstream
merging our work:

- **Layer A — upstream-first.** Open PRs, discuss, aim to get changes merged.
  Best case: everyone benefits, zero maintenance for us.
- **Layer B — maintained downstream (insurance).** Whatever upstream doesn't
  take lives in a friendly fork (`main` tracks upstream + a branch carrying our
  patches, rebased as upstream moves). IngeTrazo vendors a **pinned** version of
  Layer B behind the `formats/skp.py` seam — so a rejected PR costs us
  *maintenance*, never *capability*.

A fork only becomes its own project (a natural "libreskp") if upstream is
unresponsive/misaligned, or if we ever want a copyleft guarantee. Until then:
contribute, and keep a quiet downstream as insurance. Preserve OpenSKP's MIT
notices when vendoring; MIT is GPL-compatible, so the combined IngeTrazo ships
GPL while the parser files keep their MIT header + attribution.

## Clean-room boundary

Differential validation is strictly **black-box output comparison**: a
reference COLLADA export of the same model is compared against OpenSKP's
parse — never decompilation or copying proprietary internals into the parser.
It matches the "observed `.skp` files + their COLLADA exports" methodology the
reverse-engineering already uses.

## Findings — OpenSKP 0.2.0 wired into IngeTrazo (2026-07-21)

OpenSKP is **wired and working** (`formats/skp_openskp.py`). Measured against
the reference oracle on real files (`demuna.skp`, a .skp of the 2022 version):

- ✅ **Bounding box exact** — units (inches→m), Z-up and instance transforms all
  correct.
- ✅ **Geometry ~90–95% complete** — faces/vertices/triangles within ~5–9% of
  the oracle.

Contribution targets, most valuable first:

1. ✅ **Expose `Material.id`** — **PR submitted**
   ([openskp#3](https://github.com/iamahsanmehmood/openskp/pull/3), 2026-07-21):
   `Material.id` + `SkpModel.materials_by_id`, surfacing the join the internal
   exporter already had. Validated 19/19 face material_ids on a real 2022-version
   file. Layer B insurance: branch `expose-material-id` on
   `tuxiasumari/openskp`; IngeTrazo's adapter uses the join when present
   (guarded, so PyPI 0.2.0 still imports, just uncoloured).
2. ✅ **Texture extraction** — **PR submitted**
   ([openskp#4](https://github.com/iamahsanmehmood/openskp/pull/4), 2026-07-21):
   `Material.texture` (`Texture` dataclass — filename, tile size in inches, raw
   image bytes, `save()`), read from the material's ZIP folder with a sibling
   fallback for name mismatches. Validated 2/2 textures on a real 2022-version file.
   Integration branch `ingetrazo` on `tuxiasumari/openskp` merges #3 + #4 for
   IngeTrazo's venv until they ship on PyPI. Measured after both: **18/18
   materials, 2/2 textures — exact parity with the oracle.**
3. ✅ **"~5–9% skipped faces" — resolved 2026-07-21: measurement artefact, not
   parser loss.** Raw DAE = 4516 tris = OpenSKP's parse exactly; surface area
   matches to 0.00% (327.268 vs 327.269 m²). The deltas came from comparing a
   fused path against raw polygons. Harness now uses `area_m2` as the
   fusion-invariant truth metric; IngeTrazo's `apply_payload` runs the same
   fusion pipeline as its DAE import. **No upstream work needed.**
4. ✅ **Instance-level materials — PR submitted**
   ([openskp#5](https://github.com/iamahsanmehmood/openskp/pull/5), 2026-07-21):
   `Instance.material_id` (the `D007`/`D107` under the `6419` node —
   "paint the component"). Found on the plaza: 24/274 instances carry a
   material (granite pergolas, wood floors). IngeTrazo's adapter now resolves
   the inheritance (face material `None` → nearest painted ancestor;
   prototypes split per inherited material so a red and a green copy don't
   wrongly share). Also fixed on our side: texture filenames that are full
   Windows paths (`C:\Users\...\toro.png`, `P:/Projects/...png`)
   are reduced to a safe basename before writing.
5. ✅ **"Image entities" — solved (2026-07-21): it was an ENCODING bug, not a
   missing entity class.** The tree foliage IS ordinary faces with the
   Celtis material (front `D107` *and* back `AF0D`, photo-fitted
   `uv_transform`) — but the parser decoded entity names as
   `ascii, errors='ignore'`, so the TLV name `"Celtis_australis_s cópia"`
   became `"...s cpia"`, failed the name join to the XML material file, and
   the material was unresolvable. A guaranteed hit for any file authored in
   Spanish/Portuguese/French. **PR submitted**
   ([openskp#7](https://github.com/iamahsanmehmood/openskp/pull/7)): all six
   decode sites switch to UTF-8. Measured after: Celtis foliage **445 m² vs
   the oracle's 444**, total painted **2274 m² vs the oracle's 2205** — the
   pure path now paints *more* than the reference DAE (instance-material
   inheritance that export drops). Lesson: a "missing feature" can
   be a one-word bug — measure per-material before reverse-engineering.
6. ✅ **Per-face texture mapping — DECODED and shipped** (2026-07-21). The
   user authored the controlled experiment (`textura.skp`: untouched /
   rotated / distorted squares) and it cracked the convention: the stored
   3×3 row-major matrix maps **texture space → face plane**, so
   ``uvq = [p·xr, p·yr, 1] @ inv(M)``, ``u = uvq[0]/uvq[2]/tile_w`` (plane
   basis ``xr = normalize(Z×n)``, ``yr = n×xr``, inches; projective for
   4-pin distortion). Validated to rms < 1e-5 on 150 photo-fitted flag
   triangles vs reference ground truth. **PR submitted**
   ([openskp#6](https://github.com/iamahsanmehmood/openskp/pull/6)):
   `Face.uv_transform` / `uv_transform_back` with the recipe documented.
   IngeTrazo's adapter bakes the exact per-vertex UVs into the per-face
   `uvw` affine its renderer already consumes — the Peru flag now shows
   red *and* white. Original investigation notes kept below.

   **(original notes)** Per-face texture mapping (upstream, located but not yet decoded) —
   photo-fitted/positioned textures (e.g. a waving Peru-flag mesh) carry a
   per-face mapping the parser doesn't read, so IngeTrazo's planar fallback
   shows a single corner of the image (the user's "solid red flag"). We
   FOUND where it lives, per face, under the face's entity-info block:
   `D007 → DC05 → DD05 → B136 → B236 → 1027 → 1127 (front) / 1227 (back)
   → 1327 → { 1427: flag(=1), 1527: 9×f64 3×3 matrix, 1627: 3×f64 }` —
   and the 9-double matrix is per-face and projective-looking (its [8]
   element varies ≈0.98–1.06, the signature of a 4-pin distorted
   mapping). What's missing is the exact convention: tested affine and
   homography readings (row/col-major, inverse, conventional plane axes)
   against ground-truth UVs recovered from the DAE oracle (200 matched
   triangles) — none closes (best rms ≈0.30 in wrapped UV). The 2D basis
   the format uses is not the naive normal-derived axes. Next step: a
   CONTROLLED experiment — a minimal .skp authored by hand with a
   known positioned texture (unrotated square / 90°-rotated / distorted)
   to calibrate the basis cleanly, instead of a photo-fitted waving mesh.
   Related finds while digging: `D207` under the face's `D007` = the BACK
   material (428921 on the flag), and `AF0D` = a repeated material ref —
   both worth exposing upstream too (back-painted faces currently import
   colourless).
6. **Instance-tree misplacement (upstream, latent)** — found while digging
   into #3: in a real 2022-version file, an instance is attached to the wrong parent
   definition (Rodeo#2 under Derrick instead of the root) and a pure-wireframe
   component (`CASCO.dwg`, 137 verts / 156 edges, 0 faces) is never instanced.
   Positions happen to come out right; the hierarchy is wrong. Candidate for
   an upstream issue with repro.
7. ✅ **Image entities (face-me cutouts) — decoded and shipped (2026-07-21).**
   An Image placed in the model wraps a standard `6419` instance inside the
   image-specific `9013 → 401F` containers (previously opaque → the image
   looked "never placed"), and its backing quad definition carries TLV kind
   `8315 == 2`. **PR submitted**
   ([openskp#9 → #8](https://github.com/iamahsanmehmood/openskp/pull/8)):
   `CONTAINER_TAGS += {9013, 401F}` + `Definition.is_image`. IngeTrazo's
   adapter pulls each image out as its own group; cutout images (real alpha)
   become `billboard = "mesh"` face-me sprites that turn toward the camera —
   same rule as the DAE import. Verified on the plaza: the bull
   (`toro.png`, 1.85×2.11 m above the arch) and the statue
   (`campesiono.png`, 2.44 m on its pedestal) both surface as billboards.
   The exact "always face camera" component flag remains undecoded (the
   alpha heuristic covers the practical cases).
   **Superseded (2026-10-26):** the flag is decoded now and drives the
   billboards; Image entities stay static panels as in SketchUp (the
   heuristic turned transparent reference plans into face-me sprites).
8. **Legacy MFC (v8–v20)** version coverage, if not already handled.

The differential harness lives at **`scripts/skp_diff.py`**:
`python scripts/skp_diff.py model.skp [--dae model.dae]` loads a reference
COLLADA export of the same model and diffs a structural fingerprint against
the pure backend's parse.

## Introduction issue

Posted upstream as
[openskp#2](https://github.com/iamahsanmehmood/openskp/issues/2); the text
lives there.
