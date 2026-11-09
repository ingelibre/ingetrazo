# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The run-time fix for legacy dimensions anchored inside groups
(formats/openskp_compat.py; upstream iamahsanmehmood/openskp#384).

A user's .skp house (2018 version) opened with 2 of its 72 root entities: a
dimension anchored to a vertex inside nested groups was read with a fixed
length, and the root reader stopped at the next item. Synthetic bytes —
the user's files are not in the repository."""
from __future__ import annotations

import struct


def big(slot: int) -> bytes:
    return struct.pack('<HI', 0x7FFF, slot)


def test_the_patch_is_installed_and_reads_instance_paths():
    from formats import openskp_compat
    from openskp import legacy as L
    openskp_compat.apply()
    assert hasattr(L, "_connection_paths")
    assert L._READERS['CDimensionLinear'] is L._read_dimlinear
    data = (big(0x0F69CA) + struct.pack('<I', 2) + big(0x166157)
            + big(0x165BBC) + struct.pack('<I', 0) + b'TAIL')
    r = L._R(data, 0)
    extra, p1, p2 = L._connection_paths(None, r)
    assert (extra, p1, p2) == (0x0F69CA, [0x166157, 0x165BBC], [])
    assert data[r.pos:] == b'TAIL'


def test_an_empty_path_is_the_old_fixed_layout():
    """Loose-geometry dimensions — every one that already parsed — keep
    their exact length: a null ref and two empty lists are 10 bytes."""
    from formats import openskp_compat
    from openskp import legacy as L
    openskp_compat.apply()
    r = L._R(b'\x00' * 10 + b'TAIL', 0)
    assert L._connection_paths(None, r) == (None, [], [])
    assert r.pos == 10


def test_apply_is_idempotent_and_leaves_a_fixed_upstream_alone(monkeypatch):
    from formats import openskp_compat
    openskp_compat.apply()
    assert openskp_compat.apply() is False          # second call: no-op
    monkeypatch.setattr(openskp_compat, "_applied", False)
    assert openskp_compat.apply() is False          # upstream has it now


class _Archive:
    """Just enough of the legacy reader's archive for one layer record: no
    attribute container, no persistent ids."""
    has_pid = False

    def __init__(self, ver):
        self.ver = ver

    def read_object(self, r, expect=None):
        return 0, None, None


def _utf16(text: str) -> bytes:
    return b'\xff\xfe\xff' + bytes([len(text)]) + text.encode('utf-16le')


def _layer_record(tail: int) -> bytes:
    """A plain-colour layer record whose fixed tail is ``tail`` bytes."""
    return (_utf16('Layer0') + b'\x00\x00\x00\x00' + _utf16('Layer_Layer0')
            + b'\x00\x01' + b'\xff\x54\x54\xff' + _utf16('')
            + b'\x00' * (tail - 8 - 5) + b'\x00\x00\x00\x00\x00\x00\xe0\x3f'
            + b'\x00' * 5)


def test_a_2019_layer_record_reads_its_two_extra_bytes():
    """#157: from the 2019 version on the layer record ends 23 bytes after
    its last string; reading 21 left the first definition's entity count
    two bytes early, and the castle did not open."""
    from formats import openskp_compat
    from openskp import legacy as L
    openskp_compat.apply()
    data = _layer_record(23) + b'TAIL'
    r = L._R(data, 0)
    rec = L._READERS['CLayer'](_Archive(19), r)
    assert rec['name'] == 'Layer0'
    assert data[r.pos:] == b'TAIL'


def test_older_layer_records_keep_their_length():
    """A 2018 record is 21 bytes long, and two zero bytes after it belong to
    whatever follows — they are not eaten."""
    from formats import openskp_compat
    from openskp import legacy as L
    openskp_compat.apply()
    for ver in (17, 18, 20):
        data = _layer_record(21) + b'\x00\x00TAIL'
        r = L._R(data, 0)
        L._READERS['CLayer'](_Archive(ver), r)
        assert data[r.pos:] == b'\x00\x00TAIL', ver


# ── VFF annotations (#1226) ────────────────────────────────────────────
# Synthetic records in the shapes the scans read: flat TLV fields inside
# a CC 5B / F0 55 record, the definitions inside F401 > F901 > 7017 >
# 7117 > 7C15. The reporter's file is not in the repository.

def _tlv(tag, payload):
    return struct.pack('<HI', tag, len(payload)) + payload


def _free_conn(point):
    inner = _tlv(0x5209, struct.pack('<I', 1)) \
        + _tlv(0x520A, struct.pack('<3d', *point))
    return _tlv(0x5208, inner)


def _record(marker, body):
    return marker + struct.pack('<I', len(body)) + body


def _wrap(tag_bytes, payload):
    return tag_bytes + struct.pack('<I', len(payload)) + payload


def _dim_record(a, b, axis, offset=5.0):
    body = _tlv(0x5BCD, _free_conn(a)) + _tlv(0x5BCE, _free_conn(b)) \
        + _tlv(0x5BCF, struct.pack('<3d', 0, 0, 1)) \
        + _tlv(0x5BD0, struct.pack('<3d', 1, 0, 0)) \
        + _tlv(0x5BD1, struct.pack('<I', axis)) \
        + _tlv(0x5BD2, struct.pack('<d', offset))
    return _record(b'\xcc\x5b', body)


def _text_record(text, point, label_raw):
    body = _tlv(0x55F1, text.encode()) + _tlv(0x55F4, _free_conn(point)) \
        + _tlv(0x55F5, struct.pack('<3d', *label_raw))
    return _record(b'\xf0\x55', body)


def _model_dat_with_definition(*records):
    defs = _wrap(b'\x7c\x15', b''.join(records))
    return _wrap(b'\xf4\x01', _wrap(b'\xf9\x01', _wrap(b'\x70\x17',
                 _wrap(b'\x71\x17', defs))))


def test_vff_scans_read_the_axis_and_the_texts():
    from formats import openskp_compat as C
    dat = _dim_record((0, 0, 0), (100, 0, 0), axis=2) \
        + _text_record('9 steps', (50, 50, 50), (-5, 0, 0))
    dims = C._scan_vff_dimensions(dat, {}, {})
    assert len(dims) == 1
    assert dims[0]['axis'] == 2
    assert dims[0]['a'] == (0, 0, 0) and dims[0]['b'] == (100, 0, 0)
    texts = C._scan_vff_texts(dat, {}, {})
    assert len(texts) == 1
    assert texts[0]['text'] == '9 steps'
    assert texts[0]['point'] == (50, 50, 50)
    assert texts[0]['label_raw'] == (-5, 0, 0)


def test_resolve_moves_owned_annotations_onto_the_definition():
    from types import SimpleNamespace as NS

    from openskp.model import Dimension

    from formats import openskp_compat as C
    dat = _model_dat_with_definition(
        _dim_record((0, 0, 0), (100, 0, 0), axis=1),
        _text_record('9 steps', (50, 50, 50), (-5, 0, 0)))
    defn = NS(vertices={1: NS(x=0, y=0, z=0), 2: NS(x=100, y=100, z=100)},
              dimensions=[], texts=[])
    root = NS(texts=[])
    dm = Dimension(a=(0, 0, 0), b=(100, 0, 0), offset=5.0,
                   plane_x=(0, 0, 1), normal=(1, 0, 0))
    model = NS(definitions={40: defn}, dimensions=[dm], root=root)
    C._parse_tables.vff = (dat, {}, {})
    touched = C.resolve_vff_annotations(model)
    assert touched == 2
    # The dimension left the model list with its axis, on its definition.
    assert model.dimensions == []
    assert defn.dimensions == [dm]
    assert dm.vff_axis == 1 and dm.vff_owned is True
    # The text was rebuilt on the definition; the stored label triple is
    # relative to the anchor here (the absolute reading is off-model).
    assert [t.text for t in defn.texts] == ['9 steps']
    tx = defn.texts[0]
    assert tx.point == (50, 50, 50)
    assert tx.label_point == (45, 50, 50)
    assert tx.vff_recovered is True
    assert root.texts == []
