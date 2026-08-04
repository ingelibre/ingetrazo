# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Photogrammetric mesh — the drone survey itself (Track G, G6).

The other half of the unified flow's first step: ``georef/terrain.py`` drapes a
*global* DEM under the model, this brings in **your own** flight — the textured
mesh WebODM/ODM reconstructs from the drone photos, at survey resolution instead
of 30 m SRTM cells.

Display-only, like terrain and the tile layer: it is **never** part of
``Scene.mesh``. A photogrammetric mesh is reference geometry to trace *over* —
hundreds of thousands of noise-shaped triangles that would drown the topology
engine's weld/heal and are not editable geometry in any useful sense
(invariant #4). Everything here is NumPy arrays ready for one GL upload, not
``Face``/``Edge`` objects.

WHERE ODM PUTS THE COORDINATES (the thing that trips everyone up)
    ``odm_texturing/odm_textured_model_geo.obj`` is *not* raw UTM, despite the
    ``_geo``. ODM subtracts a whole-metre UTM anchor and writes the remainder,
    so the vertices are small numbers (a few hundred metres) around that anchor
    — no float32 precision problem, and no need for the non-georeferenced twin
    (recent ODM versions don't even export one). The anchor lives in

        odm_georeferencing/odm_georeferencing_model_geo.txt
            WGS84 UTM 18S
            717623 8278698

    X and Y are metres east/north of it; **Z is absolute altitude**, straight
    from the reconstruction — the drone's GNSS, so ellipsoidal unless the
    processing used ground control points. So placing the mesh is: shift X/Y by
    where that anchor falls in the scene's local frame, and drop Z by the
    scene's vertical origin (:func:`vertical_origin`).

THE VERTICAL ORIGIN IS RECORDED, NOT DISCARDED
    The scene works in local metres, so ~1750 m of altitude has to come off —
    but the amount is written to ``datum.alt``, so any elevation can be
    reported as a real altitude instead of a number floating above an unknown
    plane. It is derived from the survey and from nothing else: an earlier
    version borrowed it from the global DEM, which mixed two vertical datums
    (the DEM is orthometric, this is ellipsoidal) *and* made the result depend
    on whether tiles had downloaded, so the same model could import twice at
    two different sets of elevations.

Pure geometry + NumPy here; reading the texture images and uploading to GL is
the viewport's business (they are large — a single ODM atlas is routinely
16k–24k pixels square).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtGui import QVector3D

from georef.datum import utm_inverse

# ODM writes the anchor file inside its own stage folder, a sibling of
# odm_texturing/ — look there first, then next to the .obj itself.
_GEO_ANCHOR_NAME = "odm_georeferencing_model_geo.txt"
_GEO_ANCHOR_DIRS = ("../odm_georeferencing", ".", "odm_georeferencing")

# Vertical reference tokens. Stored, not translated — the UI renders them.
VERTICAL_ODM = "odm"        # the photogrammetric reconstruction's own heights
VERTICAL_DEM = "dem"        # a global DEM (orthometric, EGM96-ish)
VERTICAL_LOCAL = "local"    # an arbitrary zero: relative heights only


@dataclass(frozen=True)
class ODMAnchor:
    """The UTM point ODM subtracted from every vertex of the ``_geo`` model."""

    east: float
    north: float
    zone: int
    northern: bool

    @property
    def hemisphere(self) -> str:
        return "N" if self.northern else "S"


@dataclass
class PhotoMaterial:
    """One ``usemtl`` run: which texture, and the triangles that use it.

    ODM splits the model across ~20 atlases, so the renderer walks these ranges
    and binds one texture per draw instead of one per triangle. ``start``/
    ``count`` index into :attr:`PhotoMesh.triangles`.
    """

    name: str
    texture: Path | None      # as declared by the .mtl; may not exist on disk
    start: int
    count: int


class PhotoMesh:
    """A georeferenced photogrammetric survey, placed in the scene's local frame.

    Display-only reference geometry (invariant #4). Arrays are GL-shaped: one
    entry per *unique* vertex/UV pair, because OBJ indexes position and texture
    coordinate separately and GL cannot.
    """

    def __init__(self, vertices, uvs, triangles, materials,
                 source: Path | None = None, anchor: ODMAnchor | None = None) -> None:
        self.vertices = vertices        # (N, 3) float32, local metres
        self.uvs = uvs                  # (N, 2) float32
        self.triangles = triangles      # (M, 3) uint32 indices
        self.materials = materials      # list[PhotoMaterial], in draw order
        self.source = source            # the .obj it came from
        self.anchor = anchor            # None = placed at the origin, ungeoreferenced
        self.visible = True
        # material index → the QImage actually in use (already downscaled to
        # what this GPU accepts). Carried on the mesh so saving the document
        # never has to reach back to the 455 MB ODM export — an .igz that only
        # works while the original folder survives would defeat the point.
        self.images: dict = {}
        # Where this survey's Z came from, so a document can say what its
        # elevations mean. ODM writes whatever the flight was reconstructed
        # against: the drone's GNSS (ellipsoidal) unless the processing used
        # ground control points with known orthometric heights. We cannot tell
        # which from the file, and pretending otherwise is how a profile ends
        # up in an expediente with elevations nobody can defend.
        self.vertical_reference = VERTICAL_ODM
        # Layer this survey is tagged with, exactly like a Group: hiding the
        # layer hides the survey, through the same machinery as everything else
        # (``core.layers.layer_of`` reads this attribute).
        self.layer: str | None = None
        self._index = None              # plan grid, built on the first query

    def invalidate_index(self) -> None:
        """Drop the plan index after moving the vertices (the import re-zeroes
        Z when there's no DEM, and a stale index would answer from the old
        geometry)."""
        self._index = None

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def triangle_count(self) -> int:
        return int(self.triangles.shape[0])

    @property
    def georeferenced(self) -> bool:
        return self.anchor is not None

    @property
    def missing_textures(self) -> list[Path]:
        """Declared atlases that aren't on disk — ODM exports are often moved
        without their 400 MB of PNGs, and the model then renders flat grey."""
        return [m.texture for m in self.materials
                if m.texture is not None and not m.texture.is_file()]

    def bounds(self):
        """``(min, max)`` corners in local metres, or ``(None, None)`` if empty."""
        if self.vertex_count == 0:
            return None, None
        lo = self.vertices.min(axis=0)
        hi = self.vertices.max(axis=0)
        return (QVector3D(float(lo[0]), float(lo[1]), float(lo[2])),
                QVector3D(float(hi[0]), float(hi[1]), float(hi[2])))

    # ---- Querying the surface ---------------------------------------------
    # What makes the survey *useful* rather than just visible: the elevation
    # under a plan position. Every civil question downstream — where the bridge
    # abutments land, the longitudinal profile of a canal, cut and fill against
    # a design surface — reduces to asking this a few hundred times.

    def height_at(self, x: float, y: float) -> float | None:
        """Terrain Z at local ``(x, y)``, or ``None`` outside the survey.

        Where the mesh folds over itself (a cliff face, a wall reconstructed
        with overhang) several triangles cover the same plan point; the
        **highest** wins, which is the surface you would see looking down and
        the one you would set a level on.
        """
        index = self._ensure_index()
        if index is None:
            return None
        cells, starts, (minx, miny, cell, nx, ny) = index

        i = int((x - minx) // cell)
        j = int((y - miny) // cell)
        if not (0 <= i < nx and 0 <= j < ny):
            return None
        c = j * nx + i
        candidates = cells[starts[c]:starts[c + 1]]
        if candidates.size == 0:
            return None

        import numpy as np

        tri = self.triangles[candidates]
        a = self.vertices[tri[:, 0]]
        b = self.vertices[tri[:, 1]]
        cv = self.vertices[tri[:, 2]]

        # Barycentric coordinates in plan. The determinant is twice the signed
        # XY area; a degenerate (vertical) triangle has none and drops out.
        v0x, v0y = b[:, 0] - a[:, 0], b[:, 1] - a[:, 1]
        v1x, v1y = cv[:, 0] - a[:, 0], cv[:, 1] - a[:, 1]
        det = v0x * v1y - v1x * v0y
        good = np.abs(det) > 1e-12
        if not good.any():
            return None

        px, py = x - a[:, 0], y - a[:, 1]
        u = np.where(good, (px * v1y - v1x * py) / np.where(good, det, 1.0), -1.0)
        v = np.where(good, (v0x * py - px * v0y) / np.where(good, det, 1.0), -1.0)
        # A hair of tolerance so a point exactly on a shared edge belongs to
        # one of the two triangles instead of falling through the crack.
        inside = good & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1.0 + 1e-9)
        if not inside.any():
            return None

        z = a[:, 2] + u * (b[:, 2] - a[:, 2]) + v * (cv[:, 2] - a[:, 2])
        return float(z[inside].max())

    def _ensure_index(self):
        """Build (once) a uniform plan grid binning triangles into cells.

        Lazy: importing a survey you only want to look at should not pay for
        it. Built vectorised — 362k triangles is too many for a Python loop,
        and this is the structure every elevation query goes through.
        """
        if getattr(self, "_index", None) is not None:
            return self._index
        if self.triangle_count == 0 or self.vertex_count == 0:
            return None

        import numpy as np

        tri = self.triangles
        xs = self.vertices[:, 0][tri]
        ys = self.vertices[:, 1][tri]
        tmin_x, tmax_x = xs.min(axis=1), xs.max(axis=1)
        tmin_y, tmax_y = ys.min(axis=1), ys.max(axis=1)

        minx, maxx = float(tmin_x.min()), float(tmax_x.max())
        miny, maxy = float(tmin_y.min()), float(tmax_y.max())
        width, height = max(maxx - minx, 1e-6), max(maxy - miny, 1e-6)

        # Aim at a handful of triangles per cell. Bounded both ways: too fine
        # wastes memory on empty cells, too coarse makes every query a scan.
        target = max(1, int(np.sqrt(self.triangle_count / 4.0)))
        nx = max(1, min(target, 2048))
        ny = max(1, min(target, 2048))
        cell = max(width / nx, height / ny)
        nx = max(1, int(width / cell) + 1)
        ny = max(1, int(height / cell) + 1)

        i0 = np.clip(((tmin_x - minx) // cell).astype(np.int64), 0, nx - 1)
        i1 = np.clip(((tmax_x - minx) // cell).astype(np.int64), 0, nx - 1)
        j0 = np.clip(((tmin_y - miny) // cell).astype(np.int64), 0, ny - 1)
        j1 = np.clip(((tmax_y - miny) // cell).astype(np.int64), 0, ny - 1)

        span_x = i1 - i0 + 1
        span_y = j1 - j0 + 1
        counts = span_x * span_y
        total = int(counts.sum())
        if total > 16_000_000:          # pathological span: give up on the index
            return None                 # rather than allocate half the RAM

        ids = np.repeat(np.arange(tri.shape[0], dtype=np.int64), counts)
        starts_of = np.concatenate(([0], np.cumsum(counts)[:-1]))
        within = np.arange(total, dtype=np.int64) - np.repeat(starts_of, counts)
        wide = np.repeat(span_x, counts)
        cell_i = np.repeat(i0, counts) + within % wide
        cell_j = np.repeat(j0, counts) + within // wide
        cell_id = cell_j * nx + cell_i

        order = np.argsort(cell_id, kind="stable")
        cells = ids[order]
        counts_per_cell = np.bincount(cell_id, minlength=nx * ny)
        starts = np.concatenate(([0], np.cumsum(counts_per_cell))).astype(np.int64)

        self._index = (cells, starts, (minx, miny, cell, nx, ny))
        return self._index


#: Percentile used as "the foot of the survey". Not the true minimum: a
#: photogrammetric mesh has spikes where reconstruction failed, and on the
#: survey this was built against the lowest vertex sits 45 m under the 0.1th
#: percentile — 94 vertices out of 222 622. Anchoring on that would drop the
#: whole scene into a hole that isn't there.
FOOT_PERCENTILE = 1.0


def vertical_origin(mesh: PhotoMesh) -> float | None:
    """The absolute elevation that should become the scene's local Z=0.

    Taken from the survey itself and from nothing else. An earlier version
    borrowed it from the global DEM, which was wrong twice over: the DEM is
    orthometric while a reconstruction's heights are the drone's GNSS
    (ellipsoidal), so the subtraction mixed two vertical datums — and it
    depended on tiles having finished downloading, so the same model imported
    twice could land at different elevations.

    The value is **the foot of the survey**, so the model sits on the Z=0 plane
    with the ground rising away from it. The version before this one used the
    survey's height at the scene origin, which sounded principled and was not:
    the scene origin is ODM's anchor, a rounded UTM point with no relation to
    the site. On a 285 m-deep quebrada it landed mid-slope and left 60 % of the
    terrain hanging below the flat base map — the map read as buried, and the
    map is the one thing that has to read as ground.
    """
    if mesh is None or mesh.triangle_count == 0:
        return None
    import numpy as np
    return float(np.percentile(mesh.vertices[:, 2], FOOT_PERCENTILE))


class PhotoMeshSampler:
    """A :mod:`georef.dem` sampler backed by the survey instead of a global DEM.

    Same three members :func:`georef.profile.sample_profile` asks for, so a
    longitudinal profile can come off the drone flight — centimetres per pixel
    over the actual site — rather than 30 m SRTM cells interpolated from
    space. For a bridge across a quebrada that is the difference between a
    profile you can set abutments on and a smooth curve that misses the gorge.

    ``ensure_area`` is a no-op: there is nothing to fetch, the survey is
    already here. Outside its footprint ``elevation_at_local`` returns ``None``
    and the profile shows a gap, which is honest — the drone did not fly there.
    """

    def __init__(self, mesh: PhotoMesh, datum) -> None:
        self.mesh = mesh
        self.datum = datum

    def ensure_area(self, lat_s, lon_w, lat_n, lon_e) -> None:
        return None

    def elevation_at_local(self, point) -> float | None:
        """ABSOLUTE elevation, matching :class:`~georef.dem.DEMSampler`.

        The mesh stores local scene metres; a sampler's contract is real
        altitudes (``build_terrain`` subtracts its ground reference from what
        the DEM sampler returns). Returning local metres here would make a
        profile mean something different depending on which sampler happened
        to be in use — the exact kind of silent inconsistency that puts an
        undefendable column of numbers into a deliverable.
        """
        z = self.mesh.height_at(point.x(), point.y())
        if z is None:
            return None
        return z + float(getattr(self.datum, "alt", 0.0) or 0.0)

    def elevation_at(self, lat: float, lon: float) -> float | None:
        return self.elevation_at_local(self.datum.geodetic_to_local(lat, lon))


# ---------------------------------------------------------------------------
# Document storage
# ---------------------------------------------------------------------------
# A survey belongs *in* the document. The Agisoft→SketchUp habit it replaces
# ended with the model saved inside the .skp; a reference mesh that has to be
# re-imported every time you open the file is not the same tool. Geometry goes
# in as one compressed NumPy archive (8.4 MB → 4.9 MB on the real survey) and
# the atlases as JPEG at the size they are actually used — roughly 29 MB all in,
# against the 455 MB of the ODM export it no longer depends on.

GEOMETRY_ENTRY = "survey/geometry.npz"
ATLAS_ENTRY = "survey/atlas-{:02d}.jpg"


def pack_mesh(mesh: PhotoMesh) -> tuple[dict, dict]:
    """``(json_metadata, blobs)`` for storing ``mesh`` in an ``.igz``."""
    import io

    import numpy as np

    buffer = io.BytesIO()
    np.savez_compressed(buffer, vertices=mesh.vertices, uvs=mesh.uvs,
                        triangles=mesh.triangles)
    blobs = {GEOMETRY_ENTRY: buffer.getvalue()}

    materials = []
    for index, material in enumerate(mesh.materials):
        entry = {"name": material.name,
                 "start": int(material.start), "count": int(material.count)}
        image = mesh.images.get(index)
        if image is not None and not image.isNull():
            member = ATLAS_ENTRY.format(index)
            data = _image_bytes(image)
            if data:
                blobs[member] = data
                entry["atlas"] = member
        materials.append(entry)

    meta = {"materials": materials, "visible": bool(mesh.visible),
            "geometry": GEOMETRY_ENTRY, "layer": mesh.layer,
            # Saved explicitly: a document reopened next year has to be able to
            # say what its elevations are measured against.
            "vertical_reference": mesh.vertical_reference}
    if mesh.anchor is not None:
        meta["anchor"] = {"east": mesh.anchor.east, "north": mesh.anchor.north,
                          "zone": mesh.anchor.zone,
                          "northern": mesh.anchor.northern}
    if mesh.source is not None:
        meta["source"] = str(mesh.source)       # provenance only, never resolved
    return meta, blobs


def _image_bytes(image) -> bytes:
    """A QImage as JPEG bytes. Aerial imagery has no alpha and no hard edges,
    so JPEG is the right trade — and the container stores blobs uncompressed,
    which would make PNG pay twice."""
    from PySide6.QtCore import QBuffer, QByteArray

    store = QByteArray()
    buffer = QBuffer(store)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    ok = image.save(buffer, "JPG", 92)
    buffer.close()
    return bytes(store) if ok else b""


def unpack_mesh(meta: dict, read_blob) -> PhotoMesh | None:
    """Rebuild a :class:`PhotoMesh` from ``meta`` plus a ``read_blob(member)``.

    Returns ``None`` when the geometry is missing or unreadable — a damaged
    survey block must not stop the rest of the document from opening.
    """
    import io

    import numpy as np
    from PySide6.QtGui import QImage

    try:
        raw = read_blob(meta.get("geometry", GEOMETRY_ENTRY))
        if not raw:
            return None
        with np.load(io.BytesIO(raw)) as archive:
            vertices = archive["vertices"]
            uvs = archive["uvs"]
            triangles = archive["triangles"]
    except Exception:  # noqa: BLE001 — a broken block is not a broken document
        return None

    anchor = None
    raw_anchor = meta.get("anchor")
    if raw_anchor:
        try:
            anchor = ODMAnchor(float(raw_anchor["east"]), float(raw_anchor["north"]),
                               int(raw_anchor["zone"]), bool(raw_anchor["northern"]))
        except (KeyError, TypeError, ValueError):
            anchor = None

    materials, images = [], {}
    for index, entry in enumerate(meta.get("materials", [])):
        materials.append(PhotoMaterial(
            name=entry.get("name", ""), texture=None,
            start=int(entry.get("start", 0)), count=int(entry.get("count", 0))))
        member = entry.get("atlas")
        if not member:
            continue
        data = read_blob(member)
        if not data:
            continue
        image = QImage()
        if image.loadFromData(data) and not image.isNull():
            images[index] = image

    mesh = PhotoMesh(vertices, uvs, triangles, materials, anchor=anchor)
    mesh.images = images
    mesh.visible = bool(meta.get("visible", True))
    mesh.vertical_reference = meta.get("vertical_reference", VERTICAL_ODM)
    mesh.layer = meta.get("layer")
    source = meta.get("source")
    if source:
        mesh.source = Path(source)
    return mesh


# ---------------------------------------------------------------------------
# Sidecar files
# ---------------------------------------------------------------------------

def parse_anchor(text: str) -> ODMAnchor | None:
    """Parse ``odm_georeferencing_model_geo.txt``.

    Two lines: a CRS name (``WGS84 UTM 18S``) and the easting/northing. Returns
    ``None`` for anything that isn't a UTM anchor we can act on — a projected
    CRS we don't understand is not an error worth raising, it just means the
    mesh lands at the origin and the user places it by hand.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return None

    zone, northern = None, None
    for token in lines[0].replace("UTM", " ").split():
        token = token.strip().upper()
        if token[:-1].isdigit() and token[-1] in ("N", "S"):
            zone, northern = int(token[:-1]), token[-1] == "N"
            break
        if token.isdigit():                     # "UTM 18 S" spelled apart
            zone = int(token)
        elif token in ("N", "S") and zone is not None:
            northern = token == "N"
    if zone is None or northern is None:
        return None

    parts = lines[1].split()
    if len(parts) < 2:
        return None
    try:
        east, north = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    return ODMAnchor(east, north, zone, northern)


def find_anchor(obj_path: Path) -> ODMAnchor | None:
    """Locate and parse the anchor file for an ODM ``.obj``."""
    obj_path = Path(obj_path)
    for rel in _GEO_ANCHOR_DIRS:
        candidate = (obj_path.parent / rel / _GEO_ANCHOR_NAME).resolve()
        if candidate.is_file():
            anchor = parse_anchor(candidate.read_text(errors="replace"))
            if anchor is not None:
                return anchor
    return None


def parse_mtl(text: str) -> dict[str, str | None]:
    """Material name → ``map_Kd`` filename (``None`` when untextured)."""
    materials: dict[str, str | None] = {}
    current = None
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "newmtl" and len(parts) >= 2:
            current = parts[1]
            materials.setdefault(current, None)
        elif parts[0] == "map_Kd" and len(parts) >= 2 and current is not None:
            # Keep the whole tail: ODM filenames have no spaces, but hand-edited
            # .mtl files do, and dropping the rest would silently lose the map.
            materials[current] = " ".join(parts[1:])
    return materials


# ---------------------------------------------------------------------------
# The OBJ itself
# ---------------------------------------------------------------------------

def _parse_obj(text: str):
    """Split an OBJ into raw arrays plus the ``usemtl`` runs.

    Returns ``(positions, texcoords, corner_v, corner_t, runs)`` where the corner
    arrays are one entry per triangle corner (already fan-triangulated) and
    ``runs`` is ``[(material_name, first_triangle, triangle_count)]``.
    """
    positions: list[tuple[float, float, float]] = []
    texcoords: list[tuple[float, float]] = []
    corner_v: list[int] = []
    corner_t: list[int] = []
    runs: list[list] = []

    for line in text.splitlines():
        if not line:
            continue
        tag, _, rest = line.partition(" ")
        if tag == "v":
            p = rest.split()
            positions.append((float(p[0]), float(p[1]), float(p[2])))
        elif tag == "vt":
            p = rest.split()
            # OBJ V runs bottom-up, images top-down — flip once, here, so the
            # renderer never has to think about it.
            texcoords.append((float(p[0]), 1.0 - float(p[1])))
        elif tag == "f":
            corners = rest.split()
            if len(corners) < 3:
                continue
            vs, ts = [], []
            for corner in corners:
                bits = corner.split("/")
                vi = int(bits[0])
                ti = int(bits[1]) if len(bits) > 1 and bits[1] else 0
                # OBJ indices are 1-based; negative counts back from the end.
                vs.append(vi - 1 if vi > 0 else len(positions) + vi)
                ts.append(0 if ti == 0 else
                          (ti if ti > 0 else len(texcoords) + ti + 1))
            for k in range(1, len(vs) - 1):     # fan-triangulate n-gons
                corner_v.extend((vs[0], vs[k], vs[k + 1]))
                corner_t.extend((ts[0], ts[k], ts[k + 1]))
            if runs:
                runs[-1][2] += len(vs) - 2
        elif tag == "usemtl":
            name = rest.strip()
            start = len(corner_v) // 3
            if runs and runs[-1][2] == 0:
                runs[-1][0] = name          # empty run, just relabel it
            else:
                runs.append([name, start, 0])

    return positions, texcoords, corner_v, corner_t, runs


def _weld_corners(corner_v, corner_t, positions, texcoords):
    """Collapse (position, texcoord) corner pairs into GL vertices.

    OBJ indexes position and UV independently; GL needs one array. Vectorised
    with ``np.unique`` because the real files run to a million corners and a
    Python dict lookup per corner is the whole import time.
    """
    n_pos = len(positions)
    n_uv = len(texcoords)
    if not corner_v:
        return (np.zeros((0, 3), np.float32), np.zeros((0, 2), np.float32),
                np.zeros((0, 3), np.uint32))

    vi = np.asarray(corner_v, dtype=np.int64)
    ti = np.asarray(corner_t, dtype=np.int64)        # 0 = no texcoord
    np.clip(vi, 0, max(n_pos - 1, 0), out=vi)
    np.clip(ti, 0, n_uv, out=ti)

    key = vi * (n_uv + 1) + ti
    uniq, inverse = np.unique(key, return_inverse=True)

    out_v = uniq // (n_uv + 1)
    out_t = uniq % (n_uv + 1)

    pos = np.asarray(positions, dtype=np.float64)
    vertices = pos[out_v]

    uvs = np.zeros((uniq.size, 2), dtype=np.float32)
    has_uv = out_t > 0
    if n_uv and has_uv.any():
        uv_table = np.asarray(texcoords, dtype=np.float32)
        uvs[has_uv] = uv_table[out_t[has_uv] - 1]

    triangles = inverse.astype(np.uint32).reshape(-1, 3)
    return vertices, uvs, triangles


def _place(vertices, datum, anchor: ODMAnchor | None, ground_ref: float):
    """Move ODM's anchor-relative metres into the scene's local frame (in place)."""
    if anchor is None:
        # No anchor: treat the file as already-local and only apply the ground
        # reference, so it at least lands on the same Z plane as everything else.
        vertices[:, 2] -= ground_ref
        return vertices

    if anchor.zone == datum.zone and anchor.northern == datum.northern:
        # Same UTM zone: a pure translation, so the whole mesh moves at once.
        origin = datum.utm_to_local(anchor.east, anchor.north, 0.0)
        vertices[:, 0] += origin.x()
        vertices[:, 1] += origin.y()
    else:
        # Different zone — the two grids are rotated relative to each other, so
        # a translation would skew the survey. Reproject properly, per vertex.
        # Rare (the datum normally comes from the same site), hence the loop.
        for i in range(vertices.shape[0]):
            lat, lon = utm_inverse(anchor.east + vertices[i, 0],
                                   anchor.north + vertices[i, 1],
                                   anchor.zone, anchor.northern)
            local = datum.geodetic_to_local(lat, lon, 0.0)
            vertices[i, 0] = local.x()
            vertices[i, 1] = local.y()

    vertices[:, 2] -= ground_ref
    return vertices


def load_odm_obj(obj_path, datum, ground_ref: float = 0.0,
                 anchor: ODMAnchor | None = None) -> PhotoMesh:
    """Read an ODM textured model and place it in ``datum``'s local frame.

    ``ground_ref`` is :func:`georef.surface.ground_reference` — the terrain
    elevation at the scene origin. Pass the same value the terrain was built
    with and the survey lands exactly on it.

    ``anchor`` overrides the sidecar lookup (for files moved away from their
    ODM folder, or to place an ungeoreferenced mesh deliberately).
    """
    obj_path = Path(obj_path)
    if anchor is None:
        anchor = find_anchor(obj_path)

    positions, texcoords, corner_v, corner_t, runs = _parse_obj(
        obj_path.read_text(errors="replace"))
    vertices, uvs, triangles = _weld_corners(
        corner_v, corner_t, positions, texcoords)
    vertices = _place(vertices, datum, anchor, ground_ref)

    materials = []
    if runs:
        maps: dict[str, str | None] = {}
        mtl = _sidecar_mtl(obj_path)
        if mtl is not None:
            maps = parse_mtl(mtl.read_text(errors="replace"))
        for name, start, count in runs:
            if count == 0:
                continue
            image = maps.get(name)
            # Keep the declared path even when the file is absent: a survey that
            # travelled without its atlases should say so, not silently render
            # untextured. The UI reports :attr:`PhotoMesh.missing_textures`.
            materials.append(PhotoMaterial(
                name=name,
                texture=(obj_path.parent / image) if image else None,
                start=start, count=count))
    if not materials and triangles.size:
        materials = [PhotoMaterial("", None, 0, int(triangles.shape[0]))]

    return PhotoMesh(vertices.astype(np.float32), uvs, triangles, materials,
                     source=obj_path, anchor=anchor)


# ---------------------------------------------------------------------------
# Texture atlases
# ---------------------------------------------------------------------------
# ODM texturing produces a handful of very large atlases. A real survey here
# ships one 24576x24576 PNG — bigger than any GPU will accept (the AMD 780M
# this was developed on reports GL_MAX_TEXTURE_SIZE = 16384) and 1 GB of VRAM
# on its own. So the sizes are planned before anything is read: the hardware
# limit is a hard ceiling, and a memory budget is the practical one, since an
# integrated GPU shares system RAM and a survey is *reference* imagery — it
# competes with the model the user is actually drawing.

_BYTES_PER_TEXEL = 4            # RGBA8, how GL stores it whatever the file says
_MIPMAP_FACTOR = 4 / 3          # a full mip chain adds a third on top
_MIN_ATLAS = 256                # below this the imagery is useless to trace over

DEFAULT_TEXTURE_BUDGET = 1024 * 1024 * 1024     # 1 GiB of texture memory


def _fit(size, limit):
    """Scale ``(w, h)`` down to fit ``limit`` on both axes, keeping the ratio."""
    w, h = size
    if w <= limit and h <= limit:
        return (w, h)
    scale = limit / max(w, h)
    return (max(1, int(w * scale)), max(1, int(h * scale)))


def atlas_bytes(sizes) -> int:
    """VRAM the given atlas sizes will occupy, mip chain included."""
    return int(sum(w * h for w, h in sizes) * _BYTES_PER_TEXEL * _MIPMAP_FACTOR)


def plan_texture_sizes(sizes, gl_max: int,
                       budget: int = DEFAULT_TEXTURE_BUDGET) -> list[tuple[int, int]]:
    """Decide what size each atlas should be loaded at.

    ``sizes`` are the on-disk ``(w, h)`` pairs, ``gl_max`` is the driver's
    ``GL_MAX_TEXTURE_SIZE``. Everything is first clamped to the hardware limit
    (non-negotiable — an oversized upload simply fails), then the largest atlas
    is halved repeatedly until the estimated total fits ``budget``. Halving the
    *largest* keeps detail where the small atlases already are, and costs it
    where one enormous sheet covers most of the model.

    Never scales below :data:`_MIN_ATLAS`: a survey you cannot read is not a
    useful trade for memory, and at that point the answer is a smaller export.
    """
    targets = [_fit(s, gl_max) for s in sizes]
    if not targets:
        return targets

    while atlas_bytes(targets) > budget:
        biggest = max(range(len(targets)), key=lambda i: targets[i][0] * targets[i][1])
        w, h = targets[biggest]
        if max(w, h) <= _MIN_ATLAS:
            break                       # can't shrink further without ruining it
        targets[biggest] = (max(1, w // 2), max(1, h // 2))
    return targets


def load_atlas(path: Path, target: tuple[int, int]):
    """Read one atlas at ``target`` size, going through the app's texture cache.

    Two Qt facts make this less obvious than it looks:

    - ``QImageReader`` refuses images over :meth:`allocationLimit` (256 MB by
      default), which every ODM atlas exceeds. It has to be lifted or the read
      returns null with a misleading "out of memory".
    - ``setScaledSize`` does **not** avoid decoding the full image for PNG —
      measured 7.4 s and 2.5 GB peak for the 24576px atlas, the same with or
      without it. Hence the cache: that cost is paid once per file, and later
      opens read a small JPEG instead.
    """
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QImageReader

    path = Path(path)
    cached = _atlas_cache_path(path, target)
    if cached is not None and cached.is_file():
        reader = QImageReader(str(cached))
        image = reader.read()
        if not image.isNull():
            return image

    previous = QImageReader.allocationLimit()
    QImageReader.setAllocationLimit(0)          # 0 = no limit
    try:
        reader = QImageReader(str(path))
        source = reader.size()
        if source.isValid() and (source.width() > target[0]
                                 or source.height() > target[1]):
            reader.setScaledSize(source.scaled(
                QSize(*target), Qt.AspectRatioMode.KeepAspectRatio))
        image = reader.read()
    finally:
        QImageReader.setAllocationLimit(previous)

    if image.isNull():
        return image
    if cached is not None:
        try:
            cached.parent.mkdir(parents=True, exist_ok=True)
            # JPEG: aerial imagery has no alpha and no hard edges to preserve,
            # and a PNG of the same atlas is an order of magnitude slower to
            # re-read — which is the whole point of caching it.
            image.save(str(cached), "JPG", 92)
        except OSError:
            pass                                # cache is an optimisation only
    return image


def _atlas_cache_path(path: Path, target: tuple[int, int]) -> Path | None:
    """Cache location for a downscaled atlas, keyed by source identity + size."""
    try:
        from core.texture import texture_cache_root
        stat = path.stat()
        import hashlib
        key = f"{path.resolve()}|{stat.st_size}|{int(stat.st_mtime)}|{target[0]}x{target[1]}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        return texture_cache_root() / "odm" / f"{digest}-{path.stem}.jpg"
    except Exception:  # noqa: BLE001 — no cache is survivable, a crash isn't
        return None


def _sidecar_mtl(obj_path: Path) -> Path | None:
    """The ``.mtl`` named by the OBJ, falling back to the same stem."""
    try:
        with obj_path.open("r", errors="replace") as fh:
            for line in fh:
                if line.startswith("mtllib"):
                    name = line.partition(" ")[2].strip()
                    candidate = obj_path.parent / name
                    if candidate.is_file():
                        return candidate
                    break
                if line.startswith(("v ", "f ")):
                    break               # past the header, no mtllib
    except OSError:
        return None
    same_stem = obj_path.with_suffix(".mtl")
    return same_stem if same_stem.is_file() else None
