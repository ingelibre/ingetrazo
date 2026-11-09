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
    /// A BVH over the hard edges (their ends' boxes, grown), so a query
    /// near a pixel skips the far branches of a big prototype.
    eorder: Vec<u32>,
    enodes: Vec<Node>,
}

/// A BVH over ``n`` boxes ``blo``/``bhi`` (centres ``cen``): its nodes,
/// grown well past rounding, and the order the leaves index.
fn build_bvh(blo: &[[f64; 3]], bhi: &[[f64; 3]], cen: &[[f64; 3]]) -> (Vec<u32>, Vec<Node>) {
    let n = blo.len();
    let mut order: Vec<u32> = (0..n as u32).collect();
    let mut nodes = Vec::new();
    if n == 0 {
        return (order, nodes);
    }
    nodes.push(Node { lo: [0.0; 3], hi: [0.0; 3], start: 0, end: n as u32, left: 0, leaf: true });
    let mut stack = vec![0usize];
    while let Some(ni) = stack.pop() {
        let (s, e) = (nodes[ni].start as usize, nodes[ni].end as usize);
        let mut lo = [f64::INFINITY; 3];
        let mut hi = [f64::NEG_INFINITY; 3];
        let mut clo = [f64::INFINITY; 3];
        let mut chi = [f64::NEG_INFINITY; 3];
        for &r in &order[s..e] {
            let r = r as usize;
            for k in 0..3 {
                lo[k] = lo[k].min(blo[r][k]);
                hi[k] = hi[k].max(bhi[r][k]);
                clo[k] = clo[k].min(cen[r][k]);
                chi[k] = chi[k].max(cen[r][k]);
            }
        }
        let (glo, ghi) = grown(lo, hi);
        nodes[ni].lo = glo;
        nodes[ni].hi = ghi;
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
        order[s..e].select_nth_unstable_by(mid - s, |&x, &y| {
            cen[x as usize][axis].partial_cmp(&cen[y as usize][axis])
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        let left = nodes.len() as u32;
        nodes.push(Node { lo: [0.0; 3], hi: [0.0; 3], start: s as u32, end: mid as u32, left: 0, leaf: true });
        nodes.push(Node { lo: [0.0; 3], hi: [0.0; 3], start: mid as u32, end: e as u32, left: 0, leaf: true });
        nodes[ni].leaf = false;
        nodes[ni].left = left;
        stack.push(left as usize);
        stack.push(left as usize + 1);
    }
    (order, nodes)
}

/// Whether the box ``lo``/``hi``, placed by ``m`` and seen through ``mvp``,
/// can come within ``reach`` px of ``(px, py)`` — with two pixels to spare
/// for the bake's float32 rounding; a box crossing the eye plane may be
/// anywhere.
#[allow(clippy::too_many_arguments)]
fn box_may_reach(m: &[f64; 16], mvp: &[f64; 16], w: f64, h: f64, lo: [f64; 3], hi: [f64; 3],
                 px: f64, py: f64, reach: f64) -> bool {
    if !lo.iter().chain(hi.iter()).all(|v| v.is_finite()) {
        return true;
    }
    let (mut x0, mut x1, mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY,
                                            f64::INFINITY, f64::NEG_INFINITY);
    for i in 0..8 {
        let q = tp(m, [if i & 1 != 0 { hi[0] } else { lo[0] },
                       if i & 2 != 0 { hi[1] } else { lo[1] },
                       if i & 4 != 0 { hi[2] } else { lo[2] }]);
        let cw = q[0] * mvp[3] + q[1] * mvp[7] + q[2] * mvp[11] + mvp[15];
        if !(cw > 1e-9) {
            return true;
        }
        match project(mvp, q, w, h) {
            Some((sx, sy)) if sx.is_finite() && sy.is_finite() => {
                x0 = x0.min(sx);
                x1 = x1.max(sx);
                y0 = y0.min(sy);
                y1 = y1.max(sy);
            }
            _ => return true,
        }
    }
    let r = reach + 2.0;
    x0 - r <= px && px <= x1 + r && y0 - r <= py && py <= y1 + r
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
        let (mut elo, mut ehi, mut ecen) = (Vec::with_capacity(edges.len()),
                                            Vec::with_capacity(edges.len()),
                                            Vec::with_capacity(edges.len()));
        for e in &edges {
            let mut lo = [0.0; 3];
            let mut hi = [0.0; 3];
            for k in 0..3 {
                lo[k] = e[0][k].min(e[1][k]);
                hi[k] = e[0][k].max(e[1][k]);
            }
            elo.push(lo);
            ehi.push(hi);
            ecen.push([(lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5]);
        }
        let (eorder, enodes) = if edges.len() > 4 * LEAF {
            build_bvh(&elo, &ehi, &ecen)
        } else {
            (Vec::new(), Vec::new())
        };
        let mut p = Proto { v0, e1, e2, order: (0..n as u32).collect(), nodes: Vec::new(), edges,
                            eorder, enodes };
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
    /// Its world box (the pick table's), grown past rounding; infinite
    /// when the table has none.
    pub lo: [f64; 3],
    pub hi: [f64; 3],
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

/// ``views.viewport._placed_maps``'s ``tv``: a local direction through the
/// linear part of column-major ``m``, ((x·L0 + y·L1) + z·L2) term by term.
#[inline]
pub fn tv(m: &[f64; 16], a: [f64; 3]) -> [f64; 3] {
    [a[0] * m[0] + a[1] * m[4] + a[2] * m[8],
     a[0] * m[1] + a[1] * m[5] + a[2] * m[9],
     a[0] * m[2] + a[1] * m[6] + a[2] * m[10]]
}

/// Its ``tp``: a local position, ``tv`` then the translation.
#[inline]
pub fn tp(m: &[f64; 16], a: [f64; 3]) -> [f64; 3] {
    let v = tv(m, a);
    [v[0] + m[12], v[1] + m[13], v[2] + m[14]]
}

/// A hard edge's end as the bake stores it: ``tp`` rounded to float32.
#[inline]
pub fn corner(m: &[f64; 16], a: [f64; 3]) -> [f64; 3] {
    let p = tp(m, a);
    [p[0] as f32 as f64, p[1] as f32 as f64, p[2] as f32 as f64]
}

/// ``Viewport._project_px`` for one world point: widget pixel, or None
/// behind the eye (clip w not > 0). The same operations in the same order.
#[inline]
pub fn project(mvp: &[f64; 16], p: [f64; 3], w: f64, h: f64) -> Option<(f64, f64)> {
    let c = |r: usize| p[0] * mvp[r] + p[1] * mvp[4 + r] + p[2] * mvp[8 + r] + mvp[12 + r];
    let cw = c(3);
    if !(cw > 0.0) {
        return None;
    }
    let sx = (c(0) / cw * 0.5 + 0.5) * w;
    let sy = (1.0 - (c(1) / cw * 0.5 + 0.5)) * h;
    Some((sx, sy))
}

/// A box grown well past rounding, or the whole space when not finite.
pub fn grown(lo: [f64; 3], hi: [f64; 3]) -> ([f64; 3], [f64; 3]) {
    let mut ext = 0.0f64;
    let mut big = 0.0f64;
    for k in 0..3 {
        ext = ext.max(hi[k] - lo[k]);
        big = big.max(lo[k].abs()).max(hi[k].abs());
    }
    let m = 1e-6 + 1e-6 * big + 1e-4 * ext;
    let glo = [lo[0] - m, lo[1] - m, lo[2] - m];
    let ghi = [hi[0] + m, hi[1] + m, hi[2] + m];
    if glo.iter().chain(ghi.iter()).all(|v| v.is_finite()) {
        (glo, ghi)
    } else {
        ([f64::NEG_INFINITY; 3], [f64::INFINITY; 3])
    }
}

impl Placement {
    /// Whether its box's screen footprint, ``reach`` px out, can hold
    /// ``(px, py)`` — ``Viewport._placements_under_px``'s test, with a
    /// pixel to spare; a box that is not finite or crosses the eye plane
    /// may be anywhere.
    pub fn screen_may_reach(&self, mvp: &[f64; 16], w: f64, h: f64, px: f64, py: f64,
                            reach: f64) -> bool {
        if !self.lo.iter().chain(self.hi.iter()).all(|v| v.is_finite()) {
            return true;
        }
        let (mut x0, mut x1, mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY,
                                                f64::INFINITY, f64::NEG_INFINITY);
        for i in 0..8 {
            let p = [if i & 1 != 0 { self.hi[0] } else { self.lo[0] },
                     if i & 2 != 0 { self.hi[1] } else { self.lo[1] },
                     if i & 4 != 0 { self.hi[2] } else { self.lo[2] }];
            let cw = p[0] * mvp[3] + p[1] * mvp[7] + p[2] * mvp[11] + mvp[15];
            if !(cw > 1e-9) {
                return true;
            }
            match project(mvp, p, w, h) {
                Some((sx, sy)) if sx.is_finite() && sy.is_finite() => {
                    x0 = x0.min(sx);
                    x1 = x1.max(sx);
                    y0 = y0.min(sy);
                    y1 = y1.max(sy);
                }
                _ => return true,
            }
        }
        let r = reach + 1.0;
        x0 - r <= px && px <= x1 + r && y0 - r <= py && py <= y1 + r
    }

    /// The ray's parameter range inside the (grown) box, if it meets it
    /// before ``limit``.
    pub fn ray_meets_box(&self, o: [f64; 3], d: [f64; 3], limit: f64) -> bool {
        ray_meets(self.lo, self.hi, o, d, limit)
    }
}

/// Whether the ray ``o`` + t·``d``, t in [0, ``limit``], meets the box
/// ``lo``/``hi`` (with a hair to spare).
pub fn ray_meets(lo: [f64; 3], hi: [f64; 3], o: [f64; 3], d: [f64; 3], limit: f64) -> bool {
    let mut tmin = 0.0f64;
    let mut tmax = limit;
    for k in 0..3 {
        if d[k] == 0.0 {
            if o[k] < lo[k] || o[k] > hi[k] {
                return false;
            }
            continue;
        }
        let inv = 1.0 / d[k];
        let t1 = (lo[k] - o[k]) * inv;
        let t2 = (hi[k] - o[k]) * inv;
        let (a, b) = if t1 < t2 { (t1, t2) } else { (t2, t1) };
        if a.is_nan() || b.is_nan() {
            continue;
        }
        tmin = tmin.max(a);
        tmax = tmax.min(b);
    }
    tmax * (1.0 + 1e-9) + 1e-9 >= tmin
}

/// A BVH over the placements' world boxes, so a ray visits the placements
/// along it instead of all of them; those without a finite box are always
/// visited, those it is told a ray can meet nothing in never.
pub struct PlaceBvh {
    order: Vec<u32>,
    nodes: Vec<Node>,
    always: Vec<u32>,
}

impl PlaceBvh {
    pub fn new(places: &[Placement], may_meet: impl Fn(&Placement) -> bool) -> PlaceBvh {
        let mut ids = Vec::new();
        let mut always = Vec::new();
        let (mut lo, mut hi, mut cen) = (Vec::new(), Vec::new(), Vec::new());
        for (i, p) in places.iter().enumerate() {
            if !may_meet(p) {
                continue;
            }
            if p.lo.iter().chain(p.hi.iter()).all(|v| v.is_finite()) {
                ids.push(i as u32);
                lo.push(p.lo);
                hi.push(p.hi);
                cen.push([(p.lo[0] + p.hi[0]) * 0.5, (p.lo[1] + p.hi[1]) * 0.5,
                          (p.lo[2] + p.hi[2]) * 0.5]);
            } else {
                always.push(i as u32);
            }
        }
        let (order, nodes) = build_bvh(&lo, &hi, &cen);
        let order = order.into_iter().map(|k| ids[k as usize]).collect();
        PlaceBvh { order, nodes, always }
    }

    /// Calls ``f`` with every placement whose branch the ray meets before
    /// ``limit`` (a superset of those whose own box it meets), until ``f``
    /// returns false.
    pub fn on_ray(&self, o: [f64; 3], d: [f64; 3], limit: f64, mut f: impl FnMut(usize) -> bool) {
        for &i in &self.always {
            if !f(i as usize) {
                return;
            }
        }
        if self.nodes.is_empty() {
            return;
        }
        let mut stack: Vec<u32> = vec![0];
        while let Some(ni) = stack.pop() {
            let n = &self.nodes[ni as usize];
            if !ray_meets(n.lo, n.hi, o, d, limit) {
                continue;
            }
            if n.leaf {
                for &i in &self.order[n.start as usize..n.end as usize] {
                    if !f(i as usize) {
                        return;
                    }
                }
            } else {
                stack.push(n.left);
                stack.push(n.left + 1);
            }
        }
    }
}

/// One hard-edge end near the cursor: the edge, which end (0 = a, 1 = b),
/// the end as baked (world, float32), and its pixel.
pub struct Corner {
    pub edge: u32,
    pub end: u8,
    pub xyz: [f64; 3],
    pub sx: f64,
    pub sy: f64,
}

impl Proto {
    /// The ends of this prototype's hard edges, placed by ``m`` and seen
    /// through ``mvp``, within ``reach`` px of ``(px, py)`` — both ends of
    /// an edge in front of the eye, as ``Viewport.pick_vertex`` takes them.
    #[allow(clippy::too_many_arguments)]
    pub fn corners_near(&self, m: &[f64; 16], mvp: &[f64; 16], w: f64, h: f64, px: f64,
                        py: f64, reach: f64, seen: Option<&DepthLimits>, out: &mut Vec<Corner>) {
        let r2 = reach * reach;
        for i in self.edges_may_reach(m, mvp, w, h, px, py, reach, seen) {
            let e = &self.edges[i];
            let a = corner(m, e[0]);
            let b = corner(m, e[1]);
            let (Some(pa), Some(pb)) = (project(mvp, a, w, h), project(mvp, b, w, h)) else {
                continue;
            };
            for (end, xyz, (sx, sy)) in [(0u8, a, pa), (1u8, b, pb)] {
                let (dx, dy) = (sx - px, sy - py);
                if dx * dx + dy * dy <= r2 && !seen.is_some_and(|g| g.hides(xyz, sx, sy)) {
                    out.push(Corner { edge: i as u32, end, xyz, sx, sy });
                }
            }
        }
    }

    /// The hard edges whose boxes, placed by ``m``, may come within
    /// ``reach`` px of ``(px, py)`` — all of them for a small prototype —
    /// in their own order, so what is found near a pixel keeps it. With
    /// ``seen``, a box wholly behind what the frame shows wherever it may
    /// fall on screen is left out too: zoomed out over the plant of #158
    /// a million corners of a few copies lay under the cursor, nearly all
    /// under a roof, and each was projected to be told so.
    #[allow(clippy::too_many_arguments)]
    fn edges_may_reach(&self, m: &[f64; 16], mvp: &[f64; 16], w: f64, h: f64, px: f64,
                       py: f64, reach: f64, seen: Option<&DepthLimits>) -> Vec<usize> {
        if self.enodes.is_empty() {
            return (0..self.edges.len()).collect();
        }
        let mut found = Vec::new();
        let mut stack: Vec<u32> = vec![0];
        while let Some(ni) = stack.pop() {
            let n = &self.enodes[ni as usize];
            if !box_may_reach(m, mvp, w, h, n.lo, n.hi, px, py, reach) {
                continue;
            }
            if seen.is_some_and(|g| g.hides_box(m, mvp, w, h, n.lo, n.hi)) {
                continue;
            }
            if n.leaf {
                found.extend(self.eorder[n.start as usize..n.end as usize].iter()
                             .map(|&i| i as usize));
            } else {
                stack.push(n.left);
                stack.push(n.left + 1);
            }
        }
        found.sort_unstable();
        found
    }

    /// Every triangle the BVH cannot rule out for the local ray ``lo`` +
    /// t·``ld``, t ≤ ``lim``; ``f`` returns false to stop.
    pub fn for_tris_on_ray(&self, lo: [f64; 3], ld: [f64; 3], lim: f64,
                           mut f: impl FnMut(usize) -> bool) {
        if self.nodes.is_empty() {
            return;
        }
        let mut inv = [0.0; 3];
        for k in 0..3 {
            let dv = if ld[k].abs() < 1e-300 { 1e-300 } else { ld[k] };
            inv[k] = 1.0 / dv;
        }
        let lim = if lim.is_finite() { lim * (1.0 + 1e-6) + 1e-6 } else { f64::INFINITY };
        let mut stack: Vec<u32> = vec![0];
        while let Some(ni) = stack.pop() {
            let n = &self.nodes[ni as usize];
            if !Self::box_hit(n, lo, inv, lim) {
                continue;
            }
            if !n.leaf {
                stack.push(n.left);
                stack.push(n.left + 1);
                continue;
            }
            for &r in &self.order[n.start as usize..n.end as usize] {
                if !f(r as usize) {
                    return;
                }
            }
        }
    }

    /// Triangle ``r`` in world space, as ``_instance_chunk`` bakes it.
    #[inline]
    pub fn world_tri(&self, m: &[f64; 16], r: usize) -> ([f64; 3], [f64; 3], [f64; 3]) {
        (tp(m, self.v0[r]), tv(m, self.e1[r]), tv(m, self.e2[r]))
    }
}

/// What the last frame shows around the cursor, as ``Viewport._depth_limits``
/// gives it: per device pixel of a patch, the distance from the eye past
/// which a point there is hidden by something drawn (inf: it cannot say).
pub struct DepthLimits {
    pub eye: [f64; 3],
    pub lim: Vec<f64>,
    pub x0: i64,
    pub y0: i64,
    pub gw: i64,
    pub gh: i64,
    pub dpr: f64,
    pub hdev: i64,
}

impl DepthLimits {
    /// Whether the point at widget pixel ``(sx, sy)`` lies past its limit.
    #[inline]
    pub fn hides(&self, p: [f64; 3], sx: f64, sy: f64) -> bool {
        let ix = (sx * self.dpr).floor() as i64 - self.x0;
        let iy = self.hdev - 1 - (sy * self.dpr).floor() as i64 - self.y0;
        if ix < 0 || iy < 0 || ix >= self.gw || iy >= self.gh {
            return false;
        }
        let l = self.lim[(iy * self.gw + ix) as usize];
        let (dx, dy, dz) = (p[0] - self.eye[0], p[1] - self.eye[1], p[2] - self.eye[2]);
        (dx * dx + dy * dy + dz * dz).sqrt() > l
    }

    /// Whether ``hides`` holds for every point of the local box ``lo``–``hi``
    /// placed by ``m`` that falls inside the patch (those outside it lie
    /// farther from the cursor than any corner asked for): the box nearer
    /// to the eye than its nearest point by a margin past rounding — the
    /// bake's float corners, the square root — than the largest limit
    /// over the pixels its screen box covers. False whenever it cannot
    /// tell (a corner of the box behind the eye, a pixel with no limit).
    pub fn hides_box(&self, m: &[f64; 16], mvp: &[f64; 16], w: f64, h: f64,
                     lo: [f64; 3], hi: [f64; 3]) -> bool {
        if !lo.iter().chain(hi.iter()).all(|v| v.is_finite()) {
            return false;
        }
        let (mut wlo, mut whi) = ([f64::INFINITY; 3], [f64::NEG_INFINITY; 3]);
        let (mut x0, mut x1, mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY,
                                                f64::INFINITY, f64::NEG_INFINITY);
        for i in 0..8 {
            let q = tp(m, box_corner(lo, hi, i));
            let cw = q[0] * mvp[3] + q[1] * mvp[7] + q[2] * mvp[11] + mvp[15];
            if !(cw > 1e-9) {
                return false;
            }
            let Some((sx, sy)) = project(mvp, q, w, h) else { return false };
            if !(sx.is_finite() && sy.is_finite()) {
                return false;
            }
            x0 = x0.min(sx);
            x1 = x1.max(sx);
            y0 = y0.min(sy);
            y1 = y1.max(sy);
            for k in 0..3 {
                wlo[k] = wlo[k].min(q[k]);
                whi[k] = whi[k].max(q[k]);
            }
        }
        // The pixels the box may fall on, a pixel wider, within the patch.
        let ix0 = (((x0 - 1.0) * self.dpr).floor() as i64 - self.x0).max(0);
        let ix1 = (((x1 + 1.0) * self.dpr).floor() as i64 - self.x0).min(self.gw - 1);
        let iy0 = (self.hdev - 1 - ((y1 + 1.0) * self.dpr).floor() as i64 - self.y0).max(0);
        let iy1 = (self.hdev - 1 - ((y0 - 1.0) * self.dpr).floor() as i64 - self.y0).min(self.gh - 1);
        if ix0 > ix1 || iy0 > iy1 {
            return true;
        }
        let mut lmax = 0.0f64;
        for iy in iy0..=iy1 {
            for &l in &self.lim[(iy * self.gw + ix0) as usize..=(iy * self.gw + ix1) as usize] {
                if !(l < f64::INFINITY) {
                    return false;
                }
                lmax = lmax.max(l);
            }
        }
        let mut d2 = 0.0f64;
        let mut big = 0.0f64;
        for k in 0..3 {
            let e = self.eye[k];
            let g = if e < wlo[k] { wlo[k] - e } else if e > whi[k] { e - whi[k] } else { 0.0 };
            d2 += g * g;
            big = big.max(wlo[k].abs()).max(whi[k].abs()).max(e.abs());
        }
        d2.sqrt() - (1e-6 * big + 1e-9) > lmax * (1.0 + 1e-9)
    }
}

/// ``core.edge_grid.segment_distances`` for one segment: the pixel
/// distance from ``(px, py)`` to ``a``–``b``, operation for operation.
#[inline]
pub fn segment_distance(ax: f64, ay: f64, bx: f64, by: f64, px: f64, py: f64) -> f64 {
    let (dx, dy) = (bx - ax, by - ay);
    let l2 = dx * dx + dy * dy;
    let safe = if l2 > 1e-12 { l2 } else { 1.0 };
    let t = (((px - ax) * dx + (py - ay) * dy) / safe).clamp(0.0, 1.0);
    (ax + t * dx - px).hypot(ay + t * dy - py)
}

/// One hard edge near the cursor: its distance, the position of its
/// placement among the candidates, which edge, which placement, its ends
/// as baked. Ordered by (distance, candidate, edge).
pub struct NearEdge {
    pub d: f64,
    pub k: usize,
    pub edge: u32,
    pub place: i64,
    pub a: [f64; 3],
    pub b: [f64; 3],
}

impl NearEdge {
    fn key_cmp(&self, o: &NearEdge) -> std::cmp::Ordering {
        self.d.total_cmp(&o.d).then(self.k.cmp(&o.k)).then(self.edge.cmp(&o.edge))
    }
}
impl PartialEq for NearEdge {
    fn eq(&self, o: &Self) -> bool {
        self.key_cmp(o) == std::cmp::Ordering::Equal
    }
}
impl Eq for NearEdge {}
impl PartialOrd for NearEdge {
    fn partial_cmp(&self, o: &Self) -> Option<std::cmp::Ordering> {
        Some(self.key_cmp(o))
    }
}
impl Ord for NearEdge {
    fn cmp(&self, o: &Self) -> std::cmp::Ordering {
        self.key_cmp(o)
    }
}

/// The nearest ``cap`` edges within ``radius`` found so far (all of them
/// when ``cap`` is 0): what a box farther than ``reach()`` can no longer
/// change is skipped whole.
pub struct NearHeap {
    cap: usize,
    radius: f64,
    /// Farther than this cannot enter (another heap's worst, when full).
    bound: f64,
    items: std::collections::BinaryHeap<NearEdge>,
}

impl NearHeap {
    pub fn new(cap: usize, radius: f64) -> NearHeap {
        NearHeap { cap, radius, bound: f64::INFINITY,
                   items: std::collections::BinaryHeap::new() }
    }

    /// A heap for one placement of a batch searched in parallel: what lies
    /// farther than ``bound`` (the shared heap's worst) is left out — a
    /// superset of what the shared heap takes, merged into it after.
    pub fn bounded(cap: usize, radius: f64, bound: f64) -> NearHeap {
        NearHeap { cap, radius, bound, items: std::collections::BinaryHeap::new() }
    }

    /// The distance past which nothing more enters, when full.
    pub fn worst(&self) -> f64 {
        if self.cap > 0 && self.items.len() >= self.cap {
            self.items.peek().map_or(f64::INFINITY, |t| t.d)
        } else {
            f64::INFINITY
        }
    }

    /// Whether something ``gap`` px away (at least) may still enter.
    #[inline]
    pub fn may_take(&self, gap: f64) -> bool {
        if !(gap <= self.bound) {
            return false;
        }
        if self.cap > 0 && self.items.len() >= self.cap {
            self.items.peek().is_some_and(|t| gap <= t.d)
        } else {
            gap < self.radius
        }
    }

    pub fn offer(&mut self, e: NearEdge) {
        if !(e.d < self.radius) || e.d > self.bound {
            return;
        }
        if self.cap == 0 || self.items.len() < self.cap {
            self.items.push(e);
        } else if self.items.peek().is_some_and(|t| e < *t) {
            self.items.pop();
            self.items.push(e);
        }
    }

    pub fn into_sorted(self) -> Vec<NearEdge> {
        self.items.into_sorted_vec()
    }
}

/// How far (px) the screen rectangle of the eight points ``q(0..8)`` lies
/// from ``(px, py)``, less two pixels for the bake's float32 rounding: no
/// more than any point inside their box lies from it. 0 when one is
/// behind the eye plane or not finite.
#[allow(clippy::too_many_arguments)]
fn rect_gap(q: impl Fn(usize) -> [f64; 3], mvp: &[f64; 16], w: f64, h: f64, px: f64,
            py: f64) -> f64 {
    let (mut x0, mut x1, mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY,
                                            f64::INFINITY, f64::NEG_INFINITY);
    for i in 0..8 {
        let p = q(i);
        if !p.iter().all(|v| v.is_finite()) {
            return 0.0;
        }
        let cw = p[0] * mvp[3] + p[1] * mvp[7] + p[2] * mvp[11] + mvp[15];
        if !(cw > 1e-9) {
            return 0.0;
        }
        match project(mvp, p, w, h) {
            Some((sx, sy)) if sx.is_finite() && sy.is_finite() => {
                x0 = x0.min(sx);
                x1 = x1.max(sx);
                y0 = y0.min(sy);
                y1 = y1.max(sy);
            }
            _ => return 0.0,
        }
    }
    let dx = (x0 - px).max(px - x1).max(0.0);
    let dy = (y0 - py).max(py - y1).max(0.0);
    (dx.hypot(dy) - 2.0).max(0.0)
}

#[inline]
fn box_corner(lo: [f64; 3], hi: [f64; 3], i: usize) -> [f64; 3] {
    [if i & 1 != 0 { hi[0] } else { lo[0] },
     if i & 2 != 0 { hi[1] } else { lo[1] },
     if i & 4 != 0 { hi[2] } else { lo[2] }]
}

impl Placement {
    /// ``rect_gap`` of its world box: no edge of it lies nearer the pixel.
    pub fn screen_gap(&self, mvp: &[f64; 16], w: f64, h: f64, px: f64, py: f64) -> f64 {
        rect_gap(|i| box_corner(self.lo, self.hi, i), mvp, w, h, px, py)
    }
}

impl Proto {
    /// Offers ``heap`` the hard edges of this prototype, placed by ``m``
    /// and seen through ``mvp``, at the distance ``segment_distances``
    /// gives them (both ends in front) — but those in BVH branches whose
    /// screen box lies farther than what the heap can still take.
    #[allow(clippy::too_many_arguments)]
    pub fn edges_near(&self, m: &[f64; 16], mvp: &[f64; 16], w: f64, h: f64, px: f64,
                      py: f64, k: usize, place: i64, heap: &mut NearHeap) {
        let one = |i: usize, heap: &mut NearHeap| {
            let e = &self.edges[i];
            let a = corner(m, e[0]);
            let b = corner(m, e[1]);
            let (Some((ax, ay)), Some((bx, by))) = (project(mvp, a, w, h), project(mvp, b, w, h)) else {
                return;
            };
            let d = segment_distance(ax, ay, bx, by, px, py);
            heap.offer(NearEdge { d, k, edge: i as u32, place, a, b });
        };
        if self.enodes.is_empty() {
            for i in 0..self.edges.len() {
                one(i, heap);
            }
            return;
        }
        let gap = |n: &Node| rect_gap(|c| tp(m, box_corner(n.lo, n.hi, c)), mvp, w, h, px, py);
        // Nearest branch first: the heap fills with near edges sooner.
        let mut stack: Vec<(u32, f64)> = vec![(0, gap(&self.enodes[0]))];
        while let Some((ni, g)) = stack.pop() {
            if !heap.may_take(g) {
                continue;
            }
            let n = &self.enodes[ni as usize];
            if n.leaf {
                for &i in &self.eorder[n.start as usize..n.end as usize] {
                    one(i as usize, heap);
                }
            } else {
                let (l, r) = (n.left, n.left + 1);
                let (gl, gr) = (gap(&self.enodes[l as usize]), gap(&self.enodes[r as usize]));
                if gl <= gr {
                    stack.push((r, gr));
                    stack.push((l, gl));
                } else {
                    stack.push((l, gl));
                    stack.push((r, gr));
                }
            }
        }
    }
}

