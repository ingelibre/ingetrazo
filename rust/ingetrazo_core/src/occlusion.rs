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
//!
//! A det under `DET_MIN` is read against the triangle's own size, as
//! `views.viewport._occlusion_det_ok` reads it (#1294): det is
//! (e1 × e2)·d, so a 1 mm square met head-on (det ≈ 6e-7) hid nothing.

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

/// The length of a 3-vector as `np.linalg.norm(.., axis=1)` sums it.
#[inline]
fn norm(a: [f64; 3]) -> f64 {
    ((a[0] * a[0] + a[1] * a[1]) + a[2] * a[2]).sqrt()
}

/// `_occlusion_det_ok` for one ray and one triangle: whether the det is
/// not grazing — `|det| > DET_MIN`, or `|det| > DET_MIN·|e1 × e2|·|d|` on
/// a triangle of some area — when that is sure for any summation order
/// (`det_err`, and a few ulps of the norms); None when the last bits
/// could decide.
#[inline]
fn det_ok(det: f64, det_err: f64, d: [f64; 3], e1: [f64; 3], e2: [f64; 3]) -> Option<bool> {
    let a = det.abs();
    if a - DET_MIN > det_err {
        return Some(true);
    }
    if a == 0.0 && det_err == 0.0 {
        return Some(false); // every term nought: nought in any order
    }
    // The cross product is NumPy's formula, bit for bit; its norm and the
    // ray's may round a few ulps apart.
    let scale = norm(cross(e1, e2)) * norm(d);
    if !(scale > 0.0) {
        // No area: refused by the second reading; the first decides.
        return if DET_MIN - a > det_err { Some(false) } else { None };
    }
    let thr = DET_MIN * scale;
    let thr_err = 16.0 * EPS_M * thr;
    let second = if a - thr > det_err + thr_err {
        Some(true)
    } else if thr - a > det_err + thr_err {
        Some(false)
    } else {
        None
    };
    if DET_MIN - a > det_err {
        return second; // surely not past DET_MIN: the second reading alone
    }
    // Within det_err of DET_MIN: either reading may be NumPy's.
    if second == Some(true) { Some(true) } else { None }
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
        match det_ok(det, det_err, d, e1[i], e2[i]) {
            None => {
                doubt = true;
                continue;
            }
            Some(false) => continue,
            Some(true) => {}
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
    match det_ok(det, det_err, d, e1, e2) {
        None => return None,
        Some(false) => return Some(false),
        Some(true) => {}
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

#[cfg(test)]
mod tests {
    use super::*;

    fn unit(v: [f64; 3]) -> [f64; 3] {
        let l = norm(v);
        [v[0] / l, v[1] / l, v[2] / l]
    }

    /// A square of side `s` (two triangles) met head-on-ish from 2 cm.
    fn square_hit(s: f64) -> (Option<bool>, f64, bool) {
        let d = unit([0.1, -0.2, -1.0]);
        let c = [s / 3.0, s / 3.0, 0.0];
        let o = [c[0] - d[0] * 0.02, c[1] - d[1] * 0.02, c[2] - d[2] * 0.02];
        let v0 = [[0.0, 0.0, 0.0], [s, s, 0.0]];
        let e1 = [[s, 0.0, 0.0], [-s, 0.0, 0.0]];
        let e2 = [[0.0, s, 0.0], [0.0, -s, 0.0]];
        let one = tri_occludes(o, d, 0.05, v0[0], e1[0], e2[0]);
        let (b, doubt) = span(o, &[d], &[f64::INFINITY], &[0.05], &v0, &e1, &e2);
        (one, b[0], doubt[0])
    }

    #[test]
    fn a_millimetre_square_hides_what_is_behind_it() {
        for s in [0.001, 0.0003] {
            // det = (e1 × e2)·d ≈ s² — under DET_MIN, refused before #1294.
            let (one, t, doubt) = square_hit(s);
            assert_eq!(one, Some(true), "{s}");
            assert!(!doubt, "{s}");
            assert!((t - 0.02).abs() < 1e-12, "{s} {t}");
        }
    }

    #[test]
    fn a_normal_triangle_is_read_as_before() {
        let (one, t, doubt) = square_hit(1.0);
        assert_eq!(one, Some(true));
        assert!(!doubt);
        assert!((t - 0.02).abs() < 1e-12);
        // A det past DET_MIN is accepted without looking at the size.
        assert_eq!(det_ok(2e-6, 1e-20, [0.0, 0.0, 1.0], [1e9, 0.0, 0.0], [0.0, 1e9, 0.0]),
                   Some(true));
    }

    #[test]
    fn a_grazing_ray_is_still_refused() {
        // Along the plane of a 1 m triangle, a hair above it.
        let o = [-1.0, 0.25, 1e-9];
        let d = [1.0, 0.0, 0.0];
        assert_eq!(tri_occludes(o, d, 10.0, [0.0; 3], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
                   Some(false));
        // Nearly along it: det 1e-7 of a triangle of area 0.5 — an angle of
        // 1e-7 rad, refused; the same angle on a 1 mm one too.
        let d = unit([1.0, 0.0, -1e-7]);
        let o = [-1.0, 0.25, 1e-7];
        assert_eq!(tri_occludes(o, d, 10.0, [0.0; 3], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]),
                   Some(false));
        let s = 0.001;
        let o = [-s, 0.25 * s, 1e-7 * s];
        assert_eq!(tri_occludes(o, d, 10.0, [0.0; 3], [s, 0.0, 0.0], [0.0, s, 0.0]),
                   Some(false));
    }

    #[test]
    fn a_triangle_of_no_area_hides_nothing() {
        let d = unit([0.1, -0.2, -1.0]);
        let o = [0.0, 0.0, 1.0];
        // Collinear: e1 × e2 is nought.
        let r = tri_occludes(o, d, 10.0, [0.0; 3], [1e-3, 0.0, 0.0], [2e-3, 0.0, 0.0]);
        assert_ne!(r, Some(true));
        assert_eq!(det_ok(0.0, 0.0, d, [0.0; 3], [0.0; 3]), Some(false));
    }
}
