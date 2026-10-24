// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! Which component placements a pick query can touch, without baking
//! them into world space (the experimental engine's spatial index).
//!
//! The viewport's pick index bakes a placement's triangles and edges into
//! world coordinates ("materialises" it) before its exact tests can see
//! it; on a plant of 21 406 placements it baked and re-indexed hundreds on
//! every pointer move. This module answers, per prototype in its own
//! coordinates, whether a placement can possibly matter to a query — a
//! ray, or the edges near a pixel — with margins far past the exact
//! tests' tolerances. Only what may matter is baked; the exact tests run
//! on it as before, so their results are the same.

const LEAF: usize = 8;

#[derive(Clone, Copy)]
struct Node {
    lo: [f64; 3],
    hi: [f64; 3],
    start: u32,
    end: u32,
    left: u32,
    leaf: bool,
}

/// One prototype's triangles (v0, e1, e2) with a BVH, and its hard edges.
pub struct Proto {
    v0: Vec<[f64; 3]>,
    e1: Vec<[f64; 3]>,
    e2: Vec<[f64; 3]>,
    order: Vec<u32>,
    nodes: Vec<Node>,
    edges: Vec<[[f64; 3]; 2]>,
}

#[inline]
fn sub(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}
#[inline]
fn cross(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}
#[inline]
fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

impl Proto {
    pub fn new(v0: Vec<[f64; 3]>, e1: Vec<[f64; 3]>, e2: Vec<[f64; 3]>,
               edges: Vec<[[f64; 3]; 2]>) -> Proto {
        let n = v0.len();
        let mut tlo = Vec::with_capacity(n);
        let mut thi = Vec::with_capacity(n);
        let mut cen = Vec::with_capacity(n);
        for i in 0..n {
            let a = v0[i];
            let b = [a[0] + e1[i][0], a[1] + e1[i][1], a[2] + e1[i][2]];
            let c = [a[0] + e2[i][0], a[1] + e2[i][1], a[2] + e2[i][2]];
            let mut lo = [0.0; 3];
            let mut hi = [0.0; 3];
            for k in 0..3 {
                lo[k] = a[k].min(b[k]).min(c[k]);
                hi[k] = a[k].max(b[k]).max(c[k]);
            }
            tlo.push(lo);
            thi.push(hi);
            cen.push([(lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5]);
        }
        let mut p = Proto { v0, e1, e2, order: (0..n as u32).collect(), nodes: Vec::new(), edges };
        if n == 0 {
            return p;
        }
        p.nodes.push(Node { lo: [0.0; 3], hi: [0.0; 3], start: 0, end: n as u32, left: 0, leaf: true });
        let mut stack = vec![0usize];
        while let Some(ni) = stack.pop() {
            let (s, e) = (p.nodes[ni].start as usize, p.nodes[ni].end as usize);
            let mut lo = [f64::INFINITY; 3];
            let mut hi = [f64::NEG_INFINITY; 3];
            let mut clo = [f64::INFINITY; 3];
            let mut chi = [f64::NEG_INFINITY; 3];
            for &r in &p.order[s..e] {
                let r = r as usize;
                for k in 0..3 {
                    lo[k] = lo[k].min(tlo[r][k]);
                    hi[k] = hi[k].max(thi[r][k]);
                    clo[k] = clo[k].min(cen[r][k]);
                    chi[k] = chi[k].max(cen[r][k]);
                }
            }
            // Grown well past any rounding: a box only ever skips triangles
            // the margin-ed test below would refuse anyway.
            let mut ext = 0.0f64;
            let mut big = 0.0f64;
            for k in 0..3 {
                ext = ext.max(hi[k] - lo[k]);
                big = big.max(lo[k].abs()).max(hi[k].abs());
            }
            let m = 1e-6 + 1e-6 * big + 1e-4 * ext;
            let mut glo = [lo[0] - m, lo[1] - m, lo[2] - m];
            let mut ghi = [hi[0] + m, hi[1] + m, hi[2] + m];
            if !(glo.iter().chain(ghi.iter()).all(|v| v.is_finite())) {
                glo = [f64::NEG_INFINITY; 3];
                ghi = [f64::INFINITY; 3];
            }
            p.nodes[ni].lo = glo;
            p.nodes[ni].hi = ghi;
            if e - s <= LEAF {
                continue;
            }
            let mut axis = 0;
            for k in 1..3 {
                if chi[k] - clo[k] > chi[axis] - clo[axis] {
                    axis = k;
                }
            }
            let mid = s + (e - s) / 2;
            p.order[s..e].select_nth_unstable_by(mid - s, |&x, &y| {
                cen[x as usize][axis].partial_cmp(&cen[y as usize][axis])
                    .unwrap_or(std::cmp::Ordering::Equal)
            });
            let left = p.nodes.len() as u32;
            p.nodes.push(Node { lo: [0.0; 3], hi: [0.0; 3], start: s as u32, end: mid as u32, left: 0, leaf: true });
            p.nodes.push(Node { lo: [0.0; 3], hi: [0.0; 3], start: mid as u32, end: e as u32, left: 0, leaf: true });
            p.nodes[ni].leaf = false;
            p.nodes[ni].left = left;
            stack.push(left as usize);
            stack.push(left as usize + 1);
        }
        p
    }

    pub fn n_tris(&self) -> usize {
        self.v0.len()
    }

    #[inline]
    fn box_hit(n: &Node, o: [f64; 3], inv: [f64; 3], tmax_lim: f64) -> bool {
        let mut tmin = f64::NEG_INFINITY;
        let mut tmax = f64::INFINITY;
        for k in 0..3 {
            let t1 = (n.lo[k] - o[k]) * inv[k];
            let t2 = (n.hi[k] - o[k]) * inv[k];
            let (a, b) = if t1 < t2 { (t1, t2) } else { (t2, t1) };
            if a.is_nan() || b.is_nan() {
                continue;
            }
            tmin = tmin.max(a);
            tmax = tmax.min(b);
        }
        tmax >= tmin && tmax >= -1e-6 && tmin <= tmax_lim
    }

    /// Whether the ray (local coordinates; its parameter is the world
    /// one, the map being affine) can meet a triangle at ``t`` in
    /// ``[-tol, reach]`` — barycentrics and t loosened far past the exact
    /// test's, and no refusal on a small determinant.
    pub fn ray_may_hit(&self, o: [f64; 3], d: [f64; 3], reach: f64) -> bool {
        if self.nodes.is_empty() {
            return false;
        }
        let mut inv = [0.0; 3];
        for k in 0..3 {
            let dv = if d[k].abs() < 1e-300 { 1e-300 } else { d[k] };
            inv[k] = 1.0 / dv;
        }
        let lim = if reach.is_finite() { reach * (1.0 + 1e-6) + 1e-6 } else { f64::INFINITY };
        let mut stack: Vec<u32> = vec![0];
        while let Some(ni) = stack.pop() {
            let n = &self.nodes[ni as usize];
            if !Self::box_hit(n, o, inv, lim) {
                continue;
            }
            if !n.leaf {
                stack.push(n.left);
                stack.push(n.left + 1);
                continue;
            }
            for &r in &self.order[n.start as usize..n.end as usize] {
                let r = r as usize;
                let (e1, e2) = (self.e1[r], self.e2[r]);
                let h = cross(d, e2);
                let a = dot(e1, h);
                if a == 0.0 || !a.is_finite() {
                    continue;
                }
                let f = 1.0 / a;
                let s = sub(o, self.v0[r]);
                let u = f * dot(s, h);
                const B: f64 = 1e-4;
                if !(u >= -B && u <= 1.0 + B) {
                    continue;
                }
                let q = cross(s, e1);
                let v = f * dot(d, q);
                if !(v >= -B && u + v <= 1.0 + B) {
                    continue;
                }
                let t = f * dot(e2, q);
                let tol = 1e-4 * (1.0 + t.abs());
                if t >= -tol && t <= lim + tol {
                    return true;
                }
            }
        }
        false
    }

    /// Whether anything of this prototype, mapped by ``m`` (local → clip,
    /// column-major 4×4) to a ``w``×``h`` view, comes near ``(px, py)``: a
    /// hard edge within ``edge_reach`` px (both ends in front of the eye),
    /// or a triangle whose screen box comes within ``tri_reach`` px — or a
    /// triangle with a corner behind the eye (it may cover the pixel).
    pub fn screen_near(&self, m: &[f64; 16], w: f64, h: f64, px: f64, py: f64,
                       edge_reach: f64, tri_reach: f64) -> bool {
        if self.edge_near(m, w, h, px, py, edge_reach) {
            return true;
        }
        let clip = |p: [f64; 3]| -> [f64; 4] {
            [m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
             m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
             m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14],
             m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15]]
        };
        for r in 0..self.v0.len() {
            let a = self.v0[r];
            let pts = [a, [a[0] + self.e1[r][0], a[1] + self.e1[r][1], a[2] + self.e1[r][2]],
                       [a[0] + self.e2[r][0], a[1] + self.e2[r][1], a[2] + self.e2[r][2]]];
            let (mut x0, mut x1, mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY,
                                                    f64::INFINITY, f64::NEG_INFINITY);
            for p in pts {
                let c = clip(p);
                if !(c[3] > 1e-12) {
                    return true;        // behind the eye: could be anywhere
                }
                let sx = (c[0] / c[3] * 0.5 + 0.5) * w;
                let sy = (1.0 - (c[1] / c[3] * 0.5 + 0.5)) * h;
                if !(sx.is_finite() && sy.is_finite()) {
                    return true;
                }
                x0 = x0.min(sx);
                x1 = x1.max(sx);
                y0 = y0.min(sy);
                y1 = y1.max(sy);
            }
            if x0 - tri_reach <= px && px <= x1 + tri_reach
                && y0 - tri_reach <= py && py <= y1 + tri_reach {
                return true;
            }
        }
        false
    }

    /// Whether a hard edge, mapped by ``m`` (local → clip, column-major
    /// 4×4) to a ``w``×``h`` view, passes within ``reach`` px of
    /// ``(px, py)`` with both ends in front of the eye.
    pub fn edge_near(&self, m: &[f64; 16], w: f64, h: f64, px: f64, py: f64, reach: f64) -> bool {
        let clip = |p: [f64; 3]| -> [f64; 4] {
            [m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
             m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
             m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14],
             m[3] * p[0] + m[7] * p[1] + m[11] * p[2] + m[15]]
        };
        let r2 = reach * reach;
        for e in &self.edges {
            let a = clip(e[0]);
            let b = clip(e[1]);
            if !(a[3] > 0.0 && b[3] > 0.0) {
                continue;           // an end behind the eye: never measured
            }
            let ax = (a[0] / a[3] * 0.5 + 0.5) * w;
            let ay = (1.0 - (a[1] / a[3] * 0.5 + 0.5)) * h;
            let bx = (b[0] / b[3] * 0.5 + 0.5) * w;
            let by = (1.0 - (b[1] / b[3] * 0.5 + 0.5)) * h;
            let (dx, dy) = (bx - ax, by - ay);
            let l2 = dx * dx + dy * dy;
            let t = if l2 > 1e-12 { (((px - ax) * dx + (py - ay) * dy) / l2).clamp(0.0, 1.0) } else { 0.0 };
            let (qx, qy) = (ax + t * dx - px, ay + t * dy - py);
            let d2 = qx * qx + qy * qy;
            if d2 <= r2 || !d2.is_finite() {
                return true;
            }
        }
        false
    }
}

/// A placement: its prototype, its matrix (column-major, as Qt's
/// ``data()``), and that matrix's inverse (``None``: singular).
pub struct Placement {
    pub proto: usize,
    pub m: [f64; 16],
    pub inv: Option<[f64; 12]>,
}

/// The inverse of the affine part of a column-major 4×4: rows of the
/// inverse 3×3 then the inverse translation (``x_local = A x + b``).
pub fn affine_inverse(m: &[f64; 16]) -> Option<[f64; 12]> {
    let (a, b, c) = (m[0], m[4], m[8]);
    let (d, e, f) = (m[1], m[5], m[9]);
    let (g, h, i) = (m[2], m[6], m[10]);
    let det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    if det == 0.0 || !det.is_finite() {
        return None;
    }
    let r = 1.0 / det;
    let inv = [
        (e * i - f * h) * r, (c * h - b * i) * r, (b * f - c * e) * r,
        (f * g - d * i) * r, (a * i - c * g) * r, (c * d - a * f) * r,
        (d * h - e * g) * r, (b * g - a * h) * r, (a * e - b * d) * r,
    ];
    let t = [m[12], m[13], m[14]];
    let bx = -(inv[0] * t[0] + inv[1] * t[1] + inv[2] * t[2]);
    let by = -(inv[3] * t[0] + inv[4] * t[1] + inv[5] * t[2]);
    let bz = -(inv[6] * t[0] + inv[7] * t[1] + inv[8] * t[2]);
    Some([inv[0], inv[1], inv[2], inv[3], inv[4], inv[5], inv[6], inv[7], inv[8], bx, by, bz])
}

impl Placement {
    /// The world ray in this placement's coordinates (same parameter).
    pub fn local_ray(&self, o: [f64; 3], d: [f64; 3]) -> Option<([f64; 3], [f64; 3])> {
        let v = self.inv?;
        let lo = [v[0] * o[0] + v[1] * o[1] + v[2] * o[2] + v[9],
                  v[3] * o[0] + v[4] * o[1] + v[5] * o[2] + v[10],
                  v[6] * o[0] + v[7] * o[1] + v[8] * o[2] + v[11]];
        let ld = [v[0] * d[0] + v[1] * d[1] + v[2] * d[2],
                  v[3] * d[0] + v[4] * d[1] + v[5] * d[2],
                  v[6] * d[0] + v[7] * d[1] + v[8] * d[2]];
        Some((lo, ld))
    }
}

/// ``mvp · m``, both column-major 4×4.
pub fn mat_mul(a: &[f64; 16], b: &[f64; 16]) -> [f64; 16] {
    let mut out = [0.0; 16];
    for c in 0..4 {
        for r in 0..4 {
            let mut s = 0.0;
            for k in 0..4 {
                s += a[k * 4 + r] * b[c * 4 + k];
            }
            out[c * 4 + r] = s;
        }
    }
    out
}
