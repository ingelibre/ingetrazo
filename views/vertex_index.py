# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Exact-byte vertex indexing: no welding, reordering or quantization."""
import numpy as np


def index_vertices(raw, stride):
    if not raw:
        return raw, b''
    rows = np.frombuffer(raw, dtype=f'V{stride}')
    unique, inverse = np.unique(rows, return_inverse=True)
    # Keep the array path when indexing does not save storage/work.
    if unique.nbytes + len(rows) * 4 >= len(raw) * .95:
        return raw, b''
    return unique.tobytes(), inverse.astype(np.uint32).tobytes()
