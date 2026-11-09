// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! The snap engine's occlusion rays, for one span of the pick index:
//! `Viewport._occluded_many`'s Möller–Trumbore block, operation for
//! operation in f64 (NumPy's cross formula, the 3-term sums in order, no
//! fused multiply-add).
//!
//! NumPy sums those 3 terms through `einsum` and one of them (`d @ q.T`)
//! through BLAS, whose order or FMA may round the last bit differently. So
//! each test carries the error bound of its dot products — 4·ε·Σ|aᵢbᵢ|,
//! good for any order and for FMA — and a ray whose answer could depend on
//! that last bit (a triangle within the bound of a threshold, or a nearest
//! hit within it of the point) comes back marked: the caller asks NumPy for
//! those rays. Every other ray's answer is the same by construction.

use rayon::prelude::*;

use crate::facegeom::{hypot3, Hypot};

const DET_MIN: f64 = 1e-6;
const T_MIN: f64 = 1e-6;
const EPS_M: f64 = f64::EPSILON;

#[inline]
fn cross(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

#[inline]
fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

/// The rounding a 3-term dot product may carry in another summation order.
#[inline]
fn dot_err(a: [f64; 3], b: [f64; 3]) -> f64 {
    4.0 * EPS_M * ((a[0] * b[0]).abs() + (a[1] * b[1]).abs() + (a[2] * b[2]).abs())
}

/// One ray against the span: the nearest accepted `t` (or `best` when none
/// is nearer), and whether the answer is too close to call bit for bit.
fn one_ray(o: [f64; 3], d: [f64; 3], best: f64, limit: f64,
           v0: &[[f64; 3]], e1: &[[f64; 3]], e2: &[[f64; 3]]) -> (f64, bool) {
    let mut b = best;
    let mut b_err = 0.0f64;
    let mut doubt = false;
    for i in 0..v0.len() {
        let s = [o[0] - v0[i][0], o[1] - v0[i][1], o[2] - v0[i][2]];
        let q = cross(s, e1[i]);
        let uq = dot(e2[i], q);
        let p = cross(d, e2[i]);
        let det = dot(e1[i], p);
        let det_err = dot_err(e1[i], p);
        if (det.abs() - DET_MIN).abs() <= det_err {
            doubt = true;
            continue;
        }
        if !(det.abs() > DET_MIN) {
            continue;
        }
        let inv = 1.0 / det;
        let rel = det_err / det.abs();
        let su = dot(s, p);
        let sv = dot(d, q);
        let u = su * inv;
        let v = sv * inv;
        let t = uq * inv;
        let u_err = dot_err(s, p) * inv.abs() + u.abs() * 2.0 * rel;
        let v_err = dot_err(d, q) * inv.abs() + v.abs() * 2.0 * rel;
        let t_err = dot_err(e2[i], q) * inv.abs() + t.abs() * 2.0 * rel;
        if u.abs() <= u_err || (u - 1.0).abs() <= u_err || v.abs() <= v_err
            || (u + v - 1.0).abs() <= u_err + v_err || (t - T_MIN).abs() <= t_err
        {
            doubt = true;
            continue;
        }
        if u >= 0.0 && u <= 1.0 && v >= 0.0 && u + v <= 1.0 && t > T_MIN && t < b {
            b = t;
            b_err = t_err;
        }
    }
    if b < best && (b - limit).abs() <= b_err {
        doubt = true;
    }
    (b, doubt)
}

/// For each ray `r` (direction `dirs[r]`, from `o`): the minimum of
/// `best[r]` and every accepted hit in the span, and the doubt flag.
pub fn span(o: [f64; 3], dirs: &[[f64; 3]], best: &[f64], limit: &[f64],
            v0: &[[f64; 3]], e1: &[[f64; 3]], e2: &[[f64; 3]]) -> (Vec<f64>, Vec<bool>) {
    let out: Vec<(f64, bool)> = if dirs.len() * v0.len() >= 4096 {
        (0..dirs.len()).into_par_iter()
            .map(|r| one_ray(o, dirs[r], best[r], limit[r], v0, e1, e2))
            .collect()
    } else {
        (0..dirs.len())
            .map(|r| one_ray(o, dirs[r], best[r], limit[r], v0, e1, e2))
            .collect()
    };
    out.into_iter().unzip()
}

/// ``x ≥ thr`` when ``x`` may be off by ``err``: Some when sure, None when
/// the last bits could decide.
#[inline]
fn at_least(x: f64, thr: f64, err: f64) -> Option<bool> {
    if x - thr > err {
        Some(true)
    } else if thr - x > err {
        Some(false)
    } else {
        None
    }
}

/// Whether one world triangle hides the point at ``limit`` along the ray
/// (``_occluded_many``'s acceptance, and its hit nearer than the point):
/// Some(true) / Some(false) when sure for any summation order, None when
/// the answer could hang on the last bit.
pub fn tri_occludes(o: [f64; 3], d: [f64; 3], limit: f64,
                    v0: [f64; 3], e1: [f64; 3], e2: [f64; 3]) -> Option<bool> {
    let s = [o[0] - v0[0], o[1] - v0[1], o[2] - v0[2]];
    let q = cross(s, e1);
    let uq = dot(e2, q);
    let p = cross(d, e2);
    let det = dot(e1, p);
    let det_err = dot_err(e1, p);
    if (det.abs() - DET_MIN).abs() <= det_err {
        return None;
    }
    if !(det.abs() > DET_MIN) {
        return Some(false);
    }
    let inv = 1.0 / det;
    let rel = det_err / det.abs();
    let u = dot(s, p) * inv;
    let v = dot(d, q) * inv;
    let t = uq * inv;
    let u_err = dot_err(s, p) * inv.abs() + u.abs() * 2.0 * rel;
    let v_err = dot_err(d, q) * inv.abs() + v.abs() * 2.0 * rel;
    let t_err = dot_err(e2, q) * inv.abs() + t.abs() * 2.0 * rel;
    if !(u.is_finite() && v.is_finite() && t.is_finite()) {
        return None;
    }
    let tests = [
        at_least(u, 0.0, u_err),
        at_least(1.0, u, u_err),
        at_least(v, 0.0, v_err),
        at_least(1.0, u + v, u_err + v_err),
        at_least(t, T_MIN, t_err),
        at_least(limit, t, t_err),
    ];
    if tests.iter().any(|x| *x == Some(false)) {
        return Some(false);
    }
    if tests.iter().all(|x| *x == Some(true)) {
        return Some(true);
    }
    None
}

/// ``views.viewport._hypot3_f32`` for one vector: the three-argument
/// ``std::hypot`` in float of the C++ library ``h``, as Qt's
/// ``QVector3D::length`` computes it. libstdc++'s is kept here as it was
/// (the largest magnitude scaled out), NaN included.
#[inline]
pub fn hypot3_f32(v: [f32; 3], h: Hypot) -> f32 {
    if h != Hypot::LibStdCxx {
        return hypot3(v, h);
    }
    let a = [v[0].abs(), v[1].abs(), v[2].abs()];
    let m = a[0].max(a[1]).max(a[2]);
    if !(m > 0.0) {
        return 0.0;
    }
    let q = [a[0] / m, a[1] / m, a[2] / m];
    let s = (q[0] * q[0] + q[1] * q[1]) + q[2] * q[2];
    m * s.sqrt()
}

/// ``views.viewport._unit_rays`` for one point: the unit direction from
/// ``eye`` (float) to ``p`` and the distance, both as float64 of the float
/// values QVector3D holds — or None for a point on the eye.
#[inline]
pub fn unit_ray(eye: [f32; 3], p: [f64; 3], h: Hypot) -> Option<([f64; 3], f64)> {
    let dl = [p[0] as f32 - eye[0], p[1] as f32 - eye[1], p[2] as f32 - eye[2]];
    let l = hypot3_f32(dl, h);
    if !((l as f64) >= 1e-9) {
        return None;
    }
    Some(([(dl[0] / l) as f64, (dl[1] / l) as f64, (dl[2] / l) as f64], l as f64))
}
