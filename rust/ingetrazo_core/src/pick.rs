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
    use rayon::prelude::*;
    // Per segment: None (not live), Some(None) (too long to bin) or its
    // first cell and extent — in parallel, each on its own.
    let cells: Vec<Option<Option<(i64, i64, i64, i64)>>> = (0..ax.len()).into_par_iter()
        .with_min_len(8192).map(|i| {
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
            return None;
        }
        let x0 = clip(lox / cell, cx0, cx1);
        let x1 = clip(hix / cell, cx0, cx1);
        let y0 = clip(loy / cell, cy0, cy1);
        let y1 = clip(hiy / cell, cy0, cy1);
        let (nx, ny) = (x1 - x0 + 1, y1 - y0 + 1);
        if nx * ny > max_cells {
            return Some(None);
        }
        Some(Some((x0, y0, nx, ny)))
    }).collect();
    let mut long_ids = Vec::new();
    let ncell = (ncx * ncy) as usize;
    // NumPy's stable sort by cell key, as a counting sort: segment by
    // segment, each segment's cells in order, every key's bucket filled in
    // that same order.
    let mut count = vec![0usize; ncell + 1];
    for (i, c) in cells.iter().enumerate() {
        match c {
            None => {}
            Some(None) => long_ids.push(i as i64),
            Some(Some((x0, y0, nx, ny))) => {
                for k in 0..nx * ny {
                    let key = (y0 + k / nx - cy0) * ncx + (x0 + k % nx - cx0);
                    count[key as usize + 1] += 1;
                }
            }
        }
    }
    for c in 1..=ncell {
        count[c] += count[c - 1];
    }
    let total = count[ncell];
    let mut keys = vec![0i64; total];
    let mut ids = vec![0i64; total];
    for (i, c) in cells.iter().enumerate() {
        if let Some(Some((x0, y0, nx, ny))) = c {
            for k in 0..nx * ny {
                let key = (y0 + k / nx - cy0) * ncx + (x0 + k % nx - cx0);
                let at = &mut count[key as usize];
                keys[*at] = key;
                ids[*at] = i as i64;
                *at += 1;
            }
        }
    }
    Bins { cx0, cy0, ncx, ncy, long_ids, keys, ids }
}

/// ``np.minimum`` / ``np.maximum`` of two floats: a NaN on either side
/// gives NaN.
#[inline]
fn np_min(a: f64, b: f64) -> f64 {
    if a.is_nan() || b.is_nan() { f64::NAN } else if b < a { b } else { a }
}

#[inline]
fn np_max(a: f64, b: f64) -> f64 {
    if a.is_nan() || b.is_nan() { f64::NAN } else if b > a { b } else { a }
}

/// ``np.fmax`` / ``np.fmin``: a NaN on one side gives the other side.
#[inline]
fn np_fmax(a: f64, b: f64) -> f64 {
    if a.is_nan() { b } else if b.is_nan() { a } else if b > a { b } else { a }
}

#[inline]
fn np_fmin(a: f64, b: f64) -> f64 {
    if a.is_nan() { b } else if b.is_nan() { a } else if b < a { b } else { a }
}

/// ``Viewport._ray_hits_np``'s slab test over every span box at once:
/// whether the forward ray from ``o`` along ``d`` meets box ``i``
/// (``lo[i]``–``hi[i]``), and not past ``reach`` when there is one. The
/// NumPy pass, value by value: ``inv_d`` from ``d`` with its tiny
/// components replaced by 1e-12, ``t1``/``t2`` per axis, ``np.minimum`` /
/// ``np.maximum`` of them, ``_slab_far`` / ``_slab_near`` (``fmax`` /
/// ``fmin`` over x, y, z in that order), then ``tmax >= max(tmin, 0)``.
pub fn boxes_meet(o: [f64; 3], d: [f64; 3], lo: &[f64], hi: &[f64],
                  reach: Option<f64>) -> Vec<i64> {
    let mut inv = [0.0f64; 3];
    for k in 0..3 {
        // np.where(np.abs(d) > 1e-12, d, 1e-12): a NaN fails the test.
        let dk = if d[k].abs() > 1e-12 { d[k] } else { 1e-12 };
        inv[k] = 1.0 / dk;
    }
    let n = lo.len() / 3;
    let mut out = Vec::new();
    for i in 0..n {
        let mut mn = [0.0f64; 3];
        let mut mx = [0.0f64; 3];
        for k in 0..3 {
            let t1 = (lo[3 * i + k] - o[k]) * inv[k];
            let t2 = (hi[3 * i + k] - o[k]) * inv[k];
            mn[k] = np_min(t1, t2);
            mx[k] = np_max(t1, t2);
        }
        let tmin = np_fmax(np_fmax(mn[0], mn[1]), mn[2]);
        let tmax = np_fmin(np_fmin(mx[0], mx[1]), mx[2]);
        // tmax >= np.maximum(tmin, 0.0): any NaN is no meeting.
        let mut meet = tmax >= np_max(tmin, 0.0);
        if let Some(r) = reach {
            meet = meet && tmin <= r;
        }
        if meet {
            out.push(i as i64);
        }
    }
    out
}

/// ``EdgeGrid.near``'s gather: the long segments and the ids of every cell
/// of rows ``y0..=y1``, columns ``x0..=x1`` (keys sorted, each row one
/// slice of them, as ``np.searchsorted`` finds it), sorted and without
/// repeats — what ``np.unique`` or the mask over all ``n`` gives.
#[allow(clippy::too_many_arguments)]
pub fn grid_near(keys: &[i64], ids: &[i64], long_ids: &[i64], ncx: i64, x0: i64, x1: i64,
                 y0: i64, y1: i64, n: usize) -> Vec<i64> {
    let mut cand: Vec<i64> = long_ids.to_vec();
    for row in y0..=y1 {
        let a = row * ncx + x0;
        let b = row * ncx + x1;
        // searchsorted(keys, a, "left") and (keys, b, "right").
        let lo = keys.partition_point(|&k| k < a);
        let hi = keys.partition_point(|&k| k <= b);
        if hi > lo {
            cand.extend_from_slice(&ids[lo..hi]);
        }
    }
    if cand.len() * 16 < n {
        cand.sort_unstable();
        cand.dedup();
        return cand;
    }
    let mut mark = vec![false; n];
    for &i in &cand {
        mark[i as usize] = true;
    }
    mark.iter().enumerate().filter(|(_, &m)| m).map(|(i, _)| i as i64).collect()
}

use numpy::{PyArray1, PyReadonlyArray1, PyReadonlyArray2};
use pyo3::prelude::*;

/// ``Viewport._ray_hits_np``'s box test over the span boxes ``lo``/``hi``
/// (B,3) float64 (pick::boxes_meet): the indices of the boxes the ray
/// meets, in order — ``np.flatnonzero(meet)``. Over the ~11 000 spans of a
/// model of 1 400 placements the NumPy pass and the gathers were ~0.4 ms of
/// every ray a hover casts.
#[pyfunction]
#[pyo3(signature = (o, d, lo, hi, reach=None))]
pub fn ray_boxes_meet<'py>(py: Python<'py>, o: (f64, f64, f64), d: (f64, f64, f64),
                           lo: PyReadonlyArray2<'py, f64>, hi: PyReadonlyArray2<'py, f64>,
                           reach: Option<f64>) -> PyResult<Bound<'py, PyArray1<i64>>> {
    let (lo, hi) = (lo.as_array(), hi.as_array());
    if lo.shape() != hi.shape() || lo.shape()[1] != 3 {
        return Err(pyo3::exceptions::PyValueError::new_err("shape"));
    }
    let (lo, hi) = match (lo.as_slice(), hi.as_slice()) {
        (Some(a), Some(b)) => (a, b),
        _ => return Err(pyo3::exceptions::PyTypeError::new_err("contiguous")),
    };
    let out = boxes_meet([o.0, o.1, o.2], [d.0, d.1, d.2], lo, hi, reach);
    Ok(PyArray1::from_vec(py, out))
}

/// ``EdgeGrid.near``'s candidates (pick::grid_near): the sorted, repeat-free
/// indices of the segments in the cells around the cursor plus the long
/// ones. ``np.unique`` of them was ~0.2 ms of each edge query of a hover.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
pub fn edge_grid_near<'py>(py: Python<'py>, keys: PyReadonlyArray1<'py, i64>,
                           ids: PyReadonlyArray1<'py, i64>,
                           long_ids: PyReadonlyArray1<'py, i64>, ncx: i64, x0: i64,
                           x1: i64, y0: i64, y1: i64, n: usize)
    -> PyResult<Bound<'py, PyArray1<i64>>> {
    let (keys, ids, long_ids) = (keys.as_array(), ids.as_array(), long_ids.as_array());
    let (keys, ids, long_ids) = match (keys.as_slice(), ids.as_slice(), long_ids.as_slice()) {
        (Some(a), Some(b), Some(c)) => (a, b, c),
        _ => return Err(pyo3::exceptions::PyTypeError::new_err("contiguous")),
    };
    if keys.len() != ids.len() || ids.iter().chain(long_ids).any(|&i| i < 0 || i as usize >= n) {
        return Err(pyo3::exceptions::PyValueError::new_err("ids"));
    }
    let out = grid_near(keys, ids, long_ids, ncx, x0, x1, y0, y1, n);
    Ok(PyArray1::from_vec(py, out))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_ray_meets_the_boxes_it_crosses() {
        let lo = [0.0, 0.0, 0.0, 5.0, 5.0, 5.0, f64::NEG_INFINITY, f64::NEG_INFINITY,
                  f64::NEG_INFINITY];
        let hi = [1.0, 1.0, 1.0, 6.0, 6.0, 6.0, f64::INFINITY, f64::INFINITY, f64::INFINITY];
        let got = boxes_meet([0.5, 0.5, -1.0], [0.0, 0.0, 1.0], &lo, &hi, None);
        assert_eq!(got, vec![0, 2]);
        let got = boxes_meet([0.5, 0.5, -1.0], [0.0, 0.0, 1.0], &lo, &hi, Some(0.5));
        assert_eq!(got, vec![2]);
        // Behind the eye: no meeting.
        let got = boxes_meet([0.5, 0.5, 3.0], [0.0, 0.0, 1.0], &lo[..3], &hi[..3], None);
        assert!(got.is_empty());
    }

    #[test]
    fn the_grid_gathers_each_segment_once_sorted() {
        // Cells 0..4 in one row of 4; segment 3 sits in two cells.
        let keys = [0, 1, 1, 2, 3];
        let ids = [5, 3, 1, 3, 0];
        let got = grid_near(&keys, &ids, &[4], 4, 1, 2, 0, 0, 100);
        assert_eq!(got, vec![1, 3, 4]);
        let got = grid_near(&keys, &ids, &[4], 4, 1, 2, 0, 0, 6);
        assert_eq!(got, vec![1, 3, 4]);
    }
}
