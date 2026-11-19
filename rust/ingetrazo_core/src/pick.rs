// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! The hover's pick passes (views.viewport): what runs on every mouse move
//! with Line, Move and Push/Pull to tell the face, edge or corner under the
//! cursor. Each kernel is its NumPy original's arithmetic, operation by
//! operation, so both give the same bits.

/// ``Viewport._project_px`` for row ``p``: ``(px, py, in front)``. ``m`` is
/// the MVP row-major (``m[r * 4 + c]``). NumPy evaluates the clip row as
/// ``p0*m[r,0] + p1*m[r,1] + p2*m[r,2] + m[r,3]`` left to right, term by
/// term in float64; Rust never fuses a multiply-add on its own.
#[inline]
pub fn project_one(p: [f64; 3], m: &[f64; 16], w: f64, h: f64) -> (f64, f64, bool) {
    let row = |r: usize| p[0] * m[r * 4] + p[1] * m[r * 4 + 1] + p[2] * m[r * 4 + 2]
        + m[r * 4 + 3];
    let (cx, cy, cw) = (row(0), row(1), row(3));
    let ok = cw > 0.0;
    let safe = if ok { cw } else { 1.0 };
    let px = (cx / safe * 0.5 + 0.5) * w;
    let py = (1.0 - (cy / safe * 0.5 + 0.5)) * h;
    (px, py, ok)
}
