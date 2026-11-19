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

extern "C" {
    // The C library's pow, as Python's float ``**`` calls it: Rust's own
    // powf may be folded (pow(x, 2) into x*x) when the exponent is known.
    fn pow(x: f64, y: f64) -> f64;
}

/// Python's ``x ** y`` for a float ``x`` and ``y`` 2.0 or 0.5 (CPython's
/// float_pow: its special cases, then the C pow of |x|), or None where
/// Python would raise (the C pow over- or underflowing past zero sets
/// ERANGE: OverflowError).
#[inline]
fn py_pow(x: f64, y: f64) -> Option<f64> {
    if x.is_nan() {
        return Some(x);
    }
    if x.is_infinite() {
        return Some(f64::INFINITY);     // y > 0, not odd
    }
    if x == 0.0 {
        return Some(0.0);
    }
    if x < 0.0 && y != y.floor() {
        return None;                    // complex: never asked here
    }
    let a = x.abs();
    if a == 1.0 {
        return Some(1.0);
    }
    let r = unsafe { pow(a, std::hint::black_box(y)) };
    if r.is_infinite() || (r != 0.0 && r.abs() < f64::MIN_POSITIVE) {
        return None;
    }
    Some(r)
}

/// Python's ``sum()`` of three floats (CPython 3.12+): ``0 + x0``, then
/// Neumaier's compensated sum of the rest, the compensation added last
/// when it is finite and not zero.
#[inline]
fn py_sum3(x0: f64, x1: f64, x2: f64) -> f64 {
    let mut f = 0.0 + x0;
    let mut c = 0.0f64;
    for x in [x1, x2] {
        let t = f + x;
        if f.abs() >= x.abs() {
            c += (f - t) + x;
        } else {
            c += (x - t) + f;
        }
        f = t;
    }
    if c != 0.0 && c.is_finite() {
        f += c;
    }
    f
}

#[inline]
fn py_max(a: f64, b: f64) -> f64 {
    if b > a { b } else { a }
}

/// What ``core.topology.segment_intersection(p1, p2, p3, p4, tol)`` returns
/// for float32 ends: ``Ok(None)``, ``Ok(Some(point))`` (float32, as the
/// QVector3D it builds) or ``Err(())`` where Python's arithmetic raises.
fn segment_hit(p1: [f32; 3], p2: [f32; 3], p3: [f32; 3], p4: [f32; 3], tol: f64,
               h: crate::facegeom::Hypot) -> Result<Option<[f32; 3]>, ()> {
    use crate::facegeom::{length, V3};
    let sub = |a: [f32; 3], b: [f32; 3]| [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    let f64s = |a: [f32; 3]| [a[0] as f64, a[1] as f64, a[2] as f64];
    let d1 = sub(p2, p1);
    let d2 = sub(p4, p3);
    let len1 = length(V3(d1[0], d1[1], d1[2]), h) as f64;
    let len2 = length(V3(d2[0], d2[1], d2[2]), h) as f64;
    if len1 < tol || len2 < tol {
        return Ok(None);
    }
    let (d1c, d2c) = (f64s(d1), f64s(d2));
    let u1 = [d1c[0] / len1, d1c[1] / len1, d1c[2] / len1];
    let u2 = [d2c[0] / len2, d2c[1] / len2, d2c[2] / len2];
    let dot = |l: [f64; 3], r: [f64; 3]| py_sum3(l[0] * r[0], l[1] * r[1], l[2] * r[2]);
    let a = dot(u1, u1);
    let b = dot(u1, u2);
    let c = dot(u2, u2);
    let w = f64s(sub(p1, p3));
    let d = dot(u1, w);
    let e = dot(u2, w);
    let denom = a * c - b * b;
    if denom < 1e-12 {
        return Ok(None);
    }
    let s = (b * e - c * d) / denom;
    let t = (a * e - b * d) / denom;
    let margin1 = tol / len1;
    let margin2 = tol / len2;
    let s1 = s / len1;
    if !(-margin1 <= s1 && s1 <= 1.0 + margin1) {
        return Ok(None);
    }
    let t2 = t / len2;
    if !(-margin2 <= t2 && t2 <= 1.0 + margin2) {
        return Ok(None);
    }
    let (p1c, p3c) = (f64s(p1), f64s(p3));
    let on1 = [p1c[0] + u1[0] * s, p1c[1] + u1[1] * s, p1c[2] + u1[2] * s];
    let on2 = [p3c[0] + u2[0] * t, p3c[1] + u2[1] * t, p3c[2] + u2[2] * t];
    let sq = |k: usize| py_pow(on1[k] - on2[k], 2.0).ok_or(());
    let gap = py_pow(py_sum3(sq(0)?, sq(1)?, sq(2)?), 0.5).ok_or(())?;
    let distance_tol = py_max(tol, 1.0e-7 * py_max(len1, len2));
    if gap > distance_tol {
        return Ok(None);
    }
    Ok(Some([((on1[0] + on2[0]) * 0.5) as f32, ((on1[1] + on2[1]) * 0.5) as f32,
             ((on1[2] + on2[2]) * 0.5) as f32]))
}

/// ``core.topology.segment_intersection`` for the pairs ``(ii[k], jj[k])``
/// of the segments ``ends`` (N, 2, 3) float32, QVector3D's arithmetic
/// (its length ``hypot``) and then Python's, operation for operation:
/// ``(status, points)`` — status 0 no meeting, 1 the meeting point in
/// ``points[k]``, 2 one Python's arithmetic raises on (ask it there). The
/// intersection snap's pairs: up to ~470 under the cursor on the first
/// stroke of a Line inside the Plaza's 9 674-face group, ~20 ms (19-11).
#[pyfunction]
#[allow(clippy::type_complexity)]
pub fn segment_hits<'py>(py: Python<'py>, ends: numpy::PyReadonlyArray3<'py, f32>,
                         ii: numpy::PyReadonlyArray1<'py, i64>,
                         jj: numpy::PyReadonlyArray1<'py, i64>, tol: f64, hypot: &str)
    -> PyResult<(Bound<'py, PyArray1<u8>>, Bound<'py, numpy::PyArray2<f32>>)> {
    let h = crate::hypot_of(hypot)?;
    let ev = ends.as_array();
    let sh = ev.shape();
    if sh[1] != 2 || sh[2] != 3 {
        return Err(pyo3::exceptions::PyValueError::new_err("ends"));
    }
    let n = sh[0];
    let (ii, jj) = (ii.as_array(), jj.as_array());
    if ii.len() != jj.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("pairs"));
    }
    let mut pairs = Vec::with_capacity(ii.len());
    for (&i, &j) in ii.iter().zip(jj.iter()) {
        if i < 0 || j < 0 || i as usize >= n || j as usize >= n {
            return Err(pyo3::exceptions::PyValueError::new_err("pairs"));
        }
        pairs.push((i as usize, j as usize));
    }
    let pt = |i: usize, k: usize| [ev[[i, k, 0]], ev[[i, k, 1]], ev[[i, k, 2]]];
    let segs: Vec<[[f32; 3]; 2]> = (0..n).map(|i| [pt(i, 0), pt(i, 1)]).collect();
    let (status, flat) = py.detach(|| {
        let mut status = Vec::with_capacity(pairs.len());
        let mut flat = Vec::with_capacity(3 * pairs.len());
        for &(i, j) in &pairs {
            let (a, b) = (segs[i], segs[j]);
            match segment_hit(a[0], a[1], b[0], b[1], tol, h) {
                Ok(None) => { status.push(0u8); flat.extend([0.0f32; 3]); }
                Ok(Some(p)) => { status.push(1u8); flat.extend(p); }
                Err(()) => { status.push(2u8); flat.extend([0.0f32; 3]); }
            }
        }
        (status, flat)
    });
    let pts = PyArray1::from_vec(py, flat);
    use numpy::PyArrayMethods;
    Ok((PyArray1::from_vec(py, status), pts.reshape([pairs.len(), 3])?))
}
