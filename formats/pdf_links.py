# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Links between the pages of a PDF that Qt wrote (#1695).

``QPdfWriter`` writes links to web addresses only: a click on a row of the
sheet index cannot take the reader to the sheet's page. This module adds
those links after the fact, as an *incremental update* of the file: the
bytes Qt wrote stay as they are, and after them come the new ``/Link``
annotations, the page objects (or their ``/Annots`` arrays) that list them,
a new cross-reference section pointing back at Qt's (``/Prev``) and a new
trailer. A reader that understands PDF — every one does — sees the links;
the pages themselves do not change.

It reads only what Qt writes: a classic cross-reference table, a ``/Pages``
tree from the catalog, page dictionaries in plain text. Anything else
(a cross-reference stream, object streams, an encrypted file) is left
alone: :func:`add_links` says so by returning ``False`` and the PDF is
still a good PDF, only without links.

No third-party library: this runs on every desktop build, not only where
the PDF/A extras (pypdf) are installed.
"""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Points per millimetre.
PT_PER_MM = 72.0 / 25.4


@dataclass(frozen=True)
class PdfLink:
    """A clickable area on page ``page`` (from 0) that opens page
    ``target``. ``rect`` is ``(x0, y0, x1, y1)`` in PDF points, origin at
    the bottom left of the page; ``title`` is what a screen reader or a
    hover says (``/Contents``)."""

    page: int
    rect: tuple
    target: int
    title: str = ""


def mm_rect_to_pdf(rect_mm, origin_pt, page_h_pt) -> tuple:
    """A rectangle ``(x, y, w, h)`` in sheet millimetres (origin at the top
    left of what the painter paints) as ``(x0, y0, x1, y1)`` in PDF points:
    ``origin_pt`` is where the painter's origin sits on the page (the
    writer's margins), ``page_h_pt`` the page's height — PDF counts up from
    the bottom."""
    x, y, w, h = rect_mm
    ox, oy = origin_pt
    x0 = ox + x * PT_PER_MM
    x1 = ox + (x + w) * PT_PER_MM
    top = page_h_pt - (oy + y * PT_PER_MM)
    bottom = page_h_pt - (oy + (y + h) * PT_PER_MM)
    return (round(x0, 3), round(bottom, 3), round(x1, 3), round(top, 3))


# ---- Reading what Qt wrote ----------------------------------------------------

def _find_object(data: bytes, num: int) -> bytes | None:
    """The body of object ``num`` (between ``obj`` and ``endobj``) — the
    last one in the file, as an update would have it."""
    body = None
    for m in re.finditer(rb"(?<![0-9])%d\s+0\s+obj\b" % num, data):
        end = data.find(b"endobj", m.end())
        if end < 0:
            return None
        body = data[m.end():end]
    return body


def _trailer(data: bytes) -> dict | None:
    """``{"size", "root", "info", "id", "startxref"}`` of the last trailer,
    or ``None`` when the file has no classic one (a cross-reference
    stream: not Qt's, not ours to touch)."""
    sx = data.rfind(b"startxref")
    tr = data.rfind(b"trailer", 0, sx if sx >= 0 else len(data))
    if sx < 0 or tr < 0:
        return None
    m = re.match(rb"startxref\s+(\d+)", data[sx:])
    if not m:
        return None
    head = data[tr:sx]
    size = re.search(rb"/Size\s+(\d+)", head)
    root = re.search(rb"/Root\s+(\d+)\s+0\s+R", head)
    if not (size and root):
        return None
    if b"/Encrypt" in head:
        return None
    info = re.search(rb"/Info\s+(\d+)\s+0\s+R", head)
    ident = re.search(rb"/ID\s*(\[[^\]]*\])", head)
    return {"size": int(size.group(1)), "root": int(root.group(1)),
            "info": int(info.group(1)) if info else None,
            "id": ident.group(1) if ident else None,
            "startxref": int(m.group(1))}


def _ref(body: bytes, key: bytes) -> int | None:
    m = re.search(rb"/%s\s+(\d+)\s+0\s+R" % key, body)
    return int(m.group(1)) if m else None


def page_objects(data: bytes) -> list | None:
    """The object numbers of the pages, in reading order, walking the
    ``/Pages`` tree from the catalog; ``None`` if the file is not one this
    module reads."""
    tr = _trailer(data)
    if tr is None:
        return None
    root = _find_object(data, tr["root"])
    if root is None:
        return None
    top = _ref(root, b"Pages")
    if top is None:
        return None
    out: list = []
    seen: set = set()

    def walk(num: int) -> bool:
        if num in seen:
            return False
        seen.add(num)
        body = _find_object(data, num)
        if body is None:
            return False
        if re.search(rb"/Type\s*/Pages\b", body):
            kids = re.search(rb"/Kids\s*\[([^\]]*)\]", body)
            if not kids:
                return False
            for k in re.findall(rb"(\d+)\s+0\s+R", kids.group(1)):
                if not walk(int(k)):
                    return False
            return True
        if re.search(rb"/Type\s*/Page\b", body):
            out.append(num)
            return True
        return False

    return out if walk(top) else None


# ---- Writing the update --------------------------------------------------------

def _pdf_text(text: str) -> bytes:
    """A PDF text string: UTF-16BE with its mark, in hex — any language,
    no escaping to get wrong."""
    return b"<FEFF" + text.encode("utf-16-be").hex().upper().encode() + b">"


def _num(v: float) -> bytes:
    return (("%.3f" % v).rstrip("0").rstrip(".") or "0").encode()


def add_links(path, links) -> bool:
    """Add ``links`` (:class:`PdfLink`) to the PDF at ``path``, in place.
    ``True`` when they were written; ``False`` (the file untouched) when
    there were none or the file is not one this module reads. Links whose
    page or target is not in the file are skipped."""
    links = list(links or ())
    if not links:
        return False
    path = Path(path)
    data = path.read_bytes()
    tr = _trailer(data)
    pages = page_objects(data)
    if tr is None or not pages:
        return False
    links = [ln for ln in links
             if 0 <= ln.page < len(pages) and 0 <= ln.target < len(pages)]
    if not links:
        return False
    next_num = tr["size"]
    objects: dict = {}                  # number -> body (between obj/endobj)
    by_page: dict = {}
    for ln in links:
        num = next_num
        next_num += 1
        x0, y0, x1, y1 = ln.rect
        body = (b"<<\n/Type /Annot\n/Subtype /Link\n/Rect ["
                + b" ".join(_num(v) for v in (min(x0, x1), min(y0, y1),
                                              max(x0, x1), max(y0, y1)))
                + b"]\n/Border [0 0 0]\n/F 4\n/Dest [%d 0 R /Fit]\n"
                % pages[ln.target])
        if ln.title:
            body += b"/Contents " + _pdf_text(ln.title) + b"\n"
        objects[num] = body + b">>"
        by_page.setdefault(ln.page, []).append(num)
    for page, nums in by_page.items():
        pnum = pages[page]
        body = _find_object(data, pnum)
        if body is None:
            return False
        refs = b" ".join(b"%d 0 R" % n for n in nums)
        ref = re.search(rb"/Annots\s+(\d+)\s+0\s+R", body)
        inline = re.search(rb"/Annots\s*\[([^\]]*)\]", body)
        if ref:
            # Qt's way: the page names an array object; that array grows.
            anum = int(ref.group(1))
            arr = _find_object(data, anum)
            m = re.search(rb"\[([^\]]*)\]", arr or b"")
            if m is None:
                return False
            objects[anum] = b"[" + m.group(1).strip() + b" " + refs + b"]"
        elif inline:
            objects[pnum] = (body[:inline.start()] + b"/Annots ["
                             + inline.group(1).strip() + b" " + refs + b"]"
                             + body[inline.end():]).strip()
        else:
            end = body.rfind(b">>")
            if end < 0:
                return False
            objects[pnum] = (body[:end].rstrip() + b"\n/Annots [" + refs
                             + b"]\n" + body[end:]).strip()
    # The update: the objects, a cross-reference section for them alone,
    # the trailer pointing back at the previous section.
    out = bytearray(data)
    if not out.endswith(b"\n"):
        out += b"\n"
    offsets: dict = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objects[num].strip() + b"\nendobj\n"
    xref_at = len(out)
    out += b"xref\n"
    nums = sorted(offsets)
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out += b"%d %d\n" % (nums[i], j - i + 1)
        for n in nums[i:j + 1]:
            out += b"%010d 00000 n \n" % offsets[n]
        i = j + 1
    out += b"trailer\n<<\n/Size %d\n/Root %d 0 R\n" % (
        max(next_num, tr["size"]), tr["root"])
    if tr["info"] is not None:
        out += b"/Info %d 0 R\n" % tr["info"]
    if tr["id"] is not None:
        out += b"/ID " + tr["id"] + b"\n"
    out += b"/Prev %d\n>>\nstartxref\n%d\n%%%%EOF\n" % (tr["startxref"],
                                                        xref_at)
    # Written beside it and moved over: a failure halfway leaves the PDF
    # as Qt wrote it.
    fd, tmp = tempfile.mkstemp(prefix=".links-", suffix=".pdf",
                               dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(bytes(out))
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return True
