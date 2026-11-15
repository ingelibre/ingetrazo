// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! Each face of a view cut down to what nothing in front of it covers —
//! `core.vista_caras._visible_parts`, the SVG export's faces.
//!
//! The same rules as the Python pass: where an opaque face B overlaps A in
//! the drawing, B hides A on the side of the line where their nearness
//! planes cross; coplanar faces that overlap, the earlier wins; a
//! see-through face hides nothing. The regions are even-odd, as there,
//! and the booleans are `i_overlay`'s on an integer grid instead of
//! manifold3d's. One overlay per face — the face less the union of its
//! covers — and the faces in parallel.

use std::collections::HashMap;

use i_overlay::core::fill_rule::FillRule;
use i_overlay::core::overlay::{Overlay, ShapeType};
use i_overlay::core::overlay_rule::OverlayRule;
use i_overlay::i_float::int::point::IntPoint;
use rayon::prelude::*;

pub type Ring = Vec<[f64; 2]>;

/// A region on the integer grid as `i_overlay` hands it back: shapes, each
/// an outer contour and its holes.
type Shapes = Vec<Vec<Vec<IntPoint<i64>>>>;

pub struct Face {
    pub rings: Vec<Ring>,
    /// The nearness plane `(a, b, c)`: nearer where `a·x + b·y + c` is bigger.
    pub near: [f64; 3],
    pub opaque: bool,
}

/// Cells a face may cover before it counts as big (tested against every
/// face, as the ground or a roof would fill most cells anyway).
const BIG_CELLS: i64 = 64;

/// Integer units per unit of the drawing, by default: see `Setup::new`.
pub const GRID: f64 = 1e11;

/// How many of the biggest covers are tried first, on their own.
const HIDE_TRY: usize = 6;

/// How many covers are taken away at a time after that.
const COVER_BATCH: usize = 128;

/// Above this many covers a face is cut into quarters (`Setup::subtract`),
/// at most this many times over.
const SPLIT_AT: usize = 512;
const SPLIT_DEPTH: u32 = 10;

/// One cover of a face: its contours wound for a non-zero fill, its box.
struct Cover {
    contours: Vec<Vec<IntPoint<i64>>>,
    lo: [f64; 2],
    hi: [f64; 2],
    size: f64,
}

fn bbox<'a>(pts: impl Iterator<Item = &'a [f64; 2]>) -> ([f64; 2], [f64; 2]) {
    let mut lo = [f64::INFINITY; 2];
    let mut hi = [f64::NEG_INFINITY; 2];
    for p in pts {
        lo[0] = lo[0].min(p[0]);
        lo[1] = lo[1].min(p[1]);
        hi[0] = hi[0].max(p[0]);
        hi[1] = hi[1].max(p[1]);
    }
    (lo, hi)
}

fn int_bbox(shapes: &Shapes) -> (IntPoint<i64>, IntPoint<i64>) {
    let mut lo = IntPoint::new(i64::MAX, i64::MAX);
    let mut hi = IntPoint::new(i64::MIN, i64::MIN);
    for p in shapes.iter().flatten().flatten() {
        lo.x = lo.x.min(p.x);
        lo.y = lo.y.min(p.y);
        hi.x = hi.x.max(p.x);
        hi.y = hi.y.max(p.y);
    }
    (lo, hi)
}

/// A face thinner than this (drawing units: a micrometre of a model in
/// metres) is a hair: nothing to fill, nothing hidden behind it.
const HAIR: f64 = 1e-6;

fn perimeter(r: &[[f64; 2]]) -> f64 {
    let n = r.len();
    (0..n).map(|k| {
        let m = (k + 1) % n;
        ((r[m][0] - r[k][0]).powi(2) + (r[m][1] - r[k][1]).powi(2)).sqrt()
    }).sum()
}

/// Twice the signed area of a ring (f64).
fn area2(r: &[[f64; 2]]) -> f64 {
    let n = r.len();
    let mut s = 0.0;
    for k in 0..n {
        let m = (k + 1) % n;
        s += r[k][0] * r[m][1] - r[m][0] * r[k][1];
    }
    s
}

/// The part of `ring` where `dq[0]·x + dq[1]·y + dq[2] > 0` — corner by
/// corner, as `_clip_half`.
fn clip_half(ring: &[[f64; 2]], dq: [f64; 3]) -> Ring {
    let n = ring.len();
    let v: Vec<f64> = ring.iter().map(|p| p[0] * dq[0] + p[1] * dq[1] + dq[2]).collect();
    let keep: Vec<bool> = v.iter().map(|&x| x > 0.0).collect();
    if keep.iter().all(|&k| k) {
        return ring.to_vec();
    }
    if !keep.iter().any(|&k| k) {
        return Vec::new();
    }
    let mut out = Vec::with_capacity(n + 2);
    for k in 0..n {
        let m = (k + 1) % n;
        if keep[k] {
            out.push(ring[k]);
        }
        if keep[k] != keep[m] {
            let t = v[k] / (v[k] - v[m]);
            out.push([
                ring[k][0] + (ring[m][0] - ring[k][0]) * t,
                ring[k][1] + (ring[m][1] - ring[k][1]) * t,
            ]);
        }
    }
    out
}

struct Grid {
    c_lo: Vec<[i64; 2]>,
    c_hi: Vec<[i64; 2]>,
    is_big: Vec<bool>,
    big: Vec<u32>,
    cells: HashMap<(i64, i64), Vec<u32>>,
    every: Vec<u32>,
}

impl Grid {
    fn new(lo: &[[f64; 2]], hi: &[[f64; 2]], opaque: &[bool]) -> Grid {
        let n = lo.len();
        let mut sides: Vec<f64> = (0..n)
            .map(|i| (hi[i][0] - lo[i][0]).max(hi[i][1] - lo[i][1]).max(0.0))
            .collect();
        sides.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));
        let side = if n == 0 { 0.0 } else { sides[n / 2] };
        let (mut x0, mut y0, mut x1, mut y1) = (f64::INFINITY, f64::INFINITY, f64::NEG_INFINITY, f64::NEG_INFINITY);
        for i in 0..n {
            x0 = x0.min(lo[i][0]);
            y0 = y0.min(lo[i][1]);
            x1 = x1.max(hi[i][0]);
            y1 = y1.max(hi[i][1]);
        }
        let whole = (x1 - x0).max(y1 - y0).max(1e-12);
        // About one face per cell: the median face's size, not finer than
        // a thousandth of the drawing.
        let cell = side.max(whole * 1e-3).max(1e-12);
        let at = |v: f64, o: f64| ((v - o) / cell).floor() as i64;
        let c_lo: Vec<[i64; 2]> = (0..n).map(|i| [at(lo[i][0], x0), at(lo[i][1], y0)]).collect();
        let c_hi: Vec<[i64; 2]> = (0..n).map(|i| [at(hi[i][0], x0), at(hi[i][1], y0)]).collect();
        let is_big: Vec<bool> = (0..n)
            .map(|i| (c_hi[i][0] - c_lo[i][0] + 1) * (c_hi[i][1] - c_lo[i][1] + 1) > BIG_CELLS)
            .collect();
        let mut big = Vec::new();
        let mut cells: HashMap<(i64, i64), Vec<u32>> = HashMap::new();
        let mut every = Vec::new();
        for j in 0..n {
            if !opaque[j] {
                continue;
            }
            every.push(j as u32);
            if is_big[j] {
                big.push(j as u32);
                continue;
            }
            for cx in c_lo[j][0]..=c_hi[j][0] {
                for cy in c_lo[j][1]..=c_hi[j][1] {
                    cells.entry((cx, cy)).or_default().push(j as u32);
                }
            }
        }
        Grid { c_lo, c_hi, is_big, big, cells, every }
    }

    fn test(&self, lo: &[[f64; 2]], hi: &[[f64; 2]], i: usize, cand: &[u32], out: &mut Vec<u32>) {
        let (a_lo, a_hi) = (lo[i], hi[i]);
        for &j in cand {
            let j_ = j as usize;
            if j_ != i
                && lo[j_][0] < a_hi[0]
                && hi[j_][0] > a_lo[0]
                && lo[j_][1] < a_hi[1]
                && hi[j_][1] > a_lo[1]
            {
                out.push(j);
            }
        }
    }

    /// The opaque faces, other than `i`, whose boxes overlap face `i`'s,
    /// in increasing order.
    fn overlapping(&self, lo: &[[f64; 2]], hi: &[[f64; 2]], i: usize) -> Vec<u32> {
        let mut out = Vec::new();
        if self.is_big[i] {
            self.test(lo, hi, i, &self.every, &mut out);
            return out;
        }
        self.test(lo, hi, i, &self.big, &mut out);
        for cx in self.c_lo[i][0]..=self.c_hi[i][0] {
            for cy in self.c_lo[i][1]..=self.c_hi[i][1] {
                if let Some(there) = self.cells.get(&(cx, cy)) {
                    self.test(lo, hi, i, there, &mut out);
                }
            }
        }
        out.sort_unstable();
        out.dedup();
        out
    }
}

/// Everything the pass needs, made once: the boxes, the grid, the scale
/// of the integer grid.
pub struct Setup<'a> {
    faces: &'a [Face],
    lo: Vec<[f64; 2]>,
    hi: Vec<[f64; 2]>,
    grid: Grid,
    span: f64,
    min_area: f64,
    scale: f64,
    area: Vec<f64>,
    /// Each face as a region of its own — its rings made even-odd, as the
    /// Python pass's ``_section`` made them: outer contours one way, holes
    /// the other, a self-crossing ring split at its crossings — on the
    /// integer grid, and the same back in the drawing's units.
    region: Vec<Shapes>,
    region_f: Vec<Vec<Ring>>,
}

impl<'a> Setup<'a> {
    /// `min_area`: rings smaller than this (in the drawing's units squared)
    /// are dropped, as the Python pass drops them. `units`: integer units
    /// per drawing unit (see `GRID`).
    pub fn new(faces: &'a [Face], min_area: f64, units: f64) -> Setup<'a> {
        let n = faces.len();
        let mut lo = vec![[f64::INFINITY; 2]; n];
        let mut hi = vec![[f64::NEG_INFINITY; 2]; n];
        let mut biggest = 0.0f64;
        for (i, f) in faces.iter().enumerate() {
            for r in &f.rings {
                for p in r {
                    lo[i][0] = lo[i][0].min(p[0]);
                    lo[i][1] = lo[i][1].min(p[1]);
                    hi[i][0] = hi[i][0].max(p[0]);
                    hi[i][1] = hi[i][1].max(p[1]);
                    biggest = biggest.max(p[0].abs()).max(p[1].abs());
                }
            }
        }
        let mut span = 1e-9f64;
        for i in 0..n {
            span = span.max(hi[i][0] - lo[i][0]).max(hi[i][1] - lo[i][1]);
        }
        // A hair — a face seen all but edge on: a cylinder's wall from
        // above is a few hundred points back and forth along one line,
        // 0.3 mm² over half a metre — shows nothing a drawing can hold and
        // hides as little; but its hundreds of segments lying over each
        // other took the booleans seconds, and a face under a few of them
        // twenty minutes. Below `HAIR` of thickness (twice the area over
        // the perimeter), or the least area kept, a face is nothing here.
        let area: Vec<f64> = faces
            .iter()
            .map(|f| {
                let a: f64 = f.rings.iter().map(|r| area2(r).abs() * 0.5).sum();
                let p: f64 = f.rings.iter().map(|r| perimeter(r)).sum();
                if a < min_area || 2.0 * a < HAIR * p { 0.0 } else { a }
            })
            .collect();
        let covers: Vec<bool> = (0..n).map(|i| faces[i].opaque && area[i] > 0.0).collect();
        let grid = Grid::new(&lo, &hi, &covers);
        // The grid manifold3d's booleans used in the Python pass (precision
        // 8 on millimetres: 1e-11 of the drawing's unit), so a sliver the
        // clipping's rounding leaves along a shared edge falls under the
        // least area kept, as it did there — at a micrometre, a hair along a
        // 6 m edge of a slab's hidden wall came out as a face. Never so fine
        // that the drawing leaves the 64-bit engine's safe range, with room
        // for the arithmetic on differences.
        let limit = (1u64 << 60) as f64 / (biggest.max(1e-12) * 4.0);
        let scale = units.min(limit);
        let inv = 1.0 / scale;
        // Oriented by the sign of its area, a ring that crosses itself (a
        // face seen as a bow tie) kept one lobe unfilled under the non-zero
        // rule and covered less than it does: 227 slivers of the plaza the
        // Python pass had not. Made even-odd once, every region is simple
        // and wound alike, and the unions and differences below are exact.
        let region: Vec<Shapes> = (0..n)
            .into_par_iter()
            .map(|i| {
                if area[i] <= 0.0 {
                    return Vec::new();
                }
                let mut ov = Overlay::<i64>::new(16);
                for r in &faces[i].rings {
                    let mut pts: Vec<IntPoint<i64>> = Vec::with_capacity(r.len());
                    for p in r {
                        let q = IntPoint::new((p[0] * scale).round() as i64, (p[1] * scale).round() as i64);
                        if pts.last().map_or(true, |l| *l != q) {
                            pts.push(q);
                        }
                    }
                    while pts.len() > 1 && pts[0] == *pts.last().unwrap() {
                        pts.pop();
                    }
                    if pts.len() >= 3 {
                        ov.add_contour(&pts, ShapeType::Subject);
                    }
                }
                ov.overlay(OverlayRule::Subject, FillRule::EvenOdd)
            })
            .collect();
        let region_f: Vec<Vec<Ring>> = region
            .iter()
            .map(|shapes| {
                shapes
                    .iter()
                    .flatten()
                    .map(|c| c.iter().map(|p| [p.x as f64 * inv, p.y as f64 * inv]).collect())
                    .collect()
            })
            .collect();
        Setup { faces, lo, hi, grid, span, min_area, scale, area, region, region_f }
    }

    fn to_int_pt(&self, p: [f64; 2]) -> IntPoint<i64> {
        IntPoint::new((p[0] * self.scale).round() as i64, (p[1] * self.scale).round() as i64)
    }

    /// A ring on the integer grid, without the points the rounding makes
    /// one — a corner repeated, a cut landing on a corner. A cover with a
    /// zero-length edge, in the dozens of a fan of slivers over one face,
    /// sent the booleans running away (a 0.08 m² kerb of the plaza under
    /// sixty 1.5 mm facets of a curved bench never finished); the Python
    /// pass made a region of every part, which drops them too.
    fn to_int(&self, ring: &[[f64; 2]]) -> Vec<IntPoint<i64>> {
        let mut out: Vec<IntPoint<i64>> = Vec::with_capacity(ring.len());
        for p in ring {
            let q = IntPoint::new((p[0] * self.scale).round() as i64, (p[1] * self.scale).round() as i64);
            if out.last().map_or(true, |l| *l != q) {
                out.push(q);
            }
        }
        while out.len() > 1 && out[0] == *out.last().unwrap() {
            out.pop();
        }
        out
    }

    /// Face `i` less what covers it: its visible rings (drawing units).
    fn one(&self, i: usize) -> Vec<Ring> {
        if self.area[i] <= 0.0 {
            return Vec::new();
        }
        let qa = self.faces[i].near;
        let (a_lo, a_hi) = (self.lo[i], self.hi[i]);
        // Nearness differences below this are "the same plane": a millionth
        // of the drawing's size.
        let tol = 1e-6 * 1.0f64.max(qa[2].abs()).max(qa[0].abs() * self.span).max(qa[1].abs() * self.span);
        let cx = [a_lo[0], a_hi[0], a_hi[0], a_lo[0]];
        let cy = [a_lo[1], a_lo[1], a_hi[1], a_hi[1]];
        // The covers: each one's contours, wound, with its box and its box's
        // area — the biggest are tried first, so what is hidden is found
        // hidden by the roof alone and what shows loses most at once.
        let mut covers: Vec<Cover> = Vec::new();
        for j in self.grid.overlapping(&self.lo, &self.hi, i) {
            let j = j as usize;
            let fb = &self.faces[j];
            let dq = [fb.near[0] - qa[0], fb.near[1] - qa[1], fb.near[2] - qa[2]];
            let mut same = true;
            let mut behind = true;
            let mut front = true;
            for c in 0..4 {
                let at = cx[c] * dq[0] + cy[c] * dq[1] + dq[2];
                same &= at.abs() <= tol;
                behind &= at <= tol;
                front &= at > tol;
            }
            // 0: B hides nothing of A here; 1: B covers A whole where they
            // overlap; 2: B passes in front of part of A.
            let kind = if same {
                if j > i { 0 } else { 1 }
            } else if behind {
                0
            } else if front {
                1
            } else {
                2
            };
            if kind == 0 {
                continue;
            }
            if kind == 1 {
                // B whole: its region as made, wound already.
                let contours: Vec<Vec<IntPoint<i64>>> = self.region[j].iter().flatten().cloned().collect();
                if contours.is_empty() {
                    continue;
                }
                covers.push(Cover { contours, lo: self.lo[j], hi: self.hi[j],
                                    size: (self.hi[j][0] - self.lo[j][0]) * (self.hi[j][1] - self.lo[j][1]) });
                continue;
            }
            // The part of B nearer than A: each contour of B's region cut
            // to one side of the line — a simple contour stays simple and
            // keeps its winding, a hole's piece lies within its outer's. A
            // neighbour sharing an edge clips to a sliver of no area along
            // it: nothing to take away.
            let part: Vec<Ring> = self.region_f[j]
                .iter()
                .map(|r| clip_half(r, dq))
                .filter(|c| c.len() >= 3 && area2(c).abs() * 0.5 >= self.min_area)
                .collect();
            if part.is_empty() {
                continue;
            }
            let (lo, hi) = bbox(part.iter().flatten());
            let contours: Vec<Vec<IntPoint<i64>>> =
                part.iter().map(|r| self.to_int(r)).filter(|c| c.len() >= 3).collect();
            if contours.is_empty() {
                continue;
            }
            covers.push(Cover { contours, lo, hi, size: (hi[0] - lo[0]) * (hi[1] - lo[1]) });
        }
        covers.sort_by(|a, b| b.size.partial_cmp(&a.size).unwrap_or(std::cmp::Ordering::Equal));
        let refs: Vec<&Cover> = covers.iter().collect();
        let visible = self.subtract(self.region[i].clone(), &refs, 0);
        let inv = 1.0 / self.scale;
        let mut out = Vec::new();
        for shape in visible {
            for contour in shape {
                let ring: Ring = contour.iter().map(|p| [p.x as f64 * inv, p.y as f64 * inv]).collect();
                if ring.len() >= 3 && area2(&ring).abs() * 0.5 >= self.min_area {
                    out.push(ring);
                }
            }
        }
        out
    }

    /// `visible` less `covers` (biggest first). Under many covers — the
    /// ground of a whole house seen from above, under 690 000 faces — the
    /// region is cut into quarters, each taking away only the covers over
    /// it, and the pieces are joined again at the end: the one region less
    /// thousands of batches, on a region that grew holes with each, took
    /// 210 s for that one face; quarter by quarter it is a few seconds.
    fn subtract(&self, visible: Shapes, covers: &[&Cover], depth: u32) -> Shapes {
        if covers.len() <= SPLIT_AT || depth >= SPLIT_DEPTH {
            return self.subtract_batches(visible, covers);
        }
        // The biggest few first, on the whole: a roof takes the house at once.
        let head = HIDE_TRY.min(covers.len());
        let visible = self.subtract_batches(visible, &covers[..head]);
        let rest = &covers[head..];
        if visible.is_empty() {
            return visible;
        }
        let (lo, hi) = int_bbox(&visible);
        if hi.x - lo.x < 4 || hi.y - lo.y < 4 {
            return self.subtract_batches(visible, rest);
        }
        let mx = lo.x + (hi.x - lo.x) / 2;
        let my = lo.y + (hi.y - lo.y) / 2;
        let quads = [(lo.x, lo.y, mx, my), (mx, lo.y, hi.x, my),
                     (lo.x, my, mx, hi.y), (mx, my, hi.x, hi.y)];
        let pieces: Vec<Shapes> = quads
            .par_iter()
            .map(|&(x0, y0, x1, y1)| {
                let rect = vec![IntPoint::new(x0, y0), IntPoint::new(x1, y0),
                                IntPoint::new(x1, y1), IntPoint::new(x0, y1)];
                let mut ov = Overlay::<i64>::new(64);
                ov.add_source(&visible, ShapeType::Subject);
                ov.add_contour(&rect, ShapeType::Clip);
                let part = ov.overlay(OverlayRule::Intersect, FillRule::NonZero);
                if part.is_empty() {
                    return part;
                }
                let here: Vec<&Cover> = rest
                    .iter()
                    .copied()
                    .filter(|cv| {
                        let (a, b) = (self.to_int_pt(cv.lo), self.to_int_pt(cv.hi));
                        !(a.x > x1 || b.x < x0 || a.y > y1 || b.y < y0)
                    })
                    .collect();
                self.subtract(part, &here, depth + 1)
            })
            .collect();
        if depth > 0 {
            // Joined once, at the top.
            return pieces.into_iter().flatten().collect();
        }
        let mut ov = Overlay::<i64>::new(64);
        let mut any = false;
        for p in &pieces {
            if !p.is_empty() {
                ov.add_source(p, ShapeType::Subject);
                any = true;
            }
        }
        if !any {
            return Vec::new();
        }
        ov.overlay(OverlayRule::Union, FillRule::NonZero)
    }

    /// `visible` less `covers`, batch by batch: the few biggest first, on
    /// their own — a face under a roof is found hidden there, and the rest
    /// never joins a union — then the others, taken from what is left, no
    /// further once nothing is, and never a cover whose box misses what is
    /// left. One union of the thousands of faces over a plaza's ground
    /// crossed each other millions of times; the batches on a shrinking
    /// region do not.
    fn subtract_batches(&self, mut visible: Shapes, covers: &[&Cover]) -> Shapes {
        let mut at = 0usize;
        while at < covers.len() && !visible.is_empty() {
            let take = if at == 0 { HIDE_TRY } else { COVER_BATCH };
            let end = (at + take).min(covers.len());
            let (v_lo, v_hi) = int_bbox(&visible);
            let mut ov = Overlay::<i64>::new(64);
            ov.add_source(&visible, ShapeType::Subject);
            let mut any = false;
            for cv in &covers[at..end] {
                let (lo, hi) = (self.to_int_pt(cv.lo), self.to_int_pt(cv.hi));
                if lo.x > v_hi.x || hi.x < v_lo.x || lo.y > v_hi.y || hi.y < v_lo.y {
                    continue;
                }
                for c in &cv.contours {
                    ov.add_contour(c, ShapeType::Clip);
                }
                any = true;
            }
            if any {
                visible = ov.overlay(OverlayRule::Difference, FillRule::NonZero);
            }
            at = end;
        }
        visible
    }

    /// The visible rings of the faces `range`, worked out in parallel.
    pub fn chunk(&self, range: std::ops::Range<usize>) -> Vec<Vec<Ring>> {
        range.into_par_iter().map(|i| self.one(i)).collect()
    }
}
