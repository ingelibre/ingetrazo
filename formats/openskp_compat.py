# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fixes to the pinned OpenSKP that are waiting upstream — applied at run
time only while the installed OpenSKP still lacks them.

**Legacy dimensions anchored inside groups** (iamahsanmehmood/openskp#384).
A pre-2021 ``CDimensionLinear`` follows each connection ref with an entity
ref and two lists of refs — the instance paths of the anchored entity. The
pinned reader skips a FIXED 42/82 bytes there, right only while the lists
are empty (a dimension on loose geometry). Anchored to a vertex inside
nested groups, the read slides off the record and the root entity reader,
which stops at the first unreadable item, drops everything after it:
Juan José Noriega's house (a .skp of the 2018 version) opened with 2 of
its 72 root entities — walls and lawn, no upper floor, roofs, openings or
trees (12 placements instead of 2384).

**A face's own tag arrives as a number** (#700). ``Instance.layer`` is
the tag's name, but ``Face.layer`` is the tag's id in the file, and the
id → name table stays inside the parser (``SkpModel`` does not keep it).
A roof tagged "Roof" landed on a layer called 11, so hiding "Roof" left it
on screen. The table is kept from the parse and :func:`resolve_face_layers`
turns the ids into names.

**Annotations carrying their anchor in full** (a .skp of the 2017
version). MFC writes an object in full the first time anything points
at it, so a dimension or leader text anchored to a vertex the stream has not
reached yet carries that ``CVertex`` inline. The dimension reader refused a
new object as a connection point; the text reader skipped it by scanning for
the string delimiter, so its store index went unallocated, every later
reference landed one slot off (edges on edges, a class ref on a dimension)
and the file did not open — silently, as :func:`formats.skp.parse_skp`
reports any parser error as "unreadable". The text delimiter's last byte is
also 0 on some texts, not only 1.

**A definition list that ends before its count.** Edges first written in a
face come back as entity-list back-refs; right after a text, the text
reader takes them as leader attachments, and the list then reads its
definition's tail as items. The tail's signature now ends a definition list
whatever was counted (upstream checked it only after a "burn").

**Groups arrive as components.** The classic reader reads a ``CGroup``
and a ``CComponentInstance`` alike and keeps no trace of which it was, and
the 2021+ reader drops the definition's kind. The definitions placed
through a ``CGroup``, or marked as groups by their kind, are noted during
the parse (:func:`group_definitions`) so the import makes them groups
again.

**A 2019 layer record two bytes longer.** From the 2019 version on, a
layer record ends 23 bytes after its last string, not 21 (the new field is
most likely the layer's dash pattern). The reader skips 21, so in the first
definition the next count read two bytes early, came out at 33 million
and the file did not open («implausible def entity count», #157). The
2020 files still opened only because the reader already steps over zero
words between layers and around their counts there; only 2019 files take
the two extra bytes here.

**Annotations in 2021+ (VFF) files** (#1226). The VFF reader's annotation
handling lags the other ports in three ways. (1) A dimension drawn inside
a group/component is returned among the MODEL-level dimensions with its
endpoints still in the definition's local space (its connection names no
instance to lift by), so it lands displaced from the geometry the import
did transform. (2) The dimension's constraint axis (``5BD1``) is never
read, and the frame fields are taken the wrong way round — ``5BCF`` is
the plane's NORMAL and ``5BD0`` its X axis, as upstream's C++ port
settled in openskp#481: the offset vector is ``(N × X) · offset`` for
axis 1 and ``−X · offset`` for axis 2. Without the axis the importer
guessed ``cross(normal, segment)``, which for most of a staircase's
dimensions points out of the dimension plane entirely. (3) Text records
(``55F0``) are not parsed at all, so leader texts vanish.
:func:`resolve_vff_annotations` re-reads the two record kinds from the
parse's own inputs (kept by wrapping ``_parse_dimensions``, the one
place they meet), gives each dimension its axis, moves the
definition-owned dimensions onto their definition (marked ``vff_owned``
so the adapter places them per instance), and rebuilds the texts on
their owning definition or the model root (marked ``vff_recovered``).
A text whose connection type the reader cannot resolve (e.g. type 4)
keeps its label position but no anchor.

All patches are detected by BEHAVIOUR, not by version: once the upstream
reader carries ``_connection_paths`` the first is left alone, the second
only touches a face layer that is still a number, the anchor and list
fixes step aside once the text reader no longer scans for the delimiter
and the list reader no longer ties the tail check to burns, and the layer
fix once the layer reader looks at the version itself.
"""
from __future__ import annotations

import struct
import threading

_applied = False
_parse_tables = threading.local()   # the last parse's layer id → name


def apply() -> bool:
    """Install the fixes into ``openskp`` when needed. Returns True when a
    patch was installed (idempotent)."""
    global _applied
    if _applied:
        return False
    try:
        from openskp import legacy as L
    except Exception:  # noqa: BLE001 — no openskp: nothing to fix
        return False
    _applied = True
    layers = _keep_layer_table()
    ann = _keep_vff_annotation_inputs()
    texts = _fix_anchored_texts(L)
    lists = _fix_definition_list_end(L)
    groups = _note_legacy_groups(L)
    kinds = _note_definition_kinds()
    tails = _fix_layer_tail_2019(L)
    return _fix_legacy_dimensions(L) or layers or texts or lists \
        or groups or kinds or tails or ann


def _note_legacy_groups(L) -> bool:
    """Remember which definitions a classic (pre-2021) file places through a
    ``CGroup`` — a GROUP — rather than a ``CComponentInstance``.
    The reader reads both the same way and the model it builds keeps no
    trace of which it was, so a group arrived as a component. The ids land
    in a per-thread set, reset before each parse (see
    :func:`reset_group_definitions`)."""
    readers = getattr(L, "_READERS", None)
    original = (readers or {}).get("CGroup")
    if original is None or getattr(original, "_notes_groups", False):
        return False

    def read_group(ar, r):
        rec = original(ar, r)
        if isinstance(rec, dict) and rec.get("def") is not None:
            if not hasattr(_parse_tables, "groups"):
                _parse_tables.groups = set()
            _parse_tables.groups.add(rec["def"])
        return rec

    read_group._notes_groups = True
    readers["CGroup"] = read_group
    return True


def _note_definition_kinds() -> bool:
    """Remember which definitions a 2021+ file marks as GROUPS (#1029). The
    definition record carries its kind in ``8315``: 0 a component, 1 a
    group, 2 the quad behind an Image — the reader only keeps "image". It
    hands each definition's records to ``_extract_geometry_from_nodes``
    once, so that is where the kind is read; the root and the nested calls
    carry no ``8315`` and pass straight through."""
    try:
        from openskp import _core
    except Exception:  # noqa: BLE001
        return False
    original = getattr(_core, "_extract_geometry_from_nodes", None)
    if original is None or getattr(original, "_notes_kinds", False) \
            or not hasattr(_core, "extract_entity_id"):
        return False

    def _extract_geometry_from_nodes(elements, builder):
        for el in elements:
            if el.get("tag") == "8315":
                kind = _core.parse_var_int(el["payload"], 0,
                                           len(el["payload"]))
                did = _core.extract_entity_id({"children": elements})
                if did is not None:
                    _parse_tables.kinds = True
                    if kind == 1:
                        if not hasattr(_parse_tables, "groups"):
                            _parse_tables.groups = set()
                        _parse_tables.groups.add(did)
                break
        return original(elements, builder)

    _extract_geometry_from_nodes._notes_kinds = True
    _core._extract_geometry_from_nodes = _extract_geometry_from_nodes
    return True


def group_definitions() -> set:
    """The definition ids the last parse on this thread placed as GROUPS:
    through a ``CGroup`` in a classic file, by the definition's own kind in
    a 2021+ one."""
    return set(getattr(_parse_tables, "groups", None) or ())


def kinds_known(legacy: bool) -> bool:
    """Whether the last parse told groups from components: for a classic
    file when its group records are being noted (its instance records say
    which), for a 2021+ one when its definitions carried their kind."""
    if legacy:
        try:
            from openskp import legacy as L
        except Exception:  # noqa: BLE001
            return False
        reader = (getattr(L, "_READERS", None) or {}).get("CGroup")
        return bool(getattr(reader, "_notes_groups", False))
    return bool(getattr(_parse_tables, "kinds", False))


def reset_group_definitions() -> None:
    """Forget the groups of the previous parse — call before parsing."""
    _parse_tables.groups = set()
    _parse_tables.kinds = False
    _parse_tables.vff = None


def _keep_layer_table() -> bool:
    """Wrap ``openskp._core.full_parse`` so the layer id → name table it
    builds outlives the parse (both eras go through it)."""
    try:
        from openskp import _core
    except Exception:  # noqa: BLE001
        return False
    original = getattr(_core, "full_parse", None)
    if original is None or getattr(original, "_keeps_layers", False):
        return False

    def full_parse(*args, **kwargs):
        parsed = original(*args, **kwargs)
        table = (parsed.get("layer_id_to_name")
                 if isinstance(parsed, dict) else None)
        _parse_tables.layers = dict(table or {})
        return parsed

    full_parse._keeps_layers = True
    _core.full_parse = full_parse
    return True


#: Spellings of SketchUp's default tag: a face on it is on no layer.
_DEFAULT_TAGS = ("Layer0", "Layer 0", "Untagged")


def hidden_tags(names) -> frozenset:
    """The hidden tags ``names`` as the geometry may carry them: by name, and
    by the ids the last parse's table gives those names."""
    names = set(names)
    table = getattr(_parse_tables, "layers", None) or {}
    return frozenset(names | {i for i, n in table.items() if n in names})


def resolve_face_layers(model) -> int:
    """Turn the face layers that are tag ids into tag names, from the table
    of the parse that built ``model``. A face on the default tag, or on an
    id the table does not know, gets no layer. Returns how many changed."""
    table = getattr(_parse_tables, "layers", None) or {}
    changed = 0
    for defn in (getattr(model, "definitions", None) or {}).values():
        for face in (getattr(defn, "faces", None) or {}).values():
            lay = getattr(face, "layer", None)
            if isinstance(lay, bool) or not isinstance(lay, int):
                continue
            name = table.get(lay, "")
            face.layer = "" if name in _DEFAULT_TAGS else name
            changed += 1
    return changed


def _keep_vff_annotation_inputs() -> bool:
    """Wrap ``openskp._core._parse_dimensions`` so the VFF annotation
    records can be re-read after the parse: it is the one call that sees
    the raw model bytes together with both resolution tables (vertex
    positions and instance world transforms)."""
    try:
        from openskp import _core
    except Exception:  # noqa: BLE001
        return False
    original = getattr(_core, "_parse_dimensions", None)
    if original is None or getattr(original, "_keeps_vff", False):
        return False

    def _parse_dimensions(model_dat, id2pos, inst_world):
        _parse_tables.vff = (model_dat, id2pos, inst_world)
        return original(model_dat, id2pos, inst_world)

    _parse_dimensions._keeps_vff = True
    _core._parse_dimensions = _parse_dimensions
    return True


def _vff_point(block_payload, id2pos, inst_world):
    """One connection point of a VFF annotation record — the pinned
    reader's own resolution (``_parse_dimensions``' closure, which is not
    importable): type 1 is a free point, anything else resolves the
    ``520B → 53FC`` vertex reference, lifted by the named instance's
    world transform when the reference carries one."""
    from openskp import _core
    blk = _core._tlv_find(_core._tlv_items(block_payload) or [], 0x5208)
    if blk is None:
        return None
    sub = _core._tlv_items(blk) or []
    typ = _core._tlv_find(sub, 0x5209)
    typ = struct.unpack("<I", typ)[0] if typ and len(typ) == 4 else None
    if typ == 1:
        pos = _core._tlv_find(sub, 0x520A)
        return struct.unpack("<3d", pos) if pos and len(pos) == 24 else None
    ref = _core._tlv_find(sub, 0x520B)
    f53fc = _core._tlv_find(_core._tlv_items(ref) or [], 0x53FC) \
        if ref else None
    fi = _core._tlv_items(f53fc) or [] if f53fc else []
    vid = _core._tlv_find(fi, 0x53FD)
    if not vid:
        return None
    local = id2pos.get(vid.hex())
    if local is None:
        return None
    iid = _core._tlv_find(fi, 0x53FE)
    if iid and len(iid) >= 1 and iid[0] > 0 and 1 + iid[0] <= len(iid):
        world = inst_world.get(iid[1:1 + iid[0]].hex())
        if world:
            return _core.transform_point(local, world)
    return local           # no instance named — the owner's local space


def _vff_records(model_dat, marker):
    """Yield ``(offset, fields)`` for each flat-TLV record starting with
    ``marker`` whose body parses and is plausibly sized, in file order —
    the pinned reader's scan shape, shared by dimensions and texts."""
    from openskp import _core
    i, n = 0, len(model_dat)
    while True:
        j = model_dat.find(marker, i)
        if j < 0:
            return
        i = j + 1
        if j + 6 > n:
            continue
        ln = struct.unpack_from("<I", model_dat, j + 2)[0]
        if ln < 40 or j + 6 + ln > n:
            continue
        body = _core._tlv_items(model_dat[j + 6:j + 6 + ln])
        if body is not None:
            yield j, body


def _vff_definition_spans(model_dat):
    """``(start, end)`` byte spans of the file's ``7C15`` definitions, in
    file order, located with the reader's own header machinery (a lone
    ``F401`` wrapper, then the ``F901`` definition-list container). An
    annotation record inside a span belongs to that definition; outside
    every span it is model-level. ``[]`` when the shape is not found."""
    from openskp import _core
    try:
        headers = _core._flat_headers(model_dat, 0, len(model_dat))
        if len(headers) == 1 and headers[0][0] == "F401":
            _, off, size = headers[0]
            headers = _core._flat_headers(model_dat, off + 6, off + 6 + size)
        for tag, off, size in headers:
            if tag == "F901":
                defs = _core._unwrap_definitions_container(
                    model_dat, off, size)
                if defs:
                    return [(o, o + 6 + s) for _t, o, s in defs]
                return []
    except Exception:  # noqa: BLE001 — a shape we do not know: no owners
        return []
    return []


def _vff_owner(spans, offset):
    """Index of the innermost definition span holding ``offset``."""
    best = None
    for idx, (start, end) in enumerate(spans):
        if start <= offset < end and (best is None
                                      or end - start < spans[best][1]
                                      - spans[best][0]):
            best = idx
    return best


def _scan_vff_dimensions(model_dat, id2pos, inst_world):
    """The file's ``5BCC`` dimension records that resolve, in file order,
    each with the constraint axis (``5BD1``) the pinned reader drops."""
    from openskp import _core
    out = []
    for offset, body in _vff_records(model_dat, b"\xcc\x5b"):
        tags = [t for t, _ in body]
        if 0x5BCD not in tags or 0x5BCE not in tags:
            continue
        a = _vff_point(_core._tlv_find(body, 0x5BCD), id2pos, inst_world)
        b = _vff_point(_core._tlv_find(body, 0x5BCE), id2pos, inst_world)
        if a is None or b is None:
            continue
        axis_raw = _core._tlv_find(body, 0x5BD1)
        out.append({
            "offset": offset, "a": a, "b": b,
            "axis": struct.unpack("<I", axis_raw)[0]
                    if axis_raw and len(axis_raw) == 4 else None,
        })
    return out


def _scan_vff_texts(model_dat, id2pos, inst_world):
    """The file's ``55F0`` text records, in file order. ``label_raw`` is
    the stored ``55F5`` triple, whose space the caller settles (see
    :func:`resolve_vff_annotations`)."""
    from openskp import _core
    out = []
    for offset, body in _vff_records(model_dat, b"\xf0\x55"):
        tags = [t for t, _ in body]
        if 0x55F1 not in tags or 0x55F4 not in tags:
            continue
        raw = _core._tlv_find(body, 0x55F1)
        text = raw.decode("utf-8", "replace").strip() if raw else ""
        if not text:
            continue
        point = _vff_point(_core._tlv_find(body, 0x55F4),
                           id2pos, inst_world)
        label = _core._tlv_find(body, 0x55F5)
        hidden = False
        draw = _core._tlv_find(body, 0x07D0)
        if draw:
            flags = _core._tlv_find(_core._tlv_items(draw) or [], 0x07D3)
            if flags:
                hidden = bool(flags[0] & 0x01)
        out.append({
            "offset": offset, "text": text, "point": point,
            "label_raw": struct.unpack("<3d", label)
                         if label and len(label) == 24 else None,
            "hidden": hidden,
        })
    return out


def _vff_label_point(point, label_raw, bbox):
    """Settle the space of a text's stored ``55F5`` triple. Writer-made
    files store the label's absolute position; SketchUp itself stores it
    relative to the anchor (the reporter's staircase: the absolute
    reading puts both labels outside the model, the relative one lands
    each beside its anchor). Prefer whichever lands inside the owner's
    geometry bounds; when both or neither do, take the relative one —
    a label near its anchor beats one outside the model."""
    if label_raw is None:
        return None
    if point is None:
        return label_raw
    delta = tuple(p + d for p, d in zip(point, label_raw))
    if bbox is None:
        return delta
    lo, hi = bbox

    def inside(p):
        return all(lo[k] - 1.0 <= p[k] <= hi[k] + 1.0 for k in range(3))
    if inside(delta) == inside(label_raw):
        return delta
    return delta if inside(delta) else label_raw


def resolve_vff_annotations(model) -> int:
    """Repair the VFF annotations of the parse that built ``model`` (see
    the module docstring): axis-tag the model dimensions, move the
    definition-owned ones onto their definition, and rebuild the leader
    texts the reader never parsed. Returns how many annotations were
    touched; anything whose shape does not line up is left exactly as
    the reader produced it."""
    inputs = getattr(_parse_tables, "vff", None)
    _parse_tables.vff = None
    if not inputs:
        return 0
    model_dat, id2pos, inst_world = inputs
    definitions = list((getattr(model, "definitions", None) or {}).values())
    spans = _vff_definition_spans(model_dat)
    # Span order is definition order only when the counts agree; without
    # that, no ownership is assigned and everything stays model-level.
    owners_known = len(spans) == len(definitions)
    touched = 0

    def owner_defn(offset, root):
        idx = _vff_owner(spans, offset) if owners_known else None
        return definitions[idx] if idx is not None else root

    root = getattr(model, "root", None)

    # Dimensions: the scan resolves with the reader's own logic, so its
    # kept records line up 1:1, in order, with ``model.dimensions``. A
    # count mismatch means the reader changed — leave its output alone.
    model_dims = list(getattr(model, "dimensions", None) or [])
    if model_dims and not any(getattr(d, "dimensions", None)
                              for d in definitions):
        scanned = _scan_vff_dimensions(model_dat, id2pos, inst_world)
        if len(scanned) == len(model_dims):
            moved = {}
            for dm, rec in zip(model_dims, scanned):
                dm.vff_axis = rec["axis"]
                touched += 1
                defn = owner_defn(rec["offset"], None)
                if defn is not None:
                    dm.vff_owned = True
                    moved.setdefault(id(defn), (defn, []))[1].append(dm)
            for defn, dims in moved.values():
                defn.dimensions = list(getattr(defn, "dimensions", None)
                                       or []) + dims
            if moved:
                gone = {id(dm) for _d, dims in moved.values() for dm in dims}
                model.dimensions = [dm for dm in model_dims
                                    if id(dm) not in gone]

    # Texts: only when the reader produced none at all (its VFF text
    # support arriving upstream retires this half on its own).
    has_texts = bool(getattr(root, "texts", None)) or any(
        getattr(d, "texts", None) for d in definitions)
    if root is not None and not has_texts:
        from openskp.model import TextEntity
        for rec in _scan_vff_texts(model_dat, id2pos, inst_world):
            defn = owner_defn(rec["offset"], root)
            verts = (getattr(defn, "vertices", None) or {}).values()
            bbox = None
            if verts:
                pts = [(v.x, v.y, v.z) for v in verts]
                bbox = (tuple(min(p[k] for p in pts) for k in range(3)),
                        tuple(max(p[k] for p in pts) for k in range(3)))
            tx = TextEntity(
                text=rec["text"], hidden=rec["hidden"],
                point=rec["point"],
                label_point=_vff_label_point(rec["point"],
                                             rec["label_raw"], bbox))
            tx.vff_recovered = True
            defn.texts = list(getattr(defn, "texts", None) or []) + [tx]
            touched += 1
    return touched


def _fix_legacy_dimensions(L) -> bool:
    if hasattr(L, "_connection_paths") or not hasattr(L, "_read_dimlinear"):
        return False

    def _path_ref(ar, r):
        # MFC writes an object in full the first time anything points at it:
        # a dimension serialized before the group it is anchored in carries
        # that whole group here. Read it like any object then.
        if _is_new_object(r, r.pos):
            slot, _name, _value = ar.read_object(r)
            return slot
        return L._entity_ref(ar, r)

    def _connection_paths(ar, r):
        extra = L._entity_ref(ar, r)
        lists = []
        for _ in range(2):
            count = r.u32()
            if count > 1000:
                raise L.LegacyParseError(
                    f"implausible dimension path length {r.ctx()}")
            lists.append([_path_ref(ar, r) for _ in range(count)])
        return extra, lists[0], lists[1]

    def _read_dimlinear(ar, r):
        L._preamble(ar, r)
        db = L._drawbase(ar, r)
        text = r.utf16()
        ar.read_object(r, expect='CSkFont')
        b37 = r.raw(37)
        # The connection point itself can be new too: a dimension inside a
        # component, anchored to a vertex the stream has not reached yet,
        # carries that CVertex in full (seen on a .skp of the 2017 version).
        c1 = _path_ref(ar, r)
        path1 = _connection_paths(ar, r)
        b32 = r.raw(32)
        c2 = _path_ref(ar, r)
        path2 = _connection_paths(ar, r)
        b72 = r.raw(72)
        offset = struct.unpack_from('<d', b72, 52)[0]
        out = {'k': 'dimension', 'db': db, 'text': text,
               'connect': (c1, c2), 'paths': (path1, path2),
               'offset': offset}
        if struct.unpack_from('<I', b37, 5)[0] == 1:
            out['a'] = struct.unpack_from('<3d', b37, 13)
        if struct.unpack_from('<I', b32, 0)[0] == 1:
            out['b'] = struct.unpack_from('<3d', b32, 8)
        return out

    L._path_ref = _path_ref
    L._connection_paths = _connection_paths
    L._read_dimlinear = _read_dimlinear
    L._READERS['CDimensionLinear'] = _read_dimlinear
    return True


def _is_new_object(r, pos) -> bool:
    """Whether the MFC tag at ``pos`` starts an object written in full (a
    new class, a class ref, or the escaped form of one)."""
    tag = struct.unpack_from('<H', r.data, pos)[0]
    if tag == 0x7FFF:
        return bool(struct.unpack_from('<I', r.data, pos + 2)[0] & 0x80000000)
    return tag == 0xFFFF or bool(tag & 0x8000)


#: The connection block ahead of an annotation's anchor ref:
#: [u32 type][u32 4][point3d]; type 1 = free point, 2 = anchored.
_CONNECTION = (b'\x01\x00\x00\x00\x04\x00\x00\x00',
               b'\x02\x00\x00\x00\x04\x00\x00\x00')


def _fix_anchored_texts(L) -> bool:
    # co_names, not the source: a frozen build ships no .py to read
    original = getattr(L, "_read_text", None)
    if (original is None or getattr(original, "_reads_anchors", False)
            or "_STR_MARKER" not in original.__code__.co_names):
        return False

    def _read_text(ar, r):
        L._preamble(ar, r)
        db = L._drawbase(ar, r)
        ar.read_object(r, expect='CSkFont')
        start = r.pos
        window = r.data[start:start + 512]
        hits = [i for i in (window.find(c) for c in _CONNECTION) if i >= 0]
        conn = start + min(hits) if hits else None
        after_ref = conn + 34 if conn is not None else None
        if conn is not None and _is_new_object(r, conn + 32):
            r.raw(conn + 32 - r.pos)
            ar.read_object(r)
            after_ref = r.pos
        # variable-length variant middle, delimited by an 11-byte block
        # `01 00 00 00 ?? 00 03 00 00 00 ??` right before the text string
        p = r.pos
        while True:
            idx = r.data.find(L._STR_MARKER, p, r.pos + 512)
            if idx < 0:
                raise L.LegacyParseError(f"text delimiter not found {r.ctx()}")
            blk = r.data[idx - 11:idx]
            arrow = struct.unpack_from('<I', blk, 6)[0]
            if (blk[:4] == b'\x01\x00\x00\x00'
                    and arrow <= 8 and blk[10] in (0, 1)):
                break
            p = idx + 3
        point = None
        label = None
        if conn is not None and conn + 32 <= idx:
            if r.data[conn] == 1:
                point = struct.unpack_from('<3d', r.data, conn + 8)
            # placement tail: [10B ref paths][point3d LABEL]...;
            # all-zero label = screen text
            lo = after_ref + 10
            if lo + 24 <= idx:
                lp = struct.unpack_from('<3d', r.data, lo)
                if any(abs(c) > 1e-12 for c in lp):
                    label = lp
        r.raw(idx - r.pos)
        text = r.utf16()
        r.raw(5)
        attach = []
        while r.peek(2) == b'\xff\x7f':
            val = struct.unpack_from('<I', r.data, r.pos + 2)[0]
            if val & 0x80000000:
                break                    # new-object tag — the next entity
            r.raw(6)
            attach.append(val)
        return {'k': 'text', 'text': text, 'db': db, 'attach': attach,
                'p': point, 'lp': label}

    _read_text._reads_anchors = True
    L._read_text = _read_text
    L._READERS['CText'] = _read_text
    return True


def _fix_definition_list_end(L) -> bool:
    original = getattr(L, "_read_entity_list_inner", None)
    if (original is None or getattr(original, "_ends_at_tail", False)
            or "burn_stack" not in original.__code__.co_names):
        return False

    def _read_entity_list_inner(ar, r, count, owner, ents):
        while len(ents) < count:
            p = r.pos
            if (owner == 'def'
                    and struct.unpack_from('<I', r.data, p)[0] == 0
                    and r.data[p + 22:p + 25] == L._STR_MARKER):
                # the definition tail (nrel=0 + pad + 16-byte GUID + name
                # marker at +22): the list's REAL end, whatever was counted
                break
            prev_flag = ar.in_entity_list
            ar.in_entity_list = True
            try:
                s, n, v = ar.read_object(r)
            except L.LegacyParseError:
                if owner == 'root':
                    # over-declared root counts run into the document tail
                    r.pos = p
                    break
                if owner == 'def' and ar.burn_stack and ar.burn_stack[-1]:
                    r.pos = p
                    break
                raise
            finally:
                ar.in_entity_list = prev_flag
            ents.append((s, n, v))
        return ents

    _read_entity_list_inner._ends_at_tail = True
    L._read_entity_list_inner = _read_entity_list_inner
    return True


def _fix_layer_tail_2019(L) -> bool:
    # A reader that already tells the versions apart in its layer record
    # has the fix: leave it alone.
    original = getattr(L, "_read_layer", None)
    if (original is None or getattr(original, "_long_tail", False)
            or "ver" in original.__code__.co_names):
        return False

    def _read_layer(ar, r):
        rec = original(ar, r)
        if getattr(ar, "ver", None) == 19 and r.peek(2) == b"\x00\x00":
            r.raw(2)
        return rec

    _read_layer._long_tail = True
    L._read_layer = _read_layer
    L._READERS['CLayer'] = _read_layer
    return True
