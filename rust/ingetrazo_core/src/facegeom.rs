// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! What `views.viewport._face_geometry` computes per face — the Newell
//! normal, the area, the centroid and the triangles — from arrays instead
//! of `Face` objects (the experimental engine's lazy meshes).
//!
//! QVector3D is float32, and the Python code goes through it: every
//! vector operation here is the float32 operation Qt performs, in Qt's
//! order (`f32`), and every Python float operation is an `f64` one.
//! `length()` is `std::hypot(x, y, z)`, which differs between C++ standard
//! libraries; `Hypot` names the formula, and `core._native` checks at
//! start-up that it is the one this Qt uses (none: the Python bake).

#[derive(Clone, Copy, PartialEq, Eq)]
pub enum Hypot {
    /// libstdc++ (`std::__hypot3`): scale by the largest component.
    LibStdCxx,
}

#[derive(Clone, Copy)]
pub struct V3(pub f32, pub f32, pub f32);

impl V3 {
    #[inline]
    fn sub(self, o: V3) -> V3 {
        V3(self.0 - o.0, self.1 - o.1, self.2 - o.2)
    }
    #[inline]
    fn mul(self, s: f32) -> V3 {
        V3(self.0 * s, self.1 * s, self.2 * s)
    }
    #[inline]
    fn div(self, s: f32) -> V3 {
        V3(self.0 / s, self.1 / s, self.2 / s)
    }
    #[inline]
    fn dot(self, o: V3) -> f32 {
        self.0 * o.0 + self.1 * o.1 + self.2 * o.2
    }
    #[inline]
    fn cross(self, o: V3) -> V3 {
        V3(
            self.1 * o.2 - self.2 * o.1,
            self.2 * o.0 - self.0 * o.2,
            self.0 * o.1 - self.1 * o.0,
        )
    }
}

#[inline]
pub fn length(v: V3, h: Hypot) -> f32 {
    match h {
        Hypot::LibStdCxx => {
            let (x, y, z) = (v.0.abs(), v.1.abs(), v.2.abs());
            let a = if x < y {
                if y < z { z } else { y }
            } else if x < z {
                z
            } else {
                x
            };
            if a != 0.0 {
                let (xa, ya, za) = (x / a, y / a, z / a);
                a * (xa * xa + ya * ya + za * za).sqrt()
            } else {
                0.0
            }
        }
    }
}

#[inline]
fn fuzzy_null(f: f32) -> bool {
    f.abs() <= 0.00001f32
}

/// `QVector3D::normalized()`.
#[inline]
pub fn normalized(v: V3, h: Hypot) -> V3 {
    let len = length(v, h);
    if fuzzy_null(len - 1.0) {
        v
    } else if fuzzy_null(len) {
        V3(0.0, 0.0, 0.0)
    } else {
        V3(v.0 / len, v.1 / len, v.2 / len)
    }
}

/// `core.triangulate.plane_axes`.
pub fn plane_axes(normal: V3, h: Hypot) -> (V3, V3) {
    let n = normalized(normal, h);
    let mut r = V3(1.0, 0.0, 0.0);
    let mut u = r.sub(n.mul(r.dot(n)));
    if (length(u, h) as f64) < 0.1 {
        r = V3(0.0, 1.0, 0.0);
        u = r.sub(n.mul(r.dot(n)));
    }
    let u = normalized(u, h);
    let v = normalized(n.cross(u), h);
    (u, v)
}

// ---- earcut: core.triangulate's Mapbox port, node for node ---------------

struct Node {
    i: usize,
    x: f64,
    y: f64,
    prev: usize,
    next: usize,
    steiner: bool,
}

struct Ring {
    n: Vec<Node>,
}

impl Ring {
    fn node(&mut self, i: usize, x: f64, y: f64) -> usize {
        let k = self.n.len();
        self.n.push(Node { i, x, y, prev: k, next: k, steiner: false });
        k
    }
    fn insert(&mut self, i: usize, x: f64, y: f64, last: Option<usize>) -> usize {
        let k = self.node(i, x, y);
        if let Some(l) = last {
            let ln = self.n[l].next;
            self.n[k].next = ln;
            self.n[k].prev = l;
            self.n[ln].prev = k;
            self.n[l].next = k;
        }
        k
    }
    fn remove(&mut self, k: usize) {
        let (p, nx) = (self.n[k].prev, self.n[k].next);
        self.n[nx].prev = p;
        self.n[p].next = nx;
    }
    #[inline]
    fn area(&self, p: usize, q: usize, r: usize) -> f64 {
        let (p, q, r) = (&self.n[p], &self.n[q], &self.n[r]);
        (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y)
    }
    #[inline]
    fn equals(&self, a: usize, b: usize) -> bool {
        self.n[a].x == self.n[b].x && self.n[a].y == self.n[b].y
    }
    fn build_ring(&mut self, pts: &[(f64, f64)], idxs: &[usize], want_ccw: bool) -> Option<usize> {
        let m = idxs.len();
        let mut s = 0.0f64;
        for k in 0..m {
            let a = pts[idxs[k]];
            let b = pts[idxs[(k + 1) % m]];
            s += (b.0 - a.0) * (a.1 + b.1);
        }
        let clockwise = s > 0.0;
        let mut last: Option<usize> = None;
        if clockwise != want_ccw {
            for &i in idxs {
                last = Some(self.insert(i, pts[i].0, pts[i].1, last));
            }
        } else {
            for &i in idxs.iter().rev() {
                last = Some(self.insert(i, pts[i].0, pts[i].1, last));
            }
        }
        if let Some(l) = last {
            if self.equals(l, self.n[l].next) {
                self.remove(l);
                last = Some(self.n[l].next);
            }
        }
        last
    }
    fn filter_points(&mut self, start: usize, end: Option<usize>) -> usize {
        let mut end = end.unwrap_or(start);
        let mut p = start;
        loop {
            let mut again = false;
            let (pp, pn) = (self.n[p].prev, self.n[p].next);
            if !self.n[p].steiner && (self.equals(p, pn) || self.area(pp, p, pn) == 0.0) {
                self.remove(p);
                p = self.n[p].prev;
                end = p;
                if p == self.n[p].next {
                    break;
                }
                again = true;
            } else {
                p = pn;
            }
            if !again && p == end {
                break;
            }
        }
        end
    }
    fn is_ear(&self, ear: usize) -> bool {
        let (a, b, c) = (self.n[ear].prev, ear, self.n[ear].next);
        if self.area(a, b, c) >= 0.0 {
            return false;
        }
        let (ax, bx, cx) = (self.n[a].x, self.n[b].x, self.n[c].x);
        let (ay, by, cy) = (self.n[a].y, self.n[b].y, self.n[c].y);
        let x0 = py_min3(ax, bx, cx);
        let y0 = py_min3(ay, by, cy);
        let x1 = py_max3(ax, bx, cx);
        let y1 = py_max3(ay, by, cy);
        let mut p = self.n[c].next;
        while p != a {
            let (px, py) = (self.n[p].x, self.n[p].y);
            if x0 <= px && px <= x1 && y0 <= py && py <= y1
                && point_in_triangle(ax, ay, bx, by, cx, cy, px, py)
                && self.area(self.n[p].prev, p, self.n[p].next) >= 0.0
            {
                return false;
            }
            p = self.n[p].next;
        }
        true
    }
    fn earcut_linked(&mut self, ear: Option<usize>, tris: &mut Vec<[usize; 3]>, pass: u8) {
        let Some(mut ear) = ear else { return };
        let mut stop = ear;
        while self.n[ear].prev != self.n[ear].next {
            let prev = self.n[ear].prev;
            let nxt = self.n[ear].next;
            if self.is_ear(ear) {
                tris.push([self.n[prev].i, self.n[ear].i, self.n[nxt].i]);
                self.remove(ear);
                ear = self.n[nxt].next;
                stop = self.n[nxt].next;
                continue;
            }
            ear = nxt;
            if ear == stop {
                if pass == 0 {
                    let f = self.filter_points(ear, None);
                    self.earcut_linked(Some(f), tris, 1);
                } else if pass == 1 {
                    let f = self.filter_points(ear, None);
                    let e = self.cure_local_intersections(f, tris);
                    self.earcut_linked(Some(e), tris, 2);
                } else if pass == 2 {
                    self.split_earcut(ear, tris);
                }
                return;
            }
        }
    }
    fn cure_local_intersections(&mut self, start: usize, tris: &mut Vec<[usize; 3]>) -> usize {
        let mut start = start;
        let mut p = start;
        loop {
            let a = self.n[p].prev;
            let b = self.n[self.n[p].next].next;
            let pn = self.n[p].next;
            if !self.equals(a, b) && self.intersects(a, p, pn, b)
                && self.locally_inside(a, b) && self.locally_inside(b, a)
            {
                tris.push([self.n[a].i, self.n[p].i, self.n[b].i]);
                self.remove(p);
                let pn2 = self.n[p].next;
                self.remove(pn2);
                p = b;
                start = b;
            }
            p = self.n[p].next;
            if p == start {
                break;
            }
        }
        self.filter_points(p, None)
    }
    fn split_earcut(&mut self, start: usize, tris: &mut Vec<[usize; 3]>) {
        let mut a = start;
        loop {
            let mut b = self.n[self.n[a].next].next;
            while b != self.n[a].prev {
                if self.n[a].i != self.n[b].i && self.is_valid_diagonal(a, b) {
                    let c = self.split_polygon(a, b);
                    let an = self.n[a].next;
                    let a2 = self.filter_points(a, Some(an));
                    let cn = self.n[c].next;
                    let c2 = self.filter_points(c, Some(cn));
                    self.earcut_linked(Some(a2), tris, 0);
                    self.earcut_linked(Some(c2), tris, 0);
                    return;
                }
                b = self.n[b].next;
            }
            a = self.n[a].next;
            if a == start {
                break;
            }
        }
    }
    fn leftmost(&self, start: usize) -> usize {
        let mut p = start;
        let mut l = start;
        loop {
            let (px, py, lx, ly) = (self.n[p].x, self.n[p].y, self.n[l].x, self.n[l].y);
            if px < lx || (px == lx && py < ly) {
                l = p;
            }
            p = self.n[p].next;
            if p == start {
                break;
            }
        }
        l
    }
    fn find_hole_bridge(&self, hole: usize, outer: usize) -> Option<usize> {
        let mut p = outer;
        let (hx, hy) = (self.n[hole].x, self.n[hole].y);
        let mut qx = f64::NEG_INFINITY;
        let mut m: Option<usize> = None;
        loop {
            let pn = self.n[p].next;
            let (px, py, nx, ny) = (self.n[p].x, self.n[p].y, self.n[pn].x, self.n[pn].y);
            if hy <= py && hy >= ny && ny != py {
                let x = px + (hy - py) * (nx - px) / (ny - py);
                if hx >= x && x > qx {
                    qx = x;
                    m = Some(if px < nx { p } else { pn });
                    if x == hx {
                        return m;
                    }
                }
            }
            p = pn;
            if p == outer {
                break;
            }
        }
        let mut m = m?;
        let stop = m;
        let (mx, my) = (self.n[m].x, self.n[m].y);
        let mut tan_min = f64::INFINITY;
        let mut p = m;
        loop {
            let (px, py) = (self.n[p].x, self.n[p].y);
            if hx >= px && px >= mx && hx != px
                && point_in_triangle(
                    if hy < my { hx } else { qx }, hy, mx, my,
                    if hy < my { qx } else { hx }, hy, px, py)
            {
                let tan = (hy - py).abs() / (hx - px);
                if self.locally_inside(p, hole)
                    && (tan < tan_min
                        || (tan == tan_min
                            && (px > self.n[m].x
                                || (px == self.n[m].x && self.sector_contains(m, p)))))
                {
                    m = p;
                    tan_min = tan;
                }
            }
            p = self.n[p].next;
            if p == stop {
                break;
            }
        }
        Some(m)
    }
    fn sector_contains(&self, m: usize, p: usize) -> bool {
        self.area(self.n[m].prev, m, self.n[p].prev) < 0.0
            && self.area(self.n[p].next, m, self.n[m].next) < 0.0
    }
    fn locally_inside(&self, a: usize, b: usize) -> bool {
        let (ap, an) = (self.n[a].prev, self.n[a].next);
        if self.area(ap, a, an) < 0.0 {
            self.area(a, b, an) >= 0.0 && self.area(a, ap, b) >= 0.0
        } else {
            self.area(a, b, ap) < 0.0 || self.area(a, an, b) < 0.0
        }
    }
    fn middle_inside(&self, a: usize, b: usize) -> bool {
        let mut p = a;
        let mut inside = false;
        let px = (self.n[a].x + self.n[b].x) / 2.0;
        let py = (self.n[a].y + self.n[b].y) / 2.0;
        loop {
            let pn = self.n[p].next;
            let (x, y, nx, ny) = (self.n[p].x, self.n[p].y, self.n[pn].x, self.n[pn].y);
            if ((y > py) != (ny > py)) && ny != y && px < (nx - x) * (py - y) / (ny - y) + x {
                inside = !inside;
            }
            p = pn;
            if p == a {
                break;
            }
        }
        inside
    }
    fn is_valid_diagonal(&self, a: usize, b: usize) -> bool {
        let (an, ap, bn, bp) = (self.n[a].next, self.n[a].prev, self.n[b].next, self.n[b].prev);
        self.n[an].i != self.n[b].i
            && self.n[ap].i != self.n[b].i
            && !self.intersects_polygon(a, b)
            && ((self.locally_inside(a, b)
                && self.locally_inside(b, a)
                && self.middle_inside(a, b)
                && (self.area(ap, a, bp) != 0.0 || self.area(a, bp, b) != 0.0))
                || (self.equals(a, b)
                    && self.area(ap, a, an) > 0.0
                    && self.area(bp, b, bn) > 0.0))
    }
    fn on_segment(&self, p: usize, q: usize, r: usize) -> bool {
        let (p, q, r) = (&self.n[p], &self.n[q], &self.n[r]);
        py_max2(p.x, r.x) >= q.x && q.x >= py_min2(p.x, r.x)
            && py_max2(p.y, r.y) >= q.y && q.y >= py_min2(p.y, r.y)
    }
    fn intersects(&self, p1: usize, q1: usize, p2: usize, q2: usize) -> bool {
        let o1 = sign(self.area(p1, q1, p2));
        let o2 = sign(self.area(p1, q1, q2));
        let o3 = sign(self.area(p2, q2, p1));
        let o4 = sign(self.area(p2, q2, q1));
        if o1 != o2 && o3 != o4 {
            return true;
        }
        (o1 == 0 && self.on_segment(p1, p2, q1))
            || (o2 == 0 && self.on_segment(p1, q2, q1))
            || (o3 == 0 && self.on_segment(p2, p1, q2))
            || (o4 == 0 && self.on_segment(p2, q1, q2))
    }
    fn intersects_polygon(&self, a: usize, b: usize) -> bool {
        let mut p = a;
        let (ai, bi) = (self.n[a].i, self.n[b].i);
        loop {
            let pn = self.n[p].next;
            let (pi, pni) = (self.n[p].i, self.n[pn].i);
            if pi != ai && pni != ai && pi != bi && pni != bi && self.intersects(p, pn, a, b) {
                return true;
            }
            p = pn;
            if p == a {
                break;
            }
        }
        false
    }
    fn split_polygon(&mut self, a: usize, b: usize) -> usize {
        let (ai, ax, ay) = (self.n[a].i, self.n[a].x, self.n[a].y);
        let (bi, bx, by) = (self.n[b].i, self.n[b].x, self.n[b].y);
        let a2 = self.node(ai, ax, ay);
        let b2 = self.node(bi, bx, by);
        let an = self.n[a].next;
        let bp = self.n[b].prev;
        self.n[a].next = b;
        self.n[b].prev = a;
        self.n[a2].next = an;
        self.n[an].prev = a2;
        self.n[b2].next = a2;
        self.n[a2].prev = b2;
        self.n[bp].next = b2;
        self.n[b2].prev = bp;
        b2
    }
}

/// CPython's `sum()` of floats (3.12+): Neumaier's compensated sum, the
/// compensation added at the end when it is finite and not zero.
pub fn py_sum<I: Iterator<Item = f64>>(xs: I, compensated: bool) -> f64 {
    let mut f = 0.0f64;
    let mut c = 0.0f64;
    for x in xs {
        if !compensated {
            f += x;                 // CPython before 3.12
            continue;
        }
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

// Python's min/max keep the FIRST of equal values and compare with `<`/`>`.
#[inline]
fn py_min2(a: f64, b: f64) -> f64 {
    if b < a { b } else { a }
}
#[inline]
fn py_max2(a: f64, b: f64) -> f64 {
    if b > a { b } else { a }
}
#[inline]
fn py_min3(a: f64, b: f64, c: f64) -> f64 {
    py_min2(py_min2(a, b), c)
}
#[inline]
fn py_max3(a: f64, b: f64, c: f64) -> f64 {
    py_max2(py_max2(a, b), c)
}

#[inline]
fn sign(x: f64) -> i8 {
    (x > 0.0) as i8 - (x < 0.0) as i8
}

#[inline]
#[allow(clippy::too_many_arguments)]
fn point_in_triangle(ax: f64, ay: f64, bx: f64, by: f64, cx: f64, cy: f64, px: f64, py: f64) -> bool {
    (cx - px) * (ay - py) - (ax - px) * (cy - py) >= 0.0
        && (ax - px) * (by - py) - (bx - px) * (ay - py) >= 0.0
        && (bx - px) * (cy - py) - (cx - px) * (by - py) >= 0.0
}

/// `core.triangulate.earcut`.
pub fn earcut(pts: &[(f64, f64)], holes: &[usize]) -> Vec<[usize; 3]> {
    let mut r = Ring { n: Vec::with_capacity(pts.len() * 2) };
    let outer_len = if holes.is_empty() { pts.len() } else { holes[0] };
    let idxs: Vec<usize> = (0..outer_len).collect();
    let mut tris = Vec::new();
    let Some(mut outer) = r.build_ring(pts, &idxs, true) else { return tris };
    if r.n[outer].next == r.n[outer].prev {
        return tris;
    }
    if !holes.is_empty() {
        let mut queue = Vec::new();
        for k in 0..holes.len() {
            let start = holes[k];
            let end = if k + 1 < holes.len() { holes[k + 1] } else { pts.len() };
            let idxs: Vec<usize> = (start..end).collect();
            let h = r.build_ring(pts, &idxs, false).expect("a hole has corners");
            if h == r.n[h].next {
                r.n[h].steiner = true;
            }
            queue.push(r.leftmost(h));
        }
        queue.sort_by(|&a, &b| {
            (r.n[a].x, r.n[a].y)
                .partial_cmp(&(r.n[b].x, r.n[b].y))
                .unwrap_or(std::cmp::Ordering::Equal)
        });
        for hole in queue {
            if let Some(bridge) = r.find_hole_bridge(hole, outer) {
                let br = r.split_polygon(bridge, hole);
                let brn = r.n[br].next;
                r.filter_points(br, Some(brn));
                let bn = r.n[bridge].next;
                outer = r.filter_points(bridge, Some(bn));
            }
        }
    }
    r.earcut_linked(Some(outer), &mut tris, 0);
    tris
}

/// `core.triangulate.is_convex`.
fn is_convex(poly: &[(f64, f64)]) -> bool {
    let n = poly.len();
    if n < 4 {
        return true;
    }
    let mut s = 0i8;
    for i in 0..n {
        let (o, a, b) = (poly[i], poly[(i + 1) % n], poly[(i + 2) % n]);
        let cr = (a.0 - o.0) * (b.1 - o.1) - (a.1 - o.1) * (b.0 - o.0);
        if cr > 1e-9 {
            if s < 0 {
                return false;
            }
            s = 1;
        } else if cr < -1e-9 {
            if s > 0 {
                return false;
            }
            s = -1;
        }
    }
    true
}

/// One face's geometry. `rings`: its rings as vertex indices, outer first.
pub struct FaceGeom {
    pub normal: V3,
    pub ln: f32,
    pub centroid: Option<V3>,
    /// Corner vertex indices, three per triangle.
    pub tris: Vec<[u32; 3]>,
    /// The viewport's `_normal_of` (Qt's `normalized()`, not a division)
    /// and `_tris_of` (triangulated with it): what textured and two-side
    /// faces are drawn with. `None`: the same triangles as `tris`.
    pub unit: V3,
    pub tris_unit: Option<Vec<[u32; 3]>>,
}

fn triangles(pos: &[V3], rings: &[&[u32]], normal: V3, h: Hypot) -> Vec<[u32; 3]> {
    let outer = rings[0];
    let m = outer.len();
    let holes: Vec<&[u32]> = rings[1..].iter().copied().filter(|r| r.len() >= 3).collect();
    let (u, v) = plane_axes(normal, h);
    let origin = pos[outer[0] as usize];
    let proj = |i: u32| {
        let rel = pos[i as usize].sub(origin);
        (rel.dot(u) as f64, rel.dot(v) as f64)
    };
    let mut tris = Vec::new();
    if holes.is_empty() {
        let poly: Vec<(f64, f64)> = outer.iter().map(|&i| proj(i)).collect();
        if is_convex(&poly) {
            for k in 1..m - 1 {
                tris.push([outer[0], outer[k], outer[k + 1]]);
            }
            return tris;
        }
    }
    let mut master: Vec<u32> = outer.to_vec();
    let mut pts: Vec<(f64, f64)> = outer.iter().map(|&i| proj(i)).collect();
    let mut hole_idx = Vec::new();
    for hr in &holes {
        hole_idx.push(master.len());
        master.extend_from_slice(hr);
        pts.extend(hr.iter().map(|&i| proj(i)));
    }
    for t in earcut(&pts, &hole_idx) {
        tris.push([master[t[0]], master[t[1]], master[t[2]]]);
    }
    tris
}

pub fn face_geometry(pos: &[V3], rings: &[&[u32]], h: Hypot, compensated: bool) -> FaceGeom {
    let outer = rings[0];
    if outer.len() < 3 {
        return FaceGeom { normal: V3(0.0, 0.0, 1.0), ln: 0.0, centroid: None, tris: Vec::new(),
                          unit: V3(0.0, 0.0, 1.0), tris_unit: None };
    }
    // Face._newell: doubles over the float32 positions.
    let (mut nx, mut ny, mut nz) = (0.0f64, 0.0f64, 0.0f64);
    let m = outer.len();
    for k in 0..m {
        let c = pos[outer[k] as usize];
        let n = pos[outer[(k + 1) % m] as usize];
        let (x0, y0, z0) = (c.0 as f64, c.1 as f64, c.2 as f64);
        let (x1, y1, z1) = (n.0 as f64, n.1 as f64, n.2 as f64);
        nx += (y0 - y1) * (z0 + z1);
        ny += (z0 - z1) * (x0 + x1);
        nz += (x0 - x1) * (y0 + y1);
    }
    let n_raw = V3(nx as f32, ny as f32, nz as f32);
    let ln = length(n_raw, h);
    let normal = if (ln as f64) > 1e-9 { n_raw.div(ln) } else { V3(0.0, 0.0, 1.0) };
    let unit = if (ln as f64) > 1e-9 { normalized(n_raw, h) } else { V3(0.0, 0.0, 1.0) };
    // Face.centroid: Python's sum() over the loop (compensated, as
    // CPython 3.12+ adds floats), / count.
    let cnt = m as f64;
    let cx = py_sum(outer.iter().map(|&i| pos[i as usize].0 as f64), compensated);
    let cy = py_sum(outer.iter().map(|&i| pos[i as usize].1 as f64), compensated);
    let cz = py_sum(outer.iter().map(|&i| pos[i as usize].2 as f64), compensated);
    let centroid = V3((cx / cnt) as f32, (cy / cnt) as f32, (cz / cnt) as f32);
    // core.triangulate.triangulate(loop, holes, normal), and again with
    // the unit normal when that is another vector.
    let tris = triangles(pos, rings, normal, h);
    let same = unit.0.to_bits() == normal.0.to_bits() && unit.1.to_bits() == normal.1.to_bits()
        && unit.2.to_bits() == normal.2.to_bits();
    let tris_unit = if same { None } else { Some(triangles(pos, rings, unit, h)) };
    FaceGeom { normal, ln, centroid: Some(centroid), tris, unit, tris_unit }
}
