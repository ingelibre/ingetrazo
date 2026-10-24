// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! The hidden-line kernels of `core/hlr.py`, line by line:
//! `visible_spans` (with `_interval_from_linear`) and `_surface_at`, plus
//! the candidate filters `hlr_drawing` applies before calling them.
//!
//! What is new is only HOW candidates are found: a uniform 2D grid over the
//! triangles' bounding boxes instead of testing every triangle for every
//! edge. The grid returns a superset; the exact Python filter then runs on
//! it, so the candidate SET is identical. Order does not matter: the
//! occluded intervals are sorted before they are merged, as in Python.

use rayon::prelude::*;

const T_EPS: f64 = 1e-6; // core.hlr._T_EPS

/// One thread's working buffers: a visit stamp per triangle (so the grid's
/// candidates come out once each) and two index lists.
struct Scratch {
    stamp: Vec<u32>,
    tick: u32,
    pool: Vec<u32>,
    idx: Vec<u32>,
}

impl Scratch {
    fn new(n: usize) -> Self {
        Scratch { stamp: vec![0u32; n], tick: 0, pool: Vec::new(), idx: Vec::new() }
    }

    fn next_tick(&mut self) -> u32 {
        self.tick = self.tick.wrapping_add(1);
        if self.tick == 0 {
            self.stamp.iter_mut().for_each(|s| *s = 0);
            self.tick = 1;
        }
        self.tick
    }
}

pub struct Occluders {
    tris: Vec<[[f64; 3]; 3]>,
    tmin: Vec<[f64; 2]>,
    tmax: Vec<[f64; 2]>,
    tzmin: Vec<f64>,
    grid: Grid,
}

struct Grid {
    x0: f64,
    y0: f64,
    cs: f64,
    nx: usize,
    ny: usize,
    cells: Vec<Vec<u32>>,
    always: Vec<u32>, // triangles too big (or not finite) for the grid
}

impl Grid {
    fn cell_range(&self, lo: [f64; 2], hi: [f64; 2]) -> (usize, usize, usize, usize) {
        let ix = |x: f64| -> usize {
            let f = ((x - self.x0) / self.cs).floor();
            if !(f > 0.0) {
                0
            } else if f >= self.nx as f64 {
                self.nx - 1
            } else {
                f as usize
            }
        };
        let iy = |y: f64| -> usize {
            let f = ((y - self.y0) / self.cs).floor();
            if !(f > 0.0) {
                0
            } else if f >= self.ny as f64 {
                self.ny - 1
            } else {
                f as usize
            }
        };
        (ix(lo[0]), ix(hi[0]), iy(lo[1]), iy(hi[1]))
    }
}

const MAX_CELLS_PER_TRI: usize = 4096;

impl Occluders {
    pub fn new(tris: Vec<[[f64; 3]; 3]>) -> Self {
        let n = tris.len();
        let mut tmin = Vec::with_capacity(n);
        let mut tmax = Vec::with_capacity(n);
        let mut tzmin = Vec::with_capacity(n);
        // numpy's min/max over the 3 vertices (axis=1)
        for v in &tris {
            tmin.push([
                v[0][0].min(v[1][0]).min(v[2][0]),
                v[0][1].min(v[1][1]).min(v[2][1]),
            ]);
            tmax.push([
                v[0][0].max(v[1][0]).max(v[2][0]),
                v[0][1].max(v[1][1]).max(v[2][1]),
            ]);
            tzmin.push(v[0][2].min(v[1][2]).min(v[2][2]));
        }
        let grid = Self::build_grid(&tmin, &tmax);
        Occluders { tris, tmin, tmax, tzmin, grid }
    }

    fn build_grid(tmin: &[[f64; 2]], tmax: &[[f64; 2]]) -> Grid {
        let n = tmin.len();
        let (mut x0, mut y0, mut x1, mut y1) = (f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY);
        for i in 0..n {
            if tmin[i][0].is_finite() && tmax[i][0].is_finite() && tmin[i][1].is_finite() && tmax[i][1].is_finite() {
                x0 = x0.min(tmin[i][0]);
                y0 = y0.min(tmin[i][1]);
                x1 = x1.max(tmax[i][0]);
                y1 = y1.max(tmax[i][1]);
            }
        }
        if !(x1 >= x0) || !(y1 >= y0) {
            return Grid { x0: 0.0, y0: 0.0, cs: 1.0, nx: 1, ny: 1, cells: vec![Vec::new()], always: (0..n as u32).collect() };
        }
        let w = (x1 - x0).max(1e-12);
        let h = (y1 - y0).max(1e-12);
        // about two triangles per cell on average, at most 1024 per side
        let target = ((n as f64) / 2.0).max(1.0);
        let mut cs = ((w * h) / target).sqrt();
        if !(cs > 0.0) {
            cs = w.max(h);
        }
        let nx = ((w / cs).ceil() as usize).clamp(1, 1024);
        let ny = ((h / cs).ceil() as usize).clamp(1, 1024);
        let cs = (w / nx as f64).max(h / ny as f64);
        let mut grid = Grid { x0, y0, cs, nx, ny, cells: vec![Vec::new(); nx * ny], always: Vec::new() };
        for i in 0..n {
            let ok = tmin[i][0].is_finite() && tmax[i][0].is_finite() && tmin[i][1].is_finite() && tmax[i][1].is_finite();
            if !ok {
                grid.always.push(i as u32);
                continue;
            }
            let (cx0, cx1, cy0, cy1) = grid.cell_range(tmin[i], tmax[i]);
            if (cx1 - cx0 + 1) * (cy1 - cy0 + 1) > MAX_CELLS_PER_TRI {
                grid.always.push(i as u32);
                continue;
            }
            for cy in cy0..=cy1 {
                for cx in cx0..=cx1 {
                    grid.cells[cy * nx + cx].push(i as u32);
                }
            }
        }
        grid
    }

    /// Every triangle whose grid cells meet the box, each once (superset).
    fn gather(&self, lo: [f64; 2], hi: [f64; 2], stamp: &mut Vec<u32>, tick: u32, out: &mut Vec<u32>) {
        out.clear();
        out.extend_from_slice(&self.grid.always);
        for &i in &self.grid.always {
            stamp[i as usize] = tick;
        }
        let (cx0, cx1, cy0, cy1) = self.grid.cell_range(lo, hi);
        for cy in cy0..=cy1 {
            for cx in cx0..=cx1 {
                for &i in &self.grid.cells[cy * self.grid.nx + cx] {
                    if stamp[i as usize] != tick {
                        stamp[i as usize] = tick;
                        out.push(i);
                    }
                }
            }
        }
    }

    /// Every edge's visible spans. Edges are independent, so they are
    /// shared out over the cores in blocks; the blocks come back in order,
    /// so the result is the same as one edge after the other.
    pub fn visible_spans_all(&self, edges: &[([f64; 3], [f64; 3])], eps: f64) -> (Vec<i64>, Vec<(f64, f64)>) {
        let n = self.tris.len();
        let blocks: Vec<(Vec<usize>, Vec<(f64, f64)>)> = edges
            .par_chunks(256)
            .map_init(
                || Scratch::new(n),
                |s, chunk| {
                    let mut counts = Vec::with_capacity(chunk.len());
                    let mut spans = Vec::new();
                    for (a, b) in chunk {
                        let before = spans.len();
                        self.edge_spans(*a, *b, eps, s, &mut spans);
                        counts.push(spans.len() - before);
                    }
                    (counts, spans)
                },
            )
            .collect();
        let mut offsets = Vec::with_capacity(edges.len() + 1);
        let mut spans: Vec<(f64, f64)> = Vec::new();
        offsets.push(0i64);
        for (counts, sp) in blocks {
            for c in counts {
                let last = *offsets.last().unwrap();
                offsets.push(last + c as i64);
            }
            spans.extend(sp);
        }
        (offsets, spans)
    }

    /// One edge: hlr_drawing's candidate filter, exactly, then visible_spans.
    fn edge_spans(&self, a: [f64; 3], b: [f64; 3], eps: f64, s: &mut Scratch, out: &mut Vec<(f64, f64)>) {
        let a2 = [a[0], a[1]];
        let b2 = [b[0], b[1]];
        let (az, bz) = (a[2], b[2]);
        if self.tris.is_empty() {
            out.push((0.0, 1.0));
            return;
        }
        let lo = [a2[0].min(b2[0]) - 1e-9, a2[1].min(b2[1]) - 1e-9];
        let hi = [a2[0].max(b2[0]) + 1e-9, a2[1].max(b2[1]) + 1e-9];
        let zmax = if az >= bz { az } else { bz }; // Python max(az, bz)
        let tick = s.next_tick();
        self.gather(lo, hi, &mut s.stamp, tick, &mut s.pool);
        s.idx.clear();
        for &i in &s.pool {
            let i = i as usize;
            let away = self.tmax[i][0] < lo[0] || self.tmin[i][0] > hi[0] || self.tmax[i][1] < lo[1] || self.tmin[i][1] > hi[1];
            if !away && self.tzmin[i] < zmax {
                s.idx.push(i as u32);
            }
        }
        if s.idx.is_empty() {
            out.push((0.0, 1.0));
        } else {
            s.idx.sort_unstable(); // Python visits candidates in index order
            visible_spans(a2, b2, az, bz, &self.tris, &s.idx, eps, out);
        }
    }

    /// hlr_drawing's Profiles test: true = the span is an outline.
    pub fn profile_flags(&self, probes: &[([f64; 2], [f64; 2], f64)], delta: f64, ptol: f64) -> Vec<bool> {
        let n = self.tris.len();
        probes
            .par_chunks(256)
            .map_init(
                || Scratch::new(n),
                |s, chunk| chunk.iter().map(|(mid, nrm, zm)| self.probe(*mid, *nrm, *zm, delta, ptol, s)).collect::<Vec<bool>>(),
            )
            .flatten_iter()
            .collect()
    }

    fn probe(&self, mid: [f64; 2], nrm: [f64; 2], zm: f64, delta: f64, ptol: f64, s: &mut Scratch) -> bool {
        let lo2 = [mid[0] - delta * 1.001, mid[1] - delta * 1.001];
        let hi2 = [mid[0] + delta * 1.001, mid[1] + delta * 1.001];
        let zlim = zm + ptol;
        s.idx.clear();
        if !self.tris.is_empty() {
            let tick = s.next_tick();
            self.gather(lo2, hi2, &mut s.stamp, tick, &mut s.pool);
            for &i in &s.pool {
                let i = i as usize;
                let away = self.tmax[i][0] < lo2[0] || self.tmin[i][0] > hi2[0] || self.tmax[i][1] < lo2[1] || self.tmin[i][1] > hi2[1];
                if !away && self.tzmin[i] <= zlim {
                    s.idx.push(i as u32);
                }
            }
        }
        let p1 = [mid[0] + nrm[0], mid[1] + nrm[1]];
        let p2 = [mid[0] - nrm[0], mid[1] - nrm[1]];
        let s1 = self.surface_at(p1, zm, &s.idx, ptol);
        let s2 = self.surface_at(p2, zm, &s.idx, ptol);
        !s1 || !s2
    }

    /// core.hlr._surface_at over the candidate triangles ``cand``.
    fn surface_at(&self, p: [f64; 2], depth: f64, cand: &[u32], tol: f64) -> bool {
        let lim = depth + tol;
        for &i in cand {
            let v = &self.tris[i as usize];
            let a = [v[0][0], v[0][1]];
            let v0 = [v[1][0] - a[0], v[1][1] - a[1]];
            let v1 = [v[2][0] - a[0], v[2][1] - a[1]];
            let v2 = [p[0] - a[0], p[1] - a[1]];
            let den0 = v0[0] * v1[1] - v1[0] * v0[1];
            let ok = den0.abs() > 1e-18;
            let den = if ok { den0 } else { 1.0 };
            let l1 = (v2[0] * v1[1] - v1[0] * v2[1]) / den;
            let l2 = (v0[0] * v2[1] - v2[0] * v0[1]) / den;
            let l0 = 1.0 - l1 - l2;
            let inside = ok && l0 >= -1e-9 && l1 >= -1e-9 && l2 >= -1e-9;
            if !inside {
                continue;
            }
            let z = l0 * v[0][2] + l1 * v[1][2] + l2 * v[2][2];
            if z <= lim {
                return true;
            }
        }
        false
    }
}

/// core.hlr._interval_from_linear: c0 + c1·t ≥ 0 over [0,1].
#[inline]
fn interval_from_linear(c0: f64, c1: f64) -> Option<(f64, f64)> {
    if c1.abs() < 1e-15 {
        return if c0 >= 0.0 { Some((0.0, 1.0)) } else { None };
    }
    let t = -c0 / c1;
    if c1 > 0.0 {
        Some((t, 1.0))
    } else {
        Some((0.0, t))
    }
}

/// Solve the 3×3 system m·x = z by LU with partial pivoting, as LAPACK's
/// dgesv (numpy.linalg.solve) does. None where it reports a singular matrix.
fn solve3(m: [[f64; 3]; 3], z: [f64; 3]) -> Option<[f64; 3]> {
    let mut a = m;
    let mut piv = [0usize, 1, 2];
    for j in 0..3 {
        // pivot: first row with the largest |a[i][j]| (idamax)
        let mut p = j;
        let mut best = a[j][j].abs();
        for i in (j + 1)..3 {
            if a[i][j].abs() > best {
                best = a[i][j].abs();
                p = i;
            }
        }
        if a[p][j] == 0.0 {
            return None;
        }
        if p != j {
            a.swap(p, j);
            piv.swap(p, j);
        }
        let r = 1.0 / a[j][j];
        for i in (j + 1)..3 {
            a[i][j] *= r;
        }
        for i in (j + 1)..3 {
            for k in (j + 1)..3 {
                a[i][k] -= a[i][j] * a[j][k];
            }
        }
    }
    let mut y = [z[piv[0]], z[piv[1]], z[piv[2]]];
    for i in 1..3 {
        for k in 0..i {
            y[i] -= a[i][k] * y[k];
        }
    }
    for i in (0..3).rev() {
        for k in (i + 1)..3 {
            y[i] -= a[i][k] * y[k];
        }
        y[i] /= a[i][i];
    }
    Some(y)
}

/// core.hlr.visible_spans for one edge against the candidates ``idx``.
fn visible_spans(
    a2: [f64; 2],
    b2: [f64; 2],
    az: f64,
    bz: f64,
    tris: &[[[f64; 3]; 3]],
    idx: &[u32],
    eps: f64,
    out: &mut Vec<(f64, f64)>,
) {
    let d2 = [b2[0] - a2[0], b2[1] - a2[1]];
    let mut occluded: Vec<(f64, f64)> = Vec::new();
    for &k in idx {
        let t = &tris[k as usize];
        let mut v = [[t[0][0], t[0][1]], [t[1][0], t[1][1]], [t[2][0], t[2][1]]];
        let mut z = [t[0][2], t[1][2], t[2][2]];
        let area2 = (v[1][0] - v[0][0]) * (v[2][1] - v[0][1]) - (v[1][1] - v[0][1]) * (v[2][0] - v[0][0]);
        if area2.abs() < 1e-14 {
            continue; // edge-on: its own edges draw it
        }
        if area2 < 0.0 {
            v.reverse(); // enforce CCW
            z.reverse();
        }
        let (mut lo, mut hi) = (0.0f64, 1.0f64);
        let mut dead = false;
        for i in 0..3 {
            let n = (i + 1) % 3;
            let ex = v[n][0] - v[i][0];
            let ey = v[n][1] - v[i][1];
            let c0 = ex * (a2[1] - v[i][1]) - ey * (a2[0] - v[i][0]);
            let c1 = ex * d2[1] - ey * d2[0];
            match interval_from_linear(c0, c1) {
                None => {
                    dead = true;
                    break;
                }
                Some((l, h)) => {
                    lo = py_max(lo, l);
                    hi = py_min(hi, h);
                    if lo >= hi {
                        dead = true;
                        break;
                    }
                }
            }
        }
        if dead {
            continue;
        }
        let m = [[v[0][0], v[0][1], 1.0], [v[1][0], v[1][1], 1.0], [v[2][0], v[2][1], 1.0]];
        let abg = match solve3(m, z) {
            Some(x) => x,
            None => continue,
        };
        let c0 = az - (abg[0] * a2[0] + abg[1] * a2[1] + abg[2]) - eps;
        let c1 = (bz - az) - (abg[0] * d2[0] + abg[1] * d2[1]);
        let iv = match interval_from_linear(c0, c1) {
            Some(x) => x,
            None => continue,
        };
        lo = py_max(lo, iv.0);
        hi = py_min(hi, iv.1);
        if lo < hi {
            occluded.push((lo, hi));
        }
    }
    if occluded.is_empty() {
        out.push((0.0, 1.0));
        return;
    }
    // Python's tuple sort
    occluded.sort_by(|p, q| p.0.partial_cmp(&q.0).unwrap_or(std::cmp::Ordering::Equal).then(p.1.partial_cmp(&q.1).unwrap_or(std::cmp::Ordering::Equal)));
    let mut merged: Vec<(f64, f64)> = vec![occluded[0]];
    for &(lo, hi) in &occluded[1..] {
        let last = merged.last_mut().unwrap();
        if lo <= last.1 + T_EPS {
            last.1 = py_max(last.1, hi);
        } else {
            merged.push((lo, hi));
        }
    }
    let mut cursor = 0.0f64;
    for &(lo, hi) in &merged {
        if lo > cursor + T_EPS {
            out.push((cursor, py_min(lo, 1.0)));
        }
        cursor = py_max(cursor, hi);
        if cursor >= 1.0 {
            break;
        }
    }
    if cursor < 1.0 - T_EPS {
        out.push((cursor, 1.0));
    }
}

/// Python's built-in max(a, b): a unless b is greater (NaN stays as a).
#[inline]
fn py_max(a: f64, b: f64) -> f64 {
    if b > a { b } else { a }
}

/// Python's built-in min(a, b): a unless b is smaller.
#[inline]
fn py_min(a: f64, b: f64) -> f64 {
    if b < a { b } else { a }
}
