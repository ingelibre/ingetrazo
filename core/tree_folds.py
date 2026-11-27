# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Which branches of the side trees are folded, kept with the document.

Each tree of the side panels (Layers, Scenes, the Browser, BIM, the
composer's scene list) keeps a set of string keys on the scene — folder
names, group uids, row keys — under a name of its own in
``scene.tree_folds``. The panel reads and changes that very set, so the
state is per document, and the ``.igz`` writes it with the next save
(#1694). It is view state, not an edit: folding a branch is not undone and
does not mark the document modified.

What a key means is the panel's business: for most trees the set holds the
*folded* folders (everything else opens), for the Browser the *opened*
groups (everything else stays shut).
"""
from __future__ import annotations

#: The trees and what their set holds.
LAYERS = "layers"                   # folded folder names
SCENES = "scenes"                   # folded folder names (Scenes tab)
COMPOSER_SCENES = "composer_scenes"  # folded folder names (composer)
BROWSER = "browser"                 # opened group uids
BROWSER_HEADS = "browser_heads"     # folded layer / folder headings
BIM = "bim"                         # folded row keys

#: A file never brings more keys per tree than this (a damaged or hostile
#: file must not fill the memory with strings).
MAX_KEYS = 20000


def folds(scene, tree: str) -> set:
    """The live set of ``tree``'s keys on ``scene`` (made empty when the
    document has none yet). Changing it changes what the next save
    writes."""
    store = getattr(scene, "tree_folds", None)
    if not isinstance(store, dict):
        store = {}
        try:
            scene.tree_folds = store
        except AttributeError:          # a stand-in scene without the field
            return set()
    keys = store.get(tree)
    if not isinstance(keys, set):
        keys = set(keys or ())
        store[tree] = keys
    return keys


def to_payload(scene) -> dict:
    """``{tree: [keys…]}`` for the file — sorted, so a save of an unchanged
    document writes the same bytes; empty trees left out."""
    store = getattr(scene, "tree_folds", None) or {}
    out = {}
    for tree, keys in store.items():
        if not isinstance(tree, str):
            continue
        clean = sorted(k for k in keys or () if isinstance(k, str) and k)
        if clean:
            out[tree] = clean
    return out


def from_payload(scene, raw) -> None:
    """Set ``scene.tree_folds`` from what a file holds; anything that is not
    a map of names to lists of strings is ignored."""
    store: dict = {}
    if isinstance(raw, dict):
        for tree, keys in raw.items():
            if isinstance(tree, str) and isinstance(keys, list):
                store[tree] = {k for k in keys[:MAX_KEYS]
                               if isinstance(k, str) and k}
    scene.tree_folds = store
