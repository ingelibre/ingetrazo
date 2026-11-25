# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""The macOS thumbnail extension reads the picture an .igz carries (#1380).

``packaging/macos/thumbnail`` is Swift. Its reading and decoding are built
here into a small command-line tool (``check/main.swift``), which is handed
the documents IngeTrazo saves and some it never would. It must give
exactly the bytes ``formats.igz.read_thumbnail`` gives, and nothing for
what Finder should show as the plain document icon. macOS only, and only
where ``swiftc`` is there (the Command Line Tools)."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide6.QtGui import QVector3D as V  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core.scene import Scene  # noqa: E402
from formats import igz  # noqa: E402
from views.document_thumbnail import png_bytes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "packaging" / "macos" / "thumbnail"

pytestmark = pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("swiftc") is None,
    reason="macOS with the Swift compiler only")

_app = QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def check(tmp_path_factory):
    tool = tmp_path_factory.mktemp("swift") / "igz-thumbnail-check"
    subprocess.run(
        ["swiftc", "-O", "-framework", "QuickLookThumbnailing",
         str(SRC / "check" / "main.swift"),
         str(SRC / "ThumbnailProvider.swift"), str(SRC / "IgzThumbnail.swift"),
         "-o", str(tool)],
        check=True, capture_output=True, timeout=300)

    def run(doc: Path):
        """``(bytes, "WxH")`` the extension shows for ``doc``, or ``None``."""
        out = doc.with_suffix(".out.png")
        r = subprocess.run([str(tool), str(doc), str(out)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return None
        return out.read_bytes(), r.stdout.strip()
    run.tool = tool
    return run


@pytest.fixture
def check_drawn(check):
    def run(doc: Path) -> Path:
        """The picture as the extension draws it at twice its size."""
        drawn = doc.with_suffix(".drawn.png")
        subprocess.run([str(check.tool), str(doc),
                        str(doc.with_suffix(".out.png")), str(drawn)],
                       check=True, capture_output=True, timeout=60)
        return drawn
    return run


def _png(w=512, h=512) -> bytes:
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(QColor(230, 236, 245))
    p = QPainter(img)
    p.fillRect(w // 5, h // 3, w // 2, h // 3, QColor(200, 90, 60))
    p.end()
    return png_bytes(img)


def _scene():
    sc = Scene()
    sc.mesh.add_face([V(0, 0, 0), V(1, 0, 0), V(1, 1, 0), V(0, 1, 0)])
    return sc


def test_a_saved_picture_is_shown_byte_for_byte(check, tmp_path):
    doc = tmp_path / "model.igz"
    igz.save_scene(_scene(), doc, thumbnail=_png())
    got = check(doc)
    assert got is not None
    assert got[0] == igz.read_thumbnail(doc)
    assert got[1] == "512x512"


def test_the_picture_fills_a_retina_thumbnail(check_drawn, tmp_path):
    # The thumbnail's context is in pixels, the size asked for times the
    # screen's scale. Drawn at the size asked for, the picture took its
    # lower-left quarter only.
    doc = tmp_path / "model.igz"
    igz.save_scene(_scene(), doc, thumbnail=_png(300, 200))
    drawn = QImage(str(check_drawn(doc)))
    assert (drawn.width(), drawn.height()) == (600, 400)
    background = QColor(230, 236, 245)
    for x, y in ((2, 2), (597, 2), (2, 397), (597, 397)):   # every corner
        px = drawn.pixelColor(x, y)
        assert px.alpha() == 255, (x, y)
        assert abs(px.red() - background.red()) <= 2, (x, y)
    assert drawn.pixelColor(300, 200) == QColor(200, 90, 60)   # the middle


def test_documents_without_a_picture_show_the_icon(check, tmp_path):
    no_picture = tmp_path / "plain.igz"
    igz.save_scene(_scene(), no_picture, thumbnail=None)
    plain_json = tmp_path / "text.igz"
    plain_json.write_text('{"format": 1}')
    cut = tmp_path / "cut.igz"
    igz.save_scene(_scene(), tmp_path / "whole.igz", thumbnail=_png())
    cut.write_bytes((tmp_path / "whole.igz").read_bytes()[:-30])
    empty = tmp_path / "empty.igz"
    empty.write_bytes(b"")
    for doc in (no_picture, plain_json, cut, empty):
        assert check(doc) is None, doc.name


def test_only_a_stored_png_within_the_limits(check, tmp_path):
    def zipped(name, data, method=zipfile.ZIP_STORED):
        doc = tmp_path / name
        with zipfile.ZipFile(doc, "w", method) as z:
            z.writestr("scene.json", "{}")
            z.writestr("thumbnail.png", data)
        return doc
    # IngeTrazo stores the picture; a deflated one is not read (as on Windows).
    assert check(zipped("deflated.igz", _png(), zipfile.ZIP_DEFLATED)) is None
    assert check(zipped("not_png.igz", b"GIF89a" + bytes(64))) is None
    assert check(zipped("too_wide.igz", _png(5000, 8))) is None
    big = _png() + bytes(8 << 20)                   # past 8 MB
    assert check(zipped("too_big.igz", big)) is None
    assert check(zipped("fine.igz", _png(300, 200)))[1] == "300x200"


def test_a_long_archive_comment_and_zip64(check, tmp_path):
    png = _png(64, 64)
    commented = tmp_path / "commented.igz"
    with zipfile.ZipFile(commented, "w") as z:
        z.writestr("scene.json", "{}")
        z.writestr("thumbnail.png", png)
        z.comment = b"x" * 60000
    assert check(commented)[0] == png
    # Over 65535 members: the end record points at the ZIP64 one.
    many = tmp_path / "many.igz"
    with zipfile.ZipFile(many, "w") as z:
        for i in range(0x10000):
            z.writestr(f"m/{i}", b"")
        z.writestr("thumbnail.png", png)
    assert check(many)[0] == png


def test_the_extension_and_the_app_name_the_same_type():
    plist = (SRC / "Info.plist").read_text()
    spec = (ROOT / "ingetrazo.spec").read_text()
    supported = re.findall(
        r"<key>QLSupportedContentTypes</key>\s*<array>\s*<string>([^<]+)",
        plist)
    assert supported == ["com.ingetrazo.igz"]
    assert "'UTTypeIdentifier': 'com.ingetrazo.igz'" in spec
    assert "'LSItemContentTypes': ['com.ingetrazo.igz']" in spec
