// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! Which axis-aligned boxes touch: `core.intersect._touching` for every
//! pair at once. The test itself is Python's, operation for operation
//! (`lo_a <= hi_b + eps && lo_b <= hi_a + eps` on all three axes, in f64);
//! a grid over x/y only finds the candidates faster, so the answer is the
//! same pairs in the same order (row-major: by i, then by j).

use rayon::prelude::*;

pub type Box3 = ([f64; 3], [f64; 3]);

#[inline]
fn touch(a: &Box3, b: &Box3, eps: f64) -> bool {
    (0..3).all(|k| a.0[k] <= b.1[k] + eps && b.0[k] <= a.1[k] + eps)
}

/// Cells a box may span before it is kept apart and tested against all.
const MAX_CELLS: i64 = 4096;

struct Grid {
    x0: f64,
    y0: f64,
    inv: f64,
    nx: i64,
    ny: i64,
    cells: Vec<Vec<u32>>,
    big: Vec<u32>,
}

impl Grid {
    fn range(&self, lo: f64, hi: f64, o: f64, n: i64) -> (i64, i64) {
        let a = ((lo - o) * self.inv).floor() as i64;
        let b = ((hi - o) * self.inv).floor() as i64;
        (a.clamp(0, n - 1), b.clamp(0, n - 1))
    }

    fn new(boxes: &[Box3]) -> Grid {
        let mut x0 = f64::INFINITY;
        let mut y0 = f64::INFINITY;
        let mut x1 = f64::NEG_INFINITY;
        let mut y1 = f64::NEG_INFINITY;
        let mut sizes: Vec<f64> = Vec::with_capacity(boxes.len());
        for b in boxes {
            x0 = x0.min(b.0[0]);
            y0 = y0.min(b.0[1]);
            x1 = x1.max(b.1[0]);
            y1 = y1.max(b.1[1]);
            sizes.push((b.1[0] - b.0[0]).max(b.1[1] - b.0[1]));
        }
        // Cell ≈ the median box: most boxes land in 1–4 cells.
        sizes.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let med = sizes.get(sizes.len() / 2).copied().unwrap_or(1.0);
        let span = (x1 - x0).max(y1 - y0).max(1e-9);
        let mut cell = med.max(span / 2048.0).max(1e-9);
        if !cell.is_finite() {
            cell = 1.0;
        }
        let inv = 1.0 / cell;
        let nx = (((x1 - x0) * inv).floor() as i64 + 1).max(1);
        let ny = (((y1 - y0) * inv).floor() as i64 + 1).max(1);
        let mut g = Grid { x0, y0, inv, nx, ny, cells: vec![Vec::new(); (nx * ny) as usize], big: Vec::new() };
        for (j, b) in boxes.iter().enumerate() {
            let (ax, bx) = g.range(b.0[0], b.1[0], g.x0, g.nx);
            let (ay, by) = g.range(b.0[1], b.1[1], g.y0, g.ny);
            if (bx - ax + 1) * (by - ay + 1) > MAX_CELLS || !b.0[0].is_finite() || !b.1[0].is_finite()
                || !b.0[1].is_finite() || !b.1[1].is_finite()
            {
                g.big.push(j as u32);
                continue;
            }
            for y in ay..=by {
                for x in ax..=bx {
                    g.cells[(y * g.nx + x) as usize].push(j as u32);
                }
            }
        }
        g
    }

    /// Indices of every box of the grid that may touch `a` (a superset,
    /// unsorted, possibly repeated).
    fn candidates(&self, a: &Box3, eps: f64, out: &mut Vec<u32>, all: usize) -> bool {
        let lx = a.0[0] - eps;
        let hx = a.1[0] + eps;
        let ly = a.0[1] - eps;
        let hy = a.1[1] + eps;
        if !(lx.is_finite() && hx.is_finite() && ly.is_finite() && hy.is_finite()) {
            out.extend(0..all as u32);
            return true;
        }
        let (ax, bx) = self.range(lx, hx, self.x0, self.nx);
        let (ay, by) = self.range(ly, hy, self.y0, self.ny);
        if (bx - ax + 1) * (by - ay + 1) > MAX_CELLS {
            out.extend(0..all as u32);
            return true;
        }
        for y in ay..=by {
            for x in ax..=bx {
                out.extend_from_slice(&self.cells[(y * self.nx + x) as usize]);
            }
        }
        out.extend_from_slice(&self.big);
        false
    }
}

/// Every `(i, j)` with box `a[i]` touching box `b[j]`, sorted by i then j;
/// `same` (the two lists are one): j > i only.
pub fn touching(a: &[Box3], b: &[Box3], same: bool, eps: f64) -> (Vec<i64>, Vec<i64>) {
    if a.is_empty() || b.is_empty() {
        return (Vec::new(), Vec::new());
    }
    let grid = Grid::new(b);
    let rows: Vec<Vec<i64>> = a
        .par_iter()
        .enumerate()
        .map(|(i, ab)| {
            let mut cand = Vec::new();
            grid.candidates(ab, eps, &mut cand, b.len());
            cand.sort_unstable();
            cand.dedup();
            cand.into_iter()
                .filter(|&j| (!same || j as usize > i) && touch(ab, &b[j as usize], eps))
                .map(|j| j as i64)
                .collect()
        })
        .collect();
    let n: usize = rows.iter().map(|r| r.len()).sum();
    let mut ii = Vec::with_capacity(n);
    let mut jj = Vec::with_capacity(n);
    for (i, r) in rows.into_iter().enumerate() {
        for j in r {
            ii.push(i as i64);
            jj.push(j);
        }
    }
    (ii, jj)
}
