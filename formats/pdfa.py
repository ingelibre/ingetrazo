# SPDX-License-Identifier: GPL-3.0-or-later
"""Normalize Qt's XMP metadata without rasterizing the sheet.

Qt 6.11 writes pdf:Trapped, which is not a predefined XMP 2004 property.
Keep the PDF Info /Trapped entry and remove only its invalid XMP duplicate.
Every resulting file still goes through veraPDF before delivery.
"""
from pathlib import Path
import os
import tempfile
import xml.etree.ElementTree as ET


def write_quality_pdf(html, path):
    from PySide6.QtGui import QPdfWriter, QPagedPaintDevice, QPageSize, QTextDocument
    writer = QPdfWriter(str(path))
    writer.setPdfVersion(QPagedPaintDevice.PdfVersion_A1b)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setTitle("Model kalite kontrolü — EK-9")
    writer.setCreator("IngeTrazo")
    document = QTextDocument()
    document.setHtml(html)
    document.print_(writer)
    del writer
    normalize_qt_metadata(path)


def normalize_qt_metadata(path):
    try:
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, NameObject
    except ImportError as exc:
        raise ValueError("Install requirements-delivery.txt to create validated PDF/A sheets") from exc
    path = Path(path)
    writer = PdfWriter(clone_from=path)
    metadata = writer.root_object.get("/Metadata")
    if metadata is None:
        raise ValueError("Archival PDF has no XMP metadata")
    root = ET.fromstring(metadata.get_object().get_data())
    ET.register_namespace("pdfaid", "http://www.aiim.org/pdfa/ns/id/")
    for node in root.iter():
        node.attrib.pop("{http://ns.adobe.com/pdf/1.3/}Trapped", None)
    stream = DecodedStreamObject()
    stream.set_data(ET.tostring(root, encoding="utf-8", xml_declaration=True))
    stream[NameObject("/Type")] = NameObject("/Metadata")
    stream[NameObject("/Subtype")] = NameObject("/XML")
    writer.root_object[NameObject("/Metadata")] = writer._add_object(stream)
    handle, temporary = tempfile.mkstemp(prefix=".pdfa-", suffix=".pdf", dir=path.parent)
    os.close(handle)
    try:
        writer.write(temporary)
        writer.close()
        os.replace(temporary, path)
    finally:
        writer.close()
        Path(temporary).unlink(missing_ok=True)
