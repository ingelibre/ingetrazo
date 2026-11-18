# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Your own component library: folders of ``.igz`` files on your disk or
your network, browsed as a tree in the Components tray (#1088, #354).

The online library (:mod:`core.library`) is somebody else's catalogue;
this one is yours. There is no database and no index: the FOLDERS are the
categories. A subfolder is a branch, an ``.igz`` file is a component, and
the tree is read from the disk each time — so a library can be kept on a
shared drive for a whole office, sorted in the file manager, copied to a
USB stick or put under version control, and the tray shows what is there.

Each file is one component: «Save to My Library» writes ONE definition
(:func:`save_component`), and inserting a file brings it in as one
component, the way File ▸ Import ▸ IngeTrazo document does — so a library
file is also an ordinary document you can open and edit.

The folders it reads are a list kept in the settings
(:data:`SETTINGS_KEY`). With none set, it is :func:`default_folder`.
``$INGETRAZO_USER_LIBRARY`` (paths separated by ``os.pathsep``) overrides
the list, which is how it is tested and how a shared setup can be pinned.

Nothing here raises on a missing or unreachable folder: a network drive
that is not mounted reads as an empty root marked ``missing``, and the
tray says so. Qt is only used for the settings and the Documents folder.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

#: The files the library lists.
SUFFIX = ".igz"
#: Where the list of folders is kept (QSettings).
SETTINGS_KEY = "user_library/folders"
#: Where the last save went, so the next one starts there.
LAST_FOLDER_KEY = "user_library/last_folder"
#: Folders read below a root, at most: a symlink loop or a whole drive
#: picked by mistake must not hang the tray.
MAX_DEPTH = 8
#: Entries read per root, at most, for the same reason.
MAX_ENTRIES = 5000

#: Characters no file name may hold on Windows (the strictest of the three
#: systems, and a library on a shared drive is read from all of them).
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


@dataclass
class Node:
    """One entry of the tree: a folder (``is_dir``) or a component file."""
    name: str
    path: Path
    is_dir: bool
    children: list = field(default_factory=list)
    #: A root that could not be read (absent, unmounted, no permission).
    missing: bool = False

    def files(self):
        """Every component file at or below this node."""
        if not self.is_dir:
            yield self
            return
        for c in self.children:
            yield from c.files()


# ---- which folders ------------------------------------------------------
def default_folder() -> Path:
    """``Documents/IngeTrazo/Components``: where a library starts when the
    user has not chosen one. Created only when something is saved to it."""
    docs = ""
    try:
        from PySide6.QtCore import QStandardPaths
        docs = QStandardPaths.writableLocation(
            QStandardPaths.DocumentsLocation)
    except Exception:  # noqa: BLE001 - no Qt: fall back to the home
        docs = ""
    base = Path(docs) if docs else Path.home() / "Documents"
    return base / "IngeTrazo" / "Components"


def _settings():
    from PySide6.QtCore import QSettings
    return QSettings()


def _as_list(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if v]


def folders() -> list:
    """The library's root folders, in order, without repeats."""
    env = os.environ.get("INGETRAZO_USER_LIBRARY")
    if env is not None:
        raw = [p for p in env.split(os.pathsep) if p.strip()]
    else:
        raw = _as_list(_settings().value(SETTINGS_KEY))
    if not raw:
        raw = [str(default_folder())]
    out: list = []
    seen: set = set()
    for p in raw:
        path = Path(p).expanduser()
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def set_folders(paths) -> None:
    """Keep ``paths`` as the library's roots (the settings, not the env)."""
    _settings().setValue(SETTINGS_KEY, [str(Path(p)) for p in paths])


def add_folder(path) -> bool:
    """Add a root. ``False`` when it was already one."""
    path = Path(path)
    current = folders()
    key = os.path.normcase(str(path))
    if any(os.path.normcase(str(p)) == key for p in current):
        return False
    set_folders(current + [path])
    return True


def remove_folder(path) -> None:
    """Stop listing a root. Its files are not touched."""
    key = os.path.normcase(str(Path(path)))
    set_folders([p for p in folders()
                 if os.path.normcase(str(p)) != key])


def last_folder() -> Path | None:
    raw = _settings().value(LAST_FOLDER_KEY)
    return Path(str(raw)) if raw else None


def remember_folder(path) -> None:
    _settings().setValue(LAST_FOLDER_KEY, str(Path(path)))


# ---- reading the tree ---------------------------------------------------
def _sort_key(name: str):
    """Folders and files in the order a person reads them: case and accents
    aside, and «Silla 2» before «Silla 10»."""
    plain = fold(name)
    return [int(t) if t.isdigit() else t
            for t in re.split(r"(\d+)", plain)]


def fold(text: str) -> str:
    """``text`` for comparing: lower case, accents off («Baño» = «bano»)."""
    norm = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in norm
                   if not unicodedata.combining(c)).casefold()


def scan(root) -> Node:
    """The tree under ``root``: folders first, then the ``.igz`` files,
    each sorted by name. Hidden entries (a leading dot) are left out, and
    so are folders with no component anywhere below them only when they
    are not the root — an empty folder you just made still shows."""
    root = Path(root)
    node = Node(root.name or str(root), root, True)
    if not root.is_dir():
        # The default folder not made yet is an empty library, not a
        # missing one: it appears with the first component saved to it.
        node.missing = not same_path(root, default_folder())
        return node
    budget = [MAX_ENTRIES]
    _fill(node, 0, budget)
    return node


def _fill(node: Node, depth: int, budget: list) -> None:
    try:
        entries = list(os.scandir(node.path))
    except OSError:
        node.missing = depth == 0
        return
    dirs, files = [], []
    for e in entries:
        if budget[0] <= 0:
            break
        if e.name.startswith("."):
            continue
        try:
            if e.is_dir():
                dirs.append(e)
            elif e.is_file() and e.name.lower().endswith(SUFFIX):
                files.append(e)
            else:
                continue
        except OSError:
            continue
        budget[0] -= 1
    for e in sorted(dirs, key=lambda e: _sort_key(e.name)):
        child = Node(e.name, Path(e.path), True)
        if depth + 1 < MAX_DEPTH:
            _fill(child, depth + 1, budget)
        node.children.append(child)
    for e in sorted(files, key=lambda e: _sort_key(e.name)):
        node.children.append(Node(Path(e.name).stem, Path(e.path), False))


def filtered(node: Node, text: str) -> Node | None:
    """``node`` cut down to what matches ``text``: a file whose name holds
    every word of it, or a folder whose name does (then all of it stays —
    searching «baño» shows the Bathroom folder whole). ``None`` when
    nothing below matches. An empty search keeps everything."""
    words = fold(text).split()
    if not words:
        return node

    def hit(name):
        f = fold(name)
        return all(w in f for w in words)

    def walk(n: Node, depth: int):
        if not n.is_dir:
            return n if hit(n.name) else None
        if depth > 0 and hit(n.name):
            return n
        kept = [k for k in (walk(c, depth + 1) for c in n.children)
                if k is not None]
        if not kept and depth > 0:
            return None
        return Node(n.name, n.path, True, kept, n.missing)

    out = walk(node, 0)
    if out is not None and not out.children and not hit(out.name):
        return None
    return out


# ---- names and folders --------------------------------------------------
def safe_name(name: str) -> str:
    """``name`` as a file or folder name every system accepts: forbidden
    characters become «-», trailing dots and spaces go, and a name Windows
    reserves (CON, NUL…) gets a «_». Empty → «Component»."""
    out = _BAD_CHARS.sub("-", (name or "").strip()).rstrip(". ")
    if not out:
        out = "Component"
    if out.split(".")[0].upper() in _RESERVED:
        out = "_" + out
    return out[:120]


def unique_path(folder, stem: str, suffix: str = SUFFIX) -> Path:
    """``folder/stem.igz``, or ``stem (2).igz``… when that is taken."""
    folder = Path(folder)
    stem = safe_name(stem)
    p = folder / f"{stem}{suffix}"
    n = 2
    while p.exists():
        p = folder / f"{stem} ({n}){suffix}"
        n += 1
    return p


def new_folder(parent, name: str) -> Path:
    """Make a subfolder of ``parent`` (numbered when the name is taken)."""
    path = unique_path(parent, name, suffix="")
    path.mkdir(parents=True)
    return path


def rename(path, new_name: str) -> Path:
    """Rename a component file (its ``.igz`` stays) or a folder. Raises
    ``FileExistsError`` when the new name is taken, ``OSError`` otherwise."""
    path = Path(path)
    stem = safe_name(new_name)
    target = path.with_name(stem + (SUFFIX if path.is_file() else ""))
    if target == path:
        return path
    same_entry = (target.exists() and os.path.normcase(str(target))
                  == os.path.normcase(str(path)))
    if target.exists() and not same_entry:
        raise FileExistsError(str(target))
    path.rename(target)
    return target


def move_into(path, folder) -> Path:
    """Move a component file or a folder into ``folder`` (numbered when the
    name is taken there). A folder is never moved into itself or below it:
    ``ValueError``. Moving to where it already is changes nothing."""
    path, folder = Path(path), Path(folder)
    if os.path.normcase(str(path.parent)) == os.path.normcase(str(folder)):
        return path
    if path.is_dir() and is_inside(folder, [path]):
        raise ValueError(str(path))
    suffix = SUFFIX if path.is_file() else ""
    stem = path.stem if path.is_file() else path.name
    target = unique_path(folder, stem, suffix=suffix)
    import shutil
    shutil.move(str(path), str(target))
    return target


def same_path(a, b) -> bool:
    return (os.path.normcase(os.path.abspath(str(a)))
            == os.path.normcase(os.path.abspath(str(b))))


def is_inside(path, roots=None) -> bool:
    """Whether ``path`` sits in one of the library's folders."""
    path = os.path.normcase(os.path.abspath(str(path)))
    for r in roots if roots is not None else folders():
        r = os.path.normcase(os.path.abspath(str(r)))
        if path == r or path.startswith(r.rstrip("\\/") + os.sep):
            return True
    return False


# ---- saving a component -------------------------------------------------
def component_scene(definition, src_scene):
    """A document that holds ONE copy of ``definition``'s component, at its
    own axes, with the materials and layers it wears. Its geometry is
    shared with the open document (nothing is copied): it is only read, to
    be written out."""
    from copy import deepcopy
    from core.group import iter_placements
    from core.kept_components import make_template
    from core.layers import DEFAULT_LAYER, layer_of
    from core.scene import Scene
    t = make_template(definition)
    t.name = definition.name or t.name
    scene = Scene()
    scene.groups = [t]
    used_mats: set = set()
    used_layers: list = []
    for g, _m in iter_placements(t):
        for ent in [g, *g.mesh.faces, *g.mesh.edges]:
            n = layer_of(ent)
            if n != DEFAULT_LAYER and n not in used_layers:
                used_layers.append(n)
        mat = getattr(g, "material", None)
        if isinstance(mat, dict) and mat.get("mat"):
            used_mats.add(mat["mat"])
        for f in g.mesh.faces:
            a = f.attrs or {}
            if a.get("mat"):
                used_mats.add(a["mat"])
            back = a.get("back")
            if isinstance(back, dict) and back.get("mat"):
                used_mats.add(back["mat"])
    materials = getattr(src_scene, "materials", None) or {}
    scene.materials = {n: m for n, m in materials.items() if n in used_mats}
    src_layers = {ly.name: ly for ly in getattr(src_scene, "layers", ())}
    from core.layers import Layer
    for n in used_layers:
        ly = src_layers.get(n)
        scene.layers.append(deepcopy(ly) if ly is not None else Layer(n))
    return scene


def save_component(definition, src_scene, path) -> Path:
    """Write ``definition``'s component to ``path`` as a document of its
    own, creating the folder when needed. Returns the path written."""
    from formats import igz
    path = Path(path)
    if path.suffix.lower() != SUFFIX:
        path = path.with_name(path.name + SUFFIX)
    path.parent.mkdir(parents=True, exist_ok=True)
    igz.save_scene(component_scene(definition, src_scene), path)
    return path


# ---- thumbnails ---------------------------------------------------------
def thumbnail_cache() -> Path:
    """Where the pictures of library files are kept. As disposable as the
    texture cache: deleting it only costs drawing them again."""
    from core.texture import texture_cache_root
    return texture_cache_root().parent / "user-library-thumbs"


def thumbnail_path(path, size: int) -> Path | None:
    """The cached picture's place for ``path`` as it is NOW: the name
    changes with the file's size and time, so an edited component is drawn
    again and a stale picture is never shown. ``None`` = unreadable."""
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return None
    key = f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}|{size}"
    digest = hashlib.sha1(key.encode("utf-8", "surrogatepass")).hexdigest()
    return thumbnail_cache() / f"{digest}.png"


def load_component(path):
    """The component a library file holds, read into a scene of its own
    (for its picture), or ``None`` when it holds no geometry. Raises when
    the file cannot be read."""
    from core.insert import component_from_scene
    from core.scene import Scene
    from formats import igz
    temp = Scene()
    igz.load_into(temp, Path(path))
    return component_from_scene(temp, Path(path).stem)
