// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! What `views.viewport.Viewport._bake_preview_faces_py` makes of a tool's
//! preview faces (`core.geometry.Face`, fresh each frame) — the floats the
//! preview VBOs are filled with — from arrays instead of objects, and the
//! sweep a push's overlay shows (`tools.pushpull._sweep_faces`) built here
//! from the base face and the offset.
//!
//! Every QVector3D operation is the float32 one Qt performs, in Qt's order;
//! every Python float operation is an f64 one; `** 0.5` and `math.cos` /
//! `math.sin` are the C library's `pow`, `cos` and `sin`, which Python
//! calls too. `core.views` checks the whole bake against the Python one on a
//! fixed sample once (none: the Python bake).

use crate::facegeom::{length, normalized, triangles, Hypot, V3};

// The C library's, as Python's float `**` and `math.cos`/`math.sin` call
// them (glibc's pow is not sqrt: it may differ from it in the last bit).
extern "C" {
    fn pow(x: f64, y: f64) -> f64;
    fn cos(x: f64) -> f64;
    fn sin(x: f64) -> f64;
}

#[inline]
fn add(a: V3, b: V3) -> V3 {
    V3(a.0 + b.0, a.1 + b.1, a.2 + b.2)
}

/// One preview face's material: a colour run (the viewport shades it) or a
/// texture (`core.texture.face_uv_axes` inputs).
#[derive(Clone, Copy)]
pub enum Mat {
    Color,
    Tex {
        group: u32,
        /// The fitted map `[gu.xyz, cu, gv.xyz, cv]`, or `None`: the planar
        /// projection, turned by `rot` degrees, over the tile `sw`×`sh`.
        uvw: Option<[f64; 8]>,
        rot: f64,
        sw: f64,
        sh: f64,
    },
}

/// One preview face: its rings (outer first) and its material.
pub struct PFace {
    pub pos: Vec<V3>,
    pub rings: Vec<Vec<u32>>,
    pub mat: usize,
}

/// `core.geometry.Face.normal()`: Newell's sum as QVector3D adds it (each
/// term made in doubles from the float32 corners, rounded to float32, added
/// in float32), then Qt's `normalized()`.
fn face_normal(pos: &[V3], outer: &[u32], h: Hypot) -> V3 {
    if outer.len() < 3 {
        return V3(0.0, 0.0, 1.0);
    }
    let m = outer.len();
    let mut n = V3(0.0, 0.0, 0.0);
    for k in 0..m {
        let c = pos[outer[k] as usize];
        let x = pos[outer[(k + 1) % m] as usize];
        let (cx, cy, cz) = (c.0 as f64, c.1 as f64, c.2 as f64);
        let (nx, ny, nz) = (x.0 as f64, x.1 as f64, x.2 as f64);
        let t = V3(((cy - ny) * (cz + nz)) as f32, ((cz - nz) * (cx + nx)) as f32,
                   ((cx - nx) * (cy + ny)) as f32);
        n = add(n, t);
    }
    if (length(n, h) as f64) < 1e-9 {
        return V3(0.0, 0.0, 1.0);
    }
    normalized(n, h)
}

/// `Viewport._shade_factor`; `None` where Python's `round()` raises (a NaN
/// or infinite normal).
fn shade_factor(n: V3, light: V3, h: Hypot) -> Option<f64> {
    if (length(n, h) as f64) < 1e-9 {
        return Some(0.84375);
    }
    let d = (normalized(n, h).dot(light, h) as f64).abs();
    let x = (0.62 + 0.38 * d) * 32.0;
    if !x.is_finite() {
        return None;
    }
    Some(x.round_ties_even() / 32.0)
}

/// `core.texture.projection_basis` (doubles), as QVector3D axes.
fn projection_basis(n: V3) -> (V3, V3) {
    let (mut nx, mut ny, mut nz) = (n.0 as f64, n.1 as f64, n.2 as f64);
    let ln = unsafe { pow(nx * nx + ny * ny + nz * nz, 0.5) };
    if ln > 1e-30 {
        nx /= ln;
        ny /= ln;
        nz /= ln;
    }
    let (mut xx, mut xy) = (-ny, nx);
    let lx = unsafe { pow(xx * xx + xy * xy, 0.5) };
    if lx < 1e-3 {
        return if nz > 0.0 {
            (V3(1.0, 0.0, 0.0), V3(0.0, 1.0, 0.0))
        } else {
            (V3(-1.0, 0.0, 0.0), V3(0.0, 1.0, 0.0))
        };
    }
    xx /= lx;
    xy /= lx;
    (V3(xx as f32, xy as f32, 0.0),
     V3((-nz * xy) as f32, (nz * xx) as f32, (nx * xy - ny * xx) as f32))
}

/// `core.texture.face_uv_axes`: `(gu, cu, gv, cv)`.
fn uv_axes(uvw: &Option<[f64; 8]>, rot: f64, sw: f64, sh: f64, n: V3) -> (V3, f64, V3, f64) {
    if let Some(m) = uvw {
        return (V3(m[0] as f32, m[1] as f32, m[2] as f32), m[3],
                V3(m[4] as f32, m[5] as f32, m[6] as f32), m[7]);
    }
    let (mut u, mut v) = projection_basis(n);
    if rot != 0.0 {
        let a = rot * (std::f64::consts::PI / 180.0);
        let (c, s) = unsafe { (cos(a) as f32, sin(a) as f32) };
        let (u0, v0) = (u, v);
        u = add(u0.mul(c), v0.mul(s));
        v = v0.mul(c).sub(u0.mul(s));
    }
    (u.div(sw as f32), 0.0, v.div(sh as f32), 0.0)
}

/// What one bake produced: the colour faces' positions with one
/// `(material, first vertex, vertex count, shade)` per colour face, and the
/// textured runs `(group, shade, pos+uv floats)` in first-use order.
pub struct Baked {
    pub color: Vec<f32>,
    pub runs: Vec<(u32, u32, u32, f64)>,
    pub tex: Vec<(u32, f64, Vec<f32>)>,
}

pub fn bake(faces: &[PFace], mats: &[Mat], light: V3, h: Hypot) -> Option<Baked> {
    let mut out = Baked { color: Vec::new(), runs: Vec::new(), tex: Vec::new() };
    // A NaN or infinite corner: Python's arithmetic on it goes through
    // Qt's hypot outside the range the start-up probe vouches for, and its
    // shade raises anyway — Python bakes such a frame.
    if faces.iter().any(|f| f.pos.iter().any(|p| !(p.0.is_finite() && p.1.is_finite() && p.2.is_finite()))) {
        return None;
    }
    for f in faces {
        let outer: &[u32] = &f.rings[0];
        let nrm = face_normal(&f.pos, outer, h);
        let tris = if outer.len() < 3 {
            Vec::new()
        } else {
            let rings: Vec<&[u32]> = f.rings.iter().map(|r| r.as_slice()).collect();
            triangles(&f.pos, &rings, nrm, h)
        };
        let shade = shade_factor(nrm, light, h)?;
        match mats[f.mat] {
            Mat::Color => {
                let start = (out.color.len() / 3) as u32;
                for t in &tris {
                    for &i in t {
                        let p = f.pos[i as usize];
                        out.color.extend_from_slice(&[p.0, p.1, p.2]);
                    }
                }
                let count = (out.color.len() / 3) as u32 - start;
                out.runs.push((f.mat as u32, start, count, shade));
            }
            Mat::Tex { group, ref uvw, rot, sw, sh } => {
                let k = match out.tex.iter().position(|r| r.0 == group && r.1 == shade) {
                    Some(k) => k,
                    None => {
                        out.tex.push((group, shade, Vec::new()));
                        out.tex.len() - 1
                    }
                };
                let (gu, cu, gv, cv) = uv_axes(uvw, rot, sw, sh, nrm);
                let buf = &mut out.tex[k].2;
                for t in &tris {
                    for &i in t {
                        let p = f.pos[i as usize];
                        buf.extend_from_slice(&[
                            p.0, p.1, p.2,
                            (gu.dot(p, h) as f64 + cu) as f32,
                            (gv.dot(p, h) as f64 + cv) as f32,
                        ]);
                    }
                }
            }
        }
    }
    Some(out)
}

/// `tools.pushpull._sweep_faces` of one face (rings, outer first) by
/// `off`: the moved cap with its holes (material `cap`), then one quad
/// `low[i], low[j], high[j], high[i]` per edge of every ring (`wall`).
pub fn sweep(pos: &[V3], rings: &[Vec<u32>], off: V3, cap: usize, wall: usize, out: &mut Vec<PFace>) {
    let mut cpos = Vec::new();
    let mut crings = Vec::with_capacity(rings.len());
    for r in rings {
        let mut ring = Vec::with_capacity(r.len());
        for &i in r {
            ring.push(cpos.len() as u32);
            cpos.push(add(pos[i as usize], off));
        }
        crings.push(ring);
    }
    out.push(PFace { pos: cpos, rings: crings, mat: cap });
    for r in rings {
        let m = r.len();
        for i in 0..m {
            let j = (i + 1) % m;
            let (li, lj) = (pos[r[i] as usize], pos[r[j] as usize]);
            out.push(PFace {
                pos: vec![li, lj, add(lj, off), add(li, off)],
                rings: vec![vec![0, 1, 2, 3]],
                mat: wall,
            });
        }
    }
}
