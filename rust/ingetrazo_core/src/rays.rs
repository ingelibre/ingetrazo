// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! The pick index's ray pass: `views.viewport._moller_trumbore` and the
//! per-entity reduction `Viewport._ray_hits` runs on its answer (~4 ms a
//! slow Line frame in the Plaza's 9 674-face group, 19-11).
//!
//! NumPy computes the 3-term dot products of that pass in three ways —
//! `einsum("ij,ij->i")`, `q @ d` (a BLAS gemv, or a dot for one row) and
//! `norm` (`add.reduce` of the squares, a BLAS dot for the ray) — and each
//! may sum in its own order, with or without fused multiply-add, depending
//! on the CPU and the BLAS build. So every dot product here takes a MODE,
//! one of the 48 ways three products can be summed (which pair first,
//! whether each addition is fused, from +0 or not), and the caller picks
//! the modes that reproduce this NumPy on a probe at the first use (see
//! `views.viewport._mt_native`). The cross products are NumPy's formula,
//! unfused, so they are the same bits on every machine.

use numpy::{PyArray1, PyReadonlyArray1, PyReadonlyArray2, PyReadwriteArray1};
use pyo3::prelude::*;
use rayon::prelude::*;

const DET_MIN: f64 = 1e-6;
const T_MIN: f64 = 1e-6;
/// From this many rows a pass is split over the thread pool. Each row's
/// answer is its own, so the split cannot change it.
const PAR_MIN: usize = 16384;
/// How many ways `dot3` knows to sum three products.
const MODES: u8 = 48;

/// The orders of the three products, as `(i, j, k)`: `i` and `j` are summed
/// first, `k` last.
const PERMS: [[usize; 3]; 6] = [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]];

/// The dot product of `a` and `b` summed as `mode` says: `mode % 24 / 4`
/// picks the order (`PERMS`), `mode % 4` the fusing — 0: `(pi + pj) + pk`;
/// 1: `fma(ak, bk, pi + pj)`; 2: `fma(aj, bj, pi) + pk`;
/// 3: `fma(ak, bk, fma(aj, bj, pi))`, with `pi = ai * bi` rounded — and
/// from 24 on the sum starts from +0 as a SIMD or BLAS accumulator does,
/// which only turns a -0 result into +0 (NumPy's einsum here, 19-11).
#[inline(always)]
fn dot3(a: [f64; 3], b: [f64; 3], mode: u8) -> f64 {
    let [i, j, k] = PERMS[(mode % 24 / 4) as usize];
    let s = match mode % 4 {
        0 => (a[i] * b[i] + a[j] * b[j]) + a[k] * b[k],
        1 => a[k].mul_add(b[k], a[i] * b[i] + a[j] * b[j]),
        2 => a[j].mul_add(b[j], a[i] * b[i]) + a[k] * b[k],
        _ => a[k].mul_add(b[k], a[j].mul_add(b[j], a[i] * b[i])),
    };
    if mode >= 24 { s + 0.0 } else { s }
}

/// `np.cross` of two 3-vectors, as NumPy computes it (one multiply each,
/// then the subtraction: never fused).
#[inline(always)]
fn cross(a: [f64; 3], b: [f64; 3]) -> [f64; 3] {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

/// How NumPy sums each kind of dot product on this machine (see the module
/// note): `es` einsum, `mm` the gemv of `q @ d` over two rows or more,
/// `mm1` the same over a single row, `dd` `d.dot(d)` of the ray, `sq`
/// `add.reduce` of a row's squares.
#[derive(Clone, Copy)]
pub struct Modes {
    pub es: u8,
    pub mm: u8,
    pub mm1: u8,
    pub dd: u8,
    pub sq: u8,
    /// Every mode read at run time, even one built in (for the tests).
    pub dynamic: bool,
}

impl Modes {
    fn of(m: (u8, u8, u8, u8, u8)) -> PyResult<Self> {
        let ok = |x: u8| x < MODES;
        if !(ok(m.0) && ok(m.1) && ok(m.2) && ok(m.3) && ok(m.4)) {
            return Err(pyo3::exceptions::PyValueError::new_err("modes"));
        }
        Ok(Modes { es: m.0, mm: m.1, mm1: m.2, dd: m.3, sq: m.4, dynamic: false })
    }
}

/// `_moller_trumbore` for one triangle: `(t, hit)`, `t` as NumPy leaves it
/// for every row (also those not hit: `inv` is 0 there). `ES` and `MM` are
/// the modes of the einsums and of `q @ d` for this pass (`MM` hangs on
/// the pass's row count); `DYN` is the mode a mode of `DYNAMIC` stands
/// for. `dnorm` is the ray's `np.linalg.norm`, worked out once.
#[inline(always)]
#[allow(clippy::too_many_arguments)]
fn mt_one<const ES: u8, const MM: u8>(o: [f64; 3], d: [f64; 3], v0: [f64; 3], e1: [f64; 3],
                                      e2: [f64; 3], m: &Modes, mm: u8, dnorm: f64) -> (f64, bool) {
    let es = if ES == DYNAMIC { m.es } else { ES };
    let mm = if MM == DYNAMIC { mm } else { MM };
    let p = cross(d, e2);
    let det = dot3(e1, p, es);
    let mut ok = det.abs() > DET_MIN;
    if !ok && det != 0.0 {
        // The small-det reading of #1294: against the triangle's size.
        let c = cross(e1, e2);
        let scale = dot3(c, c, m.sq).sqrt() * dnorm;
        ok = det.abs() > DET_MIN * scale;
    }
    let inv = if ok { 1.0 / det } else { 0.0 };
    let s = [o[0] - v0[0], o[1] - v0[1], o[2] - v0[2]];
    let u = dot3(s, p, es) * inv;
    let q = cross(s, e1);
    let v = dot3(q, d, mm) * inv;
    let t = dot3(e2, q, es) * inv;
    let hit = ok && u >= 0.0 && u <= 1.0 && v >= 0.0 && u + v <= 1.0 && t > T_MIN;
    (t, hit)
}

/// A mode read at run time (any of them, a little slower: the order of
/// the sum is looked up on each product).
const DYNAMIC: u8 = 255;

/// The triangles of one pass: `(v0, e1, e2)` (N, 3) and which of their
/// rows the pass reads, in order.
struct Tris<'a> {
    v0: &'a [f64],
    e1: &'a [f64],
    e2: &'a [f64],
    rows: Vec<usize>,
}

#[inline(always)]
fn row3(a: &[f64], r: usize) -> [f64; 3] {
    [a[3 * r], a[3 * r + 1], a[3 * r + 2]]
}

/// `mt_one` over every row of `tr` from `lo` on, into `out`.
#[inline(always)]
fn mt_block<const ES: u8, const MM: u8>(o: [f64; 3], d: [f64; 3], tr: &Tris, m: &Modes,
                                        lo: usize, out: &mut [(f64, bool)]) {
    let mm = if tr.rows.len() == 1 { m.mm1 } else { m.mm };
    let dnorm = dot3(d, d, m.dd).sqrt();
    for (k, slot) in out.iter_mut().enumerate() {
        let r = tr.rows[lo + k];
        *slot = mt_one::<ES, MM>(o, d, row3(tr.v0, r), row3(tr.e1, r), row3(tr.e2, r), m, mm,
                                 dnorm);
    }
}

#[cfg(target_arch = "x86_64")]
#[target_feature(enable = "fma")]
unsafe fn mt_block_fma<const ES: u8, const MM: u8>(o: [f64; 3], d: [f64; 3], tr: &Tris,
                                                   m: &Modes, lo: usize,
                                                   out: &mut [(f64, bool)]) {
    // The same code where `mul_add` is one instruction instead of a call
    // into the C library (the same correctly rounded result either way).
    mt_block::<ES, MM>(o, d, tr, m, lo, out)
}

fn mt_block_with<const ES: u8, const MM: u8>(o: [f64; 3], d: [f64; 3], tr: &Tris, m: &Modes,
                                             lo: usize, out: &mut [(f64, bool)]) {
    #[cfg(target_arch = "x86_64")]
    {
        if std::arch::is_x86_feature_detected!("fma") {
            // SAFETY: the CPU has just been found to have FMA.
            unsafe { mt_block_fma::<ES, MM>(o, d, tr, m, lo, out) };
            return;
        }
    }
    mt_block::<ES, MM>(o, d, tr, m, lo, out)
}

/// `mt_block` with the pass's modes built in where they are among those
/// NumPy was seen to use (einsum from +0 in either order; the gemv's and
/// the one-row dot's fused orders) — 2-3x faster than looking each order
/// up (19-11) — and read at run time otherwise.
fn mt_block_any(o: [f64; 3], d: [f64; 3], tr: &Tris, m: &Modes, lo: usize, out: &mut [(f64, bool)]) {
    let mm = if tr.rows.len() == 1 { m.mm1 } else { m.mm };
    macro_rules! pick {
        ($($es:literal, $mm:literal);*) => {
            match (if m.dynamic { DYNAMIC } else { m.es }, mm) {
                $(($es, $mm) => mt_block_with::<$es, $mm>(o, d, tr, m, lo, out),)*
                _ => mt_block_with::<DYNAMIC, DYNAMIC>(o, d, tr, m, lo, out),
            }
        };
    }
    pick!(28, 35; 28, 27; 4, 35; 4, 27; 28, 11; 28, 3; 4, 11; 4, 3; 24, 35; 24, 27; 0, 0; 0, 24;
          24, 24)
}

/// `(t, hit)` of every row of `tr`, in its order.
fn mt_all(o: [f64; 3], d: [f64; 3], tr: &Tris, m: &Modes) -> Vec<(f64, bool)> {
    let n = tr.rows.len();
    let mut out = vec![(0.0, false); n];
    if n >= PAR_MIN {
        out.par_chunks_mut(4096).enumerate()
            .for_each(|(c, chunk)| mt_block_any(o, d, tr, m, c * 4096, chunk));
    } else {
        mt_block_any(o, d, tr, m, 0, &mut out);
    }
    out
}

fn flat3<'a>(a: &'a PyReadonlyArray2<'_, f64>, what: &str) -> PyResult<&'a [f64]> {
    let v = a.as_array();
    if v.ndim() != 2 || v.shape()[1] != 3 {
        return Err(pyo3::exceptions::PyValueError::new_err(format!("{what}: expected (N, 3)")));
    }
    a.as_slice().map_err(|_| pyo3::exceptions::PyValueError::new_err(format!("{what}: not contiguous")))
}

/// The rows a pass reads: `rows` when given, else the `(start, count)`
/// pairs of `ranges` (K, 2) when given, else all `n`.
fn rows_of(n: usize, rows: Option<PyReadonlyArray1<'_, i64>>,
           ranges: Option<PyReadonlyArray2<'_, i64>>) -> PyResult<Vec<usize>> {
    let bad = || pyo3::exceptions::PyValueError::new_err("rows out of range");
    if let Some(r) = rows {
        return r.as_array().iter()
            .map(|&i| if i >= 0 && (i as usize) < n { Ok(i as usize) } else { Err(bad()) })
            .collect();
    }
    if let Some(g) = ranges {
        let g = g.as_array();
        if g.shape()[1] != 2 {
            return Err(pyo3::exceptions::PyValueError::new_err("ranges: expected (K, 2)"));
        }
        let mut out = Vec::new();
        for k in 0..g.shape()[0] {
            let (s, c) = (g[[k, 0]], g[[k, 1]]);
            if s < 0 || c < 0 || (s + c) as usize > n {
                return Err(bad());
            }
            out.extend(s as usize..(s + c) as usize);
        }
        return Ok(out);
    }
    Ok((0..n).collect())
}

fn tris<'a>(v0: &'a PyReadonlyArray2<'_, f64>, e1: &'a PyReadonlyArray2<'_, f64>,
            e2: &'a PyReadonlyArray2<'_, f64>, rows: Option<PyReadonlyArray1<'_, i64>>,
            ranges: Option<PyReadonlyArray2<'_, i64>>) -> PyResult<Tris<'a>> {
    let (a, b, c) = (flat3(v0, "v0")?, flat3(e1, "e1")?, flat3(e2, "e2")?);
    if a.len() != b.len() || a.len() != c.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("v0, e1, e2: lengths differ"));
    }
    Ok(Tris { v0: a, e1: b, e2: c, rows: rows_of(a.len() / 3, rows, ranges)? })
}

/// The dot product of each row of `a` and `b` (N, 3) summed as `mode`
/// says: what `_mt_native` holds against NumPy's to pick the modes.
#[pyfunction]
pub fn ray_dot3_probe<'py>(py: Python<'py>, a: PyReadonlyArray2<'py, f64>,
                           b: PyReadonlyArray2<'py, f64>, mode: u8)
    -> PyResult<Bound<'py, PyArray1<f64>>> {
    let (x, y) = (flat3(&a, "a")?, flat3(&b, "b")?);
    if x.len() != y.len() || mode >= MODES {
        return Err(pyo3::exceptions::PyValueError::new_err("a, b, mode"));
    }
    let out: Vec<f64> = (0..x.len() / 3).map(|r| dot3(row3(x, r), row3(y, r), mode)).collect();
    Ok(PyArray1::from_vec(py, out))
}

/// `views.viewport._moller_trumbore(o, d, v0, e1, e2)` with the modes of
/// this NumPy: `(t, hit)` of every row, the same bits. `dynamic` reads
/// the modes at run time even where they are built in (for the tests).
#[pyfunction]
#[pyo3(signature = (o, d, v0, e1, e2, modes, dynamic=false))]
#[allow(clippy::too_many_arguments)]
pub fn ray_tris<'py>(py: Python<'py>, o: (f64, f64, f64), d: (f64, f64, f64),
                     v0: PyReadonlyArray2<'py, f64>, e1: PyReadonlyArray2<'py, f64>,
                     e2: PyReadonlyArray2<'py, f64>, modes: (u8, u8, u8, u8, u8),
                     dynamic: bool)
    -> PyResult<(Bound<'py, PyArray1<f64>>, Bound<'py, PyArray1<bool>>)> {
    let mut m = Modes::of(modes)?;
    m.dynamic = dynamic;
    let tr = tris(&v0, &e1, &e2, None, None)?;
    let (o, d) = ([o.0, o.1, o.2], [d.0, d.1, d.2]);
    let out = py.detach(|| mt_all(o, d, &tr, &m));
    let (t, hit): (Vec<f64>, Vec<bool>) = out.into_iter().unzip();
    Ok((PyArray1::from_vec(py, t), PyArray1::from_vec(py, hit)))
}

/// One pass of `Viewport._ray_hits`'s loop: `_moller_trumbore` over the
/// rows of `(v0, e1, e2)` that `rows` or `ranges` name (all when neither,
/// in that order: the row count picks `q @ d`'s mode as NumPy's would),
/// the hits whose entity `te[row] + ent_off` passes `ent_mask`, and then
/// `np.minimum.at(face_t, entity, t)` over them when `face_t` is given, or
/// the least of `best` and their t when it is not. Returns that least (or
/// `best` with `face_t`). A minimum takes no rounding, so the order the
/// hits come in cannot change it.
#[pyfunction]
#[pyo3(signature = (o, d, v0, e1, e2, te, ent_off, ent_mask, modes, rows=None, ranges=None,
                    face_t=None, best=f64::INFINITY))]
#[allow(clippy::too_many_arguments)]
pub fn ray_face_min<'py>(py: Python<'py>, o: (f64, f64, f64), d: (f64, f64, f64),
                         v0: PyReadonlyArray2<'py, f64>, e1: PyReadonlyArray2<'py, f64>,
                         e2: PyReadonlyArray2<'py, f64>, te: PyReadonlyArray1<'py, i64>,
                         ent_off: i64, ent_mask: PyReadonlyArray1<'py, bool>,
                         modes: (u8, u8, u8, u8, u8),
                         rows: Option<PyReadonlyArray1<'py, i64>>,
                         ranges: Option<PyReadonlyArray2<'py, i64>>,
                         face_t: Option<PyReadwriteArray1<'py, f64>>, best: f64)
    -> PyResult<f64> {
    let m = Modes::of(modes)?;
    let tr = tris(&v0, &e1, &e2, rows, ranges)?;
    let te = te.as_array();
    if te.len() * 3 != tr.v0.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("te: length"));
    }
    let mask = ent_mask.as_array();
    let (o, d) = ([o.0, o.1, o.2], [d.0, d.1, d.2]);
    let out = py.detach(|| mt_all(o, d, &tr, &m));
    // The entity of every row, refused here where NumPy's `ent_mask[te]`
    // would refuse it or wrap it (a negative one): Python decides those.
    let mut hits: Vec<(usize, f64)> = Vec::new();
    for (k, &(t, hit)) in out.iter().enumerate() {
        let e = te[tr.rows[k]].checked_add(ent_off)
            .filter(|&e| e >= 0 && (e as usize) < mask.len())
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("entity out of range"))?;
        if hit && mask[e as usize] {
            hits.push((e as usize, t));
        }
    }
    match face_t {
        Some(mut ft) => {
            let mut ft = ft.as_array_mut();
            if hits.iter().any(|&(e, _)| e >= ft.len()) {
                return Err(pyo3::exceptions::PyValueError::new_err("face_t: length"));
            }
            for (e, t) in hits {
                // np.minimum: the nearer; t is never NaN on a hit.
                if t < ft[e] {
                    ft[e] = t;
                }
            }
            Ok(best)
        }
        None => {
            let mut b = best;
            let mut tm = f64::INFINITY;
            for &(_, t) in &hits {
                if t < tm {
                    tm = t;
                }
            }
            if !hits.is_empty() && tm < b {
                b = tm;
            }
            Ok(b)
        }
    }
}
