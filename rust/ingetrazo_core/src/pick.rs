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

/// ``core.edge_grid.EdgeGrid``'s binning: what its constructor keeps.
pub struct Bins {
    pub cx0: i64,
    pub cy0: i64,
    pub ncx: i64,
    pub ncy: i64,
    pub long_ids: Vec<i64>,
    pub keys: Vec<i64>,
    pub ids: Vec<i64>,
}

/// ``EdgeGrid.__init__``, step by step: the segments a cursor in the view
/// can come within ``reach`` of, each binned into the cells its box covers
/// (``max_cells`` at most; longer ones go to ``long_ids``), the (cell key,
/// segment) pairs in segment then cell order, sorted stably by key —
/// NumPy's ``argsort(kind="stable")``. Floors, clips and the integer key
/// arithmetic are exact, so the bins are NumPy's. ``reach``, ``cell``,
/// ``w`` and ``h`` are finite (the caller checks).
#[allow(clippy::too_many_arguments)]
pub fn grid_bins(ax: &[f64], ay: &[f64], bx: &[f64], by: &[f64], ok: &[bool], w: f64, h: f64,
                 reach: f64, cell: f64, max_cells: i64) -> Bins {
    let cx0 = (-reach / cell).floor() as i64;
    let cy0 = (-reach / cell).floor() as i64;
    let cx1 = ((w + reach) / cell).floor() as i64;
    let cy1 = ((h + reach) / cell).floor() as i64;
    let (ncx, ncy) = (cx1 - cx0 + 1, cy1 - cy0 + 1);
    let clip = |v: f64, lo: i64, hi: i64| -> i64 {
        let f = v.floor();
        let (lo, hi) = (lo as f64, hi as f64);
        (if f < lo { lo } else if f > hi { hi } else { f }) as i64
    };
    let mut long_ids = Vec::new();
    let mut pairs: Vec<(i64, i64)> = Vec::new();
    for i in 0..ax.len() {
        // np.minimum / np.maximum: a NaN on either side gives NaN, which
        // the finiteness test below drops.
        let mn = |a: f64, b: f64| if a.is_nan() || b.is_nan() { f64::NAN } else if b < a { b } else { a };
        let mx = |a: f64, b: f64| if a.is_nan() || b.is_nan() { f64::NAN } else if b > a { b } else { a };
        let (lox, hix) = (mn(ax[i], bx[i]), mx(ax[i], bx[i]));
        let (loy, hiy) = (mn(ay[i], by[i]), mx(ay[i], by[i]));
        let live = ok[i] && lox.is_finite() && hix.is_finite() && loy.is_finite()
            && hiy.is_finite() && hix >= -reach && lox <= w + reach && hiy >= -reach
            && loy <= h + reach;
        if !live {
            continue;
        }
        let x0 = clip(lox / cell, cx0, cx1);
        let x1 = clip(hix / cell, cx0, cx1);
        let y0 = clip(loy / cell, cy0, cy1);
        let y1 = clip(hiy / cell, cy0, cy1);
        let (nx, ny) = (x1 - x0 + 1, y1 - y0 + 1);
        let span = nx * ny;
        if span > max_cells {
            long_ids.push(i as i64);
            continue;
        }
        for k in 0..span {
            let cx = x0 + k % nx;
            let cy = y0 + k / nx;
            pairs.push(((cy - cy0) * ncx + (cx - cx0), i as i64));
        }
    }
    pairs.sort_by_key(|p| p.0);              // stable, as NumPy's
    let (keys, ids) = pairs.into_iter().unzip();
    Bins { cx0, cy0, ncx, ncy, long_ids, keys, ids }
}
