# SPDX-License-Identifier: GPL-3.0-or-later
"""The Components tray's category tree: which folder each component sits in.

A library that grows past a few dozen entries turns a flat list into an
endless scroll, so the tray groups components in categories the user owns:
created, renamed, deleted, nested up to :data:`MAX_DEPTH` levels
(``Furniture ▸ Living room ▸ Floor standing``) and individually hidden — an
interior designer has no use for bearings and shafts.

Everything lives in a small SQLite file of its own in the user's data folder
(``category_node`` / ``item_category``) and is Qt-free, so the rules — depth
limit, unique sibling names, no cycles, what a delete does to its contents —
are tested without a window.

A component may be listed in SEVERAL categories — a roof fan under
Electrical, under Living room ▸ Roof and under Bedroom ▸ Roof — so an item
belongs to a set of categories, not to one.

An item the user never touched has no rows of its own: it sits where
``default_path`` (a hint from whoever lists it) says, if that category still
exists, and otherwise in ``Uncategorized`` — so a component that arrives in a
later release never vanishes, and a category the user deleted never comes
back by itself. The first edit to an item writes its current places down
first, so adding a second category never loses the default one.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

#: Top level + two sublevels: «furniture ▸ living room ▸ floor standing».
MAX_DEPTH = 3

UNCATEGORIZED = "Uncategorized"

_SEEDED = "defaults_seeded"

#: The tree a fresh install starts with. Plain English data: a category name
#: is something the user edits, so it is stored as written, never translated
#: on the way out.
DEFAULT_TREE: tuple = (
    ("Furniture", (("Living room", ()),)),
    ("Outdoor", (("Plants", ()),)),
    ("People", ()),
    ("Vehicles", ()),
)

#: Where the components that ship with the app start out, by item key
#: (``component:<key>`` for a bundled model, ``person:<key>`` for a 2D scale
#: figure — see resources/components/).
DEFAULT_PATHS: dict = {
    "component:sofa": ("Furniture", "Living room"),
    "component:banco": ("Outdoor",),
    "component:fuente": ("Outdoor",),
    "component:arbol": ("Outdoor", "Plants"),
    "component:abedul": ("Outdoor", "Plants"),
    "component:chica": ("People",),
    "component:pickup": ("Vehicles",),
    "component:suv": ("Vehicles",),
}

_DDL = """
CREATE TABLE IF NOT EXISTS category_node (
    id        TEXT PRIMARY KEY,
    parent_id TEXT REFERENCES category_node(id) ON DELETE CASCADE,
    name      TEXT NOT NULL,
    hidden    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS item_category (
    item_key TEXT NOT NULL,
    node_id  TEXT NOT NULL REFERENCES category_node(id) ON DELETE CASCADE,
    PRIMARY KEY (item_key, node_id)
);
CREATE TABLE IF NOT EXISTS taxonomy_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_category_node_parent ON category_node(parent_id);
CREATE INDEX IF NOT EXISTS idx_item_category_node ON item_category(node_id);
"""


def default_path() -> Path:
    """The per-user categories file, next to the per-user plugins folder.
    ``INGETRAZO_CATEGORIES_DB`` overrides it (the test suite does)."""
    override = os.environ.get("INGETRAZO_CATEGORIES_DB")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA")
                    or (Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME")
                    or (Path.home() / ".local" / "share"))
    return base / "ingetrazo" / "component_categories.sqlite"


@dataclass(frozen=True)
class Node:
    id: str
    parent_id: str | None
    name: str
    hidden: bool


class TaxonomyError(ValueError):
    """A category edit the rules refuse; the message is fit to show."""


def _clean(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise TaxonomyError("A category needs a name.")
    return name


class Taxonomy:
    """The category tree, kept in one SQLite file (``":memory:"`` for tests).

    Not thread-safe — use it from the GUI thread, like the widget does."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self.db_path = str(path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.db_path, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        for pragma in ("journal_mode = WAL", "foreign_keys = ON",
                       "busy_timeout = 5000"):
            try:
                self._db.execute(f"PRAGMA {pragma}")
            except sqlite3.OperationalError:
                pass                      # :memory: ignores journal_mode=WAL
        self._db.executescript(_DDL)
        self._seed_defaults()

    def close(self) -> None:
        self._db.close()

    @contextmanager
    def _transaction(self):
        self._db.execute("BEGIN")
        try:
            yield
        except Exception:
            self._db.execute("ROLLBACK")
            raise
        else:
            self._db.execute("COMMIT")

    # ---- reading ---------------------------------------------------------------

    def nodes(self) -> list[Node]:
        rows = self._db.execute(
            "SELECT id, parent_id, name, hidden FROM category_node").fetchall()
        out = [Node(r["id"], r["parent_id"], r["name"], bool(r["hidden"]))
               for r in rows]
        out.sort(key=lambda n: n.name.casefold())
        return out

    def get(self, node_id: str) -> Node | None:
        r = self._db.execute(
            "SELECT id, parent_id, name, hidden FROM category_node WHERE id=?",
            (node_id,)).fetchone()
        return Node(r["id"], r["parent_id"], r["name"], bool(r["hidden"])) \
            if r else None

    def children(self, parent_id: str | None) -> list[Node]:
        return [n for n in self.nodes() if n.parent_id == parent_id]

    def depth(self, node_id: str) -> int:
        """1 for a top-level category."""
        d, node = 0, self.get(node_id)
        while node is not None:
            d += 1
            node = self.get(node.parent_id) if node.parent_id else None
        return d

    def path(self, node_id: str) -> tuple:
        names, node = [], self.get(node_id)
        while node is not None:
            names.append(node.name)
            node = self.get(node.parent_id) if node.parent_id else None
        return tuple(reversed(names))

    def descendants(self, node_id: str) -> list[str]:
        """The ids of everything below ``node_id`` (not itself)."""
        by_parent: dict = {}
        for n in self.nodes():
            by_parent.setdefault(n.parent_id, []).append(n.id)
        out, stack = [], list(by_parent.get(node_id, ()))
        while stack:
            cur = stack.pop()
            out.append(cur)
            stack.extend(by_parent.get(cur, ()))
        return out

    def height(self, node_id: str) -> int:
        """Levels in the subtree rooted at ``node_id`` (a leaf is 1)."""
        kids = self.children(node_id)
        return 1 + max((self.height(k.id) for k in kids), default=0)

    def is_hidden(self, node_id: str) -> bool:
        """Hidden itself, or inside a hidden category — hiding a folder
        hides everything in it."""
        node = self.get(node_id)
        while node is not None:
            if node.hidden:
                return True
            node = self.get(node.parent_id) if node.parent_id else None
        return False

    def find(self, path: tuple) -> Node | None:
        """The category at this name path, matching names case-insensitively."""
        parent = None
        node = None
        for name in path:
            node = next((n for n in self.children(parent)
                         if n.name.casefold() == name.casefold()), None)
            if node is None:
                return None
            parent = node.id
        return node

    def _default_node(self, item_key: str, default_path: tuple) -> Node:
        if not default_path:
            default_path = DEFAULT_PATHS.get(item_key, ())
        if default_path:
            node = self.find(tuple(default_path))
            if node is not None:
                return node
        return self._ensure_uncategorized()

    def _explicit(self, item_key: str) -> list[Node]:
        rows = self._db.execute(
            "SELECT node_id FROM item_category WHERE item_key=?",
            (item_key,)).fetchall()
        nodes = [self.get(r["node_id"]) for r in rows]
        return [n for n in nodes if n is not None]

    def nodes_of(self, item_key: str, default_path: tuple = ()) -> list[Node]:
        """Every category an item is listed in (never empty)."""
        nodes = self._explicit(item_key)
        if nodes:
            nodes.sort(key=lambda n: self.path(n.id))
            return nodes
        return [self._default_node(item_key, default_path)]

    def choices(self, exclude: str | None = None,
                max_depth: int = MAX_DEPTH) -> list:
        """``[(id, "Furniture ▸ Living room")]`` in tree order, for a
        "Move to…" list. ``exclude`` drops a category and everything under
        it (you cannot move a folder into itself); ``max_depth`` keeps out
        the ones that would be too deep to receive it."""
        skip = {exclude, *self.descendants(exclude)} if exclude else set()
        out: list = []

        def walk(parent):
            for n in self.children(parent):
                if n.id in skip:
                    continue
                if self.depth(n.id) <= max_depth:
                    out.append((n.id, " ▸ ".join(self.path(n.id))))
                walk(n.id)
        walk(None)
        return out

    # ---- editing ---------------------------------------------------------------

    def _check_name(self, name: str, parent_id: str | None,
                    self_id: str | None = None) -> str:
        name = _clean(name)
        for sib in self.children(parent_id):
            if sib.id != self_id and sib.name.casefold() == name.casefold():
                raise TaxonomyError(f"«{name}» already exists here.")
        return name

    def create(self, name: str, parent_id: str | None = None) -> Node:
        if parent_id is not None:
            if self.get(parent_id) is None:
                raise TaxonomyError("That category no longer exists.")
            if self.depth(parent_id) + 1 > MAX_DEPTH:
                raise TaxonomyError(
                    f"Categories nest at most {MAX_DEPTH} levels deep.")
        name = self._check_name(name, parent_id)
        node_id = uuid.uuid4().hex
        with self._transaction():
            self._db.execute(
                "INSERT INTO category_node(id, parent_id, name, hidden) "
                "VALUES (?, ?, ?, 0)", (node_id, parent_id, name))
        return self.get(node_id)

    def rename(self, node_id: str, name: str) -> Node:
        node = self.get(node_id)
        if node is None:
            raise TaxonomyError("That category no longer exists.")
        name = self._check_name(name, node.parent_id, node_id)
        with self._transaction():
            self._db.execute("UPDATE category_node SET name=? WHERE id=?",
                             (name, node_id))
        return self.get(node_id)

    def set_hidden(self, node_id: str, hidden: bool) -> None:
        with self._transaction():
            self._db.execute("UPDATE category_node SET hidden=? WHERE id=?",
                             (1 if hidden else 0, node_id))

    def move(self, node_id: str, new_parent_id: str | None) -> Node:
        """Re-parent a category (``None`` = top level), keeping its subtree
        and the limit of :data:`MAX_DEPTH` levels."""
        node = self.get(node_id)
        if node is None:
            raise TaxonomyError("That category no longer exists.")
        if new_parent_id == node.parent_id:
            return node
        if new_parent_id is not None:
            if self.get(new_parent_id) is None:
                raise TaxonomyError("That category no longer exists.")
            if new_parent_id == node_id or \
                    new_parent_id in self.descendants(node_id):
                raise TaxonomyError(
                    "A category cannot be moved inside itself.")
            base = self.depth(new_parent_id)
        else:
            base = 0
        if base + self.height(node_id) > MAX_DEPTH:
            raise TaxonomyError(
                f"Categories nest at most {MAX_DEPTH} levels deep.")
        self._check_name(node.name, new_parent_id, node_id)
        with self._transaction():
            self._db.execute("UPDATE category_node SET parent_id=? WHERE id=?",
                             (new_parent_id, node_id))
        return self.get(node_id)

    def delete(self, node_id: str) -> None:
        """Delete a category and the categories inside it. Components are
        never lost: one that was listed ONLY there moves up to the parent (or
        to ``Uncategorized`` from the top level); one that is also listed
        elsewhere simply stops being listed here."""
        node = self.get(node_id)
        if node is None:
            return
        doomed = [node_id, *self.descendants(node_id)]
        marks = ",".join("?" * len(doomed))
        if node.parent_id is not None:
            target = node.parent_id
        elif node.name.casefold() == UNCATEGORIZED.casefold():
            target = None             # its items fall back to where they began
        else:
            target = self._ensure_uncategorized().id
        with self._transaction():
            stranded = []
            if target is not None:
                rows = self._db.execute(
                    f"SELECT DISTINCT item_key FROM item_category "
                    f"WHERE node_id IN ({marks})", doomed).fetchall()
                for r in rows:
                    left = self._db.execute(
                        f"SELECT 1 FROM item_category WHERE item_key=? "
                        f"AND node_id NOT IN ({marks}) LIMIT 1",
                        (r["item_key"], *doomed)).fetchone()
                    if not left:
                        stranded.append(r["item_key"])
            self._db.execute(
                f"DELETE FROM item_category WHERE node_id IN ({marks})", doomed)
            self._db.execute(
                f"DELETE FROM category_node WHERE id IN ({marks})", doomed)
            for key in stranded:
                self._db.execute(
                    "INSERT OR IGNORE INTO item_category(item_key, node_id) "
                    "VALUES (?, ?)", (key, target))

    # ---- which categories an item is in ---------------------------------------

    def _materialize(self, item_key: str, default_path: tuple) -> None:
        """Write an untouched item's current places down, so an edit adds to
        them instead of replacing them. ``Uncategorized`` is left out: for an
        item nobody filed it only means "no place yet", and the first real
        category should replace it, not sit beside it."""
        if self._explicit(item_key):
            return
        for n in self.nodes_of(item_key, default_path):
            if n.parent_id is None and n.name.casefold() == \
                    UNCATEGORIZED.casefold():
                continue          # only the stand-in for "nowhere": not a place
            self._db.execute(
                "INSERT OR IGNORE INTO item_category(item_key, node_id) "
                "VALUES (?, ?)", (item_key, n.id))

    def _require(self, node_id: str) -> None:
        if self.get(node_id) is None:
            raise TaxonomyError("That category no longer exists.")

    def add_to(self, item_key: str, node_id: str,
               default_path: tuple = ()) -> None:
        """List the item in one more category (keeping the others)."""
        self._require(node_id)
        with self._transaction():
            self._materialize(item_key, default_path)
            self._db.execute(
                "INSERT OR IGNORE INTO item_category(item_key, node_id) "
                "VALUES (?, ?)", (item_key, node_id))

    def remove_from(self, item_key: str, node_id: str,
                    default_path: tuple = ()) -> None:
        """Stop listing the item in one category. Its last category cannot be
        taken away — it goes to ``Uncategorized`` instead, so no component is
        ever unreachable."""
        with self._transaction():
            self._materialize(item_key, default_path)
            self._db.execute(
                "DELETE FROM item_category WHERE item_key=? AND node_id=?",
                (item_key, node_id))
            if not self._explicit(item_key):
                self._db.execute(
                    "INSERT OR IGNORE INTO item_category(item_key, node_id) "
                    "VALUES (?, ?)", (item_key, self._ensure_uncategorized().id))

    def move_item(self, item_key: str, from_id: str, to_id: str,
                  default_path: tuple = ()) -> None:
        """Take the item out of ``from_id`` and list it in ``to_id`` (its
        other categories stay)."""
        self._require(to_id)
        if from_id == to_id:
            return
        with self._transaction():
            self._materialize(item_key, default_path)
            self._db.execute(
                "DELETE FROM item_category WHERE item_key=? AND node_id=?",
                (item_key, from_id))
            self._db.execute(
                "INSERT OR IGNORE INTO item_category(item_key, node_id) "
                "VALUES (?, ?)", (item_key, to_id))

    # ---- internals -------------------------------------------------------------

    def _ensure_uncategorized(self) -> Node:
        """The catch-all category, created on first need. A single bare
        INSERT (no transaction of its own) because callers may already be
        inside one."""
        for n in self.children(None):
            if n.name.casefold() == UNCATEGORIZED.casefold():
                return n
        node_id = uuid.uuid4().hex
        self._db.execute(
            "INSERT INTO category_node(id, parent_id, name, hidden) "
            "VALUES (?, NULL, ?, 0)", (node_id, UNCATEGORIZED))
        return self.get(node_id)

    def _seed_defaults(self) -> None:
        """Once per file: lay down the starting tree. After that the
        tree is the user's — a deleted default never reappears."""
        done = self._db.execute(
            "SELECT 1 FROM taxonomy_meta WHERE key=?", (_SEEDED,)).fetchone()
        if done:
            return

        def build(entries, parent):
            for name, kids in entries:
                build(kids, self.create(name, parent).id)
        with self._transaction():
            self._db.execute(
                "INSERT INTO taxonomy_meta(key, value) VALUES (?, '1')",
                (_SEEDED,))
        build(DEFAULT_TREE, None)
