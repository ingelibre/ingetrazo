"""File ▸ Export ▸ Current view as DXF (José Castro Basso, FADU–UDELAR):
the view on screen as CAD lines, hidden lines removed — parallel on the
composer's layers, perspective and two-point as the window frames them."""
from __future__ import annotations

import math

import numpy as np

from PySide6.QtGui import QVector3D


def _fountain_like(scene):
    """A soft-edged solid of revolution in a group + a loose square."""
    from core.ai import _recipe_helpers
    _recipe_helpers(scene)["revolve"](
        [(0.5, 0.0), (0.6, 0.5), (0.4, 1.0)], segments=24, name="Vaso")
    scene.mesh.add_face([QVector3D(-2, -2, 0), QVector3D(2, -2, 0),
                         QVector3D(2, 2, 0), QVector3D(-2, 2, 0)])
    scene.version += 1


def _lines(path):
    import ezdxf
    return len(ezdxf.readfile(str(path)).modelspace().query("LINE"))


def test_the_view_goes_out_as_dxf_in_every_projection(tmp_path, monkeypatch):
    from views import main_window as mw
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        vp = win.viewport
        vp.resize(800, 600)
        vp.camera.set_aspect(800, 600)
        _fountain_like(vp.scene)
        lo, hi = vp.scene.bounds()
        vp.camera.fit_to(lo, hi, 1.2)
        out = {}
        for mode in ("parallel", "perspective", "two_point"):
            vp.camera.perspective = mode != "parallel"
            vp.camera.two_point = mode == "two_point"
            path = tmp_path / f"{mode}.dxf"
            monkeypatch.setattr(mw.file_dialogs, "getSaveFileName",
                                lambda *a, p=path, **k: (str(p), ""))
            win._on_export_view_dxf()
            out[mode] = _lines(path)
        assert all(n > 20 for n in out.values()), out
        import ezdxf
        layers = ezdxf.readfile(str(tmp_path / "parallel.dxf")).layers
        assert "VISTA-PERFIL" in layers
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()


def test_perspective_reads_the_same_from_the_caches_and_the_walk():
    from core.hlr import hlr_perspective
    from views.main_window import MainWindow

    win = MainWindow()
    try:
        vp = win.viewport
        vp.resize(800, 600)
        vp.camera.set_aspect(800, 600)
        _fountain_like(vp.scene)
        cam = vp.camera
        cam.yaw, cam.pitch = math.radians(-50.0), math.radians(20.0)
        a = hlr_perspective(vp.scene, cam, geometry=vp.hlr_geometry())
        b = hlr_perspective(vp.scene, cam)
        la = np.hypot(a[:, 2] - a[:, 0], a[:, 3] - a[:, 1]).sum()
        lb = np.hypot(b[:, 2] - b[:, 0], b[:, 3] - b[:, 1]).sum()
        assert la > 0 and abs(la - lb) < 1e-6 * max(la, 1.0)
    finally:
        win._saved_version = win.viewport.scene.version
        win.close()
