// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! Ray crossing counts for `core.orient.ray_parity_outside` — the engine's
//! one volumetric primitive (orientation, and the per-plane rebuild of a
//! push/pull). The exact test is `_ParityQuery.crossings_many`'s
//! Möller–Trumbore, operation for operation in f64; a BVH whose boxes are
//! grown well past the test's tolerances only skips triangles the exact
//! test would refuse anyway, so the counts are the same.

const EPS: f64 = 1e-7;
const T_MIN: f64 = 1e-6;
const LEAF: usize = 8;

#[inline]
fn cross(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

#[inline]
fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

struct Node {
    lo: [f64; 3],
    hi: [f64; 3],
    // leaf: start..end in `order`; inner: children `left`, `left + 1`…
    start: u32,
    end: u32,
    left: u32,
    leaf: bool,
}

pub struct Tris {
    a: Vec<[f64; 3]>,
    e1: Vec<[f64; 3]>,
    e2: Vec<[f64; 3]>,
    face: Vec<i64>,
    order: Vec<u32>,
    nodes: Vec<Node>,
}

fn grown(lo: [f64; 3], hi: [f64; 3]) -> ([f64; 3], [f64; 3]) {
    // The same margin as core.orient._Clusters: far beyond the exact test's
    // barycentric 1e-7 and t > 1e-6.
    let mut ext = 0.0f64;
    let mut big = 0.0f64;
    for k in 0..3 {
        ext = ext.max(hi[k] - lo[k]);
        big = big.max(lo[k].abs()).max(hi[k].abs());
    }
    let m = 1e-5 + 1e-6 * big + 1e-5 * ext;
    ([lo[0] - m, lo[1] - m, lo[2] - m], [hi[0] + m, hi[1] + m, hi[2] + m])
}

impl Tris {
    pub fn new(a: Vec<[f64; 3]>, e1: Vec<[f64; 3]>, e2: Vec<[f64; 3]>, face: Vec<i64>) -> Tris {
        let n = a.len();
        let mut tlo = Vec::with_capacity(n);
        let mut thi = Vec::with_capacity(n);
        let mut cen = Vec::with_capacity(n);
        for i in 0..n {
            let b = [a[i][0] + e1[i][0], a[i][1] + e1[i][1], a[i][2] + e1[i][2]];
            let c = [a[i][0] + e2[i][0], a[i][1] + e2[i][1], a[i][2] + e2[i][2]];
            let mut lo = [0.0; 3];
            let mut hi = [0.0; 3];
            for k in 0..3 {
                lo[k] = a[i][k].min(b[k]).min(c[k]);
                hi[k] = a[i][k].max(b[k]).max(c[k]);
            }
            tlo.push(lo);
            thi.push(hi);
            cen.push([(lo[0] + hi[0]) * 0.5, (lo[1] + hi[1]) * 0.5, (lo[2] + hi[2]) * 0.5]);
        }
        let mut t = Tris { a, e1, e2, face, order: (0..n as u32).collect(), nodes: Vec::new() };
        if n > 0 {
            t.nodes.push(Node { lo: [0.0; 3], hi: [0.0; 3], start: 0, end: n as u32, left: 0, leaf: true });
            let mut stack = vec![0usize];
            while let Some(ni) = stack.pop() {
                let (s, e) = (t.nodes[ni].start as usize, t.nodes[ni].end as usize);
                let mut lo = [f64::INFINITY; 3];
                let mut hi = [f64::NEG_INFINITY; 3];
                let mut clo = [f64::INFINITY; 3];
                let mut chi = [f64::NEG_INFINITY; 3];
                for &r in &t.order[s..e] {
                    let r = r as usize;
                    for k in 0..3 {
                        lo[k] = lo[k].min(tlo[r][k]);
                        hi[k] = hi[k].max(thi[r][k]);
                        clo[k] = clo[k].min(cen[r][k]);
                        chi[k] = chi[k].max(cen[r][k]);
                    }
                }
                let (glo, ghi) = grown(lo, hi);
                t.nodes[ni].lo = glo;
                t.nodes[ni].hi = ghi;
                // A NaN corner must never prune: such a box always "hits".
                if !(glo.iter().chain(ghi.iter()).all(|v| v.is_finite())) {
                    t.nodes[ni].lo = [f64::NEG_INFINITY; 3];
                    t.nodes[ni].hi = [f64::INFINITY; 3];
                }
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
                t.order[s..e].select_nth_unstable_by(mid - s, |&x, &y| {
                    cen[x as usize][axis]
                        .partial_cmp(&cen[y as usize][axis])
                        .unwrap_or(std::cmp::Ordering::Equal)
                });
                let left = t.nodes.len() as u32;
                t.nodes.push(Node { lo: [0.0; 3], hi: [0.0; 3], start: s as u32, end: mid as u32, left: 0, leaf: true });
                t.nodes.push(Node { lo: [0.0; 3], hi: [0.0; 3], start: mid as u32, end: e as u32, left: 0, leaf: true });
                t.nodes[ni].leaf = false;
                t.nodes[ni].left = left;
                stack.push(left as usize);
                stack.push(left as usize + 1);
            }
        }
        t
    }

    pub fn len(&self) -> usize {
        self.a.len()
    }

    #[inline]
    fn hits_box(n: &Node, o: [f64; 3], inv: [f64; 3]) -> bool {
        let mut tmin = f64::NEG_INFINITY;
        let mut tmax = f64::INFINITY;
        for k in 0..3 {
            let t1 = (n.lo[k] - o[k]) * inv[k];
            let t2 = (n.hi[k] - o[k]) * inv[k];
            let (a, b) = if t1 < t2 { (t1, t2) } else { (t2, t1) };
            // NaN (0 · ∞ on a slab plane): keep the box (never prune by it).
            if a.is_nan() || b.is_nan() {
                continue;
            }
            tmin = tmin.max(a);
            tmax = tmax.min(b);
        }
        tmax >= tmin && tmax >= 0.0
    }

    /// Crossings ahead of `o` along each of `dirs`, counting only the
    /// triangles with `mask[i]` (all when `None`) and not of face `skip`.
    pub fn crossings(&self, o: [f64; 3], dirs: &[[f64; 3]], mask: Option<&[bool]>, skip: Option<i64>) -> Vec<i64> {
        let mut out = Vec::with_capacity(dirs.len());
        let mut stack: Vec<u32> = Vec::with_capacity(64);
        for &d in dirs {
            let mut count = 0i64;
            if self.nodes.is_empty() {
                out.push(0);
                continue;
            }
            let mut inv = [0.0; 3];
            for k in 0..3 {
                let dv = if d[k].abs() < 1e-30 { 1e-30 } else { d[k] };
                inv[k] = 1.0 / dv;
            }
            stack.clear();
            stack.push(0);
            while let Some(ni) = stack.pop() {
                let n = &self.nodes[ni as usize];
                if !Self::hits_box(n, o, inv) {
                    continue;
                }
                if !n.leaf {
                    stack.push(n.left);
                    stack.push(n.left + 1);
                    continue;
                }
                for &r in &self.order[n.start as usize..n.end as usize] {
                    let r = r as usize;
                    if let Some(m) = mask {
                        if !m[r] {
                            continue;
                        }
                    }
                    if skip == Some(self.face[r]) {
                        continue;
                    }
                    if self.hit(r, o, d) {
                        count += 1;
                    }
                }
            }
            out.push(count);
        }
        out
    }

    /// `_ParityQuery.crossings_many` for one triangle and one ray.
    #[inline]
    fn hit(&self, r: usize, o: [f64; 3], d: [f64; 3]) -> bool {
        let e1 = self.e1[r];
        let e2 = self.e2[r];
        let a = self.a[r];
        let tvec = [o[0] - a[0], o[1] - a[1], o[2] - a[2]];
        let p = cross(d, e2);
        let det = dot(e1, p);
        if !(det.abs() >= EPS) {
            return false;
        }
        let inv = 1.0 / det;
        let u = dot(tvec, p) * inv;
        if !(u >= -EPS && u <= 1.0 + EPS) {
            return false;
        }
        let q = cross(tvec, e1);
        let v = dot(q, d) * inv;
        if !(v >= -EPS && u + v <= 1.0 + EPS) {
            return false;
        }
        let t = dot(e2, q) * inv;
        t > T_MIN
    }
}
