// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! The snap and inference passes that run on every pointer move.
//!
//! Each kernel is the NumPy of its Python caller operation for operation in
//! f64 (no fused multiply-add: Rust never contracts), so the candidates,
//! their order and their distances are the same bits.

use numpy::{PyArray1, PyReadonlyArray2};
use pyo3::prelude::*;

/// One mesh's rows as f64, whatever its float type (NumPy promotes a
/// float32 row the same way before multiplying by the f64 matrix).
fn rows_of(pts: &Bound<'_, PyAny>) -> PyResult<Vec<[f64; 3]>> {
    if let Ok(a) = pts.extract::<PyReadonlyArray2<'_, f64>>() {
        let v = a.as_array();
        if v.shape()[1] != 3 {
            return Err(pyo3::exceptions::PyValueError::new_err("pts"));
        }
        return Ok(v.outer_iter().map(|r| [r[0], r[1], r[2]]).collect());
    }
    let a: PyReadonlyArray2<'_, f32> = pts.extract()?;
    let v = a.as_array();
    if v.shape()[1] != 3 {
        return Err(pyo3::exceptions::PyValueError::new_err("pts"));
    }
    Ok(v.outer_iter().map(|r| [r[0] as f64, r[1] as f64, r[2] as f64]).collect())
}

/// Push/Pull's corner scan over one mesh (tools.pushpull
/// ``_infer_reference_distance``): ``Viewport._project_px`` of ``pts``
/// (N, 3) through ``mvp`` (4, 4) for a ``w`` × ``h`` viewport, then the rows
/// in front within ``thr2`` of ``(sx, sy)`` nearest first, ties in row order
/// (``np.argsort(kind="stable")``). Returns ``(rows, d2 of each, box)``,
/// ``box`` the ``(min px, max px, min py, max py)`` of the rows in front as
/// NumPy's min/max give it (NaN through), or None when none is in front.
/// ~0.2 ms of NumPy a mesh, ~10 meshes a move of a push in the Plaza (19-11).
#[pyfunction]
#[pyo3(signature = (pts, mvp, w, h, sx, sy, thr2))]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
pub fn px_near_sorted<'py>(py: Python<'py>, pts: &Bound<'py, PyAny>,
                           mvp: PyReadonlyArray2<'py, f64>, w: f64, h: f64, sx: f64,
                           sy: f64, thr2: f64)
    -> PyResult<(Bound<'py, PyArray1<i64>>, Bound<'py, PyArray1<f64>>,
                 Option<(f64, f64, f64, f64)>)> {
    let rows = rows_of(pts)?;
    let mv = mvp.as_array();
    if mv.shape() != [4, 4] {
        return Err(pyo3::exceptions::PyValueError::new_err("mvp"));
    }
    let mut m = [[0.0f64; 4]; 4];
    for (r, row) in m.iter_mut().enumerate() {
        for (c, v) in row.iter_mut().enumerate() {
            *v = mv[[r, c]];
        }
    }
    let (near, d2s, bx) = py.detach(|| scan(&rows, &m, w, h, sx, sy, thr2));
    Ok((PyArray1::from_vec(py, near), PyArray1::from_vec(py, d2s), bx))
}

#[allow(clippy::type_complexity)]
fn scan(rows: &[[f64; 3]], m: &[[f64; 4]; 4], w: f64, h: f64, sx: f64, sy: f64, thr2: f64)
    -> (Vec<i64>, Vec<f64>, Option<(f64, f64, f64, f64)>) {
    // np.min / np.max over the rows in front: NaN as soon as one is NaN
    // (the box only feeds comparisons, where any NaN is the same).
    let (mut x0, mut x1, mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY,
                                            f64::INFINITY, f64::NEG_INFINITY);
    let (mut xnan, mut ynan, mut any) = (None::<f64>, None::<f64>, false);
    let mut hits: Vec<(f64, usize)> = Vec::new();
    for (i, p) in rows.iter().enumerate() {
        // _project_px: clip = x*M[:,0] + y*M[:,1] + z*M[:,2] + M[:,3],
        // left to right, term by term.
        let clip = |k: usize| p[0] * m[k][0] + p[1] * m[k][1] + p[2] * m[k][2] + m[k][3];
        let cw = clip(3);
        if !(cw > 0.0) {
            continue;
        }
        any = true;
        let px = (clip(0) / cw * 0.5 + 0.5) * w;
        let py = (1.0 - (clip(1) / cw * 0.5 + 0.5)) * h;
        if px.is_nan() { xnan = xnan.or(Some(px)); } else {
            if px < x0 { x0 = px; }
            if px > x1 { x1 = px; }
        }
        if py.is_nan() { ynan = ynan.or(Some(py)); } else {
            if py < y0 { y0 = py; }
            if py > y1 { y1 = py; }
        }
        let (dx, dy) = (px - sx, py - sy);
        let d2 = dx * dx + dy * dy;
        if d2 <= thr2 {
            hits.push((d2, i));
        }
    }
    // Under the radius there is no NaN; the row breaks ties (stable sort).
    hits.sort_unstable_by(|a, b| a.0.partial_cmp(&b.0).unwrap().then(a.1.cmp(&b.1)));
    let bx = if any {
        let (x0, x1) = xnan.map_or((x0, x1), |v| (v, v));
        let (y0, y1) = ynan.map_or((y0, y1), |v| (v, v));
        Some((x0, x1, y0, y1))
    } else {
        None
    };
    (hits.iter().map(|t| t.1 as i64).collect(), hits.iter().map(|t| t.0).collect(), bx)
}
