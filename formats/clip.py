"""Copy and paste between IngeTrazo windows (issue #76).

The model clipboard lives on the viewport (``viewport.clipboard``), so it
never left the process: with two IngeTrazo windows open side by side,
Ctrl+C in one and Ctrl+V in the other pasted nothing. Copy now also offers
the clipboard on the SYSTEM clipboard under :data:`MIME`, and Paste adopts
it when it came from another window.

The payload is a small zip: ``clip.json`` (reference point and the loose
edges) plus ``scene.igz``, a throwaway document holding the copied faces and
groups — written by the regular ``.igz`` writer, so materials, textures,
component definitions and group axes travel exactly as they do in a file.

Encoding is LAZY: :class:`ClipMime` builds the bytes only when another
application asks for them (Qt's delayed rendering), so Ctrl+C on a big
hedge costs nothing extra in the window that copies. A paste in the same
window sees its own :class:`ClipMime` and keeps the in-memory clipboard.
"""
from __future__ import annotations

import io
import json
import tempfile
import zipfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QMimeData
from PySide6.QtGui import QVector3D

MIME = "application/x-ingetrazo-clipboard"
_FORMAT = 1


def _xyz(p: QVector3D) -> list:
    return [p.x(), p.y(), p.z()]


def encode(clip: dict) -> bytes:
    """``viewport.clipboard`` → bytes for the system clipboard."""
    from core.scene import Scene
    from formats import igz

    scene = Scene()
    for loop, holes, *rest in clip.get("faces", ()):
        try:
            face = scene.mesh.add_face(loop, holes or None)
        except ValueError:
            continue
        attrs = rest[0] if rest else None
        if attrs:
            face.attrs = dict(attrs)
    scene.groups.extend(clip.get("groups", ()))
    head = {
        "format": _FORMAT,
        "ref": _xyz(clip["ref"]),
        "edges": [[_xyz(a), _xyz(b), bool(soft), curve]
                  for a, b, soft, curve in clip.get("edges", ())],
    }
    with tempfile.TemporaryDirectory(prefix="ingetrazo-clip-") as tmp:
        path = Path(tmp) / "scene.igz"
        igz.save_scene(scene, path)
        doc = path.read_bytes()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:
        z.writestr("clip.json", json.dumps(head))
        z.writestr("scene.igz", doc)
    return out.getvalue()


def decode(data: bytes) -> dict | None:
    """Bytes from the system clipboard → a ``viewport.clipboard`` dict, or
    ``None`` when they are not a clipboard this version can read."""
    from core.scene import Scene
    from formats import igz

    try:
        from core import zip_limits
        with zipfile.ZipFile(io.BytesIO(bytes(data))) as z:
            zip_limits.check(z, "the clipboard")
            head = json.loads(z.read("clip.json"))
            doc = z.read("scene.igz")
    except (zipfile.BadZipFile, KeyError, ValueError):
        return None
    if head.get("format") != _FORMAT:
        return None
    scene = Scene()
    with tempfile.TemporaryDirectory(prefix="ingetrazo-clip-") as tmp:
        path = Path(tmp) / "scene.igz"
        path.write_bytes(doc)
        igz.load_into(scene, path)
    faces = [([QVector3D(v) for v in f.vertices],
              [[QVector3D(v) for v in h] for h in f.holes],
              dict(f.attrs) if f.attrs else {})
             for f in scene.mesh.faces]
    edges = [(QVector3D(*a), QVector3D(*b), soft, curve)
             for a, b, soft, curve in head.get("edges", ())]
    # Pasted copies of a classic group share one definition until edited,
    # as with a local copy (``Viewport.copy_selection``).
    from PySide6.QtGui import QMatrix4x4
    for g in scene.groups:
        if getattr(g, "xform", None) is None:
            g.xform = QMatrix4x4()
            g.component = False       # a group still (issue #90)
    return {"faces": faces, "edges": edges, "groups": list(scene.groups),
            "ref": QVector3D(*head["ref"])}


class ClipMime(QMimeData):
    """The system-clipboard entry of one Copy: :data:`MIME` rendered on
    demand from the clipboard dict it was made for."""

    def __init__(self, clip: dict):
        super().__init__()
        self.clip = clip
        self._bytes: QByteArray | None = None

    def formats(self):
        return [MIME]

    def hasFormat(self, mime: str) -> bool:
        return mime == MIME

    def retrieveData(self, mime, _type):
        if mime != MIME:
            return None
        if self._bytes is None:
            try:
                self._bytes = QByteArray(encode(self.clip))
            except Exception:  # noqa: BLE001 - never crash the app from here
                self._bytes = QByteArray()
        return self._bytes


def publish(clip: dict) -> None:
    """Offer ``clip`` on the system clipboard (after a Copy/Cut)."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    if not getattr(app, "_clip_flush_hooked", False):
        app._clip_flush_hooked = True
        app.aboutToQuit.connect(flush)
    QApplication.clipboard().setMimeData(ClipMime(clip))


def flush() -> None:
    """On quit, trade our lazy offer for plain data: the copy then survives
    this window closing (another window can still paste it), and no Python
    subclass is left inside Qt's clipboard while the interpreter tears down
    — the CI run of 9393ef5 passed every test and still exited with a
    segfault."""
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        return
    cb = QApplication.clipboard()
    md = cb.mimeData()
    if not isinstance(md, ClipMime):
        return
    try:
        data = md.retrieveData(MIME, None)
    except Exception:  # noqa: BLE001 - quitting: never raise from here
        data = None
    plain = QMimeData()
    if data is not None and len(data):
        plain.setData(MIME, data)
    cb.setMimeData(plain)


def foreign() -> dict | None:
    """The clipboard another IngeTrazo window copied, decoded — or ``None``
    when the system clipboard holds this window's own copy, or no model
    clipboard at all."""
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        return None
    md = QApplication.clipboard().mimeData()
    if md is None or isinstance(md, ClipMime) or not md.hasFormat(MIME):
        return None
    return decode(md.data(MIME).data())


def available() -> bool:
    """True when the system clipboard offers a model clipboard (this
    window's or another's) — for enabling Paste."""
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        return False
    md = QApplication.clipboard().mimeData()
    return md is not None and md.hasFormat(MIME)
