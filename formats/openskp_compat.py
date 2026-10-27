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

All patches are detected by BEHAVIOUR, not by version: once the upstream
reader carries ``_connection_paths`` the first is left alone, the second
only touches a face layer that is still a number, and the last two step
aside once the text reader no longer scans for the delimiter and the list
reader no longer ties the tail check to burns.
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
    texts = _fix_anchored_texts(L)
    lists = _fix_definition_list_end(L)
    return _fix_legacy_dimensions(L) or layers or texts or lists


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
