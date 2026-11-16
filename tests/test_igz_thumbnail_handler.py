# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The Windows thumbnail handler of .igz (installer/thumbnail): the DLL
the file manager asks for the picture of a document.

Driven here the way the shell drives it — DllGetClassObject → the class
factory → IInitializeWithStream on a stream over the file →
IThumbnailProvider::GetThumbnail — through ctypes, with documents built by
formats.igz. Only on Windows, and only once the DLL is built
(installer\\thumbnail\\build.cmd); elsewhere the file is skipped."""
from __future__ import annotations

import ctypes
import io
import json
import os
import sys
import uuid
import zipfile
from ctypes import wintypes
from pathlib import Path

import pytest

if sys.platform != "win32":
    pytest.skip("the thumbnail handler is a Windows DLL", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[1]
DLL = Path(os.environ.get(
    "INGETRAZO_THUMBNAIL_DLL",
    ROOT / "installer" / "thumbnail" / "build" / "ingetrazo-thumbnail.dll"))
if not DLL.is_file():
    pytest.skip(f"not built: {DLL} (installer\\thumbnail\\build.cmd)",
                allow_module_level=True)

from PySide6.QtGui import QColor, QImage, QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402
from views import document_thumbnail  # noqa: E402

_app = QApplication.instance() or QApplication([])

CLSID = "78547A98-072B-4C96-98A2-EFE80F7C48FA"
IID_IClassFactory = "00000001-0000-0000-C000-000000000046"
IID_IInitializeWithStream = "B824B49D-22AC-4161-AC8A-9916E8FA3F7F"
IID_IThumbnailProvider = "E357FCCD-A995-4576-B01F-234630154E96"
WTSAT_ARGB = 2
STGM_READ = 0
STGM_SHARE_DENY_WRITE = 0x20

HRESULT = ctypes.c_long


class GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_ubyte * 16)]

    @classmethod
    def of(cls, text: str) -> "GUID":
        g = cls()
        ctypes.memmove(g.data, uuid.UUID(text).bytes_le, 16)
        return g


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


_ole32 = ctypes.OleDLL("ole32")
_ole32.CoInitializeEx.restype = HRESULT
_shlwapi = ctypes.WinDLL("shlwapi")
_shlwapi.SHCreateStreamOnFileEx.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.BOOL,
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_shlwapi.SHCreateStreamOnFileEx.restype = HRESULT
_gdi32 = ctypes.WinDLL("gdi32")
_gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
_handler = ctypes.WinDLL(str(DLL))
_handler.DllGetClassObject.argtypes = [ctypes.POINTER(GUID), ctypes.POINTER(GUID),
                                       ctypes.POINTER(ctypes.c_void_p)]
_handler.DllGetClassObject.restype = HRESULT
_handler.DllCanUnloadNow.restype = HRESULT

try:
    _ole32.CoInitializeEx(None, 2)       # apartment, as the shell's host
except OSError:
    pass                                 # already initialised another way


def _method(obj, index, *argtypes):
    """Method ``index`` of the COM object ``obj``'s vtable, callable."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(HRESULT, ctypes.c_void_p, *argtypes)
    fn = proto(vtbl[index])
    return lambda *args: fn(obj, *args)


def _release(obj):
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    ctypes.WINFUNCTYPE(wintypes.ULONG, ctypes.c_void_p)(vtbl[2])(obj)


def thumbnail(path: Path, cx: int = 256):
    """``(hresult, width, height, alpha, bgra bytes)`` the handler gives
    for the file at ``path``: what the file manager would show."""
    factory = ctypes.c_void_p()
    hr = _handler.DllGetClassObject(ctypes.byref(GUID.of(CLSID)),
                                    ctypes.byref(GUID.of(IID_IClassFactory)),
                                    ctypes.byref(factory))
    assert hr == 0, hex(hr & 0xFFFFFFFF)
    init = ctypes.c_void_p()
    hr = _method(factory, 3, ctypes.c_void_p, ctypes.POINTER(GUID),
                 ctypes.POINTER(ctypes.c_void_p))(
        None, ctypes.byref(GUID.of(IID_IInitializeWithStream)),
        ctypes.byref(init))
    assert hr == 0, hex(hr & 0xFFFFFFFF)
    stream = ctypes.c_void_p()
    hr = _shlwapi.SHCreateStreamOnFileEx(
        str(path), STGM_READ | STGM_SHARE_DENY_WRITE, 0, False, None,
        ctypes.byref(stream))
    assert hr == 0, hex(hr & 0xFFFFFFFF)
    provider = ctypes.c_void_p()
    try:
        hr = _method(init, 3, ctypes.c_void_p, wintypes.DWORD)(stream, STGM_READ)
        assert hr == 0, hex(hr & 0xFFFFFFFF)
        hr = _method(init, 0, ctypes.POINTER(GUID),
                     ctypes.POINTER(ctypes.c_void_p))(
            ctypes.byref(GUID.of(IID_IThumbnailProvider)),
            ctypes.byref(provider))
        assert hr == 0, hex(hr & 0xFFFFFFFF)
        bitmap = wintypes.HANDLE()
        alpha = ctypes.c_int(-1)
        hr = _method(provider, 3, wintypes.UINT, ctypes.POINTER(wintypes.HANDLE),
                     ctypes.POINTER(ctypes.c_int))(
            cx, ctypes.byref(bitmap), ctypes.byref(alpha))
        if hr < 0:
            assert not bitmap.value
            return hr, 0, 0, alpha.value, b""
        bm = BITMAP()
        assert _gdi32.GetObjectW(bitmap, ctypes.sizeof(bm), ctypes.byref(bm))
        pixels = ctypes.string_at(bm.bmBits, bm.bmWidthBytes * bm.bmHeight)
        _gdi32.DeleteObject(bitmap)
        return hr, bm.bmWidth, bm.bmHeight, alpha.value, pixels
    finally:
        for obj in (provider, stream, init, factory):
            if obj.value:
                _release(obj)


def _png(w, h, color) -> bytes:
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(color))
    return document_thumbnail.png_bytes(img)


def _scene() -> Scene:
    V = QVector3D
    scene = Scene()
    scene.mesh.add_face([V(0, 0, 0), V(2, 0, 0), V(2, 2, 0), V(0, 2, 0)])
    scene.version += 1
    return scene


def _pixel(pixels, width, x, y):
    i = (y * width + x) * 4
    b, g, r, a = pixels[i:i + 4]
    return r, g, b, a


def test_a_saved_document_gives_its_picture_fitted_to_the_size_asked(tmp_path):
    path = tmp_path / "model.igz"
    igz.save_scene(_scene(), path, thumbnail=_png(512, 512, "#c83c28"))
    hr, w, h, alpha, pixels = thumbnail(path, 256)
    assert hr == 0
    assert (w, h) == (256, 256)
    assert alpha == WTSAT_ARGB
    r, g, b, a = _pixel(pixels, w, 128, 128)
    assert (abs(r - 0xc8), abs(g - 0x3c), abs(b - 0x28)) < (3, 3, 3)
    assert a == 255


def test_the_picture_keeps_its_shape_and_is_never_enlarged(tmp_path):
    path = tmp_path / "wide.igz"
    igz.save_scene(_scene(), path, thumbnail=_png(200, 100, "#2a6"))
    assert thumbnail(path, 256)[1:3] == (200, 100)
    assert thumbnail(path, 64)[1:3] == (64, 32)


def test_a_big_document_gives_its_picture_beside_the_model(tmp_path):
    """The picture is found through the central directory, wherever the
    model's members sit (megabytes of them, before and after it)."""
    path = tmp_path / "big.igz"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("document.json", json.dumps({"igz_format": 3, "scene": {}}))
        z.writestr("geom/0000.bin", os.urandom(3 << 20))
        info = zipfile.ZipInfo(igz.THUMBNAIL_ENTRY)
        info.compress_type = zipfile.ZIP_STORED
        z.writestr(info, _png(64, 64, "#00f"))
        z.writestr("textures/x.png", os.urandom(1 << 20))
    hr, w, h, _a, pixels = thumbnail(path)
    assert hr == 0 and (w, h) == (64, 64)
    assert _pixel(pixels, w, 10, 10)[:3] == (0, 0, 255)


def test_documents_without_a_picture_give_none(tmp_path):
    plain = tmp_path / "plain.igz"
    igz.save_scene(_scene(), plain)              # plain JSON
    container = tmp_path / "old.igz"
    with zipfile.ZipFile(container, "w") as z:
        z.writestr("document.json", "{}")
    for path in (plain, container):
        hr, w, h, _a, _p = thumbnail(path)
        assert hr < 0 and (w, h) == (0, 0)


def test_damaged_or_crafted_files_give_none(tmp_path):
    cases = {}
    cases["empty"] = b""
    cases["junk"] = b"PK\x03\x04" + os.urandom(4000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(igz.THUMBNAIL_ENTRY, _png(32, 32, "#888"),
                   compress_type=zipfile.ZIP_DEFLATED)
    cases["deflated"] = buf.getvalue()           # never written that way
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(igz.THUMBNAIL_ENTRY, b"\x89PNG\r\n\x1a\n" + os.urandom(500))
    cases["broken_png"] = buf.getvalue()
    good = io.BytesIO()
    with zipfile.ZipFile(good, "w") as z:
        z.writestr(igz.THUMBNAIL_ENTRY, _png(32, 32, "#888"))
    data = bytearray(good.getvalue())
    cases["truncated"] = bytes(data[:len(data) // 2]) + bytes(data[-22:])
    shifted = bytearray(data)
    end = shifted.rfind(b"PK\x05\x06")
    shifted[end + 16:end + 20] = (len(shifted) + 1000).to_bytes(4, "little")
    cases["directory_past_the_end"] = bytes(shifted)
    huge = bytearray(data)
    cd = huge.find(b"PK\x01\x02")
    huge[cd + 20:cd + 28] = (0xFFFFFFF0).to_bytes(4, "little") * 2
    cases["size_past_the_end"] = bytes(huge)
    for name, raw in cases.items():
        path = tmp_path / f"{name}.igz"
        path.write_bytes(raw)
        hr, w, h, _a, _p = thumbnail(path)
        assert hr < 0 and (w, h) == (0, 0), name


def test_the_dll_can_unload_once_nothing_holds_it(tmp_path):
    path = tmp_path / "model.igz"
    igz.save_scene(_scene(), path, thumbnail=_png(32, 32, "#123"))
    thumbnail(path)
    assert _handler.DllCanUnloadNow() == 0
