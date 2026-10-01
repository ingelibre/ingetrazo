# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Fuzzy search over short labels, after Blender's F3 menu search.

A port of Blender's ``source/blender/blenlib/intern/string_search.cc``
(GPL-2.0-or-later, © Blender Authors), the matcher behind its F3 box. Each
word of the query must find its own word in the item, trying in turn:

1. a word that STARTS with it  («ori» → Orient) — 10 points, 9 when the
   word is in the menu path rather than in the command's own name;
2. the INITIALS of consecutive words, several letters per word allowed
   («rf» → Reverse Faces, «seboulo» → Select Boundary Loop) — 4 / 3;
3. a word it matches with a few TYPING ERRORS («orinet» → Orient; one
   error per 8 letters, plus one) — 3 minus the errors.

A word of the item serves one word of the query only, and every query
word out of order costs a point. Among the best matches the one with the
shortest name comes first; with one letter typed or none, the ones used
last do. Unlike Blender, accents and case are ignored everywhere.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

#: Blender's menu separator; what separates the groups of an item.
GROUP_SEP = "▸"
_SPLIT = re.compile(r"[\s\-_/▸]+")
_UNUSED = -1


@lru_cache(maxsize=1 << 13)
def fold(text: str) -> str:
    """Lower case, no accents: «Rotación» and «rotacion» are one word.
    Remembered: the same labels are folded each time a box opens."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in decomposed
                   if not unicodedata.combining(c)).casefold()


def words_of(text: str) -> list:
    return [w for w in _SPLIT.split(fold(text)) if w]


class Item:
    """One searchable label split into words. ``groups`` are its parts —
    a menu path then the name; the last group is the MAIN one."""

    __slots__ = ("words", "main", "main_length", "total_length")

    def __init__(self, groups) -> None:
        groups = [g for g in groups if g and g.strip()]
        words, main = [], []
        for i, group in enumerate(groups):
            for w in words_of(group):
                words.append(w)
                main.append(i == len(groups) - 1)
        self.words = tuple(words)
        self.main = tuple(main)
        self.main_length = sum(len(w) for w, m in zip(words, main) if m)
        self.total_length = sum(len(g) for g in groups)


@lru_cache(maxsize=1 << 16)
def damerau_levenshtein(a: str, b: str) -> int:
    """Edits (insert, delete, substitute, swap two) turning ``a`` into
    ``b``; three rolling rows, as Blender keeps them."""
    v0 = [0] * (len(b) + 1)
    v1 = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        v2 = [i + 1] + [0] * len(b)
        for j, cb in enumerate(b):
            cost = min(v1[j + 1] + 1, v2[j] + 1, v1[j] + (ca != cb))
            if i and j and ca == b[j - 1] and a[i - 1] == cb:
                cost = min(cost, v0[j - 1] + 1)
            v2[j + 1] = cost
        v0, v1 = v1, v2
    return v1[-1]


@lru_cache(maxsize=1 << 16)
def fuzzy_errors(query: str, full: str) -> int:
    """How many errors ``query`` has as a part of ``full``; -1 when it is
    no reasonable match. 0 when it is found as it is."""
    if query in full:
        return 0
    n, m = len(query), len(full)
    if n <= 1:
        return -1
    max_errors = n // 8 + 1
    if n - m > max_errors:
        return -1
    window = min(n + max_errors, m)
    max_distance = max_errors + max(window - n, 0)
    begin, end = 0, window
    while True:
        distance = 0
        # The first or second letter is expected right: that spares most
        # of the costly distances.
        if full[begin] in (query[0], query[1]):
            distance = damerau_levenshtein(query, full[begin:end])
            if distance <= max_distance:
                return distance
        if end == m:
            return -1
        for _ in range(max(1, distance // 2)):
            if end < m:
                begin += 1
                end += 1


def _initials(query: str, item: Item, used: list, start: int = 0):
    """Word indices whose first letters spell ``query``, in order, words
    skippable; ``None`` when they cannot. Prefers more main-group words."""
    words = item.words
    if start >= len(words):
        return None
    matched: list = []
    word, char, first = start, 0, -1
    for q in query:
        while True:
            if word >= len(words):
                if first >= 0:
                    return _initials(query, item, used, first + 1)
                return None
            if used[word] != _UNUSED:
                word += 1
                continue
            if char < len(words[word]) and words[word][char] == q:
                char += 1
                matched.append(word)
                if first == -1:
                    first = word
                break
            word, char = word + 1, 0
    later = _initials(query, item, used, first + 1)
    if later is not None and _mains(later, item) > _mains(matched, item):
        return later
    return matched


def _mains(indices, item: Item) -> int:
    return sum(1 for i in indices if item.main[i])


def _best_prefix(query: str, item: Item, used: list, remaining) -> int:
    # When a later query word starts like this one, take the SHORTEST
    # word, or «t test» would stop matching «T ▸ Test».
    shortest = any(other.startswith(query) for other in remaining)
    best, best_size, best_main = -1, 1 << 30, False
    for i, w in enumerate(item.words):
        if used[i] != _UNUSED or not w.startswith(query):
            continue
        if (len(w) < best_size) if shortest else not best_main:
            best, best_size, best_main = i, len(w), item.main[i]
    return best


def score(query_words, item: Item):
    """Blender's score of ``item`` for the (folded) query words, or
    ``None`` when some word finds nothing."""
    used = [_UNUSED] * len(item.words)
    total = 1000
    for qi, q in enumerate(query_words):
        i = _best_prefix(q, item, used, query_words[qi + 1:])
        if i >= 0:
            total += 10 if item.main[i] else 9
            used[i] = qi
            continue
        hit = _initials(q, item, used)
        if hit is not None:
            total += 4 if _mains(hit, item) == len(hit) else 3
            for i in hit:
                used[i] = qi
            continue
        for i, w in enumerate(item.words):
            if used[i] == _UNUSED:
                errors = fuzzy_errors(q, w)
                if errors >= 0:
                    total += 3 - errors
                    used[i] = qi
                    break
        else:
            return None
    order = [u for u in used if u != _UNUSED]
    total -= sum(1 for a, b in zip(order, order[1:]) if a > b)
    return total


def rank(query: str, entries, recent=None) -> list:
    """Sort the ``entries`` that match ``query``, best first.

    ``entries`` are ``(payload, items)`` pairs — several items for one
    payload (the same command in two languages): the best of them counts.
    ``recent(payload)`` is a number, larger for the more recently used.
    Entries come back in the order given when nothing tells them apart."""
    query_words = words_of(query)
    scored = []
    for order, (payload, items) in enumerate(entries):
        best = None
        for item in items:
            s = score(query_words, item)
            if s is not None and (best is None or s > best[0]):
                best = (s, item)
        if best is not None:
            scored.append((best[0], order, best[1], payload))
    if not scored:
        return []
    top = max(s for s, *_ in scored)
    first = [e for e in scored if e[0] == top]
    rest = sorted((e for e in scored if e[0] != top),
                  key=lambda e: (-e[0], e[1]))
    if query_words:
        # Shorter names are likelier what was meant; an exact name thus
        # comes before the longer ones that contain it.
        first.sort(key=lambda e: (e[2].main_length, e[2].total_length))
    if recent is not None and len(query.strip()) <= 1:
        first.sort(key=lambda e: -recent(e[3]))    # stable: ties keep order
    return [e[3] for e in first + rest]
