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
    m.add_class::<HlrOccluders>()?;
    m.add_function(wrap_pyfunction!(touching_boxes, m)?)?;
    m.add_class::<ParityTris>()?;
    m.add_function(wrap_pyfunction!(occlusion_span, m)?)?;
    m.add_function(wrap_pyfunction!(face_geometry, m)?)?;
    m.add_function(wrap_pyfunction!(qt_vector_probe, m)?)?;
    m.add_function(wrap_pyfunction!(weld_points, m)?)?;
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
        _ => Err(pyo3::exceptions::PyValueError::new_err("unknown hypot")),
    }
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
}

#[pymethods]
impl InstanceSet {
    #[new]
    fn new(
        protos: Vec<PyRef<'_, InstanceProto>>,
        proto_of: PyReadonlyArray1<'_, i64>,
        mats: PyReadonlyArray2<'_, f64>,
    ) -> PyResult<Self> {
        let pr: Vec<std::sync::Arc<instances::Proto>> = protos.iter().map(|p| p.inner.clone()).collect();
        let po = proto_of.as_array();
        let m = mats.as_array();
        if m.shape()[0] != po.len() || (po.len() > 0 && m.shape()[1] != 16) {
            return Err(pyo3::exceptions::PyValueError::new_err("placements"));
        }
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
            places.push(instances::Placement { proto: k as usize, m: mm, inv: instances::affine_inverse(&mm) });
        }
        Ok(Self { protos: pr, places })
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
}

impl InstanceSet {
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
