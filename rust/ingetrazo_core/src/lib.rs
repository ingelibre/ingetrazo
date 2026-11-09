// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! Native kernels for IngeTrazo. Optional: `core/_native.py` imports this
//! module when it is built and falls back to the Python code otherwise.
//!
//! Every kernel here mirrors a Python function line by line — the same
//! arithmetic in the same order — so both give the same drawing. The only
//! thing a kernel may add is an index that finds the SAME candidates faster.

use numpy::{PyArray1, PyArray2, PyReadonlyArray2, PyReadonlyArray3, PyReadonlyArray1};
use pyo3::prelude::*;

mod boxes;
mod facegeom;
mod gltape;
mod hlr;
mod instances;
mod occlusion;
mod parity;
mod weld;

#[pymodule]
fn ingetrazo_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("SOURCE_HASH", env!("INGETRAZO_SOURCE_HASH"))?;
    m.add_class::<HlrOccluders>()?;
    m.add_function(wrap_pyfunction!(touching_boxes, m)?)?;
    m.add_class::<ParityTris>()?;
    m.add_function(wrap_pyfunction!(occlusion_span, m)?)?;
    m.add_function(wrap_pyfunction!(face_geometry, m)?)?;
    m.add_function(wrap_pyfunction!(qt_vector_probe, m)?)?;
    m.add_function(wrap_pyfunction!(weld_points, m)?)?;
    m.add_function(wrap_pyfunction!(boxes_near_px, m)?)?;
    m.add_function(wrap_pyfunction!(points_near_px, m)?)?;
    m.add_function(wrap_pyfunction!(segment_distances, m)?)?;
    m.add_function(wrap_pyfunction!(nearest_within, m)?)?;
    m.add_class::<GlReplay>()?;
    m.add_class::<InstanceProto>()?;
    m.add_class::<InstanceSet>()?;
    Ok(())
}

/// The triangles of one hidden-line pass, in camera space, with a 2D grid
/// over their bounding boxes. Built once per view by `core.hlr`.
#[pyclass(frozen)]
struct HlrOccluders {
    inner: hlr::Occluders,
}

#[pymethods]
impl HlrOccluders {
    /// ``tc``: (T,3,3) triangle vertices in camera space (x, y, depth).
    #[new]
    fn new(tc: PyReadonlyArray3<'_, f64>) -> PyResult<Self> {
        let tc = tc.as_array();
        let n = tc.shape()[0];
        let mut tris = Vec::with_capacity(n);
        for t in 0..n {
            let mut v = [[0.0f64; 3]; 3];
            for k in 0..3 {
                for c in 0..3 {
                    v[k][c] = tc[[t, k, c]];
                }
            }
            tris.push(v);
        }
        Ok(Self { inner: hlr::Occluders::new(tris) })
    }

    /// Visible t-intervals of every edge: core.hlr.visible_spans for each
    /// row, with the same candidate filter as hlr_drawing. ``a``/``b``:
    /// (E,3) endpoints in camera space. Returns ``(offsets (E+1,), spans
    /// (S,2))``: edge i owns spans[offsets[i]:offsets[i+1]].
    fn visible_spans<'py>(
        &self,
        py: Python<'py>,
        a: PyReadonlyArray2<'_, f64>,
        b: PyReadonlyArray2<'_, f64>,
        eps: f64,
    ) -> PyResult<(Bound<'py, PyArray1<i64>>, Bound<'py, PyArray2<f64>>)> {
        let a = a.as_array();
        let b = b.as_array();
        let n = a.shape()[0];
        let edges: Vec<([f64; 3], [f64; 3])> = (0..n)
            .map(|i| {
                ([a[[i, 0]], a[[i, 1]], a[[i, 2]]], [b[[i, 0]], b[[i, 1]], b[[i, 2]]])
            })
            .collect();
        let inner = &self.inner;
        let (offsets, spans) = py.detach(|| inner.visible_spans_all(&edges, eps));
        let flat: Vec<Vec<f64>> = spans.iter().map(|s| vec![s.0, s.1]).collect();
        let off = PyArray1::from_vec(py, offsets);
        let sp = if flat.is_empty() {
            PyArray2::zeros(py, [0, 2], false)
        } else {
            PyArray2::from_vec2(py, &flat)?
        };
        Ok((off, sp))
    }

    /// The Profiles test of hlr_drawing for many visible spans at once:
    /// for each row, is the background on either side of the span's
    /// midpoint? ``mid`` (N,2), ``nrm`` (N,2) the sideways probe offset,
    /// ``zm`` (N,) the span's depth at the midpoint.
    fn profile_flags<'py>(
        &self,
        py: Python<'py>,
        mid: PyReadonlyArray2<'_, f64>,
        nrm: PyReadonlyArray2<'_, f64>,
        zm: PyReadonlyArray1<'_, f64>,
        delta: f64,
        ptol: f64,
    ) -> PyResult<Bound<'py, PyArray1<bool>>> {
        let mid = mid.as_array();
        let nrm = nrm.as_array();
        let zm = zm.as_array();
        let n = mid.shape()[0];
        let probes: Vec<([f64; 2], [f64; 2], f64)> = (0..n)
            .map(|i| ([mid[[i, 0]], mid[[i, 1]]], [nrm[[i, 0]], nrm[[i, 1]]], zm[i]))
            .collect();
        let inner = &self.inner;
        let out = py.detach(|| inner.profile_flags(&probes, delta, ptol));
        Ok(PyArray1::from_vec(py, out))
    }
}

fn rows3(a: &numpy::ndarray::ArrayView2<'_, f64>) -> Vec<[f64; 3]> {
    (0..a.shape()[0]).map(|i| [a[[i, 0]], a[[i, 1]], a[[i, 2]]]).collect()
}

/// core.intersect._touching for all rows at once: the index pairs ``(i,
/// j)`` whose boxes touch (within ``eps``), sorted by i then j; ``same``:
/// j > i only. ``lo_*``/``hi_*``: (N,3) box corners.
#[pyfunction]
fn touching_boxes<'py>(
    py: Python<'py>,
    lo_a: PyReadonlyArray2<'_, f64>,
    hi_a: PyReadonlyArray2<'_, f64>,
    lo_b: PyReadonlyArray2<'_, f64>,
    hi_b: PyReadonlyArray2<'_, f64>,
    same: bool,
    eps: f64,
) -> PyResult<(Bound<'py, PyArray1<i64>>, Bound<'py, PyArray1<i64>>)> {
    let a: Vec<boxes::Box3> = rows3(&lo_a.as_array()).into_iter()
        .zip(rows3(&hi_a.as_array())).collect();
    let b: Vec<boxes::Box3> = rows3(&lo_b.as_array()).into_iter()
        .zip(rows3(&hi_b.as_array())).collect();
    let (ii, jj) = py.detach(|| boxes::touching(&a, &b, same, eps));
    Ok((PyArray1::from_vec(py, ii), PyArray1::from_vec(py, jj)))
}

/// A packed triangle set (core.orient._PackedTris) with a ray index, for
/// the parity queries of orientation and of the push/pull rebuild.
#[pyclass(frozen)]
struct ParityTris {
    inner: parity::Tris,
}

#[pymethods]
impl ParityTris {
    /// ``a``/``e1``/``e2``: (N,3) vertex A and the two edge vectors;
    /// ``face_idx``: (N,) the face of each triangle.
    #[new]
    fn new(
        a: PyReadonlyArray2<'_, f64>,
        e1: PyReadonlyArray2<'_, f64>,
        e2: PyReadonlyArray2<'_, f64>,
        face_idx: PyReadonlyArray1<'_, i64>,
    ) -> PyResult<Self> {
        let face = face_idx.as_array().to_vec();
        Ok(Self { inner: parity::Tris::new(rows3(&a.as_array()), rows3(&e1.as_array()),
                                           rows3(&e2.as_array()), face) })
    }

    fn __len__(&self) -> usize {
        self.inner.len()
    }

    /// Crossings ahead of ``origin`` (3,) along each row of ``dirs`` (R,3),
    /// over the triangles with ``mask`` True (all when None) that are not of
    /// face ``skip``. Returns a list of R ints.
    #[pyo3(signature = (origin, dirs, mask=None, skip=None))]
    fn crossings(
        &self,
        py: Python<'_>,
        origin: (f64, f64, f64),
        dirs: PyReadonlyArray2<'_, f64>,
        mask: Option<PyReadonlyArray1<'_, bool>>,
        skip: Option<i64>,
    ) -> PyResult<Vec<i64>> {
        let d = rows3(&dirs.as_array());
        let m: Option<Vec<bool>> = mask.map(|m| m.as_array().to_vec());
        if let Some(ref mm) = m {
            if mm.len() != self.inner.len() {
                return Err(pyo3::exceptions::PyValueError::new_err("mask length"));
            }
        }
        let inner = &self.inner;
        let o = [origin.0, origin.1, origin.2];
        Ok(py.detach(|| inner.crossings(o, &d, m.as_deref(), skip)))
    }
}

fn hypot_of(name: &str) -> PyResult<facegeom::Hypot> {
    match name {
        "libstdc++" => Ok(facegeom::Hypot::LibStdCxx),
        "msvc" => Ok(facegeom::Hypot::Msvc),
        _ => Err(pyo3::exceptions::PyValueError::new_err("unknown hypot")),
    }
}

/// views.viewport.Viewport._placements_under_px: the indices of the boxes
/// ``lo``/``hi`` (P,3) whose screen footprint through ``mvp`` (the 4×4,
/// row-major: clip = M·(p, 1)) comes within ``r`` px of ``(x, y)`` in a
/// ``w``×``h`` widget; a box crossing the eye plane, or not finite, counts.
/// The same operations, in parallel.
#[pyfunction]
#[allow(clippy::too_many_arguments)]
fn boxes_near_px<'py>(py: Python<'py>, lo: PyReadonlyArray2<'py, f64>,
                      hi: PyReadonlyArray2<'py, f64>, mvp: Vec<f64>, w: f64, h: f64,
                      x: f64, y: f64, r: f64) -> PyResult<Bound<'py, PyArray1<i64>>> {
    use rayon::prelude::*;
    if mvp.len() != 16 {
        return Err(pyo3::exceptions::PyValueError::new_err("mvp"));
    }
    let (lo, hi) = (rows3(&lo.as_array()), rows3(&hi.as_array()));
    if lo.len() != hi.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("boxes"));
    }
    let m = |j: usize, k: usize| mvp[4 * j + k];
    let keep: Vec<i64> = py.detach(|| (0..lo.len()).into_par_iter().filter(|&i| {
        let (a, b) = (lo[i], hi[i]);
        let (mut x0, mut x1, mut y0, mut y1) = (f64::INFINITY, f64::NEG_INFINITY,
                                                f64::INFINITY, f64::NEG_INFINITY);
        let (mut any_front, mut all_front) = (false, true);
        for c in 0..8 {
            let p = [if c & 1 != 0 { b[0] } else { a[0] },
                     if c & 2 != 0 { b[1] } else { a[1] },
                     if c & 4 != 0 { b[2] } else { a[2] }];
            if !p.iter().all(|v| v.is_finite()) {
                return true;
            }
            let clip = |j: usize| p[0] * m(j, 0) + p[1] * m(j, 1) + p[2] * m(j, 2) + m(j, 3);
            let cw = clip(3);
            if cw > 1e-9 {
                any_front = true;
                let sx = (clip(0) / cw * 0.5 + 0.5) * w;
                let sy = (1.0 - (clip(1) / cw * 0.5 + 0.5)) * h;
                x0 = x0.min(sx);
                x1 = x1.max(sx);
                y0 = y0.min(sy);
                y1 = y1.max(sy);
            } else {
                all_front = false;
            }
        }
        if any_front && !all_front {
            return true;
        }
        all_front && x0 - r <= x && x <= x1 + r && y0 - r <= y && y <= y1 + r
    }).map(|i| i as i64).collect());
    Ok(PyArray1::from_vec(py, keep))
}

/// The frame's limits as Python hands them: ``(eye, limits (gh, gw), x0,
/// y0, dpr, device height)`` (see ``Viewport._depth_limits``).
#[allow(clippy::type_complexity)]
fn depth_limits(s: (Vec<f64>, PyReadonlyArray2<'_, f64>, i64, i64, f64, i64))
    -> PyResult<instances::DepthLimits> {
    let (eye, g, x0, y0, dpr, hdev) = s;
    if eye.len() != 3 {
        return Err(pyo3::exceptions::PyValueError::new_err("seen"));
    }
    let ga = g.as_array();
    Ok(instances::DepthLimits {
        eye: [eye[0], eye[1], eye[2]], lim: ga.iter().copied().collect(),
        x0, y0, gw: ga.shape()[1] as i64, gh: ga.shape()[0] as i64, dpr, hdev })
}

/// The indices, in order, of the projected points ``(x, y)`` in front
/// (``ok``) whose squared distance to ``(px, py)`` is at most ``r``²: the
/// candidates of views.viewport.Viewport._px_near, which measures them
/// as NumPy does (650 000 corners a pointer move over the plant of #158).
/// With the points ``pts`` (N, 3) and the frame's ``seen`` limits (as
/// ``InstanceSet.corners_near`` takes them), those the frame shows
/// something in front of are left out too, as
/// ``Viewport._depth_hidden`` leaves them out: ~6 ms of NumPy over the
/// fixed corners near the cursor in that plant.
#[pyfunction]
#[pyo3(signature = (x, y, ok, px, py_, r, pts=None, seen=None))]
#[allow(clippy::too_many_arguments, clippy::type_complexity)]
fn points_near_px<'py>(py: Python<'py>, x: PyReadonlyArray1<'py, f64>,
                       y: PyReadonlyArray1<'py, f64>, ok: PyReadonlyArray1<'py, bool>,
                       px: f64, py_: f64, r: f64, pts: Option<PyReadonlyArray2<'py, f64>>,
                       seen: Option<(Vec<f64>, PyReadonlyArray2<'py, f64>, i64, i64, f64, i64)>)
    -> PyResult<Bound<'py, PyArray1<i64>>> {
    use rayon::prelude::*;
    let (x, y, ok) = (x.as_array(), y.as_array(), ok.as_array());
    if x.len() != y.len() || x.len() != ok.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("lengths"));
    }
    let seen = match (seen, &pts) {
        (Some(s), Some(p)) => {
            if p.as_array().shape() != [x.len(), 3] {
                return Err(pyo3::exceptions::PyValueError::new_err("pts"));
            }
            Some(depth_limits(s)?)
        }
        (None, _) => None,
        (Some(_), None) => return Err(pyo3::exceptions::PyValueError::new_err("pts")),
    };
    let pv = pts.as_ref().map(|p| p.as_array());
    // Read in place where contiguous (the cached projections and their
    // heads are): copying them cost as much as the pass.
    let cow = |a: numpy::ndarray::ArrayView1<'_, f64>| match a.to_slice() {
        Some(_) => None,
        None => Some(a.to_vec()),
    };
    let (xc, yc) = (cow(x), cow(y));
    let okc: Vec<bool> = ok.to_vec();
    let x: &[f64] = xc.as_deref().unwrap_or_else(|| x.to_slice().unwrap());
    let y: &[f64] = yc.as_deref().unwrap_or_else(|| y.to_slice().unwrap());
    let ok: &[bool] = &okc;
    let r2 = r * r;
    let keep: Vec<i64> = py.detach(|| (0..x.len()).into_par_iter().with_min_len(8192)
        .filter(|&i| {
            let (dx, dy) = (x[i] - px, y[i] - py_);
            ok[i] && dx * dx + dy * dy <= r2
                && !seen.as_ref().is_some_and(|s| {
                    let p = pv.as_ref().unwrap();
                    s.hides([p[[i, 0]], p[[i, 1]], p[[i, 2]]], x[i], y[i])
                })
        }).map(|i| i as i64).collect());
    Ok(PyArray1::from_vec(py, keep))
}

/// The indices of the ``cap`` smallest of ``d[:n]`` under ``radius``, by
/// distance and then index — what ``np.lexsort((cand, d[cand]))[:cap]``
/// over ``np.flatnonzero(d < radius)`` gives (views.viewport's fixed group
/// edges near the cursor). Zoomed out over the plant of #158 some 475 000
/// fixed edges lay within the radius: ~4 ms of NumPy to pick 48, twice a
/// pointer move.
#[pyfunction]
#[pyo3(signature = (d, radius, cap, n=None))]
fn nearest_within<'py>(py: Python<'py>, d: PyReadonlyArray1<'py, f64>, radius: f64,
                       cap: usize, n: Option<usize>) -> PyResult<Bound<'py, PyArray1<i64>>> {
    use rayon::prelude::*;
    let d = d.as_array();
    let n = n.unwrap_or(d.len()).min(d.len());
    let own;
    let d: &[f64] = match d.to_slice() {
        Some(s) => &s[..n],
        None => {
            own = d.iter().take(n).copied().collect::<Vec<f64>>();
            &own
        }
    };
    // Under the radius there is no NaN: the order is total.
    let by = |a: &(f64, usize), b: &(f64, usize)| {
        a.0.partial_cmp(&b.0).unwrap().then(a.1.cmp(&b.1))
    };
    let keep = |mut v: Vec<(f64, usize)>| {
        if v.len() > cap {
            v.select_nth_unstable_by(cap, by);
            v.truncate(cap);
        }
        v
    };
    let mut all: Vec<(f64, usize)> = py.detach(|| {
        let parts: Vec<Vec<(f64, usize)>> = d.par_chunks(1 << 16).enumerate()
            .map(|(c, ch)| keep(ch.iter().enumerate()
                .filter(|(_, &v)| v < radius)
                .map(|(i, &v)| (v, (c << 16) + i)).collect()))
            .collect();
        keep(parts.into_iter().flatten().collect())
    });
    all.sort_unstable_by(by);
    Ok(PyArray1::from_vec(py, all.into_iter().map(|t| t.1 as i64).collect()))
}

/// ``core.edge_grid.segment_distances``: the pixel distance from ``(px,
/// py)`` to each segment ``(ax, ay)–(bx, by)`` (inf where ``ok`` is
/// False), for all of them or only the indices ``which`` — the same
/// operations in the same order, so the same bits (``hypot`` is the C
/// library's; the caller checks it is NumPy's). Zoomed out over the plant
/// of #158 some 475 000 edges lay within 8 px of the cursor: ~11 ms of
/// NumPy a pointer move.
#[pyfunction]
#[pyo3(signature = (ax, ay, bx, by, ok, px, py_, which=None))]
#[allow(clippy::too_many_arguments)]
fn segment_distances<'py>(py: Python<'py>, ax: PyReadonlyArray1<'py, f64>,
                          ay: PyReadonlyArray1<'py, f64>, bx: PyReadonlyArray1<'py, f64>,
                          by: PyReadonlyArray1<'py, f64>, ok: PyReadonlyArray1<'py, bool>,
                          px: f64, py_: f64, which: Option<PyReadonlyArray1<'py, i64>>)
    -> PyResult<Bound<'py, PyArray1<f64>>> {
    use rayon::prelude::*;
    let (ax, ay, bx, by, ok) = (ax.as_array(), ay.as_array(), bx.as_array(), by.as_array(),
                                ok.as_array());
    let n = ax.len();
    if ay.len() != n || bx.len() != n || by.len() != n || ok.len() != n {
        return Err(pyo3::exceptions::PyValueError::new_err("lengths"));
    }
    let w: Option<Vec<usize>> = match &which {
        Some(w) => {
            let w = w.as_array();
            if w.iter().any(|&i| i < 0 || i as usize >= n) {
                return Err(pyo3::exceptions::PyValueError::new_err("which"));
            }
            Some(w.iter().map(|&i| i as usize).collect())
        }
        None => None,
    };
    let m = w.as_ref().map_or(n, |w| w.len());
    let one = |i: usize| -> f64 {
        if !ok[i] {
            return f64::INFINITY;
        }
        let (dx, dy) = (bx[i] - ax[i], by[i] - ay[i]);
        let l2 = dx * dx + dy * dy;
        let safe = if l2 > 1e-12 { l2 } else { 1.0 };
        let mut t = ((px - ax[i]) * dx + (py_ - ay[i]) * dy) / safe;
        // np.clip: maximum then minimum, NaN through.
        t = if t < 0.0 { 0.0 } else { t };
        t = if t > 1.0 { 1.0 } else { t };
        (ax[i] + t * dx - px).hypot(ay[i] + t * dy - py_)
    };
    let out: Vec<f64> = py.detach(|| (0..m).into_par_iter().with_min_len(4096)
        .map(|k| one(w.as_ref().map_or(k, |w| w[k]))).collect());
    Ok(PyArray1::from_vec(py, out))
}

/// QVector3D's own arithmetic on each row of ``v`` (N,3) float32, for the
/// start-up check that ``hypot`` is this Qt's: ``(length (N,), normalized
/// (N,3), plane u (N,3), plane v (N,3))`` — core.triangulate.plane_axes.
#[pyfunction]
fn qt_vector_probe<'py>(
    py: Python<'py>,
    v: PyReadonlyArray2<'_, f32>,
    hypot: &str,
) -> PyResult<(Bound<'py, PyArray1<f32>>, Bound<'py, PyArray2<f32>>,
               Bound<'py, PyArray2<f32>>, Bound<'py, PyArray2<f32>>)> {
    let h = hypot_of(hypot)?;
    let v = v.as_array();
    let n = v.shape()[0];
    let (mut ln, mut nz, mut pu, mut pv) = (Vec::with_capacity(n), Vec::new(), Vec::new(), Vec::new());
    for i in 0..n {
        let x = facegeom::V3(v[[i, 0]], v[[i, 1]], v[[i, 2]]);
        ln.push(facegeom::length(x, h));
        let m = facegeom::normalized(x, h);
        nz.push(vec![m.0, m.1, m.2]);
        let (a, b) = facegeom::plane_axes(x, h);
        pu.push(vec![a.0, a.1, a.2]);
        pv.push(vec![b.0, b.1, b.2]);
    }
    Ok((PyArray1::from_vec(py, ln), PyArray2::from_vec2(py, &nz)?,
        PyArray2::from_vec2(py, &pu)?, PyArray2::from_vec2(py, &pv)?))
}

/// views.viewport._face_geometry for every face of a mesh given as arrays:
/// ``pos`` (V,3) float32 vertex positions, ``corners`` every ring's vertex
/// indices (rings concatenated, each face's outer ring first),
/// ``ring_sizes`` and ``ring_counts`` (rings per face). Returns ``(normal
/// (F,3) f32, ln (F,) f32 — the Newell length, area = ln / 2 — centroid
/// (F,3) f32, NaN for a face of under three corners, tris (T,3) u32 vertex
/// indices, tri_face (T,) u32, unit (F,3) f32, tris_unit, tri_face_unit)``;
/// each face's triangles in order. ``unit`` and its triangles are the
/// viewport's ``_normal_of`` / ``_tris_of`` (Qt's normalized()).
/// ``compensated_sum``: this Python's sum() of floats is Neumaier's (3.12+).
#[pyfunction]
fn face_geometry<'py>(
    py: Python<'py>,
    pos: PyReadonlyArray2<'_, f32>,
    corners: PyReadonlyArray1<'_, i64>,
    ring_sizes: PyReadonlyArray1<'_, i64>,
    ring_counts: PyReadonlyArray1<'_, i64>,
    hypot: &str,
    compensated_sum: bool,
) -> PyResult<(Bound<'py, PyArray2<f32>>, Bound<'py, PyArray1<f32>>,
               Bound<'py, PyArray2<f32>>, Bound<'py, PyArray2<u32>>,
               Bound<'py, PyArray1<u32>>, Bound<'py, PyArray2<f32>>,
               Bound<'py, PyArray2<u32>>, Bound<'py, PyArray1<u32>>)> {
    use rayon::prelude::*;
    let h = hypot_of(hypot)?;
    let p = pos.as_array();
    let pts: Vec<facegeom::V3> = (0..p.shape()[0])
        .map(|i| facegeom::V3(p[[i, 0]], p[[i, 1]], p[[i, 2]])).collect();
    let nv = pts.len() as i64;
    let corners: Vec<u32> = corners.as_array().iter().map(|&c| {
        if c < 0 || c >= nv { u32::MAX } else { c as u32 }
    }).collect();
    if corners.iter().any(|&c| c == u32::MAX) {
        return Err(pyo3::exceptions::PyValueError::new_err("corner out of range"));
    }
    let sizes = ring_sizes.as_array().to_vec();
    let counts = ring_counts.as_array().to_vec();
    // Each face's first ring, and each ring's first corner.
    let mut ring_start = Vec::with_capacity(sizes.len() + 1);
    let mut acc = 0usize;
    for &s in &sizes {
        ring_start.push(acc);
        acc += s as usize;
    }
    ring_start.push(acc);
    if acc != corners.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("ring sizes"));
    }
    let mut face_ring = Vec::with_capacity(counts.len() + 1);
    let mut r = 0usize;
    for &c in &counts {
        face_ring.push(r);
        r += c as usize;
    }
    face_ring.push(r);
    if r != sizes.len() {
        return Err(pyo3::exceptions::PyValueError::new_err("ring counts"));
    }
    let geoms: Vec<facegeom::FaceGeom> = py.detach(|| {
        (0..counts.len()).into_par_iter().map(|f| {
            let rings: Vec<&[u32]> = (face_ring[f]..face_ring[f + 1])
                .map(|k| &corners[ring_start[k]..ring_start[k + 1]]).collect();
            facegeom::face_geometry(&pts, &rings, h, compensated_sum)
        }).collect()
    });
    let nf = geoms.len();
    let mut normal = Vec::with_capacity(nf);
    let mut ln = Vec::with_capacity(nf);
    let mut cen = Vec::with_capacity(nf);
    let mut tris = Vec::new();
    let mut tri_face = Vec::new();
    let mut unit = Vec::with_capacity(nf);
    let mut tris_u = Vec::new();
    let mut tri_face_u = Vec::new();
    for (f, g) in geoms.into_iter().enumerate() {
        unit.push(vec![g.unit.0, g.unit.1, g.unit.2]);
        for t in g.tris_unit.as_ref().unwrap_or(&g.tris) {
            tris_u.push(t.to_vec());
            tri_face_u.push(f as u32);
        }
        normal.push(vec![g.normal.0, g.normal.1, g.normal.2]);
        ln.push(g.ln);
        cen.push(match g.centroid {
            Some(c) => vec![c.0, c.1, c.2],
            None => vec![f32::NAN; 3],
        });
        for t in g.tris {
            tris.push(t.to_vec());
            tri_face.push(f as u32);
        }
    }
    let tris_arr = if tris.is_empty() {
        PyArray2::zeros(py, [0, 3], false)
    } else {
        PyArray2::from_vec2(py, &tris)?
    };
    let normal_arr = if nf == 0 { PyArray2::zeros(py, [0, 3], false) } else { PyArray2::from_vec2(py, &normal)? };
    let cen_arr = if nf == 0 { PyArray2::zeros(py, [0, 3], false) } else { PyArray2::from_vec2(py, &cen)? };
    let unit_arr = if nf == 0 { PyArray2::zeros(py, [0, 3], false) } else { PyArray2::from_vec2(py, &unit)? };
    let tris_u_arr = if tris_u.is_empty() {
        PyArray2::zeros(py, [0, 3], false)
    } else {
        PyArray2::from_vec2(py, &tris_u)?
    };
    Ok((normal_arr, PyArray1::from_vec(py, ln), cen_arr, tris_arr, PyArray1::from_vec(py, tri_face),
        unit_arr, tris_u_arr, PyArray1::from_vec(py, tri_face_u)))
}

/// core.lazy_mesh.weld (Mesh.bulk_weld on an empty mesh): ``pos`` (N,3)
/// float32 points, ``scale`` the weld cell (10**decimals), ``tol2`` the
/// probe's squared distance. Returns ``(vertex positions (V,3) float32,
/// point → vertex (N,), the point each vertex was made at (V,))``.
#[pyfunction]
fn weld_points<'py>(
    py: Python<'py>,
    pos: PyReadonlyArray2<'_, f32>,
    scale: f64,
    tol2: f64,
) -> PyResult<(Bound<'py, PyArray2<f32>>, Bound<'py, PyArray1<i64>>,
               Bound<'py, PyArray1<i64>>)> {
    let p = pos.as_array();
    let pts: Vec<[f32; 3]> = (0..p.shape()[0]).map(|i| [p[[i, 0]], p[[i, 1]], p[[i, 2]]]).collect();
    let (vpos, ids, origin) = py.detach(|| weld::weld(&pts, scale, tol2));
    let rows: Vec<Vec<f32>> = vpos.iter().map(|v| v.to_vec()).collect();
    let arr = if rows.is_empty() { PyArray2::zeros(py, [0, 3], false) } else { PyArray2::from_vec2(py, &rows)? };
    Ok((arr, PyArray1::from_vec(py, ids), PyArray1::from_vec(py, origin)))
}

/// A recorded run of OpenGL calls, replayed through the current context's
/// entry points (views.viewport._GlTape): ``GlReplay(addrs)`` with the
/// eleven entry points in opcode order (glDrawArraysInstanced,
/// glBindVertexArray, glUniform1i, glUniform1f, glUniform4f, glEnable,
/// glDisable, glCullFace, glFrontFace, glActiveTexture, glBindTexture).
#[pyclass(frozen)]
struct GlReplay {
    tape: gltape::Tape,
}

#[pymethods]
impl GlReplay {
    #[new]
    fn new(addrs: Vec<usize>) -> PyResult<Self> {
        gltape::Tape::new(&addrs)
            .map(|tape| Self { tape })
            .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("missing GL entry point"))
    }

    /// Run ``ops`` (R,5) int64 ``[opcode, a, b, c, d]`` with ``vals`` (R,4)
    /// float32. The GL context the entry points came from must be current.
    fn run(&self, ops: PyReadonlyArray2<'_, i64>, vals: PyReadonlyArray2<'_, f32>) -> PyResult<usize> {
        let o = ops.as_array();
        let v = vals.as_array();
        if o.shape()[1] != 5 || v.shape()[1] != 4 || o.shape()[0] != v.shape()[0] {
            return Err(pyo3::exceptions::PyValueError::new_err("tape shape"));
        }
        let rows: Vec<[i64; 5]> = (0..o.shape()[0])
            .map(|r| [o[[r, 0]], o[[r, 1]], o[[r, 2]], o[[r, 3]], o[[r, 4]]]).collect();
        let fl: Vec<[f32; 4]> = (0..v.shape()[0])
            .map(|r| [v[[r, 0]], v[[r, 1]], v[[r, 2]], v[[r, 3]]]).collect();
        // SAFETY: the viewport calls this inside paintGL, its context
        // current, with a tape it recorded from its own calls.
        unsafe { self.tape.run(&rows, &fl) }
            .map_err(|r| pyo3::exceptions::PyValueError::new_err(format!("bad opcode at {r}")))
    }
}

/// One prototype for the spatial index: its pick triangles (``v0``,
/// ``e1``, ``e2``: (T,3) local, as the chunk keeps them) under a BVH, and
/// its hard edges (``edges``: (E,6) local endpoints).
#[pyclass(frozen)]
struct InstanceProto {
    inner: std::sync::Arc<instances::Proto>,
}

#[pymethods]
impl InstanceProto {
    #[new]
    fn new(
        py: Python<'_>,
        v0: PyReadonlyArray2<'_, f64>,
        e1: PyReadonlyArray2<'_, f64>,
        e2: PyReadonlyArray2<'_, f64>,
        edges: PyReadonlyArray2<'_, f64>,
    ) -> PyResult<Self> {
        let (a, b, c) = (rows3(&v0.as_array()), rows3(&e1.as_array()), rows3(&e2.as_array()));
        if a.len() != b.len() || a.len() != c.len() {
            return Err(pyo3::exceptions::PyValueError::new_err("triangle arrays"));
        }
        let ev = edges.as_array();
        if ev.shape()[0] > 0 && ev.shape()[1] != 6 {
            return Err(pyo3::exceptions::PyValueError::new_err("edges (E,6)"));
        }
        let es: Vec<[[f64; 3]; 2]> = (0..ev.shape()[0]).map(|i| [
            [ev[[i, 0]], ev[[i, 1]], ev[[i, 2]]], [ev[[i, 3]], ev[[i, 4]], ev[[i, 5]]]]).collect();
        let inner = py.detach(|| instances::Proto::new(a, b, c, es));
        Ok(Self { inner: std::sync::Arc::new(inner) })
    }

    fn __len__(&self) -> usize {
        self.inner.n_tris()
    }
}

/// The placements of a scene state over their prototypes: ``protos`` (a
/// list of InstanceProto), ``proto_of`` (P,) which one each placement
/// shows, ``mats`` (P,16) their matrices column-major (QMatrix4x4.data()).
#[pyclass(frozen)]
struct InstanceSet {
    protos: Vec<std::sync::Arc<instances::Proto>>,
    places: Vec<instances::Placement>,
    bvh: instances::PlaceBvh,
}

#[pymethods]
impl InstanceSet {
    #[new]
    #[pyo3(signature = (protos, proto_of, mats, lo=None, hi=None))]
    fn new(
        protos: Vec<PyRef<'_, InstanceProto>>,
        proto_of: PyReadonlyArray1<'_, i64>,
        mats: PyReadonlyArray2<'_, f64>,
        lo: Option<PyReadonlyArray2<'_, f64>>,
        hi: Option<PyReadonlyArray2<'_, f64>>,
    ) -> PyResult<Self> {
        let pr: Vec<std::sync::Arc<instances::Proto>> = protos.iter().map(|p| p.inner.clone()).collect();
        let po = proto_of.as_array();
        let m = mats.as_array();
        if m.shape()[0] != po.len() || (po.len() > 0 && m.shape()[1] != 16) {
            return Err(pyo3::exceptions::PyValueError::new_err("placements"));
        }
        let boxes = match (&lo, &hi) {
            (Some(a), Some(b)) => {
                let (a, b) = (rows3(&a.as_array()), rows3(&b.as_array()));
                if a.len() != po.len() || b.len() != po.len() {
                    return Err(pyo3::exceptions::PyValueError::new_err("boxes"));
                }
                Some((a, b))
            }
            (None, None) => None,
            _ => return Err(pyo3::exceptions::PyValueError::new_err("lo and hi")),
        };
        let mut places = Vec::with_capacity(po.len());
        for i in 0..po.len() {
            let k = po[i];
            if k < 0 || k as usize >= pr.len() {
                return Err(pyo3::exceptions::PyValueError::new_err("proto index"));
            }
            let mut mm = [0.0f64; 16];
            for j in 0..16 {
                mm[j] = m[[i, j]];
            }
            let (blo, bhi) = match &boxes {
                Some((a, b)) => instances::grown(a[i], b[i]),
                None => ([f64::NEG_INFINITY; 3], [f64::INFINITY; 3]),
            };
            places.push(instances::Placement { proto: k as usize, m: mm,
                                               inv: instances::affine_inverse(&mm),
                                               lo: blo, hi: bhi });
        }
        // A ray meets nothing in a placement of no triangles (an empty
        // group, a container of others): it has no box in the pick table,
        // and every ray visited its ~1 400 of them over the plant of #158.
        let bvh = instances::PlaceBvh::new(&places, |p| pr[p.proto].n_tris() > 0);
        Ok(Self { protos: pr, places, bvh })
    }

    fn __len__(&self) -> usize {
        self.places.len()
    }

    /// Of placements ``cand``, those whose triangles the world ray ``o`` +
    /// t·``d`` may meet for t in [0, ``reach``] (None: unbounded) — a
    /// placement whose matrix cannot be inverted is always kept.
    #[pyo3(signature = (cand, o, d, reach=None))]
    fn ray_filter(&self, py: Python<'_>, cand: PyReadonlyArray1<'_, i64>,
                  o: (f64, f64, f64), d: (f64, f64, f64), reach: Option<f64>) -> PyResult<Vec<i64>> {
        use rayon::prelude::*;
        let c = cand.as_array().to_vec();
        self.check(&c)?;
        let (o, d) = ([o.0, o.1, o.2], [d.0, d.1, d.2]);
        let lim = reach.unwrap_or(f64::INFINITY);
        Ok(py.detach(|| c.par_iter().copied().filter(|&i| {
            let p = &self.places[i as usize];
            match p.local_ray(o, d) {
                None => true,
                Some((lo, ld)) => self.protos[p.proto].ray_may_hit(lo, ld, lim),
            }
        }).collect()))
    }

    /// Of placements ``cand``, those with something near ``(px, py)`` on a
    /// ``w``×``h`` view through ``mvp`` (16 floats, column-major): a hard
    /// edge within ``edge_reach`` px, a triangle within ``tri_reach``.
    #[allow(clippy::too_many_arguments)]
    fn screen_filter(&self, py: Python<'_>, cand: PyReadonlyArray1<'_, i64>, mvp: Vec<f64>,
                     w: f64, h: f64, px: f64, py_: f64, edge_reach: f64,
                     tri_reach: f64) -> PyResult<Vec<i64>> {
        use rayon::prelude::*;
        if mvp.len() != 16 {
            return Err(pyo3::exceptions::PyValueError::new_err("mvp"));
        }
        let c = cand.as_array().to_vec();
        self.check(&c)?;
        let mut a = [0.0f64; 16];
        a.copy_from_slice(&mvp);
        Ok(py.detach(|| c.par_iter().copied().filter(|&i| {
            let p = &self.places[i as usize];
            let m = instances::mat_mul(&a, &p.m);
            self.protos[p.proto].screen_near(&m, w, h, px, py_, edge_reach, tri_reach)
        }).collect()))
    }

    /// The hard-edge ends of placements ``cand`` within ``reach`` px of
    /// ``(px, py)`` on a ``w``×``h`` view through ``mvp`` (16 floats,
    /// column-major): ``(place, edge, end, xyz (N,3), sx, sy)`` — each end
    /// as the bake would store it (float32) and its pixel as
    /// ``Viewport._project_px`` gives it, bit for bit; an edge counts only
    /// with both ends in front of the eye. In ``cand`` order, then edge,
    /// then end.
    #[allow(clippy::too_many_arguments, clippy::type_complexity)]
    #[pyo3(signature = (cand, mvp, w, h, px, py_, reach, seen=None))]
    fn corners_near<'py>(&self, py: Python<'py>, cand: PyReadonlyArray1<'py, i64>, mvp: Vec<f64>,
                         w: f64, h: f64, px: f64, py_: f64, reach: f64,
                         seen: Option<(Vec<f64>, PyReadonlyArray2<'py, f64>, i64, i64, f64, i64)>)
        -> PyResult<(Bound<'py, PyArray1<i64>>, Bound<'py, PyArray1<i64>>,
                     Bound<'py, PyArray1<i64>>, Bound<'py, PyArray2<f64>>,
                     Bound<'py, PyArray1<f64>>, Bound<'py, PyArray1<f64>>)> {
        use rayon::prelude::*;
        if mvp.len() != 16 {
            return Err(pyo3::exceptions::PyValueError::new_err("mvp"));
        }
        let c = cand.as_array().to_vec();
        self.check(&c)?;
        let mut a = [0.0f64; 16];
        a.copy_from_slice(&mvp);
        // (eye, limits (gh, gw), x0, y0, dpr, device height): corners the
        // frame shows something in front of are left out here.
        let seen = match seen {
            Some(s) => Some(depth_limits(s)?),
            None => None,
        };
        let seen = seen.as_ref();
        let found: Vec<(i64, Vec<instances::Corner>)> = py.detach(|| c.par_iter().filter_map(|&i| {
            let p = &self.places[i as usize];
            if !p.screen_may_reach(&a, w, h, px, py_, reach) {
                return None;
            }
            let mut out = Vec::new();
            self.protos[p.proto].corners_near(&p.m, &a, w, h, px, py_, reach, seen, &mut out);
            if out.is_empty() { None } else { Some((i, out)) }
        }).collect());
        let n: usize = found.iter().map(|f| f.1.len()).sum();
        let (mut pl, mut ed, mut en) = (Vec::with_capacity(n), Vec::with_capacity(n), Vec::with_capacity(n));
        let (mut xyz, mut sx, mut sy) = (Vec::with_capacity(n), Vec::with_capacity(n), Vec::with_capacity(n));
        for (i, cs) in found {
            for k in cs {
                pl.push(i);
                ed.push(k.edge as i64);
                en.push(k.end as i64);
                xyz.push(vec![k.xyz[0], k.xyz[1], k.xyz[2]]);
                sx.push(k.sx);
                sy.push(k.sy);
            }
        }
        let xyz = if xyz.is_empty() {
            PyArray2::zeros(py, [0, 3], false)
        } else {
            PyArray2::from_vec2(py, &xyz).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))?
        };
        Ok((PyArray1::from_vec(py, pl), PyArray1::from_vec(py, ed), PyArray1::from_vec(py, en),
            xyz, PyArray1::from_vec(py, sx), PyArray1::from_vec(py, sy)))
    }

    /// The hard edges of placements ``cand`` within ``radius`` px of
    /// ``(px, py)`` on a ``w``×``h`` view through ``mvp`` (both ends in
    /// front), the nearest ``cap`` of them (0: all) by (distance, place in
    /// ``cand``, edge): ``(place, edge, a (N,3), b (N,3), d)`` — the ends as
    /// the bake stores them, the distance as ``segment_distances`` gives
    /// it, bit for bit.
    #[allow(clippy::too_many_arguments, clippy::type_complexity)]
    fn edges_near<'py>(&self, py: Python<'py>, cand: PyReadonlyArray1<'py, i64>, mvp: Vec<f64>,
                       w: f64, h: f64, px: f64, py_: f64, radius: f64, cap: usize)
        -> PyResult<(Bound<'py, PyArray1<i64>>, Bound<'py, PyArray1<i64>>,
                     Bound<'py, PyArray2<f64>>, Bound<'py, PyArray2<f64>>,
                     Bound<'py, PyArray1<f64>>)> {
        use rayon::prelude::*;
        if mvp.len() != 16 {
            return Err(pyo3::exceptions::PyValueError::new_err("mvp"));
        }
        let c = cand.as_array().to_vec();
        self.check(&c)?;
        let mut a = [0.0f64; 16];
        a.copy_from_slice(&mvp);
        // The candidates by how near their boxes come on screen, nearest
        // first: once the heap holds ``cap`` edges, a box farther than the
        // worst of them holds none that could enter, nor do the rest.
        let mut gaps: Vec<(f64, usize, i64)> = py.detach(|| c.par_iter().enumerate()
            .filter_map(|(k, &i)| {
                let g = self.places[i as usize].screen_gap(&a, w, h, px, py_);
                if g < radius { Some((g, k, i)) } else { None }
            }).collect());
        gaps.sort_by(|x, y| x.0.total_cmp(&y.0).then(x.1.cmp(&y.1)));
        let all = py.detach(|| {
            let mut heap = instances::NearHeap::new(cap, radius);
            // In batches, nearest first, each placement of a batch on its
            // own heap in parallel, bounded by the shared heap's worst: a
            // dense corner of the plant of #158 kept ~4 000 placements
            // within reach of the cursor, walked one after another. Merged
            // in the batch's order, the shared heap ends as the walk left
            // it: (distance, candidate, edge) orders the edges wholly.
            let mut at = 0;
            while at < gaps.len() {
                if !heap.may_take(gaps[at].0) {
                    break;
                }
                let size = if at == 0 { 8 } else { 64 };
                let hi = (at + size).min(gaps.len());
                let bound = heap.worst();
                let found: Vec<Vec<instances::NearEdge>> = gaps[at..hi].par_iter()
                    .map(|&(g, k, i)| {
                        let mut own = instances::NearHeap::bounded(cap, radius, bound);
                        if own.may_take(g) {
                            let p = &self.places[i as usize];
                            self.protos[p.proto].edges_near(&p.m, &a, w, h, px, py_, k, i,
                                                            &mut own);
                        }
                        own.into_sorted()
                    }).collect();
                for e in found.into_iter().flatten() {
                    heap.offer(e);
                }
                at = hi;
            }
            heap.into_sorted()
        });
        let n = all.len();
        let (mut pl, mut ed, mut d) = (Vec::with_capacity(n), Vec::with_capacity(n), Vec::with_capacity(n));
        let (mut av, mut bv) = (Vec::with_capacity(n), Vec::with_capacity(n));
        for e in all {
            pl.push(e.place);
            ed.push(e.edge as i64);
            d.push(e.d);
            av.push(e.a.to_vec());
            bv.push(e.b.to_vec());
        }
        let arr = |v: Vec<Vec<f64>>| -> PyResult<Bound<'py, PyArray2<f64>>> {
            if v.is_empty() {
                Ok(PyArray2::zeros(py, [0, 3], false))
            } else {
                PyArray2::from_vec2(py, &v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }
        };
        Ok((PyArray1::from_vec(py, pl), PyArray1::from_vec(py, ed), arr(av)?, arr(bv)?,
            PyArray1::from_vec(py, d)))
    }

    /// Whether the triangles of placements ``cand`` hide the point at
    /// ``limit[r]`` along each ray from ``origin`` (``dirs`` (R,3)) — the
    /// placements as baked, without baking them. ``(hidden, doubt)``: a
    /// doubtful ray's answer could hang on the last bit (or a placement
    /// cannot be inverted); the caller decides it on ``ray_tris``.
    fn occluded<'py>(&self, py: Python<'py>, cand: PyReadonlyArray1<'py, i64>,
                     origin: (f64, f64, f64), dirs: PyReadonlyArray2<'py, f64>,
                     limit: PyReadonlyArray1<'py, f64>)
        -> PyResult<(Bound<'py, PyArray1<bool>>, Bound<'py, PyArray1<bool>>)> {
        use rayon::prelude::*;
        let c = cand.as_array().to_vec();
        self.check(&c)?;
        let o = [origin.0, origin.1, origin.2];
        let d = rows3(&dirs.as_array());
        let l = limit.as_array().to_vec();
        if l.len() != d.len() {
            return Err(pyo3::exceptions::PyValueError::new_err("limit"));
        }
        // The candidates as a mask: each ray walks the placements' BVH.
        let mut mask = vec![false; self.places.len()];
        for &i in &c {
            mask[i as usize] = true;
        }
        let out: Vec<(bool, bool)> = py.detach(|| (0..d.len()).into_par_iter()
            .map(|r| self.occluded_ray(&mask, o, d[r], l[r])).collect());
        let (hid, dbt): (Vec<bool>, Vec<bool>) = out.into_iter().unzip();
        Ok((PyArray1::from_vec(py, hid), PyArray1::from_vec(py, dbt)))
    }

    /// The first of ``pts`` (N,3), in order, that nothing hides from
    /// ``eye`` — ``Viewport._occluded_many_now`` asked of each in turn, in
    /// one call: the ray to each point built as ``_unit_rays`` builds it
    /// (float coordinates, the three-argument hypot of ``hypot``, the
    /// float division), the placements ``cand`` of this set and, when given,
    /// those ``stat_cand`` of ``stat`` (the pick index's own triangles)
    /// asked as there. ``(first, doubts)``: the index of the first point
    /// both call seen (-1: none), and before it, in order, those either
    /// could not call bit for bit — the caller asks them as before. A
    /// point on the eye is seen, as there. Over the plant of #158 the
    /// ~7000 corners a roof hides near the cursor were a dozen calls.
    #[pyo3(signature = (cand, eye, pts, stat=None, stat_cand=None, hypot="libstdc++"))]
    fn first_clear<'py>(&self, py: Python<'py>, cand: PyReadonlyArray1<'py, i64>,
                        eye: (f64, f64, f64), pts: PyReadonlyArray2<'py, f64>,
                        stat: Option<PyRef<'py, InstanceSet>>,
                        stat_cand: Option<PyReadonlyArray1<'py, i64>>,
                        hypot: &str)
        -> PyResult<(i64, Bound<'py, PyArray1<i64>>)> {
        use rayon::prelude::*;
        let h = hypot_of(hypot)?;
        let c = cand.as_array().to_vec();
        self.check(&c)?;
        let mut mask = vec![false; self.places.len()];
        for &i in &c {
            mask[i as usize] = true;
        }
        let st: Option<&InstanceSet> = stat.as_deref();
        let smask = match (st, &stat_cand) {
            (Some(t), Some(sc)) => {
                let sc = sc.as_array().to_vec();
                t.check(&sc)?;
                let mut m = vec![false; t.places.len()];
                for &i in &sc {
                    m[i as usize] = true;
                }
                m
            }
            (None, None) => Vec::new(),
            _ => return Err(pyo3::exceptions::PyValueError::new_err("stat and stat_cand")),
        };
        let p = rows3(&pts.as_array());
        let e = [eye.0 as f32, eye.1 as f32, eye.2 as f32];
        let o = [e[0] as f64, e[1] as f64, e[2] as f64];
        // 0 seen, 1 hidden, 2 doubt.
        let call = |q: [f64; 3]| -> u8 {
            let Some((d, dist)) = occlusion::unit_ray(e, q, h) else {
                return 0;
            };
            let limit = dist - 1e-3;
            let mut doubt = false;
            if let Some(t) = st {
                let (h, db) = t.occluded_ray(&smask, o, d, limit);
                if h {
                    return 1;
                }
                doubt |= db;
            }
            let (h, db) = self.occluded_ray(&mask, o, d, limit);
            if h {
                return 1;
            }
            if doubt || db { 2 } else { 0 }
        };
        let (first, doubts) = py.detach(|| {
            // Each point once, where it first comes: a corner shared by
            // several edges comes once per end, and gives what it gave.
            let key = |q: &[f64; 3]| q.map(|v| if v == 0.0 { 0u64 } else { v.to_bits() });
            let mut seen = std::collections::HashSet::with_capacity(p.len());
            let at: Vec<usize> = (0..p.len())
                .filter(|&i| p[i].iter().any(|v| v.is_nan()) || seen.insert(key(&p[i])))
                .collect();
            let mut doubts: Vec<i64> = Vec::new();
            // The nearest alone first (usually the answer), then batches
            // growing four times over, as the caller's loop took them.
            let (mut k, mut size) = (0usize, 1usize);
            while k < at.len() {
                let hi = (k + size).min(at.len());
                let got: Vec<u8> = at[k..hi].par_iter().map(|&i| call(p[i])).collect();
                for (j, g) in got.into_iter().enumerate() {
                    match g {
                        0 => return (at[k + j] as i64, doubts),
                        2 => doubts.push(at[k + j] as i64),
                        _ => {}
                    }
                }
                k = hi;
                size = if size == 1 { 8 } else { (size * 4).min(1024) };
            }
            (-1, doubts)
        });
        Ok((first, PyArray1::from_vec(py, doubts)))
    }

    /// The world triangles (v0, e1, e2), as baked, of placements ``cand``
    /// that the ray from ``origin`` along ``d`` may meet before ``limit`` —
    /// a superset of what the exact test accepts. A placement that cannot
    /// be inverted gives all of its triangles.
    #[allow(clippy::type_complexity)]
    fn ray_tris<'py>(&self, py: Python<'py>, cand: PyReadonlyArray1<'py, i64>,
                     origin: (f64, f64, f64), d: (f64, f64, f64), limit: f64)
        -> PyResult<(Bound<'py, PyArray2<f64>>, Bound<'py, PyArray2<f64>>, Bound<'py, PyArray2<f64>>)> {
        let c = cand.as_array().to_vec();
        self.check(&c)?;
        let (o, d) = ([origin.0, origin.1, origin.2], [d.0, d.1, d.2]);
        let (mut a, mut b, mut e) = (Vec::new(), Vec::new(), Vec::new());
        for &i in &c {
            let p = &self.places[i as usize];
            if !p.ray_meets_box(o, d, limit) {
                continue;
            }
            let pr = &self.protos[p.proto];
            let mut take = |r: usize| {
                let (x, y, z) = pr.world_tri(&p.m, r);
                a.push(x.to_vec());
                b.push(y.to_vec());
                e.push(z.to_vec());
                true
            };
            match p.local_ray(o, d) {
                Some((lo, ld)) => pr.for_tris_on_ray(lo, ld, limit, &mut take),
                None => (0..pr.n_tris()).for_each(|r| { take(r); }),
            }
        }
        let arr = |v: Vec<Vec<f64>>| -> PyResult<Bound<'py, PyArray2<f64>>> {
            if v.is_empty() {
                Ok(PyArray2::zeros(py, [0, 3], false))
            } else {
                PyArray2::from_vec2(py, &v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }
        };
        Ok((arr(a)?, arr(b)?, arr(e)?))
    }

    /// ``ray_tris`` with whose each triangle is: ``(place, tri, v0, e1,
    /// e2)`` for the placements ``cand`` the ray walks the placements' BVH
    /// to, ordered by placement then prototype triangle — a superset of
    /// what the exact test accepts, for the caller to decide on.
    #[allow(clippy::type_complexity)]
    fn ray_cands<'py>(&self, py: Python<'py>, cand: PyReadonlyArray1<'py, i64>,
                      origin: (f64, f64, f64), d: (f64, f64, f64), limit: f64)
        -> PyResult<(Bound<'py, PyArray1<i64>>, Bound<'py, PyArray1<i64>>,
                     Bound<'py, PyArray2<f64>>, Bound<'py, PyArray2<f64>>,
                     Bound<'py, PyArray2<f64>>)> {
        let c = cand.as_array().to_vec();
        self.check(&c)?;
        let (o, d) = ([origin.0, origin.1, origin.2], [d.0, d.1, d.2]);
        let mut mask = vec![false; self.places.len()];
        for &i in &c {
            mask[i as usize] = true;
        }
        let mut met: Vec<usize> = Vec::new();
        self.bvh.on_ray(o, d, limit, |i| {
            if mask[i] && self.places[i].ray_meets_box(o, d, limit) {
                met.push(i);
            }
            true
        });
        met.sort_unstable();
        met.dedup();
        let (mut pl, mut tr) = (Vec::new(), Vec::new());
        let (mut a, mut b, mut e) = (Vec::new(), Vec::new(), Vec::new());
        for i in met {
            let p = &self.places[i];
            let pr = &self.protos[p.proto];
            let mut rows: Vec<usize> = Vec::new();
            match p.local_ray(o, d) {
                Some((lo, ld)) => pr.for_tris_on_ray(lo, ld, limit, |r| {
                    rows.push(r);
                    true
                }),
                None => rows.extend(0..pr.n_tris()),
            }
            rows.sort_unstable();
            rows.dedup();
            for r in rows {
                let (x, y, z) = pr.world_tri(&p.m, r);
                pl.push(i as i64);
                tr.push(r as i64);
                a.push(x.to_vec());
                b.push(y.to_vec());
                e.push(z.to_vec());
            }
        }
        let arr = |v: Vec<Vec<f64>>| -> PyResult<Bound<'py, PyArray2<f64>>> {
            if v.is_empty() {
                Ok(PyArray2::zeros(py, [0, 3], false))
            } else {
                PyArray2::from_vec2(py, &v).map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))
            }
        };
        Ok((PyArray1::from_vec(py, pl), PyArray1::from_vec(py, tr), arr(a)?, arr(b)?, arr(e)?))
    }
}

impl InstanceSet {
    /// Whether the placements in ``mask`` hide the point at ``limit`` along
    /// the ray: ``(hidden, doubt)``. Any one that hides it settles it, so
    /// the order they are met in does not matter.
    fn occluded_ray(&self, mask: &[bool], o: [f64; 3], d: [f64; 3], limit: f64) -> (bool, bool) {
        let mut doubt = false;
        let mut found = false;
        self.bvh.on_ray(o, d, limit, |i| {
            if !mask[i] {
                return true;
            }
            let p = &self.places[i];
            if !p.ray_meets_box(o, d, limit) {
                return true;
            }
            let Some((lo, ld)) = p.local_ray(o, d) else {
                doubt = true;
                return true;
            };
            let pr = &self.protos[p.proto];
            let mut hidden = false;
            pr.for_tris_on_ray(lo, ld, limit, |r| {
                let (v0, e1, e2) = pr.world_tri(&p.m, r);
                match occlusion::tri_occludes(o, d, limit, v0, e1, e2) {
                    Some(true) => {
                        hidden = true;
                        false
                    }
                    Some(false) => true,
                    None => {
                        doubt = true;
                        true
                    }
                }
            });
            if hidden {
                found = true;
                return false;
            }
            true
        });
        if found { (true, false) } else { (false, doubt) }
    }

    fn check(&self, c: &[i64]) -> PyResult<()> {
        if c.iter().any(|&i| i < 0 || i as usize >= self.places.len()) {
            return Err(pyo3::exceptions::PyValueError::new_err("placement index"));
        }
        Ok(())
    }
}

/// ``Viewport._occluded_many``'s block for one span: rays from ``origin``
/// along the rows of ``dirs`` (R,3), against the span's triangles ``v0``,
/// ``e1``, ``e2`` (N,3). Returns ``(best, doubt)``: per ray, the minimum of
/// ``best`` (R,) and every accepted hit, and whether that answer could hang
/// on the last bit (then the caller asks NumPy), with ``limit`` (R,) the
/// distance of the point the ray goes to.
#[pyfunction]
fn occlusion_span<'py>(
    py: Python<'py>,
    origin: (f64, f64, f64),
    dirs: PyReadonlyArray2<'py, f64>,
    best: PyReadonlyArray1<'py, f64>,
    limit: PyReadonlyArray1<'py, f64>,
    v0: PyReadonlyArray2<'py, f64>,
    e1: PyReadonlyArray2<'py, f64>,
    e2: PyReadonlyArray2<'py, f64>,
) -> PyResult<(Bound<'py, PyArray1<f64>>, Bound<'py, PyArray1<bool>>)> {
    let o = [origin.0, origin.1, origin.2];
    let d = rows3(&dirs.as_array());
    let b = best.as_array().to_vec();
    let l = limit.as_array().to_vec();
    let (a, x, y) = (rows3(&v0.as_array()), rows3(&e1.as_array()), rows3(&e2.as_array()));
    let (nb, doubt) = py.detach(|| occlusion::span(o, &d, &b, &l, &a, &x, &y));
    Ok((PyArray1::from_vec(py, nb), PyArray1::from_vec(py, doubt)))
}
