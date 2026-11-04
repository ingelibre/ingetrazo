#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Ibrahim Halim Gokbulut (h-skycloud).
"""Check the Turkish catalogue against current canonical source messages."""
import collections
import json
from pathlib import Path
import re
import string

ROOT = Path(__file__).resolve().parents[1]


def verify():
    errors = []
    def unique(pairs):
        data = {}
        for k, v in pairs:
            if k in data:
                errors.append(f"Duplicate key: {k!r}")
            data[k] = v
        return data

    source = json.loads((ROOT / "i18n/es.json").read_text(encoding="utf-8"))
    target = json.loads((ROOT / "i18n/tr.json").read_text(encoding="utf-8"), object_pairs_hook=unique)
    for key in source.keys() - target.keys():
        errors.append(f"Missing key: {key!r}")
    for key in target.keys() - source.keys():
        errors.append(f"Unexpected key: {key!r}")
    patterns = {
        "IFC/schema identifiers": r"\b(?:Ifc[A-Za-z0-9_]+|(?:Pset|Qto)_[A-Za-z0-9_]+|PredefinedType)\b",
        "file extensions": r"(?<!\w)\.[A-Za-z][A-Za-z0-9]{1,7}\b",
        "markup": r"<[A-Za-z_][^>]*>",
        "printf": r"%(?:\([^)]*\))?[0-9.$+#-]*[sdif]",
    }
    formatter = string.Formatter()
    for key, value in target.items():
        if not isinstance(value, str) or not value.strip():
            errors.append(f"Empty/non-string: {key!r}")
            continue
        fields = lambda text: collections.Counter((f, spec, conv) for _, f, spec, conv in formatter.parse(text) if f is not None)
        if fields(key) != fields(value):
            errors.append(f"Brace fields: {key!r}")
        for name, pattern in patterns.items():
            if collections.Counter(re.findall(pattern, key)) != collections.Counter(re.findall(pattern, value)):
                errors.append(f"{name}: {key!r}")
        if key.count("\n") != value.count("\n"):
            errors.append(f"Newlines: {key!r}")
        if (key.startswith(" ") and not value.startswith(" ")) or (key.endswith(" ") and not value.endswith(" ")):
            errors.append(f"Boundary spaces: {key!r}")
    return {"source_keys": len(source), "turkish_keys": len(target), "errors": errors}


if __name__ == "__main__":
    report = verify()
    print(json.dumps(report, ensure_ascii=True, indent=2))
    raise SystemExit(bool(report["errors"]))
