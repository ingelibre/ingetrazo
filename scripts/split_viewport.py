#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Split ``views/viewport.py`` into the ``views/viewport/`` package (#901).

The ``Viewport`` class becomes one mixin per job (``render.py``,
``picking.py``, ``snapping.py``...), the module-level helpers go to
``_support.py``, and ``__init__.py`` keeps the signals, ``__init__``,
``set_document`` and a few document-wide members. It is a pure move: every
member is copied **verbatim** (same text, same indentation, same order
inside its module), so ``git log -L`` and a reviewer can follow it.

The split follows pkoska's PR #901 (commit a0766383): every member that
existed then goes where he put it (``scripts/split_viewport_map.json``,
section ``pr901``). A member added later is placed by, in order:

1. the hand-written ``exceptions`` of the map file (each with its reason);
2. the name ``RULES`` below (families such as ``_epoch_*`` or ``*shadow*``);
3. its neighbours in the file: when the nearest #901-placed member before
   it and the one after it agree, it goes with them — new methods are
   written next to the ones they work with (on the #901 members themselves
   this rule agrees with pkoska 322 times out of 328);
4. a vote of the members it calls and that call it;
5. otherwise the script stops and asks for an exception.

Two things keep the package behaving as the one module did:

* ``Viewport.X`` inside a method is left as it is (a class-wide counter
  such as ``Viewport.painting += 1``, an unbound call such as
  ``Viewport._paint_frame(self)`` that a test patches on ``Viewport``). A
  module that names ``Viewport`` gets a ``Viewport = None`` placeholder
  and ``__init__.py`` sets it to the class once the class exists.
* ``views.viewport`` is still the module the tests and the switches know:
  a name set on it (``monkeypatch.setattr(views.viewport, "_NO_SNAP_FAST",
  True)``) is set in every part that holds it, and a name read off it that
  ``__init__`` does not hold is read live from the part that does.

Usage, from the repository root::

    python scripts/split_viewport.py            # write views/viewport/
    python scripts/split_viewport.py --check    # verify it
    python scripts/split_viewport.py --plan     # where each member goes

``--check`` compares the package against the original file (the working
tree's ``views/viewport.py`` if it is still there, else the last committed
one, or ``--orig FILE``): every line of every member is in the package
exactly once and in its module; every global a part reads is bound in it;
``dir(Viewport)`` and every member's code object are the same as before;
every name the repository imports or reads from ``views.viewport`` still
resolves; and a name patched on ``views.viewport`` reaches every part.
``--extract-map REV`` rebuilds the ``pr901`` section from pkoska's branch.
"""
from __future__ import annotations

import argparse
import ast
import builtins
import collections
import importlib
import importlib.util
import json
import os
import re
import subprocess
import symtable
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = Path("views/viewport.py")
PKG = Path("views/viewport")
MAP_FILE = Path(__file__).with_name("split_viewport_map.json")
WIDTH = 79

#: Name families for members added after #901: (regex, module, why). Tried
#: after the hand-written exceptions and before the neighbours.
RULES = [
    (r"^_paint_|^_frame_cache_", "render",
     "paintGL's passes and the frame cache they fill"),
    (r"^_epoch_|^_inst_pool_|^_INST_|^_instances_",
     "instancing", "the instanced pool and its placements epochs"),
    (r"shadow|SHADOW", "shadows", "sun shadows"),
    (r"^_section_box|^pick_section_box$|^_box_covers_plane$|"
     r"^_box_with_grips$|^_press_on_box_chip$|^_draw_section_box",
     "sections", "section boxes"),
    (r"^_cut_|^CUT_|^_section_|^_draw_section_|^_draw_cut_",
     "sections", "the section cut"),
    (r"composition", "overlay", "the camera's composition guides"),
    (r"^_occlu|^_OCCLUDED", "occlusion", "screen-depth occlusion"),
    (r"zoom_value", "value_input", "the value box with Zoom on"),
    (r"linetype|line_words", "render",
     "the model's edges drawn in their layer's line type"),
]

#: The package's own names: never propagated, never shadowed by a part.
_RESERVED = {"Viewport", "__getattr__", "_PARTS", "_ViewportPackage"}


# ---------------------------------------------------------------------------
# Reading the original
# ---------------------------------------------------------------------------

class Member:
    """One statement of the ``Viewport`` class body and the lines it owns:
    from the line after the previous statement to its own last line, so
    the comments written above a member travel with it."""

    def __init__(self, stmt, start, end, lines):
        self.stmt = stmt
        self.start = start            # 1-based, inclusive
        self.end = end
        self.text = "".join(lines[start - 1:end])
        self.names = _bound_names(stmt)
        self.module = None
        self.why = None

    @property
    def name(self):
        return self.names[0] if self.names else f"<line {self.stmt.lineno}>"

    @property
    def is_def(self):
        return isinstance(self.stmt, (ast.FunctionDef, ast.AsyncFunctionDef))


def _bound_names(stmt):
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                         ast.ClassDef)):
        return [stmt.name]
    out = []
    targets = []
    if isinstance(stmt, ast.Assign):
        targets = stmt.targets
    elif isinstance(stmt, (ast.AnnAssign, ast.AugAssign)):
        targets = [stmt.target]
    for t in targets:
        for n in ast.walk(t):
            if isinstance(n, ast.Name):
                out.append(n.id)
    return out


class Original:
    """``views/viewport.py`` taken apart."""

    def __init__(self, text, filename="views/viewport.py"):
        self.text = text
        self.filename = filename
        self.lines = text.splitlines(keepends=True)
        self.tree = ast.parse(text, filename)
        body = self.tree.body
        classes = [i for i, n in enumerate(body)
                   if isinstance(n, ast.ClassDef) and n.name == "Viewport"]
        if len(classes) != 1:
            raise SystemExit("split_viewport: no single class Viewport")
        self.cls_index = classes[0]
        self.cls = body[self.cls_index]
        if self.cls_index != len(body) - 1:
            raise SystemExit("split_viewport: code after class Viewport — "
                             "teach the script where it goes")
        if self.cls.decorator_list:
            raise SystemExit("split_viewport: Viewport has decorators")
        doc = body[0]
        if not (isinstance(doc, ast.Expr)
                and isinstance(doc.value, ast.Constant)
                and isinstance(doc.value.value, str)):
            raise SystemExit("split_viewport: no module docstring")
        self.doc_node = doc
        self.header = "".join(self.lines[:doc.lineno - 1])
        self.docstring = "".join(self.lines[doc.lineno - 1:doc.end_lineno])
        self.prelude = body[1:self.cls_index]
        self.prelude_start = doc.end_lineno + 1
        # The class: its header line(s) up to its docstring, then members.
        cbody = self.cls.body
        cdoc = cbody[0]
        if not (isinstance(cdoc, ast.Expr)
                and isinstance(cdoc.value, ast.Constant)):
            raise SystemExit("split_viewport: Viewport has no docstring")
        self.cls_doc = "".join(self.lines[cdoc.lineno - 1:cdoc.end_lineno])
        self.cls_bases = [ast.get_source_segment(text, b)
                          for b in self.cls.bases]
        self.members = []
        prev_end = cdoc.end_lineno
        for stmt in cbody[1:]:
            m = Member(stmt, prev_end + 1, stmt.end_lineno, self.lines)
            prev_end = stmt.end_lineno
            if not m.names:
                raise SystemExit(f"split_viewport: class-level statement at "
                                 f"line {stmt.lineno} binds no name")
            self.members.append(m)
        self.trailing = "".join(self.lines[prev_end:])
        if self.trailing.strip():
            raise SystemExit("split_viewport: text after the last member")
        self._module_bindings()

    # -- module level ------------------------------------------------------

    def _module_bindings(self):
        """name -> ("import", stmt, alias) or ("support", None, None)."""
        self.bindings = {}
        self.rebound = collections.defaultdict(set)   # name -> {func names}
        for stmt in self.prelude:
            if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                if (isinstance(stmt, ast.ImportFrom)
                        and stmt.module == "__future__"):
                    continue
                for a in stmt.names:
                    if a.name == "*":
                        raise SystemExit("split_viewport: star import")
                    bound = (a.asname or a.name.split(".")[0])
                    self.bindings[bound] = ("import", stmt, a)
            else:
                for n in _bound_names(stmt):
                    self.bindings[n] = ("support", None, None)
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Global):
                owner = _enclosing_function(self.tree, node)
                for n in node.names:
                    self.rebound[n].add(owner)
                    self.bindings.setdefault(n, ("support", None, None))

    # -- the globals each member reads ---------------------------------------

    def member_globals(self):
        """{member: set of global names it reads or writes}."""
        st = symtable.symtable(self.text, self.filename, "exec")
        cls_tab = next(c for c in st.get_children()
                       if c.get_name() == "Viewport"
                       and c.get_type() == "class")
        funcs = collections.defaultdict(list)
        for child in cls_tab.get_children():
            funcs[child.get_name()].append(child)
        class_names = {n for m in self.members for n in m.names}
        out = {}
        earlier = set()       # class names bound above: class-local reads
        for m in self.members:
            names = set()
            if m.is_def:
                tabs = funcs.get(m.name, [])
                tab = next((t for t in tabs
                            if t.get_lineno() in (m.stmt.lineno,)
                            or t.get_lineno() == _def_line(m.stmt)), None)
                if tab is None:
                    raise SystemExit(f"split_viewport: no symbol table for "
                                     f"{m.name} (line {m.stmt.lineno})")
                names |= _table_globals(tab)
                # Evaluated in the class body: decorators, defaults,
                # annotations (strings here, kept for the readers).
                evald = list(m.stmt.decorator_list)
                a = m.stmt.args
                evald += list(a.defaults) + [d for d in a.kw_defaults if d]
                for arg in a.posonlyargs + a.args + a.kwonlyargs + [
                        a.vararg, a.kwarg]:
                    if arg is not None and arg.annotation is not None:
                        evald.append(arg.annotation)
                if m.stmt.returns is not None:
                    evald.append(m.stmt.returns)
                for e in evald:
                    names |= _ast_names(e) - earlier
            else:
                names |= _ast_names(m.stmt) - earlier
            earlier |= set(m.names)
            out[m] = names
        self.class_names = class_names
        return out


def _def_line(stmt):
    return stmt.lineno


def _enclosing_function(tree, target):
    best = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= target.lineno <= node.end_lineno:
                if best is None or node.lineno > best.lineno:
                    best = node
    return best.name if best else "<module>"


def _table_globals(tab):
    names = set()
    for s in tab.get_symbols():
        if s.is_global() and (s.is_referenced() or s.is_assigned()):
            names.add(s.get_name())
    for c in tab.get_children():
        names |= _table_globals(c)
    return names


def _ast_names(node):
    """Names a class-body expression reads (over-approximate: a
    comprehension's own variable is filtered later as unbound)."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)
            and isinstance(n.ctx, ast.Load)}


def _annotation_strings(stmt):
    """The names inside string annotations (``from __future__ import
    annotations``): kept importable for type readers."""
    out = set()
    if not isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return out
    a = stmt.args
    anns = [x.annotation for x in a.posonlyargs + a.args + a.kwonlyargs
            + [a.vararg, a.kwarg] if x is not None and x.annotation]
    if stmt.returns is not None:
        anns.append(stmt.returns)
    for ann in anns:
        out |= _ast_names(ann)
    return out


# ---------------------------------------------------------------------------
# The map
# ---------------------------------------------------------------------------

def load_map():
    data = json.loads(MAP_FILE.read_text(encoding="utf-8"))
    return data


def assign(orig, data, verbose=False):
    """Give each member its module; returns the (module, reason) table."""
    modules = {m["module"] for m in data["modules"]} | {"__init__"}
    pr = data["pr901"]
    exc = {k: v["module"] for k, v in data["exceptions"].items()}
    for k, v in list(pr.items()) + list(exc.items()):
        if v not in modules:
            raise SystemExit(f"split_viewport: {k} -> unknown module {v}")
    members = orig.members
    # #901 positions for the neighbour rule.
    placed = [pr.get(m.name) for m in members]
    calls = _member_calls(orig)
    by_name = collections.defaultdict(list)
    for m in members:
        for n in m.names:
            by_name[n].append(m)
    homeless = []
    for i, m in enumerate(members):
        name = m.name
        if (isinstance(m.stmt, ast.Assign) and isinstance(m.stmt.value,
                                                          ast.Call)
                and isinstance(m.stmt.value.func, ast.Name)
                and m.stmt.value.func.id == "Signal"):
            m.module, m.why = "__init__", "a Qt signal stays on the class"
        elif name in ("__init__", "set_document"):
            m.module, m.why = "__init__", "kept on the class (#901)"
        elif name in pr:
            m.module, m.why = pr[name], "#901"
        elif name in exc:
            m.module, m.why = exc[name], "exception: " + \
                data["exceptions"][name]["why"]
        else:
            rule = next(((mod, why) for rx, mod, why in RULES
                         if re.search(rx, name)), None)
            if rule:
                m.module, m.why = rule[0], "rule: " + rule[1]
                continue
            before = next((placed[j] for j in range(i - 1, -1, -1)
                           if placed[j]), None)
            after = next((placed[j] for j in range(i + 1, len(members))
                          if placed[j]), None)
            if before is not None and before == after:
                m.module, m.why = before, "neighbours"
                continue
            votes = collections.Counter()
            for other in calls[name]["calls"] | calls[name]["by"]:
                if other in pr:
                    votes[pr[other]] += 1
            top = votes.most_common(2)
            if top and (len(top) == 1 or top[0][1] > top[1][1]):
                m.module, m.why = top[0][0], f"vote {dict(votes)}"
                continue
            homeless.append(f"  {name} (line {m.stmt.lineno}; neighbours "
                            f"{before}/{after}, votes {dict(votes)})")
    if homeless:
        raise SystemExit("split_viewport: no home for these members; add "
                         f"them to the exceptions of {MAP_FILE.name}:\n"
                         + "\n".join(homeless))
    # A property and its setter, or a name bound twice: one module.
    for n, ms in by_name.items():
        mods = {m.module for m in ms}
        if len(mods) > 1:
            raise SystemExit(f"split_viewport: {n} bound in {mods}")
    # Class-body statements that read a class name bound above them (a
    # setter's ``@x.setter``, ``B = frozenset(A)``) need it beside.
    earlier = set()
    for m in members:
        if m.is_def:
            evald = set()
            a = m.stmt.args
            for d in (list(m.stmt.decorator_list) + list(a.defaults)
                      + [k for k in a.kw_defaults if k]):
                evald |= _ast_names(d)
        else:
            evald = _ast_names(m.stmt)
        reads, earlier = evald & earlier, earlier | set(m.names)
        for n in reads:
            other = by_name[n][0].module
            if other != m.module:
                raise SystemExit(
                    f"split_viewport: {m.name} ({m.module}) reads class "
                    f"name {n} at class creation, which goes to {other}")
    return members


def _member_calls(orig):
    """{name: {"calls": names it reads off self/Viewport, "by": readers}}."""
    names = {n for m in orig.members for n in m.names}
    out = {n: {"calls": set(), "by": set()} for n in names}
    for m in orig.members:
        for node in ast.walk(m.stmt):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in ("self", "Viewport", "cls", "vp")
                    and node.attr in names and node.attr != m.name):
                out[m.name]["calls"].add(node.attr)
                out[node.attr]["by"].add(m.name)
    return out


# ---------------------------------------------------------------------------
# Writing the package
# ---------------------------------------------------------------------------

def _fmt_from(module, items):
    one = f"from {module} import {', '.join(items)}\n"
    if len(one) <= WIDTH + 1:
        return one
    lead = f"from {module} import ("
    pad = " " * len(lead)
    out, line = [], lead
    for i, it in enumerate(items):
        piece = it + ("," if i < len(items) - 1 else ")")
        if line not in (lead,) and len(line) + 1 + len(piece) > WIDTH:
            out.append(line.rstrip() + "\n")
            line = pad + piece
        else:
            line = line + ("" if line == lead else " ") + piece
    out.append(line + "\n")
    return "".join(out)


def _alias_text(a):
    return a.name + (f" as {a.asname}" if a.asname else "")


def import_block(orig, needed):
    """Import statements, in the original's order, binding ``needed``."""
    out = []
    for stmt in orig.prelude:
        if not isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__":
            continue
        keep = [a for a in stmt.names
                if (a.asname or a.name.split(".")[0]) in needed]
        if not keep:
            continue
        if isinstance(stmt, ast.Import):
            for a in keep:
                out.append(f"import {_alias_text(a)}\n")
        else:
            mod = "." * stmt.level + (stmt.module or "")
            out.append(_fmt_from(mod, [_alias_text(a) for a in keep]))
    return "".join(out)


def support_import(orig, names):
    order = {n: i for i, n in enumerate(orig.bindings)}
    names = sorted(names, key=lambda n: order.get(n, 1 << 30))
    return _fmt_from("views.viewport._support", names) if names else ""


def build(orig, data, repo_names):
    """{relative path: text} of the package."""
    members = assign(orig, data)
    mglobals = orig.member_globals()
    builtin = set(dir(builtins))
    mods = data["modules"]
    files = {}
    head = orig.header
    by_mod = collections.defaultdict(list)
    for m in members:
        by_mod[m.module].append(m)

    def needs(ms, extra=()):
        need = set(extra)
        for m in ms:
            need |= mglobals[m]
            need |= {n for n in _annotation_strings(m.stmt)
                     if n in orig.bindings}
        unknown = sorted(n for n in need if n not in orig.bindings
                         and n not in builtin and n != "Viewport")
        need = {n for n in need if n in orig.bindings or n == "Viewport"}
        return need, unknown

    def members_text(ms):
        out = []
        for i, m in enumerate(ms):
            t = m.text
            if i == 0:
                t = "\n" + t.lstrip("\n")
            out.append(t)
        return "".join(out)

    unknown_all = {}
    for spec in mods:
        mod, mixin, doc = spec["module"], spec["mixin"], spec["doc"]
        ms = by_mod.get(mod, [])
        need, unknown = needs(ms)
        if unknown:
            unknown_all[mod] = unknown
        imports = [n for n in need if n in orig.bindings
                   and orig.bindings[n][0] == "import"]
        support = [n for n in need if n in orig.bindings
                   and orig.bindings[n][0] == "support"]
        text = [head, f'"""{doc}"""\n', "from __future__ import annotations\n"]
        block = import_block(orig, set(imports))
        sup = support_import(orig, support)
        if block or sup:
            text.append("\n")
            text.append(block)
            text.append(sup)
        if "Viewport" in need:
            text.append(VIEWPORT_PLACEHOLDER.replace("function", "method"))
        text.append(f"\n\nclass {mixin}:\n    \"\"\"{doc}\"\"\"\n")
        text.append(members_text(ms))
        files[f"{mod}.py"] = "".join(text)

    # _support.py: the original's module level, its imports trimmed.
    files["_support.py"] = support_text(orig, data)

    # __init__.py
    ms = by_mod.get("__init__", [])
    base_names = set()
    for b in orig.cls.bases:
        base_names |= _ast_names(b)
    need, unknown = needs(ms, base_names)
    if unknown:
        unknown_all["__init__"] = unknown
    need.discard("Viewport")
    reexport = sorted(n for n in repo_names
                      if n not in need and n not in _RESERVED
                      and n in orig.bindings)
    missing = sorted(n for n in repo_names if n not in orig.bindings
                     and n not in _RESERVED
                     and n not in orig.class_names)
    imports = {n for n in need if orig.bindings[n][0] == "import"}
    support = {n for n in need if orig.bindings[n][0] == "support"}
    re_imp = {n for n in reexport if orig.bindings[n][0] == "import"}
    re_sup = {n for n in reexport if orig.bindings[n][0] == "support"}
    parts = ["_support"] + [s["module"] for s in mods]
    text = [head, orig.docstring, "from __future__ import annotations\n\n",
            "import sys as _vp_sys\n", "import types as _vp_types\n"]
    block = import_block(orig, imports)
    if block or support:
        text.append("\n")
        text.append(block)
        text.append(support_import(orig, support))
    if re_imp or re_sup:
        text.append("\n# Re-exported: other modules and the tests import "
                    "these from views.viewport.\n")
        text.append(import_block(orig, re_imp))
        text.append(support_import(orig, re_sup))
    text.append("\n")
    text.append(_fmt_from("views.viewport", parts))
    for spec in mods:
        text.append(f"from views.viewport.{spec['module']} import "
                    f"{spec['mixin']}\n")
    bases = [s["mixin"] for s in mods] + orig.cls_bases
    lead = "class Viewport("
    line = lead
    lines = []
    for i, b in enumerate(bases):
        piece = b + ("," if i < len(bases) - 1 else "):")
        if line != lead and len(line) + 1 + len(piece) > WIDTH:
            lines.append(line.rstrip() + "\n")
            line = " " * len(lead) + piece
        else:
            line = line + ("" if line == lead else " ") + piece
    lines.append(line + "\n")
    text.append("\n\n" + "".join(lines))
    text.append(orig.cls_doc)
    text.append(members_text(ms))
    uses_vp = [s["module"] for s in mods
               if "Viewport" in needs(by_mod.get(s["module"], []))[0]]
    if "Viewport" in support_reads_viewport(orig):
        uses_vp.insert(0, "_support")
    text.append(PACKAGE_TAIL.format(
        parts=", ".join(parts),
        set_vp="".join(f"{p}.Viewport = Viewport\n" for p in uses_vp)))
    files["__init__.py"] = "".join(text)
    return files, members, unknown_all, missing


PACKAGE_TAIL = '''

# ---- views.viewport, still one module (#901) --------------------------------
# The methods that name ``Viewport.X`` find the class itself.
{set_vp}
#: Every part of the package; __init__ last, as it holds the least.
_PARTS = ({parts})


class _ViewportPackage(_vp_types.ModuleType):
    """``views.viewport`` as the one module it was before the split: a name
    set on it — a test's ``monkeypatch.setattr(views.viewport, ...)``, a
    switch flipped by a script — is set in every part that holds it, so
    the code in every part sees it, as when all of it was one file."""

    def __setattr__(self, name, value):
        held = [p for p in _PARTS if name in vars(p)]
        if not isinstance(value, _vp_types.ModuleType):
            for part in held:
                setattr(part, name, value)
        if not held or name in vars(self):
            super().__setattr__(name, value)

    def __delattr__(self, name):
        held = [p for p in _PARTS if name in vars(p)]
        for part in held:
            delattr(part, name)
        if not held or name in vars(self):
            super().__delattr__(name)


def __getattr__(name):
    """A name of a part read off views.viewport, live (a flag a helper
    rebinds with ``global`` reads as it is now)."""
    for part in _PARTS:
        d = vars(part)
        if name in d:
            return d[name]
    raise AttributeError(f"module {{__name__!r}} has no attribute {{name!r}}")


_vp_sys.modules[__name__].__class__ = _ViewportPackage
'''


def support_text(orig, data):
    """The original's module level verbatim, its import statements cut down
    to the names the module level itself reads."""
    used = set()
    for stmt in orig.prelude:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue
        for n in ast.walk(stmt):
            if isinstance(n, ast.Name):
                used.add(n.id)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                pass
        used |= _annotation_strings(stmt)
    lines = orig.lines
    out = []
    pos = orig.prelude_start            # 1-based next line to copy
    for stmt in orig.prelude:
        if not isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__":
            continue
        out.append("".join(lines[pos - 1:stmt.lineno - 1]))
        keep = [a for a in stmt.names
                if (a.asname or a.name.split(".")[0]) in used]
        if keep:
            if isinstance(stmt, ast.Import):
                out.append("".join(f"import {_alias_text(a)}\n"
                                   for a in keep))
            else:
                mod = "." * stmt.level + (stmt.module or "")
                out.append(_fmt_from(mod, [_alias_text(a) for a in keep]))
        pos = stmt.end_lineno + 1
    cls_first = orig.cls.lineno
    out.append("".join(lines[pos - 1:cls_first - 1]))
    body = "".join(out).rstrip("\n") + "\n"
    if "Viewport" in support_reads_viewport(orig):
        body += VIEWPORT_PLACEHOLDER
    return orig.header + f'"""{data["support_doc"]}"""\n' + body


VIEWPORT_PLACEHOLDER = (
    "\n#: The Viewport class, set by views/viewport/__init__.py once it "
    "exists: a\n#: function here that names ``Viewport.X`` reads (and "
    "writes) the class itself.\nViewport = None\n")


def support_reads_viewport(orig):
    """Global names the module-level functions read at call time."""
    st = symtable.symtable(orig.text, orig.filename, "exec")
    prelude_funcs = {s.name for s in orig.prelude
                     if isinstance(s, (ast.FunctionDef, ast.ClassDef))}
    out = set()
    for c in st.get_children():
        if c.get_name() in prelude_funcs:
            out |= _table_globals(c)
    return out


# ---------------------------------------------------------------------------
# What the repository reads from views.viewport
# ---------------------------------------------------------------------------

_SKIP_DIRS = {".git", "venv", ".venv", "node_modules", "build", "dist",
              "__pycache__", ".rustlib", "target"}


def repo_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS
                       and not d.startswith(".tmp")
                       and not (rel == Path("views") and d == "viewport")]
        for f in filenames:
            if f.endswith(".py"):
                p = Path(dirpath, f)
                if p.relative_to(root) == SRC:
                    continue
                if p.resolve() == Path(__file__).resolve():
                    continue
                yield p


def scan_repo(root):
    """What every other file takes from views.viewport.

    Returns ``(imported, read, patched, hazards)``: names imported with
    ``from views.viewport import``, attributes read off the module,
    names set on it, and ``(file, line, what)`` for code that looks at the
    file itself (its source, ``Viewport.__dict__``)."""
    imported = collections.defaultdict(set)
    read = collections.defaultdict(set)
    patched = collections.defaultdict(set)
    hazards = []
    for p in repo_files(root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "viewport" not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        rel = str(p.relative_to(root))
        aliases = set()
        dotted = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.module == "views.viewport":
                    for a in node.names:
                        imported[a.name].add(rel)
                elif node.module == "views":
                    for a in node.names:
                        if a.name == "viewport":
                            aliases.add(a.asname or "viewport")
            elif isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "views.viewport":
                        if a.asname:
                            aliases.add(a.asname)
                        else:
                            dotted = True
        for node in ast.walk(tree):
            target = None
            if isinstance(node, ast.Attribute):
                v = node.value
                if isinstance(v, ast.Name) and v.id in aliases:
                    target = node.attr
                elif (dotted and isinstance(v, ast.Attribute)
                      and v.attr == "viewport"
                      and isinstance(v.value, ast.Name)
                      and v.value.id == "views"):
                    target = node.attr
                if target:
                    if isinstance(node.ctx, (ast.Store, ast.Del)):
                        patched[target].add(rel)
                    else:
                        read[target].add(rel)
            if isinstance(node, ast.Call):
                f = node.func
                fname = (f.attr if isinstance(f, ast.Attribute)
                         else getattr(f, "id", None))
                if fname in ("setattr", "delattr", "setitem") and node.args:
                    a0 = node.args[0]
                    is_mod = (isinstance(a0, ast.Name) and a0.id in aliases)
                    if (is_mod and len(node.args) > 1
                            and isinstance(node.args[1], ast.Constant)):
                        patched[node.args[1].value].add(rel)
                    if (isinstance(a0, ast.Constant)
                            and isinstance(a0.value, str)
                            and a0.value.startswith("views.viewport.")):
                        patched[a0.value.split(".", 2)[2].split(".")[0]].add(
                            rel)
                if fname == "patch" and node.args:
                    a0 = node.args[0]
                    if (isinstance(a0, ast.Constant)
                            and isinstance(a0.value, str)
                            and a0.value.startswith("views.viewport.")):
                        patched[a0.value.split(".", 2)[2].split(".")[0]].add(
                            rel)
        for i, line in enumerate(text.splitlines(), 1):
            if re.search(r"Viewport\.__dict__|vars\(Viewport\)", line):
                hazards.append((rel, i, "copies members off "
                                "Viewport.__dict__ (mixins hold them)"))
            if re.search(r"""["']viewport\.py["']|viewport\.__file__|"""
                         r"""vpmod\.__file__|\bviewport\.py["']""", line):
                if not line.lstrip().startswith("#"):
                    hazards.append((rel, i, "reads the viewport's source "
                                    "file"))
    for d in (imported, read, patched):
        for k in [k for k in d if k in ("viewport",)]:
            del d[k]
    return imported, read, patched, hazards


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

DOCS = Path("docs/architecture.md")
DOCS_HEAD = "## Viewport package"


def docs_section(data):
    rows = ["| `__init__.py` | `Viewport` | The class: its Qt signals, "
            "`__init__`, the document (`set_document`), hover and the "
            "projection toggles |"]
    for spec in data["modules"]:
        rows.append(f"| `{spec['module']}.py` | `{spec['mixin']}` | "
                    f"{spec['doc']} |")
    rows.append(f"| `_support.py` | — | {data['support_doc']} |")
    return "\n".join([
        DOCS_HEAD, "",
        "`views/viewport/` holds the `Viewport` widget: one class, made of "
        "one mixin per job (#901). Import it as `from views.viewport import "
        "Viewport`.", "",
        "| Module | Mixin | Job |", "| --- | --- | --- |", *rows, "",
        "Put a new method in the mixin that owns its job. The mixins share "
        "one object and its attributes; a narrow interface between them is "
        "future work.", "",
        "Two things keep the package working as the one module it was:", "",
        "- A method may name the class itself (`Viewport.painting += 1`, "
        "`Viewport._paint_frame(self)`): each part that does has a "
        "`Viewport = None` placeholder that `__init__.py` sets to the class "
        "once it exists, so these read and write the real class and a test "
        "that patches `Viewport.X` still reaches them.",
        "- `views.viewport` is still the module the tests and the switches "
        "know: a name set on it (`monkeypatch.setattr(views.viewport, "
        "\"_NO_SNAP_FAST\", True)`) is set in every part that holds it, and "
        "a name read off it that `__init__.py` does not hold is read live "
        "from the part that does.", "",
        "`scripts/split_viewport.py` made the split from the single "
        "`views/viewport.py`, and `scripts/split_viewport.py --check` "
        "verifies it against that file (each member verbatim, the same "
        "code objects, the same `dir(Viewport)`).", ""])


def write_docs(data):
    path = ROOT / DOCS
    text = path.read_text(encoding="utf-8")
    section = docs_section(data)
    if DOCS_HEAD in text:
        a = text.index(DOCS_HEAD)
        b = text.find("\n## ", a + 1)
        text = text[:a] + section + (text[b + 1:] if b >= 0 else "")
    elif "\n## Scene graph" in text:
        a = text.index("\n## Scene graph") + 1
        text = text[:a] + section + "\n" + text[a:]
    else:
        text = text.rstrip("\n") + "\n\n" + section
    path.write_text(text, encoding="utf-8")


def cmd_split(args):
    src = ROOT / SRC
    if not src.exists():
        raise SystemExit(f"split_viewport: {SRC} not found (already split?)")
    orig = Original(src.read_text(encoding="utf-8"))
    data = load_map()
    imported, read, patched, hazards = scan_repo(ROOT)
    files, members, unknown, missing = build(orig, data, set(imported))
    for mod, names in unknown.items():
        print(f"warning: {mod} reads names bound nowhere: {names}")
    if missing:
        raise SystemExit(f"split_viewport: the repository imports from "
                         f"views.viewport names it does not have: {missing}")
    out = ROOT / PKG
    out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    src.unlink()
    write_docs(data)
    counts = collections.Counter(m.module for m in members)
    print(f"views/viewport.py -> {PKG}/: {len(members)} members in "
          f"{len(files)} files")
    for mod in ["__init__"] + [s["module"] for s in data["modules"]]:
        print(f"  {mod:14} {counts[mod]:4}")
    for rel, line, what in hazards:
        print(f"note: {rel}:{line}: {what}")
    print("now run: python scripts/split_viewport.py --check")


def cmd_plan(args):
    src = ROOT / SRC
    text = (src.read_text(encoding="utf-8") if src.exists()
            else original_text(args.orig))
    orig = Original(text)
    data = load_map()
    members = assign(orig, data)
    counts = collections.Counter(m.module for m in members)
    lines_by = collections.Counter()
    for m in members:
        lines_by[m.module] += m.end - m.start + 1
    for m in members:
        if m.why != "#901" or args.all:
            print(f"{m.stmt.lineno:6} {m.name:40} {m.module:13} {m.why}")
    print()
    for mod in ["__init__"] + [s["module"] for s in data["modules"]]:
        print(f"{mod:14} {counts[mod]:4} members {lines_by[mod]:6} lines")
    # How the rules would have placed pkoska's own members.
    bad = []
    for name, mod in data["pr901"].items():
        for rx, rmod, _ in RULES:
            if re.search(rx, name):
                if rmod != mod:
                    bad.append((name, mod, rmod))
                break
    if bad:
        print("\nrules that disagree with #901 (#901 wins):")
        for b in bad:
            print("  ", *b)


def original_text(spec):
    """The original file: ``spec`` (a path or ``REV:path``), else the
    working tree's, else the last commit that still had it."""
    if spec:
        p = Path(spec)
        if p.exists():
            return p.read_text(encoding="utf-8")
        return _git("show", spec)
    src = ROOT / SRC
    if src.exists():
        return src.read_text(encoding="utf-8")
    try:
        return _git("show", f"HEAD:{SRC}")
    except subprocess.CalledProcessError:
        pass
    rev = _git("rev-list", "-1", "HEAD", "--", str(SRC)).strip()
    return _git("show", f"{rev}^:{SRC}")


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


class Report:
    def __init__(self):
        self.errors = []
        self.notes = []

    def error(self, msg):
        self.errors.append(msg)
        print("FAIL", msg)

    def ok(self, msg):
        print("ok  ", msg)

    def note(self, msg):
        self.notes.append(msg)
        print("note", msg)


def cmd_check(args):
    rep = Report()
    text = original_text(args.orig)
    orig = Original(text)
    data = load_map()
    pkg = ROOT / PKG
    if not (pkg / "__init__.py").exists():
        raise SystemExit("split_viewport: views/viewport/ not found")
    if (ROOT / SRC).exists() and not args.orig:
        rep.error(f"{SRC} still exists beside the package")
    files = {p.name: p.read_text(encoding="utf-8")
             for p in sorted(pkg.glob("*.py"))}
    members = assign(orig, data)
    spec_mods = ["__init__"] + [s["module"] for s in data["modules"]]
    expect = {s + ".py" for s in spec_mods} | {"_support.py"}
    if set(files) != expect:
        rep.error(f"package files {sorted(set(files) ^ expect)}")

    # 1. Verbatim: every member's text once, in its module; nothing else.
    bad = 0
    for m in members:
        body = m.text.lstrip("\n")
        where = [f for f, t in files.items() if t.count(body)]
        n = sum(t.count(body) for t in files.values())
        if n != 1 or where != [m.module + ".py"]:
            bad += 1
            rep.error(f"{m.name}: text found {n}x in {where}, "
                      f"expected once in {m.module}.py")
    orig_lines = collections.Counter(
        ln for m in members for ln in m.text.splitlines() if ln.strip())
    new_lines = collections.Counter()
    for f, t in files.items():
        tree = ast.parse(t)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and (
                    node.name == "Viewport" or node.name.endswith("Mixin")):
                seg = t.splitlines()[node.body[0].end_lineno:node.end_lineno]
                new_lines.update(ln for ln in seg if ln.strip())
    if orig_lines != new_lines:
        diff = (orig_lines - new_lines) + (new_lines - orig_lines)
        rep.error(f"class-body lines differ: {list(diff.items())[:5]}")
    elif not bad:
        rep.ok(f"{len(members)} members, {sum(orig_lines.values())} "
               f"non-blank lines: each once, verbatim, in its module")
    sup = files.get("_support.py", "")
    for stmt in orig.prelude:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            continue
        seg = "".join(orig.lines[stmt.lineno - 1:stmt.end_lineno])
        if sup.count(seg) != 1:
            rep.error(f"module level at line {stmt.lineno} not verbatim "
                      f"in _support.py")
    rep.ok("module level copied verbatim into _support.py")

    # 2. Every global a part reads is bound in it (a symbol-table check).
    builtin = set(dir(builtins)) | {"__file__", "__name__", "__doc__",
                                    "__spec__", "__path__", "__builtins__"}
    unbound_before = _unbound(orig.text, orig.filename, builtin)
    for f, t in files.items():
        un = _unbound(t, f, builtin) - unbound_before
        if un:
            rep.error(f"{f}: reads names it does not bind: {sorted(un)}")
    rep.ok("every global each part reads is bound in that part")
    # A global a helper rebinds (``global X``) is read only beside it.
    for name, owners in orig.rebound.items():
        readers = [f for f, t in files.items()
                   if name in _globals_read(t, f)]
        homes = {f for f in readers if re.search(
            rf"^\s+global [^\n]*\b{name}\b", files[f], re.M)}
        if len(readers) > 1 and (set(readers) - homes):
            rep.error(f"{name} is rebound in {sorted(homes)} but read as a "
                      f"copy in {sorted(set(readers) - homes)}")
    rep.ok("globals rebound with `global` are read only where rebound")
    # A name a part holds must not be a part's own module name.
    for f, t in files.items():
        if f == "__init__.py":
            continue            # it imports the parts by name, on purpose
        g = _module_level_names(t)
        clash = g & set(m[:-3] for m in files)
        if clash:
            rep.error(f"{f} binds {clash}, the name of a part")
    # super() in a mixin reaches what it reached before.
    _check_super(files, data, rep)

    # 3. At run time: dir(Viewport), every member's code object.
    _runtime_check(orig, text, data, rep)

    # 4. What the repository takes from views.viewport.
    imported, read, patched, hazards = scan_repo(ROOT)
    _repo_check(imported, read, patched, rep)
    for rel, line, what in hazards:
        rep.note(f"{rel}:{line}: {what}")

    print()
    if rep.errors:
        print(f"{len(rep.errors)} problem(s)")
        return 1
    print("split_viewport --check: all good")
    return 0


def _unbound(text, filename, builtin):
    """Global names a module's code reads that it never binds."""
    tree = ast.parse(text)
    bound = _module_level_names(text)
    st = symtable.symtable(text, filename, "exec")
    used = set()

    def walk(tab):
        for s in tab.get_symbols():
            if tab.get_type() != "module" and s.is_global() and \
                    s.is_referenced():
                used.add(s.get_name())
        for c in tab.get_children():
            walk(c)
    walk(st)
    for s in st.get_symbols():
        if s.is_referenced():
            used.add(s.get_name())
    del tree
    return {n for n in used if n not in bound and n not in builtin}


def _globals_read(text, filename):
    st = symtable.symtable(text, filename, "exec")
    used = set()

    def walk(tab):
        for s in tab.get_symbols():
            if tab.get_type() == "function" and s.is_global() and \
                    s.is_referenced():
                used.add(s.get_name())
        for c in tab.get_children():
            walk(c)
    walk(st)
    return used


def _module_level_names(text):
    tree = ast.parse(text)
    out = set()
    for stmt in tree.body:
        if isinstance(stmt, (ast.Import, ast.ImportFrom)):
            for a in stmt.names:
                out.add(a.asname or a.name.split(".")[0])
        else:
            out |= set(_bound_names(stmt))
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            out |= set(node.names)
    return out


def _check_super(files, data, rep):
    order = [s["module"] for s in data["modules"]]
    defined = {}
    for mod in order:
        tree = ast.parse(files[mod + ".py"])
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        defined[mod] = {n for s in cls.body for n in _bound_names(s)}
    for i, mod in enumerate(order):
        tree = ast.parse(files[mod + ".py"])
        later = set().union(*[defined[m] for m in order[i + 1:]] or [set()])
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "super"
                    and not node.value.args):
                if node.attr in later:
                    rep.error(f"{mod}: super().{node.attr} now reaches a "
                              f"later mixin")
    rep.ok("super() calls in the mixins reach the Qt base as before")


def _instructions(code):
    """The instructions of ``code``, without what the compiler varies with
    the module around the function: since Python 3.14 a call like
    ``QTimer.singleShot(...)`` compiles as a plain attribute load plus
    ``PUSH_NULL`` when ``QTimer`` is also imported at the module's top
    level, and as a method load when it is not — the same call."""
    import dis
    out = []
    for ins in dis.get_instructions(code):
        if ins.opname == "PUSH_NULL":
            continue
        if ins.opname == "LOAD_ATTR":
            out.append((ins.opname, ins.argval))
        elif ins.opcode in dis.hasjump or ins.opname.startswith(
                ("JUMP", "POP_JUMP", "FOR_ITER", "SEND")):
            out.append((ins.opname, ins.argrepr))
        elif isinstance(ins.argval, types.CodeType):
            out.append((ins.opname, ins.argval.co_name))
        else:
            out.append((ins.opname, repr(ins.argval)))
    return out


def _code_same(a, b, path, diffs):
    for attr in ("co_names", "co_varnames", "co_freevars", "co_cellvars",
                 "co_argcount", "co_posonlyargcount", "co_kwonlyargcount",
                 "co_flags", "co_nlocals", "co_name"):
        if getattr(a, attr, None) != getattr(b, attr, None):
            diffs.append(f"{path}: {attr}")
            return
    if a.co_code != b.co_code and _instructions(a) != _instructions(b):
        diffs.append(f"{path}: instructions")
        return
    if len(a.co_consts) != len(b.co_consts):
        diffs.append(f"{path}: consts")
        return
    for i, (x, y) in enumerate(zip(a.co_consts, b.co_consts)):
        if isinstance(x, types.CodeType) and isinstance(y, types.CodeType):
            _code_same(x, y, f"{path}.{x.co_name}", diffs)
        elif type(x) is not type(y) or (x != y and not (x != x and y != y)):
            diffs.append(f"{path}: const {i}")


def _value_same(x, y):
    if type(x) is object and type(y) is object:
        return True                     # a sentinel such as _NO_PAINT
    if isinstance(x, tuple) and isinstance(y, tuple):
        return len(x) == len(y) and all(map(_value_same, x, y))
    if isinstance(x, dict) and isinstance(y, dict):
        return x.keys() == y.keys() and all(_value_same(x[k], y[k])
                                            for k in x)
    return repr(x) == repr(y)


def _func_same(a, b, path, diffs):
    _code_same(a.__code__, b.__code__, path, diffs)
    if not (_value_same(a.__defaults__, b.__defaults__)
            and _value_same(a.__kwdefaults__, b.__kwdefaults__)):
        diffs.append(f"{path}: defaults")


def _static_lookup(cls, name):
    for k in cls.__mro__:
        if name in k.__dict__:
            return k, k.__dict__[name]
    return None, None


def _runtime_check(orig, text, data, rep):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    os.chdir(ROOT)
    tmp = Path(tempfile.mkdtemp(prefix="split-viewport-"))
    path = tmp / "_viewport_original.py"
    path.write_text(text, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_viewport_original", path)
    old_mod = importlib.util.module_from_spec(spec)
    sys.modules["_viewport_original"] = old_mod
    spec.loader.exec_module(old_mod)
    new_pkg = importlib.import_module("views.viewport")
    Old, New = old_mod.Viewport, new_pkg.Viewport
    old_dir, new_dir = set(dir(Old)), set(dir(New))
    extra = new_dir - old_dir
    gone = old_dir - new_dir
    if gone:
        rep.error(f"dir(Viewport) lost {sorted(gone)}")
    if extra - {"__dict__", "__weakref__"}:
        rep.error(f"dir(Viewport) gained {sorted(extra)}")
    elif not gone:
        rep.ok(f"dir(Viewport): the same {len(old_dir)} names"
               + (f" (+ {sorted(extra)} of the mixins)" if extra else ""))
    diffs = []
    owner_mod = {m.name: m.module for m in orig.members}
    member_names = {n for m in orig.members for n in m.names}
    for name in sorted(old_dir & new_dir):
        ok_, a = _static_lookup(Old, name)
        nk, b = _static_lookup(New, name)
        if ok_ is Old and name not in member_names:
            continue            # made by Python or Qt per class (__doc__...)
        if name in ("__dict__", "__weakref__"):
            continue            # the mixins are plain classes: theirs
        if ok_ is Old:
            want = owner_mod.get(name)
            where = (nk.__module__ if nk is not None else None)
            exp = ("views.viewport" if want == "__init__"
                   else f"views.viewport.{want}")
            if where != exp:
                diffs.append(f"{name}: defined in {where}, expected {exp}")
            if type(a) is not type(b):
                diffs.append(f"{name}: {type(a).__name__} became "
                             f"{type(b).__name__}")
                continue
            if isinstance(a, types.FunctionType):
                _func_same(a, b, name, diffs)
            elif isinstance(a, (staticmethod, classmethod)):
                _func_same(a.__func__, b.__func__, name, diffs)
            elif isinstance(a, property):
                for part in ("fget", "fset", "fdel"):
                    x, y = getattr(a, part), getattr(b, part)
                    if (x is None) != (y is None):
                        diffs.append(f"{name}.{part}")
                    elif x is not None:
                        _func_same(x, y, f"{name}.{part}", diffs)
            elif type(a).__name__ == "Signal":
                if str(a) != str(b):
                    diffs.append(f"{name}: signal {a} != {b}")
            else:
                try:
                    same = a == b
                    if not isinstance(same, bool):
                        same = repr(a) == repr(b)
                except Exception:                       # noqa: BLE001
                    same = repr(a) == repr(b)
                if not same:
                    diffs.append(f"{name}: value {a!r} != {b!r}")
        elif nk is not None and (nk.__module__ or "").startswith(
                "views.viewport"):
            diffs.append(f"{name}: comes from {nk.__name__} now, from "
                         f"{ok_.__name__ if ok_ else None} before")
        elif a is not b:
            diffs.append(f"{name}: inherited from a different object")
    if diffs:
        for d in diffs[:40]:
            rep.error(d)
    else:
        rep.ok("every member: same kind, same code object, same value, in "
               "its module; inherited ones from the same Qt base")
    st_old = set(getattr(Old, "__static_attributes__", ()))
    st_new = set()
    for k in New.__mro__:
        if k.__module__.startswith("views.viewport"):
            st_new |= set(k.__dict__.get("__static_attributes__", ()))
    if st_old != st_new:
        rep.error(f"self.X attributes differ: {sorted(st_old ^ st_new)}")
    else:
        rep.ok(f"the {len(st_old)} instance attributes the methods set "
               f"(__static_attributes__) are the same, now per mixin")
    mro_old = [k.__name__ for k in Old.__mro__[1:]]
    mro_new = [k.__name__ for k in New.__mro__[1:]
               if not k.__module__.startswith("views.viewport")]
    if mro_old != mro_new:
        rep.error(f"MRO past the mixins differs: {mro_old} / {mro_new}")
    else:
        rep.ok("MRO: the mixins, then the same Qt bases as before")
    # Module level: the same names, the same objects for constants.
    new_names = set(vars(new_pkg))
    for part in new_pkg._PARTS:
        new_names |= set(vars(part))
    read_anywhere = _globals_read(orig.text, orig.filename) | {
        n.id for n in ast.walk(orig.tree) if isinstance(n, ast.Name)}
    lost = 0
    for n in orig.bindings:
        if n not in new_names and n not in orig.rebound:
            if orig.bindings[n][0] == "import" and n not in read_anywhere:
                rep.note(f"import of {n} dropped: nothing in the original "
                         f"reads it")
                continue
            lost += 1
            rep.error(f"module-level {n} is in no part")
    if not lost:
        rep.ok("every module-level name the original uses is in a part")
    # A name set on views.viewport reaches every part that holds it.
    probe = "_NO_SNAP_FAST"
    holders = [p for p in new_pkg._PARTS if probe in vars(p)]
    old = getattr(new_pkg, probe)
    sentinel = object()
    setattr(new_pkg, probe, sentinel)
    reached = all(vars(p)[probe] is sentinel for p in holders)
    setattr(new_pkg, probe, old)
    back = all(vars(p)[probe] is old for p in holders)
    if not (reached and back and holders):
        rep.error("setting views.viewport._NO_SNAP_FAST does not reach "
                  "the parts")
    else:
        rep.ok(f"a name set on views.viewport reaches the "
               f"{len(holders)} parts that hold it, and is restored")


def _repo_check(imported, read, patched, rep):
    import views.viewport as pkg
    bad = [n for n in imported if not hasattr(pkg, n)]
    if bad:
        rep.error(f"`from views.viewport import` fails for {sorted(bad)}")
    else:
        rep.ok(f"`from views.viewport import X` works for the "
               f"{len(imported)} names the repository imports")
    bad = [n for n in read if not hasattr(pkg, n)]
    subs = {p.__name__.rsplit(".", 1)[1] for p in pkg._PARTS}
    bad = [n for n in bad if n not in subs]
    if bad:
        rep.error(f"views.viewport.X fails for {sorted(bad)}: "
                  + "; ".join(f"{n} in {sorted(read[n])}" for n in bad))
    else:
        rep.ok(f"views.viewport.X resolves for the {len(read)} names the "
               f"repository reads off the module")
    for n in sorted(patched):
        holders = [p.__name__ for p in pkg._PARTS if n in vars(p)]
        if not holders and not hasattr(pkg, n):
            old = sys.modules.get("_viewport_original")
            if old is not None and not hasattr(old, n):
                rep.note(f"{n} is set on views.viewport in "
                         f"{sorted(patched[n])} but the original did not "
                         f"have it either (a guarded patch)")
                continue
            rep.error(f"{n} is patched on views.viewport "
                      f"({sorted(patched[n])}) but no part holds it")
    rep.ok(f"the {len(patched)} names the tests set on views.viewport are "
           f"held by a part (each set reaches them all): "
           + ", ".join(sorted(patched)))


# ---------------------------------------------------------------------------
# The map from pkoska's branch
# ---------------------------------------------------------------------------

def cmd_extract(args):
    rev = args.extract_map
    files = _git("ls-tree", "--name-only", rev, "views/viewport/").split()
    pr = {}
    docs = {}
    order = None
    for f in files:
        text = _git("show", f"{rev}:{f}")
        tree = ast.parse(text)
        mod = Path(f).stem
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and (
                    node.name.endswith("Mixin") or node.name == "Viewport"):
                for s in node.body:
                    for n in _bound_names(s):
                        pr[n] = mod
                if node.name == "Viewport":
                    order = [ast.unparse(b) for b in node.bases]
                else:
                    docs[node.name] = (mod, ast.get_docstring(node))
    by_mixin = {k: v for k, v in docs.items()}
    data = load_map() if MAP_FILE.exists() else {"exceptions": {}}
    data["pr901_source"] = rev
    data["modules"] = [{"module": by_mixin[b][0], "mixin": b,
                        "doc": by_mixin[b][1]}
                       for b in order if b in by_mixin]
    data["support_doc"] = ast.get_docstring(ast.parse(
        _git("show", f"{rev}:views/viewport/_support.py")))
    data["pr901"] = dict(sorted(pr.items()))
    MAP_FILE.write_text(json.dumps(data, indent=1, ensure_ascii=False)
                        + "\n", encoding="utf-8")
    print(f"{MAP_FILE.name}: {len(pr)} members from {rev}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="verify views/viewport/ against the original")
    ap.add_argument("--plan", action="store_true",
                    help="print where the members not placed by #901 go")
    ap.add_argument("--all", action="store_true",
                    help="with --plan: every member")
    ap.add_argument("--orig", help="the original file (path or REV:path)")
    ap.add_argument("--extract-map", metavar="REV",
                    help="rebuild the pr901 section from pkoska's branch")
    args = ap.parse_args(argv)
    os.chdir(ROOT)
    if args.extract_map:
        return cmd_extract(args)
    if args.plan:
        return cmd_plan(args)
    if args.check:
        return cmd_check(args)
    return cmd_split(args)


if __name__ == "__main__":
    sys.exit(main())
