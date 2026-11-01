# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""A paper-space layout missing from the layout dictionary (Windows round
0.6.0: a 14 MB DWG converted fine, then failed with «'OF-01'»).

MTEXT columns on that layout made ezdxf raise a bare KeyError while
loading, in its strict reader and in recover mode alike. The import now
reads the drawing, model space intact."""
from __future__ import annotations

import pytest

ezdxf = pytest.importorskip("ezdxf")

from core.scene import Scene                              # noqa: E402
from formats.dxf_in import load_dxf, open_document         # noqa: E402


def _bruised(tmp_path):
    """A drawing with a line in model space and MTEXT columns on a paper
    layout «OF-01» that the layout dictionary no longer lists."""
    doc = ezdxf.new("R2013")
    doc.modelspace().add_line((0, 0, 0), (5, 0, 0))
    ps = doc.layouts.new("OF-01")
    ps.add_mtext_static_columns(["uno", "dos"], width=5, gutter_width=1,
                                height=10)
    ok = tmp_path / "ok.dxf"
    doc.saveas(str(ok))
    doc = ezdxf.readfile(str(ok))
    doc.rootdict["ACAD_LAYOUT"].discard("OF-01")
    out = tmp_path / "of-01.dxf"
    doc.saveas(str(out))
    return out


def test_ezdxf_alone_still_fails_on_it(tmp_path):
    """The file is the bruise: plain ezdxf cannot read it (if a future
    ezdxf can, this test says the workaround may go)."""
    path = _bruised(tmp_path)
    with pytest.raises(KeyError):
        ezdxf.readfile(str(path))


def test_open_document_reads_it(tmp_path):
    doc = open_document(_bruised(tmp_path))
    assert [e.dxftype() for e in doc.modelspace()] == ["LINE"]


def test_the_import_brings_the_model_space_in(tmp_path):
    scene = Scene()
    load_dxf(scene, _bruised(tmp_path))
    edges = [e for g in scene.groups for e in g.mesh.edges] \
        if scene.groups else list(scene.mesh.edges)
    assert edges, "the model-space line did not arrive"


def test_the_lookup_is_put_back_afterwards(tmp_path):
    from ezdxf.layouts.layouts import Layouts
    before = Layouts.get_layout_by_key
    open_document(_bruised(tmp_path))
    assert Layouts.get_layout_by_key is before


def test_a_sound_drawing_reads_as_before(tmp_path):
    doc = ezdxf.new("R2013")
    doc.modelspace().add_line((0, 0, 0), (1, 0, 0))
    doc.layouts.new("OF-01")
    out = tmp_path / "sano.dxf"
    doc.saveas(str(out))
    assert open_document(out).layouts.names() == ["Model", "Layout1", "OF-01"]
