// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! Ear-clipping triangulation of a polygon with holes —
//! `core.triangulate.earcut`, the Mapbox earcut as that module ports it
//! (no z-order hashing), step for step: the same ring built the same way
//! round, the same ears found in the same order, the same recoveries from
//! degeneracies, so the triangles come out identical, index for index.
//! The nodes of the doubly linked ring live in an arena, `prev` and `next`
//! being indices into it.

const NONE: usize = usize::MAX;

struct Node {
    i: usize,
    x: f64,
    y: f64,
    prev: usize,
    next: usize,
    steiner: bool,
}

pub struct Earcut<'a> {
    pts: &'a [[f64; 2]],
    nodes: Vec<Node>,
    pub triangles: Vec<[usize; 3]>,
}

impl<'a> Earcut<'a> {
    fn new(pts: &'a [[f64; 2]]) -> Earcut<'a> {
        Earcut { pts, nodes: Vec::with_capacity(pts.len() + 16), triangles: Vec::new() }
    }

    fn insert_node(&mut self, i: usize, x: f64, y: f64, last: usize) -> usize {
        let id = self.nodes.len();
        if last == NONE {
            self.nodes.push(Node { i, x, y, prev: id, next: id, steiner: false });
        } else {
            let next = self.nodes[last].next;
            self.nodes.push(Node { i, x, y, prev: last, next, steiner: false });
            self.nodes[next].prev = id;
            self.nodes[last].next = id;
        }
        id
    }

    fn remove_node(&mut self, n: usize) {
        let (p, q) = (self.nodes[n].prev, self.nodes[n].next);
        self.nodes[q].prev = p;
        self.nodes[p].next = q;
    }

    fn signed_area_idx(&self, idxs: &[usize]) -> f64 {
        let mut s = 0.0;
        let n = idxs.len();
        for k in 0..n {
            let a = self.pts[idxs[k]];
            let b = self.pts[idxs[(k + 1) % n]];
            s += (b[0] - a[0]) * (a[1] + b[1]);
        }
        s
    }

    fn build_ring(&mut self, idxs: &[usize], want_ccw: bool) -> usize {
        // signed_area_idx > 0 means clockwise here.
        let clockwise = self.signed_area_idx(idxs) > 0.0;
        let mut last = NONE;
        if clockwise != want_ccw {
            for &i in idxs {
                last = self.insert_node(i, self.pts[i][0], self.pts[i][1], last);
            }
        } else {
            for &i in idxs.iter().rev() {
                last = self.insert_node(i, self.pts[i][0], self.pts[i][1], last);
            }
        }
        if last != NONE && self.equals(last, self.nodes[last].next) {
            self.remove_node(last);
            last = self.nodes[last].next;
        }
        last
    }

    #[inline]
    fn area(&self, p: usize, q: usize, r: usize) -> f64 {
        let (p, q, r) = (&self.nodes[p], &self.nodes[q], &self.nodes[r]);
        (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y)
    }

    #[inline]
    fn equals(&self, a: usize, b: usize) -> bool {
        self.nodes[a].x == self.nodes[b].x && self.nodes[a].y == self.nodes[b].y
    }

    fn filter_points(&mut self, start: usize, end: usize) -> usize {
        if start == NONE {
            return start;
        }
        let mut end = if end == NONE { start } else { end };
        let mut p = start;
        loop {
            let mut again = false;
            let (pp, pn) = (self.nodes[p].prev, self.nodes[p].next);
            if !self.nodes[p].steiner && (self.equals(p, pn) || self.area(pp, p, pn) == 0.0) {
                self.remove_node(p);
                p = self.nodes[p].prev;
                end = p;
                if p == self.nodes[p].next {
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
        let (a, b, c) = (self.nodes[ear].prev, ear, self.nodes[ear].next);
        if self.area(a, b, c) >= 0.0 {
            return false;
        }
        let (ax, ay) = (self.nodes[a].x, self.nodes[a].y);
        let (bx, by) = (self.nodes[b].x, self.nodes[b].y);
        let (cx, cy) = (self.nodes[c].x, self.nodes[c].y);
        let x0 = ax.min(bx).min(cx);
        let y0 = ay.min(by).min(cy);
        let x1 = ax.max(bx).max(cx);
        let y1 = ay.max(by).max(cy);
        let mut p = self.nodes[c].next;
        while p != a {
            let (px, py) = (self.nodes[p].x, self.nodes[p].y);
            if x0 <= px && px <= x1 && y0 <= py && py <= y1
                && point_in_triangle(ax, ay, bx, by, cx, cy, px, py)
                && self.area(self.nodes[p].prev, p, self.nodes[p].next) >= 0.0
            {
                return false;
            }
            p = self.nodes[p].next;
        }
        true
    }

    fn earcut_linked(&mut self, ear: usize, pass: u8) {
        if ear == NONE {
            return;
        }
        let mut ear = ear;
        let mut stop = ear;
        while self.nodes[ear].prev != self.nodes[ear].next {
            let prev = self.nodes[ear].prev;
            let nxt = self.nodes[ear].next;
            if self.is_ear(ear) {
                self.triangles.push([self.nodes[prev].i, self.nodes[ear].i, self.nodes[nxt].i]);
                self.remove_node(ear);
                ear = self.nodes[nxt].next;
                stop = ear;
                continue;
            }
            ear = nxt;
            if ear == stop {
                // No ear found — recover from degeneracies.
                if pass == 0 {
                    let f = self.filter_points(ear, NONE);
                    self.earcut_linked(f, 1);
                } else if pass == 1 {
                    let f = self.filter_points(ear, NONE);
                    let c = self.cure_local_intersections(f);
                    self.earcut_linked(c, 2);
                } else if pass == 2 {
                    self.split_earcut(ear);
                }
                return;
            }
        }
    }

    fn cure_local_intersections(&mut self, start: usize) -> usize {
        let mut start = start;
        let mut p = start;
        loop {
            let a = self.nodes[p].prev;
            let pn = self.nodes[p].next;
            let b = self.nodes[pn].next;
            if !self.equals(a, b)
                && self.intersects(a, p, pn, b)
                && self.locally_inside(a, b)
                && self.locally_inside(b, a)
            {
                self.triangles.push([self.nodes[a].i, self.nodes[p].i, self.nodes[b].i]);
                self.remove_node(p);
                self.remove_node(self.nodes[p].next);
                p = b;
                start = b;
            }
            p = self.nodes[p].next;
            if p == start {
                break;
            }
        }
        self.filter_points(p, NONE)
    }

    fn split_earcut(&mut self, start: usize) {
        let mut a = start;
        loop {
            let mut b = self.nodes[self.nodes[a].next].next;
            while b != self.nodes[a].prev {
                if self.nodes[a].i != self.nodes[b].i && self.is_valid_diagonal(a, b) {
                    let c = self.split_polygon(a, b);
                    let an = self.nodes[a].next;
                    let a2 = self.filter_points(a, an);
                    let cn = self.nodes[c].next;
                    let c2 = self.filter_points(c, cn);
                    self.earcut_linked(a2, 0);
                    self.earcut_linked(c2, 0);
                    return;
                }
                b = self.nodes[b].next;
            }
            a = self.nodes[a].next;
            if a == start {
                break;
            }
        }
    }

    fn eliminate_holes(&mut self, hole_indices: &[usize], outer: usize) -> usize {
        let mut queue: Vec<usize> = Vec::with_capacity(hole_indices.len());
        let total = self.pts.len();
        for k in 0..hole_indices.len() {
            let start = hole_indices[k];
            let end = if k + 1 < hole_indices.len() { hole_indices[k + 1] } else { total };
            let idxs: Vec<usize> = (start..end).collect();
            let h = self.build_ring(&idxs, false);
            if h == self.nodes[h].next {
                self.nodes[h].steiner = true;
            }
            queue.push(self.get_leftmost(h));
        }
        queue.sort_by(|&m, &n| {
            let (a, b) = (&self.nodes[m], &self.nodes[n]);
            (a.x, a.y).partial_cmp(&(b.x, b.y)).unwrap_or(std::cmp::Ordering::Equal)
        });
        let mut outer = outer;
        for hole in queue {
            outer = self.eliminate_hole(hole, outer);
        }
        outer
    }

    fn eliminate_hole(&mut self, hole: usize, outer: usize) -> usize {
        let bridge = self.find_hole_bridge(hole, outer);
        if bridge == NONE {
            return outer;
        }
        let bridge_reverse = self.split_polygon(bridge, hole);
        let brn = self.nodes[bridge_reverse].next;
        self.filter_points(bridge_reverse, brn);
        let bn = self.nodes[bridge].next;
        self.filter_points(bridge, bn)
    }

    fn get_leftmost(&self, start: usize) -> usize {
        let mut p = start;
        let mut leftmost = start;
        loop {
            let (px, py) = (self.nodes[p].x, self.nodes[p].y);
            let (lx, ly) = (self.nodes[leftmost].x, self.nodes[leftmost].y);
            if px < lx || (px == lx && py < ly) {
                leftmost = p;
            }
            p = self.nodes[p].next;
            if p == start {
                break;
            }
        }
        leftmost
    }

    fn find_hole_bridge(&self, hole: usize, outer: usize) -> usize {
        let mut p = outer;
        let (hx, hy) = (self.nodes[hole].x, self.nodes[hole].y);
        let mut qx = f64::NEG_INFINITY;
        let mut m = NONE;
        // The edge whose crossing with a +x ray from the hole is closest.
        loop {
            let pn = self.nodes[p].next;
            let (px, py) = (self.nodes[p].x, self.nodes[p].y);
            let (nx, ny) = (self.nodes[pn].x, self.nodes[pn].y);
            if hy <= py && hy >= ny && ny != py {
                let x = px + (hy - py) * (nx - px) / (ny - py);
                if hx >= x && x > qx {
                    qx = x;
                    m = if px < nx { p } else { pn };
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
        if m == NONE {
            return NONE;
        }
        // A reflex vertex inside the candidate triangle, closer in angle.
        let stop = m;
        let (mx, my) = (self.nodes[m].x, self.nodes[m].y);
        let mut tan_min = f64::INFINITY;
        p = m;
        loop {
            let (px, py) = (self.nodes[p].x, self.nodes[p].y);
            if hx >= px && px >= mx && hx != px
                && point_in_triangle(
                    if hy < my { hx } else { qx }, hy,
                    mx, my,
                    if hy < my { qx } else { hx }, hy,
                    px, py)
            {
                let tan = (hy - py).abs() / (hx - px);
                if self.locally_inside(p, hole)
                    && (tan < tan_min
                        || (tan == tan_min
                            && (px > self.nodes[m].x
                                || (px == self.nodes[m].x && self.sector_contains(m, p)))))
                {
                    m = p;
                    tan_min = tan;
                }
            }
            p = self.nodes[p].next;
            if p == stop {
                break;
            }
        }
        m
    }

    fn sector_contains(&self, m: usize, p: usize) -> bool {
        self.area(self.nodes[m].prev, m, self.nodes[p].prev) < 0.0
            && self.area(self.nodes[p].next, m, self.nodes[m].next) < 0.0
    }

    fn locally_inside(&self, a: usize, b: usize) -> bool {
        let (ap, an) = (self.nodes[a].prev, self.nodes[a].next);
        if self.area(ap, a, an) < 0.0 {
            self.area(a, b, an) >= 0.0 && self.area(a, ap, b) >= 0.0
        } else {
            self.area(a, b, ap) < 0.0 || self.area(a, an, b) < 0.0
        }
    }

    fn middle_inside(&self, a: usize, b: usize) -> bool {
        let mut p = a;
        let mut inside = false;
        let px = (self.nodes[a].x + self.nodes[b].x) / 2.0;
        let py = (self.nodes[a].y + self.nodes[b].y) / 2.0;
        loop {
            let pn = self.nodes[p].next;
            let (x0, y0) = (self.nodes[p].x, self.nodes[p].y);
            let (x1, y1) = (self.nodes[pn].x, self.nodes[pn].y);
            if ((y0 > py) != (y1 > py)) && y1 != y0 && (px < (x1 - x0) * (py - y0) / (y1 - y0) + x0) {
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
        let (ap, an) = (self.nodes[a].prev, self.nodes[a].next);
        let (bp, bn) = (self.nodes[b].prev, self.nodes[b].next);
        self.nodes[an].i != self.nodes[b].i
            && self.nodes[ap].i != self.nodes[b].i
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
        let (p, q, r) = (&self.nodes[p], &self.nodes[q], &self.nodes[r]);
        p.x.max(r.x) >= q.x && q.x >= p.x.min(r.x) && p.y.max(r.y) >= q.y && q.y >= p.y.min(r.y)
    }

    fn intersects(&self, p1: usize, q1: usize, p2: usize, q2: usize) -> bool {
        let o1 = sign(self.area(p1, q1, p2));
        let o2 = sign(self.area(p1, q1, q2));
        let o3 = sign(self.area(p2, q2, p1));
        let o4 = sign(self.area(p2, q2, q1));
        if o1 != o2 && o3 != o4 {
            return true;
        }
        if o1 == 0 && self.on_segment(p1, p2, q1) {
            return true;
        }
        if o2 == 0 && self.on_segment(p1, q2, q1) {
            return true;
        }
        if o3 == 0 && self.on_segment(p2, p1, q2) {
            return true;
        }
        if o4 == 0 && self.on_segment(p2, q1, q2) {
            return true;
        }
        false
    }

    fn intersects_polygon(&self, a: usize, b: usize) -> bool {
        let mut p = a;
        let (ai, bi) = (self.nodes[a].i, self.nodes[b].i);
        loop {
            let pn = self.nodes[p].next;
            if self.nodes[p].i != ai && self.nodes[pn].i != ai
                && self.nodes[p].i != bi && self.nodes[pn].i != bi
                && self.intersects(p, pn, a, b)
            {
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
        let a2 = self.nodes.len();
        self.nodes.push(Node { i: self.nodes[a].i, x: self.nodes[a].x, y: self.nodes[a].y, prev: NONE, next: NONE, steiner: false });
        let b2 = self.nodes.len();
        self.nodes.push(Node { i: self.nodes[b].i, x: self.nodes[b].x, y: self.nodes[b].y, prev: NONE, next: NONE, steiner: false });
        let an = self.nodes[a].next;
        let bp = self.nodes[b].prev;
        self.nodes[a].next = b;
        self.nodes[b].prev = a;
        self.nodes[a2].next = an;
        self.nodes[an].prev = a2;
        self.nodes[b2].next = a2;
        self.nodes[a2].prev = b2;
        self.nodes[bp].next = b2;
        self.nodes[b2].prev = bp;
        b2
    }
}

#[inline]
fn sign(x: f64) -> i32 {
    (x > 0.0) as i32 - (x < 0.0) as i32
}

#[inline]
#[allow(clippy::too_many_arguments)]
fn point_in_triangle(ax: f64, ay: f64, bx: f64, by: f64, cx: f64, cy: f64, px: f64, py: f64) -> bool {
    (cx - px) * (ay - py) - (ax - px) * (cy - py) >= 0.0
        && (ax - px) * (by - py) - (bx - px) * (ay - py) >= 0.0
        && (bx - px) * (cy - py) - (cx - px) * (by - py) >= 0.0
}

/// `core.triangulate.earcut`: the triangles of `pts` (the outer ring, then
/// each hole's points, `hole_indices` where each hole starts) as index
/// triples into `pts`.
pub fn earcut(pts: &[[f64; 2]], hole_indices: &[usize]) -> Vec<[usize; 3]> {
    let mut e = Earcut::new(pts);
    let has_holes = !hole_indices.is_empty();
    let outer_len = if has_holes { hole_indices[0] } else { pts.len() };
    let idxs: Vec<usize> = (0..outer_len).collect();
    let mut outer = e.build_ring(&idxs, true);
    if outer == NONE || e.nodes[outer].next == e.nodes[outer].prev {
        return Vec::new();
    }
    if has_holes {
        outer = e.eliminate_holes(hole_indices, outer);
    }
    e.earcut_linked(outer, 0);
    e.triangles
}
